"""Đo phễu (funnel) của cổng `cell_locator` trên 37 câu L1 của tập eval sạch.

`cell_locator` (src/finance_qa/modules/solve/solvers/cell_locator.py) là solver
xác định một cell duy nhất. `build_request` (dòng 208-235) lọc câu hỏi qua năm
điều kiện theo đúng thứ tự code, rồi `locate_single_cell` (dòng 356-414) tìm
hàng/cột thật trên bảng và áp bốn điều kiện nữa trước khi nhận (`done=True`).

Script này KHÔNG gọi LLM, KHÔNG chạy pipeline, chỉ đọc dữ liệu đã có sẵn trên
đĩa. Điều đó để lại một lỗ hổng đo lường thật, không giả lập được:

  - `tickers`/`years`/`multi_year`/`multi_company`/`doc_type`/`answer_shape`
    trong state thật đến từ node `understand` (một lệnh gọi LLM). Ở đây chúng
    được thay bằng cột cùng tên trong `data/metadata/questions_enriched.jsonl`,
    tức đầu ra của `modules/data/preprocessing/questions.py::enrich()` — một
    pipeline rule-based khác, không phải LLM và không phải cái `understand`
    dùng khi chạy thật (ngoại lệ: `tickers` dùng đúng `find_tickers`, cũng là
    hàm `understand` gọi, nên cột này khớp state thật; các cột năm/doc_type/
    answer_shape là XẤP XỈ, có thể lệch với state LLM thật của v9).
  - `operation` (lookup/formula/compare/multi_step) không có mặt trong
    `questions_enriched.jsonl` — không có cách nào tái tạo ngoại tuyến. Điều
    kiện 4 (`operation not in {"", "lookup"} and answer_shape != "single_cell"`)
    được ép luôn qua bằng cách đặt `operation=""`, nên script này KHÔNG đếm câu
    nào bị điều kiện 4 loại — cột đó ghi "không đo được", không phải "0 câu".
  - `metric` (chuỗi gợi ý từ LLM) không có; đặt `metric=""`. `direct_metric_phrases`
    vẫn chạy hàm thật trên chuỗi câu hỏi nên vẫn bắt được cụm từ chính, chỉ mất
    nhánh alias-theo-metric-key.
  - Danh sách bảng đưa vào `locate_single_cell(table_ids=..., shortlist=...)`
    lấy từ `relevant_tables` của submission đã nộp — đây là danh sách CUỐI
    CÙNG sau khi executor đã chạy xong, không phải shortlist retrieval lúc
    `cell_locator` thực sự nhìn thấy (shortlist gốc rộng hơn, ~106 bảng qua hard
    filter). Dùng nó là theo đúng yêu cầu đo ("bảng mà run đã nộp thực sự có"),
    nhưng số bảng thật cell_locator từng thấy khi chạy có thể nhiều hơn.

Vì hai lỗ hổng trên, số "claimed" ở đây là ước lượng, không phải con số chạy
thật của solver trên submission đã nộp (submission không lưu field `solver`).

Dùng:
    PYTHONPATH=src:scripts .venv_bge/bin/python scripts/gate_cell_locator_funnel.py \
        output/submission_v9_sign/submission.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from finance_qa.core.paths import QUESTION_METADATA_PATH, RAW_QUESTIONS_PATH  # noqa: E402
from finance_qa.modules.solve.solvers.cell_locator import (  # noqa: E402
    build_request,
    locate_single_cell,
)

from gate_type_split import level  # noqa: E402
from score_clean_eval import as_float, correct, load_labels, load_submission  # noqa: E402

# Thứ tự đúng như code, để in phễu theo cùng thứ tự build_request/locate_single_cell
# kiểm. "reason" là chuỗi y hệt cell_locator.py trả về, không viết lại.
STEPS: list[tuple[str, str]] = [
    ("P1", "needs exactly one ticker and one year"),
    ("P2", "multi-axis question"),
    ("P3", "derived or comparison marker"),
    ("P4", "not a lookup-shaped question"),
    ("P5", "no metric phrase"),
    ("S6", "no candidate tables"),
    ("S7", "no located numeric cell"),
    ("S8", "below confidence threshold"),
    ("S9", "ambiguous located cells"),
]
STEP_LABEL = {
    "P1": "P1 đúng 1 mã + 1 năm (proxy)",
    "P2": "P2 không multi-axis (proxy)",
    "P3": "P3 không có dấu hiệu derived/so sánh",
    "P4": "P4 lookup-shaped (ép qua, không đo được)",
    "P5": "P5 có cụm từ chỉ tiêu",
    "S6": "S6 có bảng ứng viên",
    "S7": "S7 tìm được cell số",
    "S8": "S8 vượt ngưỡng tin cậy 0.78",
    "S9": "S9 không mơ hồ (ambiguous)",
}


def load_enriched() -> dict[int, dict]:
    out: dict[int, dict] = {}
    with QUESTION_METADATA_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rec = json.loads(line)
                out[rec["id"]] = rec
    return out


def load_questions() -> dict[int, str]:
    out: dict[int, str] = {}
    with RAW_QUESTIONS_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rec = json.loads(line)
                out[rec["id"]] = rec["question"]
    return out


def build_state(qid: int, question: str, enriched: dict[int, dict]) -> dict:
    """State xấp xỉ cho một câu hỏi, xem giới hạn ở docstring đầu file."""
    e = enriched.get(qid, {})
    return {
        "question": question,
        "tickers": e.get("tickers") or [],
        "years": e.get("years") or [],
        "multi_year": bool(e.get("multi_year")),
        "multi_company": bool(e.get("multi_company")),
        "operation": "",  # ép qua P4, xem docstring
        "answer_shape": e.get("answer_shape") or "single_cell",
        "metric": "",
        "doc_type": e.get("doc_type") or "unknown",
        "unit_hint": e.get("unit_hint") or "",
    }


def run_gate(qid: int, question: str, table_ids: list[str], enriched: dict[int, dict]) -> str:
    """Trả về tên bước mà câu hỏi này dừng lại, hoặc "claimed"."""
    state = build_state(qid, question, enriched)
    request, reason = build_request(state)
    if request is None:
        return {v: k for k, v in STEPS}.get(reason, f"P?:{reason}")
    try:
        hit, diag = locate_single_cell(state, table_ids=table_ids, shortlist=[])
    except Exception as exc:  # noqa: BLE001 - ghi lại lỗi thay vì làm sập script đo
        return f"lỗi: {type(exc).__name__}: {exc}"
    if diag.get("done"):
        return "claimed"
    return {v: k for k, v in STEPS}.get(diag.get("reason", ""), f"S?:{diag.get('reason')}")


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    sub_path = sys.argv[1]
    labels = load_labels()
    questions = load_questions()
    enriched = load_enriched()
    sub = load_submission(sub_path)

    l1_ids = sorted(
        qid for qid, lab in labels.items()
        if as_float(lab.get("answer")) is not None and level(questions[qid]) == "L1"
    )
    print(f"L1 trong tập eval sạch: {len(l1_ids)} câu\n")

    stop_at: dict[int, str] = {}
    for qid in l1_ids:
        table_ids = list((sub.get(qid) or {}).get("relevant_tables") or [])
        stop_at[qid] = run_gate(qid, questions[qid], table_ids, enriched)

    # Phễu: đếm số câu còn sống sau từng bước, theo đúng thứ tự code.
    order = [s for s, _ in STEPS]
    alive = set(l1_ids)
    print("phễu (đúng thứ tự code, xem docstring cho các bước không đo được):")
    print(f"  bắt đầu                                    {len(alive):>3}")
    rejected_by_step: dict[str, list[int]] = {}
    for step in order:
        rejected = [q for q in alive if stop_at[q] == step]
        rejected_by_step[step] = rejected
        alive -= set(rejected)
        print(f"  sau {STEP_LABEL[step]:<38}{len(alive):>3}   (loại {len(rejected)})")
    # Câu lỗi (ngoại lệ khi chạy locate_single_cell), nếu có.
    errored = [q for q in alive if str(stop_at[q]).startswith("lỗi:")]
    if errored:
        alive -= set(errored)
        print(f"  lỗi khi chạy locate_single_cell            {len(alive):>3}   (lỗi {len(errored)})")
    claimed = sorted(q for q in alive if stop_at[q] == "claimed")
    print(f"  claimed                                    {len(claimed):>3}\n")

    worst = max(rejected_by_step, key=lambda s: len(rejected_by_step[s]))
    print(f"bước loại nhiều nhất: {STEP_LABEL[worst]} ({len(rejected_by_step[worst])} câu)\n")

    print("id bị loại theo từng bước:")
    for step in order:
        ids = rejected_by_step[step]
        if ids:
            print(f"  {step}: {ids}")
    if errored:
        print(f"  lỗi: {errored} -> {[stop_at[q] for q in errored]}")
    print(f"\nclaimed: {claimed}")

    # Câu 3: trong số L1 sai mà bảng gold đã có trong relevant_tables đã nộp,
    # cổng cell_locator claim được bao nhiêu.
    wrong_with_report_in_shortlist: list[int] = []
    for qid in l1_ids:
        lab = labels[qid]
        gold = as_float(lab.get("answer"))
        got = as_float((sub.get(qid) or {}).get("answer"))
        if correct(got, gold):
            continue
        report = str(lab.get("report_id") or "")
        shortlist_str = " ".join(str(t) for t in (sub.get(qid) or {}).get("relevant_tables") or [])
        if report and report in shortlist_str:
            wrong_with_report_in_shortlist.append(qid)

    claimed_of_wrong = [q for q in wrong_with_report_in_shortlist if stop_at[q] == "claimed"]
    print(
        f"\nL1 sai, gold report đã có trong relevant_tables đã nộp: "
        f"{len(wrong_with_report_in_shortlist)} câu -> {wrong_with_report_in_shortlist}"
    )
    print(
        f"trong số đó, cổng cell_locator claim: {len(claimed_of_wrong)} câu -> {claimed_of_wrong}"
    )


if __name__ == "__main__":
    main()
