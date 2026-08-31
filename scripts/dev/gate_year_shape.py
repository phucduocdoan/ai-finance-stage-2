"""Câu hỏi "năm nào": pipeline trả về một số tiền, gold là một cái năm.

53 câu trong 1.012 hỏi *năm nào* một chỉ tiêu đạt cực trị. `raw_selection_linker`
trả đúng dạng năm cho 17/18 câu nó nhận, bằng thủ pháp `(<ô thắng>) * 0 + <năm>` —
query chạy lại vẫn ra năm nên `EXECUTION_ACCURACY` không vỡ. Còn `codegen` (28 câu)
và `selection_facts` (7 câu) trả về giá trị của ô thắng, tức sai theo định nghĩa.
Cả 35 câu đó đã được đọc tay: không câu nào mơ hồ, tất cả đều hỏi một cái năm.

Vấn đề đo lường: chỉ 3/35 câu có gold, và 2 trong đó do `raw_selection_linker` giải
đúng rồi. Nên không thể chấm điểm một prototype — không có đáp án để so. Gate này
làm việc khác: lấy **ý kiến thứ hai độc lập**. Mô hình chỉ thấy câu hỏi và đúng
những bảng bằng chứng pipeline đã thấy, và chỉ được trả về một cái năm. Đem so với
năm suy ngược ra từ `pandas_query` của pipeline.

Chỗ hai bên đồng thuận là bằng chứng mạnh, theo đúng kết quả đã đo của
`gate_cot.py`: nơi PoT và CoT đồng ý thì 32/32 đúng, không một dương tính giả nào.
Chỗ bất đồng là danh sách phải soi tay để dựng gold thật.

Prompt cố ý để trung tính. Không nhắc gì tới chuyện dòng chi phí in số âm nên
"cao nhất" phải so theo độ lớn, dù q879 đang chọn năm có giá trị âm nhất-gần-0 —
nhét gợi ý đó vào sẽ làm hỏng chính phép so sánh mà gate này cần.

Phân nhóm cấu trúc (từ `pandas_query` + năm trong report_id của evidence):
    A  18 câu  có max() qua nhiều năm       -> có năm suy ngược để so
    Y  13 câu  bằng chứng chỉ chạm 1 năm    -> không có gì để so sánh
    X   3 câu  giá trị 0, hỏng sâu
    B   1 câu  nhiều năm, không có max()

Nhóm Y là phép thử ngược quan trọng: nếu prototype cũng trả sai trên chính bộ bằng
chứng đó, thì 13 câu ấy là lỗi *chọn bằng chứng* chứ không phải lỗi dạng đáp án, và
bước chiếu năm không cứu được chúng.

Chạy:
  LLM_MODEL=Qwen3.5-9B PYTHONPATH=src:scripts .venv_bge/bin/python scripts/gate_year_shape.py
  ... --limit 4      # smoke, chạy cái này trước
  ... --bucket A     # chỉ nhóm có năm suy ngược
"""

import _bootstrap  # noqa: F401

import argparse
import asyncio
import json
import re
from pathlib import Path

import pandas as pd

from finance_qa.core.llm import achat
from finance_qa.modules.data.table_store import load_frame
from finance_qa.modules.solve.common.context import table_context

from score_gold75 import load_gold

RUN = Path("artifacts/runs/full1012_v7.jsonl")

YEAR_QUESTION = re.compile(r"n[aă]m n[aà]o", re.I)
YEAR_VALUE = re.compile(r"^(19|20)\d\d$")
YEAR_IN_ID = re.compile(r"_(20\d\d)_")
CSV_NAME = re.compile(r"([A-Za-z0-9_]+)_table_(\d+)\.csv$")
TERM = re.compile(r"df\d+\.iloc\[[^\]]+\]\[[^\]]+\]")
DFN = re.compile(r"df\d+")
HAS_MAX = re.compile(r"\b(max|min|idxmax)\s*\(")

SYSTEM = """Bạn là trợ lý phân tích báo cáo tài chính Việt Nam.

Bạn được cho một câu hỏi và toàn bộ nội dung các bảng bằng chứng. Số ở đầu mỗi dòng
lưới là vị trí dòng đó. Câu hỏi này hỏi MỘT NĂM, không hỏi một số tiền.

Quy ước đọc số:
- Định dạng Việt Nam: dấu `.` phân cách hàng nghìn, dấu `,` là thập phân.
  "38.446.527.451" là 38446527451.
- Số trong ngoặc là số âm: "(500.000)" là -500000.
- Nếu bảng khai "Triệu VND" hay "Tỷ VND" thì phải quy về cùng đơn vị trước khi so sánh.
- Mỗi bảng thuộc về một năm; tên bảng có chứa năm của nó.

Hãy suy luận ngắn gọn: xác định chỉ tiêu câu hỏi nhắc tới, đọc giá trị của nó ở từng
năm được liệt kê trong câu hỏi, rồi so sánh.

Nếu bằng chứng không đủ để so sánh tất cả các năm mà câu hỏi liệt kê, hãy trả lời
`Answer: unknown` thay vì đoán.

DÒNG CUỐI CÙNG phải đúng định dạng sau, không gì khác:
Answer: <một năm gồm 4 chữ số>

Ví dụ: `Answer: 2022`. Không đơn vị, không giải thích, không Markdown ở dòng đó."""

_ANSWER_LINE = re.compile(r"Answer:\s*(unknown|\d{4})", re.IGNORECASE)
_ANY_YEAR = re.compile(r"\b(19|20)\d\d\b")


def parse_year(raw: str) -> tuple[str | None, str]:
    """(năm, cách lấy được). Phân biệt dòng marker sạch với việc cào từ đuôi."""
    if not raw:
        return None, "empty"
    marker = _ANSWER_LINE.findall(raw)
    if marker:
        value = raw[raw.upper().rfind("ANSWER:") :].split(":", 1)[1].strip().split()[0]
        return (None, "unknown") if value.lower().startswith("unknown") else (value[:4], "marker")
    tail = _ANY_YEAR.findall(raw)
    if tail:
        # findall trả về group, cần quét lại để lấy cả 4 chữ số
        years = re.findall(r"\b(?:19|20)\d\d\b", raw)
        return years[-1], "scraped"
    return None, "no year"


def evidence_map(rec: dict) -> dict[str, str]:
    """dfN -> table_id, dựng từ đường dẫn csv trong submission item."""
    out: dict[str, str] = {}
    for ev in rec["item"].get("evidence") or []:
        m = CSV_NAME.search(ev.get("csv_path", ""))
        if m:
            out[ev["variable"]] = f"{m.group(1)}|{m.group(2)}"
    return out


def implied_year(rec: dict) -> str | None:
    """Năm mà pipeline *ngụ ý* đã thắng, suy ngược từ query.

    Chỉ đọc được khi giá trị mỗi năm nằm gọn trong một hạng tử. Với những câu mà giá
    trị một năm là tổng nhiều dòng (q1008), hạng tử lớn nhất không phải năm thắng, nên
    hàm này trả None thay vì đoán bừa — thà thiếu còn hơn so sai.
    """
    query = str(rec["item"].get("pandas_query") or "")
    if not HAS_MAX.search(query):
        return None
    ev = evidence_map(rec)
    try:
        frames = {v: load_frame(t) for v, t in ev.items()}
    except Exception:  # noqa: BLE001 - câu này không suy ngược được, không phải lỗi gate
        return None
    values: dict[str, float] = {}
    for term in TERM.findall(query):
        try:
            values[term] = float(eval(term, {"pd": pd}, frames))  # noqa: S307
        except Exception:  # noqa: BLE001 - ô không đọc được thì bỏ qua hạng tử đó
            continue
    if not values:
        return None
    # Tổng các hạng tử khác hẳn đáp án đã submit => giá trị mỗi năm là một tổng,
    # không phải một ô, nên hạng tử lớn nhất không nói lên năm nào thắng.
    best = max(values, key=lambda k: values[k])
    submitted = rec["item"].get("answer")
    if isinstance(submitted, (int, float)) and submitted:
        if abs(values[best] - float(submitted)) / max(abs(float(submitted)), 1.0) > 0.01:
            return None
    var = DFN.search(best).group(0)
    m = YEAR_IN_ID.search(ev.get(var, ""))
    return m.group(1) if m else None


def bucket_of(rec: dict) -> str:
    ev = evidence_map(rec)
    years = {m.group(1) for t in ev.values() if (m := YEAR_IN_ID.search(t))}
    query = str(rec["item"].get("pandas_query") or "")
    answer = rec["item"].get("answer")
    if not answer:
        return "X"
    if len(years) < 2:
        return "Y"
    return "A" if HAS_MAX.search(query) else "B"


def targets() -> list[dict]:
    """35 câu hỏi năm mà pipeline trả về một thứ không phải năm."""
    out = []
    for line in RUN.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        if not YEAR_QUESTION.search(rec["question"]):
            continue
        if rec.get("solver") not in {"codegen", "selection_facts"}:
            continue
        head = str(rec["item"].get("answer")).split(".")[0]
        if YEAR_VALUE.match(head):
            continue
        out.append(rec)
    return sorted(out, key=lambda r: r["id"])


def build_prompt(question: str, table_ids: list[str]) -> tuple[str, int]:
    blocks = []
    for i, table_id in enumerate(table_ids, 1):
        try:
            frame = load_frame(table_id)
        except Exception:  # noqa: BLE001 - bảng pipeline cũng không đọc được
            continue
        blocks.append(table_context(f"df{i}", table_id, frame, grid=True))
    return f"Câu hỏi: {question}\n\n" + "\n\n".join(blocks), len(blocks)


async def ask(rec: dict, max_tokens: int) -> dict:
    tables = list((rec.get("diag") or {}).get("evidence_tables") or [])
    prompt, n_tables = build_prompt(rec["question"], tables)
    try:
        raw = await achat(
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
            thinking=False,
            max_tokens=max_tokens,
        )
    except Exception as exc:  # noqa: BLE001 - báo theo câu, cả run vẫn chạy tiếp
        return {"year": None, "how": f"error: {type(exc).__name__}", "n_tables": n_tables}
    year, how = parse_year(raw or "")
    return {"year": year, "how": how, "n_tables": n_tables, "chars": len(raw or "")}


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="smoke: chỉ chạy N câu đầu")
    ap.add_argument("--bucket", default="", help="lọc theo nhóm A/B/X/Y")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--max-tokens", type=int, default=2048)
    ap.add_argument("--out", default="artifacts/runs/gate_year_shape.json")
    args = ap.parse_args()

    recs = targets()
    if args.bucket:
        recs = [r for r in recs if bucket_of(r) in set(args.bucket)]
    if args.limit:
        recs = recs[: args.limit]
    print(f"{len(recs)} câu, {args.workers} luồng, max_tokens={args.max_tokens}")

    gold = load_gold()
    limit = asyncio.Semaphore(args.workers)

    async def one(rec: dict) -> tuple[int, dict]:
        async with limit:
            return rec["id"], await ask(rec, args.max_tokens)

    results = dict(await asyncio.gather(*(one(r) for r in recs)))

    agree = disagree = no_ref = unknown = 0
    lines = []
    for rec in recs:
        qid = rec["id"]
        res = results[qid]
        ref = implied_year(rec)
        g = gold.get(qid)
        gold_year = str(g["gold_answer"]).split(".")[0] if g else None
        if res["year"] is None:
            verdict, unknown = "prototype không trả năm", unknown + 1
        elif ref is None:
            verdict, no_ref = "không suy ngược được năm của pipeline", no_ref + 1
        elif res["year"] == ref:
            verdict, agree = "ĐỒNG THUẬN", agree + 1
        else:
            verdict, disagree = "BẤT ĐỒNG", disagree + 1
        mark = ""
        if gold_year:
            mark = f"  [gold={gold_year}: prototype {'đúng' if res['year'] == gold_year else 'SAI'}]"
        lines.append(
            f"  q{qid:<5}{bucket_of(rec)}  pipeline={ref or '-':<6}prototype={res['year'] or '-':<6}"
            f"({res['how']}, {res['n_tables']} bảng)  {verdict}{mark}"
        )
    print("\n".join(lines))
    print(f"\nđồng thuận {agree}   bất đồng {disagree}   "
          f"không có tham chiếu {no_ref}   prototype bỏ trống {unknown}")
    print("\nĐồng thuận là bằng chứng, không phải chứng minh. Bất đồng là danh sách soi tay.")

    Path(args.out).write_text(
        json.dumps({str(r["id"]): {**results[r["id"]], "bucket": bucket_of(r),
                                   "implied": implied_year(r)} for r in recs},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"đã ghi {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
