"""Regression tests for deterministic metric -> row-label hints."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from finance_qa.modules.solve.codegen.codegen import build_prompt
from finance_qa.modules.solve.common.metric_hints import (
    metric_hints,
    metric_search_labels,
    render_metric_hints,
)


def check(name: str, condition: bool) -> None:
    print(f"{'ok  ' if condition else 'FAIL'} {name}")
    if not condition:
        raise AssertionError(name)


Q363 = ("Trong giai đoạn 2016-2020, vào năm KBC có tỷ số D/E cao nhất, "
        "hệ số khả năng thanh toán lãi vay là bao nhiêu lần?")
Q439 = ("Trong giai đoạn 2018-2024 của HPG, xét các năm có biên lợi nhuận gộp "
        "thấp hơn mức trung vị. ROE của năm có tỷ lệ dòng tiền thuần từ hoạt động "
        "kinh doanh trên doanh thu thuần cao nhất là bao nhiêu phần trăm?")
Q45 = "Tổng nợ phải trả của công ty mẹ BAB đến ngày 31/12/2020 là bao nhiêu triệu đồng?"


names = [h.name for h in metric_hints(Q363)]
check("D/E alias selects debt-to-equity", any("D/E" in name for name in names))
check("ICR alias selects interest coverage", any("lãi vay" in name for name in names))

rendered = render_metric_hints(Q363)
check("D/E rows name liabilities", "Nợ phải trả" in rendered)
check("D/E rows name equity", "Vốn chủ sở hữu" in rendered)
check("ICR rows name interest expense", "Chi phí lãi vay" in rendered)
check("D/E search expands to primitive row labels",
      metric_search_labels(Q363)[:2] == ["Tổng nợ phải trả", "Nợ phải trả"])

names = [h.name for h in metric_hints(Q439)]
check("question text can select several metrics", len(names) >= 3)
check("gross margin selected", any("Biên lợi nhuận gộp" in name for name in names))
check("ROE selected", "ROE" in names)
check("CFO/DTT selected", "CFO/DTT" in names)

check("structured metric selects without textual alias",
      [h.name for h in metric_hints("Doanh nghiệp nào tốt hơn?", metric="quick_ratio")]
      == ["Hệ số thanh toán nhanh"])
check("single-cell liability lookup does not get D/E hint", metric_hints(Q45) == [])
check("no hint renders empty string", render_metric_hints(Q45) == "")
check("single-cell liability lookup does not expand", metric_search_labels(Q45) == [])

frames = {"df1": pd.DataFrame({"Chỉ tiêu": ["NỢ PHẢI TRẢ", "VỐN CHỦ SỞ HỮU"], "2020": [3, 2]})}
names = {"df1": "KBC_financial_statements_2020_consolidated|9"}
check("build_prompt keeps hints off by default",
      "Gợi ý cách đọc chỉ tiêu" not in build_prompt(Q363, frames, names))
check("build_prompt can opt into hints",
      "Gợi ý cách đọc chỉ tiêu" in build_prompt(Q363, frames, names, use_metric_hints=True))

print("tất cả PASS")
