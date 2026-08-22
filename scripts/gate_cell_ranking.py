"""Bộ chấm ô của `raw_table_linker` có xếp ô gold lên đầu không, đo offline.

`gate_selection_vs_reading.py` chỉ ra chỗ nghẽn là chọn ô, không phải chất lượng header:
44 câu mà bảng gold không vào được `df` thì sai cả 44, còn khi nó vào được thì pipeline
đúng 65%. Sáu câu có bảng gold ở *hạng 0* của shortlist mà solver vẫn không nạp, vì
`raw_table_linker` chấm theo ô chứ theo bảng, rồi chọn một dòng na ná ở báo cáo chính với
confidence 0.90+ (q164 lấy "Khấu hao TSCĐ và bất động sản đầu tư" thay cho "Trích khấu hao
trong năm"; q703 lấy "Các khoản phải thu ngắn hạn" thay cho số ròng với bên liên quan).

Gate này cô lập đúng bộ chấm đó. Scope (mã, năm, hợp nhất/riêng) lấy từ `report_id` của
nhãn, tức là **cho không** bước understand, nên mọi câu trượt ở đây là lỗi của riêng bộ
chấm. `build_request` và `build_candidates` đều xác định, nên gate không gọi LLM và chạy
lại được bao nhiêu lần cũng được.

Đọc kết quả:
- `hạng 0`     bộ chấm đã đúng, câu sai vì lý do khác
- `trong 12`   ô gold có trong pool production nhưng dưới một ô nhiễu -> sửa bộ chấm
- `ngoài 12`   pool production cắt mất nó -> `limit_per_slot` mới là chỗ chặn
- `ngoài pool` bước dựng ứng viên không sinh ra ô đó -> không phải việc của bộ chấm

Tách nhãn một ô và nhãn nhiều ô, vì gộp lại thì con số vô nghĩa: nhãn nhiều ô đòi *mọi*
thành phần lên hạng cao, mà q703 chẳng hạn cần cộng trừ 5 dòng thuyết minh bên liên quan.
Trượt ở đó là thiếu bước tổ hợp, không phải bộ chấm xếp sai.

Dùng:
    PYTHONPATH=src .venv_bge/bin/python scripts/gate_cell_ranking.py
    PYTHONPATH=src .venv_bge/bin/python scripts/gate_cell_ranking.py --ids 164,703 --show 8
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from score_clean_eval import correct, load_labels  # type: ignore

from finance_qa.modules.solve.solvers.raw_table_linker import build_candidates, build_request
from finance_qa.modules.tools.numeric import parse_number

RUN = Path("artifacts/runs/full1012_v7.jsonl")
SUBMISSION = Path("output/submission_v8_round2/submission.json")
# `build_candidates` cắt còn 12 ô mỗi slot trong production. Lấy rộng để thấy hạng thật,
# rồi so lại với 12 để biết cắt có phải chỗ chặn hay không.
PRODUCTION_LIMIT = 12
DEEP_LIMIT = 400
REPORT = re.compile(r"([A-Z0-9]{2,5})_financial_statements_(\d{4})(?:_([a-z]+))?")


def scope(label: dict) -> tuple[list[str], list[int], str]:
    """Mã, năm và loại báo cáo lấy thẳng từ nhãn, tức scope đúng được cho không."""
    hits = REPORT.findall(str(label.get("report_id") or ""))
    tickers = list(dict.fromkeys(t for t, _, _ in hits))
    years = list(dict.fromkeys(int(y) for _, y, _ in hits))
    kinds = {k for _, _, k in hits if k in {"consolidated", "separate"}}
    return tickers, years, kinds.pop() if len(kinds) == 1 else "unknown"


def gold_values(label: dict) -> list[float]:
    """Giá trị các ô gold, đọc từ `raw_cell_value`."""
    text = str(label.get("raw_cell_value") or "")
    out = []
    for token in dict.fromkeys(re.findall(r"\d{1,3}(?:\.\d{3})+", text)):
        value = parse_number(token)
        if value is not None:
            out.append(abs(value))
    return out


def rank_of(candidates: list, target: float) -> int | None:
    """Hạng của ứng viên đầu tiên khớp giá trị gold."""
    for index, candidate in enumerate(candidates):
        if candidate.value and abs(abs(candidate.value) - target) <= max(target * 1e-9, 0.5):
            return index
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", help="chỉ chạy các câu này, cách nhau bởi dấu phẩy")
    ap.add_argument("--show", type=int, default=0, help="in mấy ứng viên đầu của mỗi câu")
    args = ap.parse_args()

    labels = load_labels()
    submission = {int(it["id"]): it for it in json.loads(SUBMISSION.read_text())}
    run: dict[int, dict] = {}
    for line in RUN.read_text().splitlines():
        if line.strip():
            record = json.loads(line)
            run[record["id"]] = record

    ids = sorted(i for i in labels if labels[i].get("answer") is not None and i in submission)
    if args.ids:
        keep = {int(x) for x in args.ids.split(",")}
        ids = [i for i in ids if i in keep]

    tally: Counter[tuple[str, str]] = Counter()
    detail: dict[str, list[int]] = defaultdict(list)
    refused: Counter[str] = Counter()
    for i in ids:
        label, record = labels[i], run.get(i, {})
        targets = gold_values(label)
        tickers, years, doc_type = scope(label)
        request, reason = build_request(
            {"question": submission[i].get("question") or "", "tickers": tickers,
             "years": years, "doc_type": doc_type}
        )
        if not targets:
            group = "nhãn không có số"
        elif request is None:
            group = "linker không nhận"
            refused[reason] += 1
        else:
            candidates, _ = build_candidates(
                request, table_ids=record.get("table_ids") or [], limit_per_slot=DEEP_LIMIT
            )
            ranks = [rank_of(candidates, t) for t in targets]
            if any(r is None for r in ranks):
                group = "ngoài pool"
            else:
                worst = max(ranks)  # type: ignore[type-var]
                group = "hạng 0" if worst == 0 else (
                    f"trong {PRODUCTION_LIMIT}" if worst < PRODUCTION_LIMIT else f"ngoài {PRODUCTION_LIMIT}"
                )
            if args.show:
                print(f"\nq{i} gold {targets} hạng {ranks}  ({group})")
                for c in candidates[: args.show]:
                    print(f"  {c.score:.3f} {c.table_id} r{c.row_position} {c.column!r}"
                          f" = {c.value:.0f}  {c.row_label[:60]!r}")
        arity = "một ô" if len(targets) == 1 else "nhiều ô"
        hit = correct(submission[i].get("answer"), label["answer"])
        tally[(arity, group)] += 1
        detail[f"{arity:<8}{'đúng' if hit else 'sai '} / {group}"].append(i)

    print(f"\n{len(ids)} câu, scope cho không từ nhãn, không gọi LLM\n")
    order = ["hạng 0", f"trong {PRODUCTION_LIMIT}", f"ngoài {PRODUCTION_LIMIT}",
             "ngoài pool", "linker không nhận", "nhãn không có số"]
    print(f"{'':<20}{'một ô':>8}{'nhiều ô':>10}")
    for group in order:
        one, many = tally[("một ô", group)], tally[("nhiều ô", group)]
        if one or many:
            print(f"  {group:<18}{one:>8}{many:>10}")
    print()
    for key in sorted(detail):
        print(f"  {key:<34} {sorted(detail[key])}")
    if refused:
        print("\nlý do linker không nhận câu:")
        for reason, n in refused.most_common():
            print(f"  {n:>3}  {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
