"""Câu sàng lọc mà selection_facts giải được (thật hoặc tái dựng): plan sai, hay số sai.

`gate_selection_reasons.py` đo `selection_facts` giải 48/1012 câu, điểm 1/5 trên tập
sạch, và trong 20 câu sàng lọc nó giải thì điểm 0/4. Riêng biệt, 40 câu sàng lọc khác
đã có plan `deterministic_selection_plan` báo "supported" (21 argmax, 12 argmin, 7
filter_aggregate) mà điểm 0/6 ở chỗ có nhãn. Trước khi mở rộng phạm vi giải cho
selection_facts, câu hỏi phải trả lời là: cái gãy nằm ở *plan* (đọc sai câu hỏi thành
đúng loại truy vấn) hay ở *số* (plan đúng nhưng StatementFactStore đọc sai ma_so).

Gate này duyệt đúng 6 câu có nhãn nằm trong hai nhóm trên (hợp của "solver ==
selection_facts" và "plan tái dựng supported"), rồi in cả chuỗi: câu hỏi -> plan ->
từng fact đọc từ StatementFactStore -> giá trị chọn -> so với nhãn.

Hai nguồn dữ liệu khác nhau cho mỗi câu:

- Nếu `record["solver"] == "selection_facts"`: plan/fact/giá trị đã CHẠY THẬT, đọc
  thẳng từ `diag["selection_facts"]` trong bản ghi run. Không tính lại gì cả.
- Nếu không (câu chỉ nằm trong nhóm "plan tái dựng supported" của
  `gate_selection_reasons.py`, tức thật ra do solver khác giải): plan chưa từng chạy
  thật, nên gate này TỰ CHẠY `execute_plan` trên plan tái dựng để xem nó đọc ra số gì
  hoặc lỗi gì. Đây là plan giả lập, không phải plan router thật đã dùng -- ghi rõ.

Việc "plan đúng hay sai" là đọc câu hỏi, máy không tự chấm được. Gate này in ra cờ máy
tính được (dùng chính các cụm từ trong `common/intent.py`: YEAR_ANSWER_MARKER cho câu
hỏi "vào năm nào", MEDIAN_FILTER_CUE/SIGN_FILTER_CUE/FILTER_MARKER cho predicate còn
trong câu nhưng plan.filters lại rỗng, TOP_N_CUE cho câu xin "N công ty ... nhất" mà
plan lại chọn đúng 1 người thắng) làm bằng chứng, cộng với verdict viết tay có lý do
cụ thể, để người đọc không phải tin lời mà có thể tự kiểm bằng cờ.

Dùng:
    PYTHONPATH=src:scripts .venv_bge/bin/python scripts/probe_selection_plans.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from score_clean_eval import correct, load_labels, load_submission  # type: ignore

sys.path.insert(0, "scripts")
from gate_screening_class import is_screening  # noqa: E402
from gate_selection_reasons import state_of  # noqa: E402

from finance_qa.modules.solve.common.intent import (
    FILTER_MARKER,
    MEDIAN_FILTER_CUE,
    SIGN_FILTER_CUE,
    YEAR_ANSWER_MARKER,
    intent_norm,
)
from finance_qa.modules.solve.facts.structured_facts import StructuredFactError, execute_plan
from finance_qa.modules.solve.solvers.selection_facts import deterministic_selection_plan

SUBMISSION = "output/submission_v9_sign/submission.json"
RUN = Path("artifacts/runs/full1012_v7.jsonl")
OUT = Path("artifacts/runs/probe_selection_plans.out")

# "3 doanh nghiệp có ... cao nhất" xin TOP N công ty, không phải một người thắng.
TOP_N_CUE = re.compile(
    r"\b\d+\s+(?:doanh\s+nghiep|cong\s+ty)\b.{0,40}"
    r"\b(?:cao\s+nhat|lon\s+nhat|thap\s+nhat|nho\s+nhat)\b"
)

# Verdict đọc câu hỏi mà ra -- không phải thứ máy tự suy được. Mỗi câu kèm bằng chứng
# cụ thể, và cờ máy tính ở phần in ra xác nhận từng bằng chứng đó có mặt trong câu hỏi
# hoặc trong plan.
VERDICT: dict[int, tuple[str, str]] = {
    410: (
        "plan sai",
        "Câu hỏi là lọc rồi chọn (D/E dưới trung vị nhóm, rồi ROE cao nhất trong số "
        "sống sót), nhưng khi có marker cao nhất/thấp nhất, deterministic_selection_plan "
        "chỉ gọi _filter() (ngưỡng số tuyệt đối) chứ không gọi _median_filters() -- "
        "filter rơi mất hoàn toàn (filters=[]), và _answer_metric quay ra gán nhầm "
        "de_ratio làm answer_metric, roe làm selector_metric, tức trả lời D/E của công "
        "ty ROE cao nhất chứ không trả lời ROE của công ty đạt điều kiện D/E.",
    ),
    467: (
        "plan sai",
        "Câu hỏi cần chọn TOP 3 công ty rồi tính tỉ trọng trên một metric khác (tiền và "
        "khoản tương đương tiền của cả nhóm), nhưng selection_facts chỉ biết chọn đúng 1 "
        "người thắng (argmax) và 'tiền và khoản tương đương tiền' không có alias trong "
        "catalog, nên answer_metric tụt về default là chính selector (gross_margin) -- "
        "plan trả lại biên lợi nhuận gộp của 1 công ty, không phải tỉ trọng tiền của 3.",
    ),
    492: (
        "plan sai",
        "Selector đúng ra là tỉ số CFO / lợi nhuận thuần HĐKD (một composite không có "
        "trong catalog), nhưng bị xấp xỉ thành 'cfo' thô -- ai có CFO tuyệt đối thấp nhất "
        "thắng, không phải ai có tỉ số thấp nhất. Filter 'lợi nhuận HĐKD dương' cũng rơi "
        "mất cùng lý do như câu 410: nhánh có marker chỉ gọi _filter(), không gọi "
        "_sign_filters().",
    ),
    842: (
        "plan sai (một phần)",
        "Chọn đúng năm (winner=2022, khớp nhãn) nên phần xếp hạng không sai, nhưng "
        "answer_metric bị gán là profit_before_tax thay vì chuỗi đặc biệt 'year' mà "
        "_execute_selection cần để trả năm thắng ra làm đáp án -- selection_facts.py "
        "không import YEAR_ANSWER_MARKER/TICKER_ANSWER_MARKER dù intent.py đã định nghĩa "
        "cả hai, nên không có nhánh nào nhận ra câu hỏi xin 'vào năm nào'.",
    ),
    376: (
        "plan sai",
        "Catalog chỉ đăng ký 'hệ số thanh toán hiện hành' / 'hệ số thanh toán nhanh' cho "
        "current_ratio/quick_ratio; câu hỏi dùng 'tỉ số thanh toán hiện hành' / 'tỉ số "
        "thanh toán nhanh' -- biến thể 'tỉ số' này không khớp alias nào, nên cả filter "
        "(current_ratio > 1.5) và selector (quick_ratio thấp nhất) đều không neo được, "
        "và plan tụt về metric gần marker nhất tình cờ khớp được (inventory_to_assets).",
    ),
    380: (
        "plan sai",
        "Câu hỏi cần chọn TOP 5 công ty theo doanh thu rồi đếm số công ty thoả ĐỒNG THỜI "
        "hai điều kiện (quick_ratio > 1 và de_ratio < 1.5). 'lớn nhất' bị đọc thành marker "
        "argmax 1-người-thắng, và cả hai filter đứng SAU marker trong câu nên _filter() "
        "không xét tới (chỉ xét match.start() < marker_pos) -- cả top-N và đếm-đồng-thời "
        "đều rơi mất.",
    ),
}


def fmt_plan(plan: dict) -> str:
    filters = [
        f"{f['metric']} {f['relation']} {f.get('value')} "
        f"({'trung vị' if f.get('value_source') == 'median' else 'literal'})"
        for f in (plan.get("filters") or [])
    ]
    return (
        f"operation={plan.get('operation')} axis={plan.get('axis')} "
        f"tickers={plan.get('tickers')} years={plan.get('years')}\n"
        f"    selector_metric={plan.get('selector_metric') or '-'} "
        f"selector_order={plan.get('selector_order') or '-'}\n"
        f"    answer_metric={plan.get('answer_metric') or plan.get('answer_expression') or '-'}\n"
        f"    filters={filters or '[]'}\n"
        f"    aggregation={plan.get('aggregation') or '-'}  target_unit={plan.get('target_unit') or '-'}"
    )


_TUONG_DUONG = re.compile(r"tuong\s+duong")


def _sign_cue_hit(norm_q: str) -> bool:
    # "tương đương" (equivalent, as in "tiền và các khoản tương đương tiền")
    # normalises to "... tuong duong ...", and SIGN_FILTER_CUE's bare "duong"
    # matches the tail of that on purpose (intent.py:170-174 says the bare-token
    # match is deliberate and disambiguation belongs to the caller). Guard the
    # one false-positive substring seen in this probe's 6 questions (q467)
    # rather than trust every bare hit.
    match = SIGN_FILTER_CUE.search(norm_q)
    return bool(match) and not _TUONG_DUONG.search(norm_q, max(0, match.start() - 6), match.end())


def mechanical_flags(question: str, plan: dict) -> list[str]:
    """Cờ tính được bằng máy, không cần đọc hiểu câu hỏi."""
    norm_q = intent_norm(question)
    flags = []
    if YEAR_ANSWER_MARKER.search(norm_q) and plan.get("answer_metric") != "year":
        flags.append("year-answer mismatch: câu xin 'vào năm nào' nhưng answer_metric != 'year'")
    predicate_cues = (
        MEDIAN_FILTER_CUE.search(norm_q)
        or _sign_cue_hit(norm_q)
        or FILTER_MARKER.search(norm_q)
    )
    if predicate_cues and not (plan.get("filters") or []):
        flags.append("predicate cue có trong câu nhưng plan.filters rỗng")
    if TOP_N_CUE.search(norm_q) and plan.get("operation") in {"argmax", "argmin"}:
        flags.append("câu xin top-N công ty nhưng plan chỉ chọn 1 người thắng (argmax/argmin)")
    return flags


def chain_from_diag(record: dict) -> tuple[dict, list[dict], dict, str]:
    """Plan/facts/selected đã chạy thật, đọc thẳng từ diag của bản ghi run."""
    sf = record["diag"]["selection_facts"]
    return sf["plan"], sf["facts"], sf["selected"], "thật (solver=selection_facts)"


def chain_from_simulation(record: dict) -> tuple[dict, list[dict], dict, str]:
    """Plan chưa từng chạy thật: tái dựng state rồi tự gọi execute_plan để xem nó ra gì."""
    state = state_of(record)
    plan = deterministic_selection_plan(state)
    try:
        out = execute_plan(plan, question=state["question"], unit_hint=state.get("unit_hint", ""))
        return plan.model_dump(), out["diag"]["facts"], out["diag"]["selected"], (
            f"giả lập (solver thật là {record.get('solver')}), chạy execute_plan thành công, "
            f"answer giả lập = {out['answer']}"
        )
    except StructuredFactError as exc:
        return plan.model_dump(), [], {}, (
            f"giả lập (solver thật là {record.get('solver')}), execute_plan LỖI: {exc}"
        )


def group_facts(facts: list[dict]) -> dict[tuple[str, int], list[dict]]:
    out: dict[tuple[str, int], list[dict]] = {}
    for f in facts:
        out.setdefault((f["ticker"], f["year"]), []).append(f)
    return out


def main() -> int:
    labels = load_labels()
    sub = load_submission(SUBMISSION)
    scored = {i for i, g in labels.items() if g.get("answer") is not None and i in sub}
    records = {
        int(r["id"]): r
        for r in (json.loads(l) for l in RUN.read_text().splitlines() if l.strip())
    }
    screening = {qid for qid, r in records.items() if is_screening(str(r.get("question") or ""))}

    solved = sorted(
        qid for qid in screening if records[qid].get("solver") == "selection_facts" and qid in scored
    )
    supported = []
    for qid in sorted(screening):
        if qid not in scored:
            continue
        plan = deterministic_selection_plan(state_of(records[qid]))
        if plan.supported:
            supported.append(qid)

    ids = sorted(set(solved) | set(supported))

    lines: list[str] = []

    def emit(text: str = "") -> None:
        print(text)
        lines.append(text)

    emit(f"\n{len(solved)} câu sàng lọc có nhãn do selection_facts giải thật: {solved}")
    emit(f"{len(supported)} câu sàng lọc có nhãn có plan tái dựng supported: {supported}")
    emit(f"hợp của hai nhóm: {len(ids)} câu -- {ids}\n")

    buckets: dict[str, list[int]] = {}
    for qid in ids:
        record = records[qid]
        question = str(record.get("question") or "")
        gold = labels[qid]["answer"]
        submitted = sub[qid].get("answer")
        real_solver = record.get("solver")

        emit("=" * 78)
        emit(f"q{qid}  {question}")
        emit(f"  solver thật: {real_solver}   nhãn: {gold}   submission: {submitted}   "
             f"đúng: {correct(submitted, gold)}")

        if real_solver == "selection_facts":
            plan, facts, selected, source = chain_from_diag(record)
        else:
            plan, facts, selected, source = chain_from_simulation(record)
        emit(f"  nguồn plan: {source}")
        emit(f"  plan: {fmt_plan(plan)}")

        flags = mechanical_flags(question, plan)
        for flag in flags:
            emit(f"  cờ máy: {flag}")

        if facts:
            emit("  fact đọc từ StatementFactStore (ticker, năm -> ma_so, nhãn dòng, giá trị):")
            for (ticker, year), rows in group_facts(facts).items():
                emit(f"    {ticker} {year}:")
                for row in rows:
                    emit(f"      ma_so={row['ma_so']:<5} {row['label']!r:<60} = {row['value']}")
        if selected:
            emit(f"  selected: {selected}")

        verdict, reason = VERDICT.get(qid, ("chưa xếp loại", "câu này không có verdict viết tay"))
        emit(f"  VERDICT: {verdict}")
        emit(f"    lý do: {reason}")
        buckets.setdefault(verdict, []).append(qid)

    emit("\nTổng kết theo verdict:")
    for verdict, qids in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
        emit(f"  {verdict:<20}{len(qids):>3} câu   {sorted(qids)}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
