"""LLM judge stage: pick the evidence tables out of a candidate pool.

Replaces the cross-encoder reranker of the original Q7 design (user's call:
"chưa cần rerank model mà cứ dùng llm local làm rerank cũng được").

Two consequences of using a judge instead of a cross-encoder, both measured on
data/eval/evalset.json (see docs/investigations/v0_retrieval_pipeline.md):

- The pool is the **union** of BM25 top-N and dense top-N, NOT the RRF ranking.
  A judge reads every candidate, so the order inside the pool is irrelevant and
  only pool recall matters -- and RRF *loses* recall here (union@30 78.7% vs
  RRF@30 67.3%) because the dense ranking is noisy enough that fusion promotes
  its bad hits over BM25's good ones.
- `report_id` goes into the prompt. It encodes ticker+year+scope, and a
  multi-year question ("2016 den 2020") cannot be answered without knowing
  which year each candidate belongs to.

Served by the vLLM instance already running on this box (port 8990,
Qwen/Qwen3-8B-Instruct, 32k ctx) -- so the judge costs no VRAM of ours. That
server belongs to another project; keep concurrency modest.
"""

from __future__ import annotations

import re

import httpx

# The transport and the vLLM/DeepInfra branching live in finance_qa.core.llm; the
# judge only builds a prompt and reads the reply.
from finance_qa.core.http import run_sync
from finance_qa.core.llm import achat

MAX_PICKS = 10   # Q7: top-K final = 5-10

# No fixed truncation. It was 400 chars, which silently cut the evidence out of
# exactly the tables that mattered: a bank income statement runs 750-950 chars and
# "Lãi thuần từ hoạt động dịch vụ" sits at char ~430; "TỔNG TÀI SẢN" is the *last*
# label of a 1,095-char balance sheet. 5 of the 6 single-table questions the judge
# got wrong had their queried line item past char 400.
DOC_CHARS: int | None = None

# ...but "no truncation" is not a policy either: a 131-candidate pool built 92,620
# chars = 32,775 tokens and the server returned HTTP 400, which `judge()` swallowed
# into an empty pick list -- silently losing a question whose GT sat at pool
# position 0. So the length is now *budgeted* rather than fixed: keep every
# candidate, and only start capping per-candidate length when the prompt does not
# fit, longest tables first. Candidates are what recall depends on; characters past
# ~1k in one note table are not.
CTX_TOKENS = 32_768
THINK_TOKENS = 4_096
CHARS_PER_TOKEN = 2.7   # measured on this corpus: 92,620 chars -> 32,775 tokens
CAP_LADDER = (None, 1600, 1200, 900, 700, 500, 350)

PROMPT = """Bạn đang chọn bảng dữ liệu (table) làm bằng chứng để trả lời một câu hỏi tài chính.

CÂU HỎI: {question}

DANH SÁCH BẢNG ỨNG VIÊN (mỗi dòng: [số] report_id | tiêu đề và nhãn dòng của bảng):
{candidates}

Nhiệm vụ: chọn TẤT CẢ các bảng chứa số liệu cần để trả lời, không chọn thừa.
- `report_id` cho biết mã cổ phiếu, năm, và loại báo cáo (consolidated = hợp nhất, separate = riêng/công ty mẹ).
- Nếu câu hỏi trải nhiều năm, phải chọn bảng của TỪNG năm được hỏi.
- Nếu cần nhiều chỉ tiêu ở các bảng khác nhau, chọn tất cả các bảng đó.
- Xếp bảng chắc chắn nhất lên đầu. Chọn tối đa {max_picks} bảng.

Chỉ in ra JSON, không giải thích:
{{"picks": [số, số, ...]}}"""


def _render(
    question: str, pool: list[tuple[str, str]], cap: int | None, max_picks: int
) -> str:
    lines = [
        f"[{i}] {key.rsplit('|', 1)[0]} | {text if cap is None else text[:cap]}"
        for i, (key, text) in enumerate(pool)
    ]
    return PROMPT.format(
        question=question, candidates="\n".join(lines), max_picks=max_picks
    )


def build_prompt(
    question: str, pool: list[tuple[str, str]], max_picks: int = MAX_PICKS
) -> str:
    """Render the pool, tightening the per-candidate cap only as far as it takes to fit.

    Every candidate always survives -- the pool is the recall ceiling, so dropping
    one is strictly worse than shortening one.
    """
    # 5% margin: CHARS_PER_TOKEN is a corpus average and a pool that happens to be
    # heavy on digits or OCR garbage tokenizes worse than average.
    budget = int((CTX_TOKENS - THINK_TOKENS) * CHARS_PER_TOKEN * 0.95)
    ladder = (DOC_CHARS,) if DOC_CHARS is not None else CAP_LADDER
    for cap in ladder:
        prompt = _render(question, pool, cap, max_picks)
        if len(prompt) <= budget:
            return prompt
    return prompt


async def acall_llm(
    prompt: str,
    thinking: bool = False,
    timeout: int = 600,
    max_tokens: int | None = None,
) -> str:
    """Single-turn completion. Kept as a named function because `generator` and two
    probe scripts call it directly with a bare prompt."""
    return await achat(
        [{"role": "user", "content": prompt}],
        thinking=thinking,
        max_tokens=max_tokens,
        timeout=timeout,
    )


def call_llm(
    prompt: str,
    thinking: bool = False,
    timeout: int = 600,
    max_tokens: int | None = None,
) -> str:
    return run_sync(acall_llm(prompt, thinking, timeout, max_tokens))


def parse_picks(raw: str, n_pool: int, max_picks: int = MAX_PICKS) -> list[int]:
    """Pull the index list out of the reply, tolerating prose and think blocks."""
    raw = raw.split("</think>")[-1]
    match = re.search(r'"picks"\s*:\s*\[([^\]]*)\]', raw)
    body = match.group(1) if match else raw
    picks, seen = [], set()
    for tok in re.findall(r"\d+", body):
        i = int(tok)
        if i < n_pool and i not in seen:
            seen.add(i)
            picks.append(i)
    return picks[:max_picks]


class Judge:
    """LLM judge stage, holding pick-cap and default-thinking as instance state
    rather than module globals -- the same shape as `EmbeddingClient`/
    `RerankerClient` in `retrievers.clients`, so `CandidateRetriever` can take a
    judge instance the way it takes a dense backend or reranker.
    """

    def __init__(
        self,
        *,
        max_picks: int = MAX_PICKS,
        thinking: bool = True,
        max_tokens: int | None = None,
    ) -> None:
        self.max_picks = max_picks
        self.thinking = thinking
        # None keeps `core.llm`'s own default (256 without thinking), which is ample for
        # the bare-JSON reply PROMPT asks for -- measured 12 completion tokens. A judge
        # variant whose prompt asks for anything before the JSON has to raise this, or the
        # reply is truncated before the JSON and `parse_picks` scrapes digits out of prose.
        self.max_tokens = max_tokens

    def build_prompt(self, question: str, pool: list[tuple[str, str]]) -> str:
        return build_prompt(question, pool, self.max_picks)

    async def apick(
        self, question: str, pool: list[tuple[str, str]], *, thinking: bool | None = None
    ) -> list[str]:
        """Pool of (key, doc_text) -> keys the LLM considers evidence, best first.

        `thinking` defaults to the instance's default: without it the model fills
        the pick quota with junk (recall@15 69.3% vs 84-89%). It costs ~15x the
        latency, which retrieval can afford because the whole batch waits
        concurrently on one event loop.

        Returns [] if the call fails; the caller decides whether to fall back to
        the retrieval order rather than having that policy buried here.
        """
        thinking = self.thinking if thinking is None else thinking
        try:
            raw = await acall_llm(
                self.build_prompt(question, pool),
                thinking=thinking,
                max_tokens=self.max_tokens,
            )
        except httpx.HTTPStatusError as exc:
            # Loud, because the one time this fired it was a context overflow that
            # cost a question outright and looked like a judge quality problem for
            # two runs.
            print(f"  judge HTTP {exc.response.status_code}: {exc.response.text[:300]!r}")
            return []
        except (httpx.HTTPError, TimeoutError, OSError) as exc:
            print(f"  judge call failed: {exc}")
            return []
        return [pool[i][0] for i in parse_picks(raw, len(pool), self.max_picks)]

    def pick(
        self, question: str, pool: list[tuple[str, str]], *, thinking: bool | None = None
    ) -> list[str]:
        return run_sync(self.apick(question, pool, thinking=thinking))


_default_judge = Judge()


async def ajudge(
    question: str, pool: list[tuple[str, str]], thinking: bool = True
) -> list[str]:
    """Free-function form of `Judge().apick`, for the offline probe scripts."""
    return await _default_judge.apick(question, pool, thinking=thinking)


def judge(
    question: str, pool: list[tuple[str, str]], thinking: bool = True
) -> list[str]:
    return run_sync(ajudge(question, pool, thinking))
