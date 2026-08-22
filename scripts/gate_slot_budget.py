"""Độ phủ mã/năm của các bảng mà codegen thật sự được xem.

Tầng đo rẻ nhất của nhánh sàng lọc nhiều công ty: `codegen_budget` là hàm thuần,
nên chạy lại nó trên `relevant_tables` của một submission đã có là đo được chính xác
bảng nào sẽ nằm trước mặt model -- không gọi LLM, không chạy pipeline.

Nó **không** đo điểm. Phủ đủ mã chỉ là điều kiện cần: model vẫn phải đọc đúng hàng và
tính đúng. Nhưng câu không phủ đủ thì chắc chắn sai, nên đây là chặn trên rẻ, và nó
tách được hai câu hỏi vốn bị lẫn vào nhau -- "truy hồi có tìm được dữ liệu không" và
"model có dùng được dữ liệu không".

Dùng:
    PYTHONPATH=src .venv_bge/bin/python scripts/gate_slot_budget.py \
        output/submission_v8_round2/submission.json
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path

from finance_qa.agents.finance.config import FinanceAgentConfig
from finance_qa.agents.finance.graph import codegen_budget
from finance_qa.core.paths import QUESTION_METADATA_PATH

SLOT = re.compile(r"^([A-Z0-9]+)_financial_statements_(20\d\d)")


def slots_of(table_ids: list[str]) -> set[tuple[str, str]]:
    return {(m.group(1), m.group(2)) for m in map(SLOT.match, table_ids) if m}


def arms() -> list[tuple[str, FinanceAgentConfig, bool]]:
    """Ba nhánh: hiện trạng, trộn-mà-không-nới, và trộn-có-nới.

    Nhánh giữa là nhánh đáng quan tâm nhất khi chấm điểm cho kết quả trung tính: nó
    thay đổi *thứ tự* mà không nạp thêm bảng nào, nên nó không thể gánh cái giá mà
    `codegen_max_tables` đã đo được (10 bảng tệ hơn 3). Cái nó mua được ít hơn nhánh
    thứ ba, nhưng nó mua bằng không.
    """
    base = FinanceAgentConfig()
    # 12 viết thẳng ra đây, không đọc mặc định: mặc định đã chốt về 3 (bằng
    # `codegen_max_tables`, tức tắt phần nới) sau khi ba nhánh dưới đây cho điểm y hệt
    # nhau. Đọc mặc định sẽ làm nhánh thứ ba trùng nhánh thứ hai, và bảng số này mất
    # luôn nhánh đối chứng của chính nó.
    narrow = replace(base, codegen_max_tables_multi_company=base.codegen_max_tables)
    wide = replace(base, codegen_max_tables_multi_company=12)
    return [
        (f"hiện trạng ({base.codegen_max_tables} bảng, theo hạng)", narrow, False),
        (f"trộn, không nới ({base.codegen_max_tables} bảng)", narrow, True),
        ("trộn + nới (trần 12)", wide, True),
    ]


def measure(rows: list[dict], subs: dict[int, list[str]], cfg: FinanceAgentConfig,
            interleave: bool) -> dict:
    hit = Counter()
    loaded = []
    for r in rows:
        tickers = r.get("tickers") or []
        if len(tickers) < 2:
            continue
        table_ids = subs.get(r["id"])
        if not table_ids:
            hit["table_ids rỗng"] += 1
            continue
        state = {**r, "table_ids": table_ids}
        ordered, budget = codegen_budget(state, cfg)
        if not interleave:
            # Nhánh cũ: cắt thẳng đầu danh sách, không trộn.
            ordered = table_ids
        head = ordered[:budget]
        loaded.append(len(head))
        slots = slots_of(head)
        hit["phủ đủ mã" if set(tickers) <= {tk for tk, _ in slots} else "thiếu mã"] += 1
        # Độ phủ năm là cái bị đánh đổi: xếp công ty làm trục ngoài nghĩa là mọi công
        # ty xuất hiện trước khi công ty nào xuất hiện lần hai, nên câu vừa nhiều công
        # ty vừa nhiều năm sẽ mất năm trước khi mất công ty. Đo, đừng đoán.
        want_years = {str(y) for y in (r.get("years") or [])}
        if want_years:
            got_pairs = {(tk, y) for tk, y in slots}
            full = all(
                (tk, y) in got_pairs for tk in tickers for y in want_years
            )
            hit["  trong đó phủ đủ cả ô mã×năm" if full else "  thiếu ô mã×năm"] += 1
    n = hit["phủ đủ mã"] + hit["thiếu mã"] + hit["table_ids rỗng"]
    return {
        "n": n,
        "hit": hit,
        "bảng nạp trung vị": sorted(loaded)[len(loaded) // 2] if loaded else 0,
        "bảng nạp max": max(loaded) if loaded else 0,
    }


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    rows = [
        json.loads(line)
        for line in QUESTION_METADATA_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    subs = {
        int(it["id"]): it.get("relevant_tables") or []
        for it in json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    }
    for name, cfg, interleave in arms():
        r = measure(rows, subs, cfg, interleave)
        full = r["hit"]["phủ đủ mã"]
        print(f"\n{name}  ({r['n']} câu >= 2 mã)")
        print(f"  phủ đủ mọi mã : {full}/{r['n']} = {full / r['n']:.0%}")
        for key, val in sorted(r["hit"].items()):
            if key != "phủ đủ mã":
                print(f"  {key:<14}: {val}")
        print(f"  bảng nạp      : trung vị {r['bảng nạp trung vị']}, max {r['bảng nạp max']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
