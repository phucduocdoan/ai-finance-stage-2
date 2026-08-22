"""Vì sao `selection_facts` từ chối 123 câu sàng lọc, bóc theo nguyên nhân thật.

`diag["capability_router"]` ghi lý do từ chối, và trên 210 câu sàng lọc thì 123 câu
cùng một lý do "no max/min selection marker". Con số đó vô dụng, vì đọc
`deterministic_selection_plan` (selection_facts.py:544-567) thì lý do ấy được trả về
trong bốn tình huống khác nhau: dưới 2 mã, `len(years) != 1`, không bắt được chỉ số nào
trong catalog, hoặc nhánh aggregate từ chối bằng đúng `_NO_GROUP_FILTER` (lúc đó lý do
riêng của nó bị ghi đè). Bốn cái đó cần bốn cách sửa khác nhau.

Gate này gọi thẳng `deterministic_selection_plan` chứ không đọc lại chuỗi lý do, rồi
tách 123 câu kia theo nguyên nhân thật và đếm điểm từng nhóm trên tập eval sạch.

Hai chỗ phải dựng lại vì bản ghi run không lưu:

- `tickers`: đọc từ report_id trong `record["table_ids"]`, đúng cách
  `gate_sign_replay.py:42-48` làm. Lọc cứng chỉ cho qua bảng khớp scope, nên tập report
  *là* danh sách mã understand chọn.
- `years`: **xấp xỉ**. understand lấy năm từ LLM (`understand.py:141`, `result.years`
  rồi `expand_years`), không phải hàm thuần, nên ở đây năm được vét từ văn bản câu hỏi
  rồi cho qua đúng `expand_years` đó. Xấp xỉ này quan trọng vì chính nó quyết định cửa
  `len(years) == 1`, nên con số nhóm "len(years) != 1" phải đọc như chặn trên.

Dùng:
    PYTHONPATH=src:scripts .venv_bge/bin/python scripts/gate_selection_reasons.py
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

from score_clean_eval import correct, load_labels, load_submission  # type: ignore

from finance_qa.agents.finance.utils import expand_years
from finance_qa.modules.solve.solvers.selection_facts import (
    _metric_occurrences,
    deterministic_selection_plan,
)

sys.path.insert(0, "scripts")
from gate_screening_class import is_screening  # noqa: E402

SUBMISSION = "output/submission_v9_sign/submission.json"
RUN = Path("artifacts/runs/full1012_v7.jsonl")
OUT = Path("artifacts/runs/gate_selection_reasons.out")
TICKER_IN_REPORT = re.compile(r"([A-Z0-9]{2,5})_financial_statements_")
YEAR = re.compile(r"(?:19|20)\d{2}")
NO_MAX_MIN = "no max/min selection marker"


def state_of(record: dict) -> dict:
    question = " ".join(str(record.get("question") or "").split())
    return {
        "question": question,
        "tickers": sorted(set(TICKER_IN_REPORT.findall(" ".join(record.get("table_ids") or [])))),
        "years": expand_years([int(y) for y in YEAR.findall(question)]),
        "unit_hint": "",
        "doc_type": "",
    }


def sub_cause(state: dict) -> str:
    """Nguyên nhân thật khi plan trả về "no max/min selection marker"."""
    tickers, years = state["tickers"], state["years"]
    if len(tickers) < 2:
        return f"dưới 2 mã (đọc được {len(tickers)})"
    if len(years) != 1:
        return f"len(years) = {len(years)}"
    if not _metric_occurrences(state["question"]):
        return "không có chỉ số nào trong catalog"
    return "nhánh aggregate từ chối: no group filter to aggregate over"


def main() -> int:
    labels = load_labels()
    sub = load_submission(SUBMISSION)
    scored = {i for i, g in labels.items() if g.get("answer") is not None and i in sub}
    records = [json.loads(l) for l in RUN.read_text().splitlines() if l.strip()]
    screening = [r for r in records if is_screening(" ".join(str(r.get("question") or "").split()))]

    def score(ids: list[int]) -> str:
        ids = [i for i in ids if i in scored]
        ok = sum(correct(sub[i].get("answer"), labels[i]["answer"]) for i in ids)
        return f"{ok}/{len(ids)}" if ids else "-"

    plans: dict[str, list[int]] = {}
    causes: dict[str, list[int]] = {}
    years_seen: Counter[int] = Counter()
    for record in screening:
        qid = int(record["id"])
        state = state_of(record)
        plan = deterministic_selection_plan(state)
        key = f"{plan.operation}: {plan.reason}" if not plan.supported else f"CHẠY ĐƯỢC: {plan.operation}"
        plans.setdefault(key, []).append(qid)
        if not plan.supported and plan.reason == NO_MAX_MIN:
            causes.setdefault(sub_cause(state), []).append(qid)
            years_seen[len(state["years"])] += 1

    lines: list[str] = []

    def emit(text: str) -> None:
        print(text)
        lines.append(text)

    emit(f"\n{len(screening)} câu sàng lọc, gọi thẳng deterministic_selection_plan\n")
    for key, ids in sorted(plans.items(), key=lambda kv: -len(kv[1])):
        emit(f"  {len(ids):>4}  {score(ids):<7} {key}")

    emit(f"\nbóc nhóm \"{NO_MAX_MIN}\":\n")
    for cause, ids in sorted(causes.items(), key=lambda kv: -len(kv[1])):
        emit(f"  {len(ids):>4}  {score(ids):<7} {cause}")
        emit(f"        {sorted(ids)}")
    emit(f"\nphân bố số năm vét được trong nhóm đó: {dict(sorted(years_seen.items()))}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
