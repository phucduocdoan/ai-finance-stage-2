"""PoT vs CoT on the questions codegen actually handles.

BTC's own deck (docs/competition/_2026__AIGuru___Finance_Tabular_QA 1.pdf p39) reports
that every model under 10B they tested answers *better* with chain-of-thought than with
program-of-thought -- Qwen3-4B 4.64% -> 11.56%, Qwen2.5-Coder-7B 0.30% -> 9.49%,
Granite-4.1-3B 2.08% -> 9.09% -- and that PoT syntax-crash rate at that size reaches
99%. We serve Qwen3.5-9B and every answer in this repo comes from PoT; `grep` finds no
chain-of-thought path anywhere in `src/finance_qa`. So the claim has never been tested
here, which is what this script is for.

Scope, and it is deliberately narrow. The five deterministic solvers are not in
question: they already win 33 of the 73 gold questions and they do not write code, so
PoT-vs-CoT says nothing about them. Only the 40 questions that fall through to
`codegen` are contested, and those are the ones scored here. Evidence is held fixed by
replaying `diag.evidence_tables` out of the control run -- the exact table ids codegen
was shown, in the order it saw them -- so the *only* difference between the arms is
whether the model writes a pandas expression or reasons in prose.

Control arm costs nothing: the codegen answers are already in the artifact.

The CoT prompt follows the deck's own CoT contract (p34): exactly one numeric value,
Vietnamese number conventions, unsigned differences as a non-negative absolute value,
no intermediate rounding, final answer rounded to 2 decimals.

One consequence to keep in view when reading the result: a CoT answer has no
`pandas_query` behind it, so an all-CoT submission would score ~0 on
EXECUTION_ACCURACY (currently 0.3024 against ANSWER_ACCURACY 0.3043). This gate
measures the answering ceiling, not a drop-in replacement.

Result, 2026-08-21, `Qwen3.5-9B`, max_tokens 3072 (artifacts/runs/gate_cot_3072.json):

    PoT (control)   22/40
    CoT             23/40      churn floor, CoT vs CoT: 4 questions
    CoT (again)     23/40

One question apart, against a floor of four: at this checkpoint CoT does not beat PoT,
and p39 does not reproduce. The likely reason is the one p39 could not account for --
our PoT is not naive, it has a repair loop, `verify_answer`, and five solvers in front
of it.

The finding worth keeping is the second-order one. The two strategies overlap on only
15 of 40, union 30/40, and *where they agree they are right*: 15/15 and then 17/17,
32 for 32 with no false positive. Agreement adds no points by itself -- PoT was already
right on those -- but it is a cheap, precise detector for the 25 questions that are not
trustworthy, 15 of which have a correct answer sitting in one of the two arms. That is
where an arbiter call would pay, and the oracle ceiling of picking correctly is 52 ->
60 of 73. Caveats: n=32 is small, and agreement is biased toward easy questions, which
is why it works as a difficulty signal and also why 100% will not survive a bigger set.

Run:
  LLM_MODEL=Qwen3.5-9B PYTHONPATH=src:scripts .venv_bge/bin/python scripts/gate_cot.py
  ... --limit 8          # smoke
  ... --repeat           # second CoT arm, for the churn floor
  ... --max-tokens 1536  # the too-small budget the first run used; see MAX_TOKENS
"""

import _bootstrap  # noqa: F401

import argparse
import asyncio
import json
import re
from pathlib import Path

from finance_qa.core.llm import achat
from finance_qa.modules.data.table_store import load_frame
from finance_qa.modules.solve.common.context import table_context

from score_gold75 import close, load_gold, TOL

CONTROL = Path("artifacts/runs/gold73_qwen35_planner.jsonl")

# Straight from the deck's CoT template (p34). The output constraint is the part that
# matters most: without "chỉ một dòng cuối", a 9B model ends on a sentence and the
# number scraper picks up a year or an intermediate product instead of the answer.
COT_SYSTEM = """Bạn là trợ lý phân tích báo cáo tài chính Việt Nam.

Bạn được cho câu hỏi và toàn bộ nội dung các bảng bằng chứng. Số ở đầu mỗi dòng lưới
là vị trí dòng đó.

Hãy suy luận từng bước, ngắn gọn:
1. Xác định ô số liệu nào câu hỏi cần, ở bảng nào, dòng nào, cột nào.
2. Đọc giá trị thô đúng như in trong bảng.
3. Thực hiện phép tính cần thiết.
4. Đổi về đơn vị mà câu hỏi yêu cầu.

Quy ước bắt buộc:
- Định dạng số Việt Nam: dấu `.` phân cách hàng nghìn, dấu `,` là thập phân.
  "38.446.527.451" là 38446527451.
- Số trong ngoặc là số âm: "(500.000)" là -500000.
- Đơn vị: nếu bảng khai báo "Triệu VND" hay "Tỷ VND" thì phải nhân lại trước khi đổi.
- Chênh lệch KHÔNG có hướng ("chênh lệch", "cách biệt") thì lấy trị tuyệt đối, không âm.
  Chênh lệch CÓ hướng ("tăng", "giảm", "so với") thì giữ nguyên dấu.
- KHÔNG làm tròn ở bước trung gian. Chỉ làm tròn kết quả cuối cùng 2 chữ số thập phân.
- Nếu bảng in 12,5 cho 12,5% thì phần trăm là 12.5.

DÒNG CUỐI CÙNG phải đúng định dạng sau, không gì khác:
Answer: <một số duy nhất>

Ở dòng đó dùng dấu `.` làm dấu thập phân và KHÔNG dùng dấu phân cách hàng nghìn:
viết `1041601` chứ không phải `1.041.601`, viết `53.82` chứ không phải `53,82`.
Không đơn vị, không ký hiệu, không Markdown ở dòng đó."""

# 1536 was the first guess and it was too small: at that budget 6 of 40 replies in one
# arm and 12 of 40 in the next ran out of tokens mid-reasoning, 3.3-4.9k chars in, before
# reaching their `Answer:` line -- and a truncated reply scores as whatever number happens
# to be last, which is noise. Every `scraped` case was a truncation, none was the model
# ignoring the format. So the cap is a parameter now, and the reported result uses 3072.
MAX_TOKENS = 3072

# `Answer:` first, and only then fall back. The fallback exists because a truncated
# reply has no marker line at all, and scoring those as None would hide the truncation
# rate inside the accuracy number instead of reporting it.
_ANSWER_LINE = re.compile(r"Answer:\s*([-+]?[\d.,]*\d)", re.IGNORECASE)
_ANY_NUMBER = re.compile(r"[-+]?\d[\d.,]*")


def parse_answer(raw: str) -> tuple[float | None, str]:
    """(value, how) -- `how` distinguishes a clean marker from a scraped tail."""
    if not raw:
        return None, "empty"
    matches = _ANSWER_LINE.findall(raw)
    if matches:
        value = _to_float(matches[-1])
        if value is not None:
            return value, "marker"
    tail = _ANY_NUMBER.findall(raw)
    for token in reversed(tail):
        value = _to_float(token)
        if value is not None:
            return value, "scraped"
    return None, "no number"


def _to_float(token: str) -> float | None:
    """Read a number the model may have written in either convention.

    The prompt asks for a plain float, and mostly gets one, but the model is reasoning
    about Vietnamese tables and drifts into their format -- the first smoke run answered
    q120 with `1.041.601`, which is 1041601 and was being thrown away.

      `1.234,56`     comma present -> `.` is thousands, `,` is decimal.  Unambiguous.
      `208.253.200`  two or more dots and no comma -> all thousands.     Unambiguous.
      `1.041`        one dot, exactly three digits after -> thousands.   A guess, but the
                     prompt asks for two decimals, so a 3-digit tail is the separator.
      `53.82`        anything else -> plain decimal.
    """
    token = token.strip().rstrip(".")
    if not token:
        return None
    if "," in token:
        token = token.replace(".", "").replace(",", ".")
    elif token.count(".") > 1 or re.fullmatch(r"[-+]?\d{1,3}\.\d{3}", token):
        token = token.replace(".", "")
    try:
        return float(token)
    except ValueError:
        return None


def build_prompt(question: str, table_ids: list[str]) -> tuple[str, int]:
    """Question + the same grids codegen saw. Returns (prompt, n_tables_loaded)."""
    blocks = []
    for i, table_id in enumerate(table_ids, 1):
        try:
            frame = load_frame(table_id)
        except Exception:  # noqa: BLE001 - a table codegen could not read either
            continue
        blocks.append(table_context(f"df{i}", table_id, frame, grid=True))
    return f"Câu hỏi: {question}\n\n" + "\n\n".join(blocks), len(blocks)


async def acot(question: str, table_ids: list[str], max_tokens: int) -> dict:
    prompt, n_tables = build_prompt(question, table_ids)
    try:
        raw = await achat(
            [{"role": "system", "content": COT_SYSTEM},
             {"role": "user", "content": prompt}],
            thinking=False,
            max_tokens=max_tokens,
        )
    except Exception as exc:  # noqa: BLE001 - reported per question, run continues
        return {"answer": None, "how": f"error: {type(exc).__name__}", "n_tables": n_tables}
    value, how = parse_answer(raw or "")
    return {"answer": value, "how": how, "n_tables": n_tables,
            "chars": len(raw or ""), "raw_tail": (raw or "")[-160:]}


async def run_arm(records: list[dict], workers: int, max_tokens: int) -> dict[int, dict]:
    limit = asyncio.Semaphore(workers)

    async def one(rec: dict) -> tuple[int, dict]:
        async with limit:
            tables = (rec.get("diag") or {}).get("evidence_tables") or []
            return rec["id"], await acot(rec["question"], list(tables), max_tokens)

    return dict(await asyncio.gather(*(one(r) for r in records)))


def _off_by_scale(pred, gold_answer) -> bool:
    """Right digits, wrong unit -- the answer is a power of 1000 away from gold.

    Worth counting separately: it is not a reasoning failure, it is the unit re-scaling
    step, and it is fixable in the prompt rather than by changing strategy.
    """
    if pred is None:
        return False
    return any(close(pred, gold_answer * s, TOL)
               for s in (1e-9, 1e-6, 1e-3, 1e3, 1e6, 1e9))


def gold_values() -> dict[int, float]:
    """qid -> gold as a float. Three of the 73 are year strings ('2019'), as in
    `score_gold75.score`, which coerces at the comparison instead of at load."""
    return {qid: float(row["gold_answer"]) for qid, row in load_gold().items()}


def report(label: str, results: dict[int, dict], gold: dict[int, float]) -> set[int]:
    hits = {qid for qid, res in results.items()
            if qid in gold and close(res["answer"], gold[qid], TOL)}
    scraped = sum(1 for r in results.values() if r["how"] == "scraped")
    missing = sum(1 for r in results.values() if r["answer"] is None)
    scale = sum(1 for qid, r in results.items()
                if qid not in hits and qid in gold
                and _off_by_scale(r["answer"], gold[qid]))
    print(f"  {label:<22}{len(hits):>3}/{len(results):<4}"
          f"  no-number {missing:>2}  scraped {scraped:>2}  off-by-1000x {scale:>2}")
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="first N contested questions (smoke)")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--repeat", action="store_true", help="second CoT arm (churn floor)")
    ap.add_argument("--max-tokens", type=int, default=MAX_TOKENS)
    ap.add_argument("--out", type=Path, default=Path("artifacts/runs/gate_cot.json"))
    args = ap.parse_args()

    gold = gold_values()
    records =[json.loads(l) for l in CONTROL.read_text(encoding="utf-8").splitlines() if l.strip()]
    contested = [r for r in records if r["solver"] == "codegen" and r["id"] in gold]
    if args.limit:
        contested = contested[: args.limit]
    print(f"control: {CONTROL.name}")
    print(f"contested (solver=codegen, gold known): {len(contested)} of {len(records)}\n")

    pot = {r["id"]: {"answer": (r.get("item") or {}).get("answer"), "how": "pot"}
           for r in contested}
    print(f"  {'arm':<22}{'hit':>3}/{'n':<4}")
    pot_hits = report("PoT (control)", pot, gold)

    arms = {"CoT": asyncio.run(run_arm(contested, args.workers, args.max_tokens))}
    if args.repeat:
        arms["CoT (again)"] = asyncio.run(
            run_arm(contested, args.workers, args.max_tokens)
        )
    cot_hits = {name: report(name, res, gold) for name, res in arms.items()}

    first = cot_hits["CoT"]
    print(f"\n  PoT only : {sorted(pot_hits - first)}")
    print(f"  CoT only : {sorted(first - pot_hits)}")
    print(f"  both     : {len(pot_hits & first)}")
    print(f"  union    : {len(pot_hits | first)}/{len(contested)}")
    if "CoT (again)" in cot_hits:
        second = cot_hits["CoT (again)"]
        moved = (first - second) | (second - first)
        print(f"  churn floor (CoT vs CoT): {len(moved)} moved {sorted(moved)}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(
        {"contested": [r["id"] for r in contested],
         "pot_hits": sorted(pot_hits),
         "arms": {n: {str(k): v for k, v in res.items()} for n, res in arms.items()}},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
