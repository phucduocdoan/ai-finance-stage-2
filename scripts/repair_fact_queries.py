"""Thay `pandas_query` hằng số của các fact solver bằng biểu thức đọc thẳng ô CSV.

Luật cuộc thi (`final_submission.md`): "Không được gán cứng, mã hóa hoặc lưu sẵn
kết quả dưới bất kỳ hình thức nào. Các câu hỏi vi phạm quy định này sẽ không được
tính điểm." Ví dụ luật đưa ra là `result = 2.06`.

`execute_plan` tính đáp án bằng số học Python trên fact lấy từ parquet rồi ghi
`pandas_query = repr(answer)` kèm `evidence: []`. Đúng dạng bị cấm. Trên lần chạy
31/08 có 106/1012 câu như vậy: formula_facts 55, selection_facts 50, codegen 1.

`facts/cellexpr.py` đã sửa gốc, nhưng chỉ có tác dụng cho lần chạy mới. Các file
run đã có trên đĩa thì vá được ngay mà không cần gọi lại LLM, vì `diag` giữ nguyên
`plan` đã dùng: phát lại `execute_plan` với đúng plan đó là ra biểu thức.

Chỉ ghi đè khi đáp án phát lại trùng khít đáp án cũ (rel_tol 1e-9) và biểu thức
mới không còn là hằng số. Câu nào không định vị được ô thì giữ nguyên: vẫn vi phạm
luật, nhưng thà thế còn hơn ship biểu thức đọc nhầm ô rồi hỏng cả đáp án lẫn
`EXECUTION_ACCURACY`.

Chạy TRƯỚC `fill_from_arms.py` và `rescale_below_floor.py`: cả hai sửa `answer`
hoặc bọc `pandas_query`, phát lại sau đó sẽ lệch.

Dùng:
    PYTHONPATH=src .venv_bge/bin/python scripts/repair_fact_queries.py \
        artifacts/runs/full1012.jsonl artifacts/runs/full1012_repaired.jsonl
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter
from pathlib import Path

from finance_qa.modules.solve.facts.execute import execute_plan
from finance_qa.modules.solve.facts.schema import StructuredPlan

from rescale_below_floor import QUESTIONS, as_float, records

PLAN_KEYS = ("formula_facts", "selection_facts", "structured_facts")


def is_constant(query: object) -> bool:
    """Query chỉ là một con số, tức đáp án được gán cứng."""
    text = str(query or "").strip()
    return bool(text) and as_float(text) is not None


def questions() -> dict[int, dict]:
    return {
        int(json.loads(line)["id"]): json.loads(line)
        for line in QUESTIONS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def replayed(rec: dict, question: dict) -> dict | None:
    """Kết quả phát lại plan đã ghi trong diag, hoặc None nếu không phát lại được."""
    diag = rec.get("diag") or {}
    payload = next(
        (diag[key] for key in PLAN_KEYS if isinstance(diag.get(key), dict) and diag[key].get("plan")),
        None,
    )
    if payload is None:
        return None
    try:
        plan = StructuredPlan.model_validate(payload["plan"])
        return execute_plan(
            plan,
            question=str(question.get("question") or ""),
            unit_hint=str(question.get("unit_hint") or ""),
        )
    except Exception:
        return None


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    recs = records(src)
    meta = questions()

    stats: Counter[str] = Counter()
    for qid, rec in recs.items():
        item = rec.get("item") or {}
        if not is_constant(item.get("pandas_query")):
            continue
        stats["hằng số"] += 1
        result = replayed(rec, meta.get(qid) or {})
        if result is None:
            stats["không phát lại được"] += 1
            continue
        old = as_float(item.get("answer"))
        if old is None or not math.isclose(result["answer"], old, rel_tol=1e-9):
            stats["đáp án lệch"] += 1
            continue
        if is_constant(result["pandas_query"]):
            stats["không định vị được ô"] += 1
            continue
        item["pandas_query"] = result["pandas_query"]
        item["evidence"] = result["evidence"]
        stats["vá được"] += 1

    dst.write_text(
        "".join(json.dumps(recs[q], ensure_ascii=False) + "\n" for q in sorted(recs)),
        encoding="utf-8",
    )
    print(f"{dict(stats)} trên {len(recs)} câu -> {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
