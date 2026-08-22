"""Tách 73 câu sai của v8 thành lỗi *chọn bảng* và lỗi *đọc bảng*.

Nhãn clean eval mang theo `raw_cell_value` nguyên văn, ví dụ `444.917.590.949`. Chuỗi đó
đủ hiếm để tìm thẳng trong corpus: nó chỉ nằm ở đúng những bảng chứa ô gold. Đối chiếu tập
bảng đó với hai tầng bằng chứng của v8 cho ba nhóm rời nhau, không tốn lời gọi LLM nào:

- ngoài shortlist — retrieval không đưa bảng gold vào `table_ids`
- ngoài df       — có trong shortlist, nhưng solver không nạp thành `df1..dfN`
- đã nạp         — solver có bảng gold trong tay và vẫn trả sai, tức lỗi đọc/suy luận

Ba chỗ dễ đo sai, đã xử lý:

- Tập df là `diag.evidence_tables`, **không** phải `table_ids`. `table_ids` là shortlist
  rộng mà submission đem đi nộp làm `relevant_tables` (bằng đúng nó trên cả 1012 câu);
  solver chỉ nạp một nhóm nhỏ hơn. q32 có 8 bảng trong `table_ids` nhưng đúng 1 df.
- Phải quét theo mã cổ phiếu chứ không theo `report_id`. Câu hỏi nhiều năm chỉ được nhãn
  ghi một report: q866 hỏi 2018-2020 mà `report_id` chỉ có SJG_2018, hai trong ba số của
  nó nằm ở SJG_2019 và SJG_2020.
- So sánh trên chuỗi thô của CSV, không trên frame đã `normalize_frame`: hàm đó đổi ô
  thành float nên `200.405.269.967` không còn tồn tại dưới dạng chuỗi.

Dùng:
    .venv_bge/bin/python scripts/gate_selection_vs_reading.py
    .venv_bge/bin/python scripts/gate_selection_vs_reading.py --ids 20,684,866
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

from score_clean_eval import correct, load_labels  # type: ignore

RUN = Path("artifacts/runs/full1012_v7.jsonl")
SUBMISSION = Path("output/submission_v8_round2/submission.json")
TABLES = Path("data/tables")

# Số tiền kiểu Việt Nam. Đòi ít nhất hai nhóm nghìn (>= một triệu) để chuỗi đủ hiếm; hạ
# xuống một nhóm chỉ khi mẫu chặt không rút được gì, vì `22.743` khớp bừa rất nhiều bảng.
STRICT = re.compile(r"\d{1,3}(?:\.\d{3}){2,}")
LOOSE = re.compile(r"\d{1,3}(?:\.\d{3})+")
TICKER = re.compile(r"([A-Z0-9]{2,5})_financial_statements")


def tokens(label: dict) -> list[str]:
    """Các chuỗi số trong nhãn, đủ hiếm để định vị bảng.

    `ocr_quote` là dự phòng cho những nhãn mà `raw_cell_value` viết bằng lời ("tính từ
    nhiều số liệu ...") thay vì ghi con số.
    """
    for field in ("raw_cell_value", "ocr_quote"):
        text = str(label.get(field) or "")
        for pattern in (STRICT, LOOSE):
            found = sorted(set(pattern.findall(text)))
            if found:
                return found
    return []


@lru_cache(maxsize=None)
def ticker_dirs(ticker: str) -> tuple[Path, ...]:
    return tuple(sorted(TABLES.glob(f"{ticker}_financial_statements_*")))


@lru_cache(maxsize=None)
def holders(ticker: str, token: str) -> frozenset[str]:
    """Các `table_id` của mã này chứa nguyên văn `token`, mọi năm, mọi loại báo cáo."""
    out = set()
    for directory in ticker_dirs(ticker):
        for path in directory.glob("table_*.csv"):
            if token in path.read_text(encoding="utf-8", errors="replace"):
                out.add(f"{directory.name}|{path.stem.removeprefix('table_')}")
    return frozenset(out)


def locate(label: dict) -> dict[str, frozenset[str]]:
    """token -> tập bảng chứa nó, quét mọi mã cổ phiếu mà nhãn nhắc tới."""
    tickers = sorted(set(TICKER.findall(str(label.get("report_id") or ""))))
    if not tickers:
        return {}
    return {
        tok: frozenset().union(*(holders(t, tok) for t in tickers))
        for tok in tokens(label)
    }


GROUPS = ("đã nạp", "ngoài df", "ngoài shortlist", "không có df", "không dò được")


def classify(found: dict[str, frozenset[str]], loaded: set[str], shortlist: set[str]) -> str:
    """Nhóm của một câu, lấy theo token *tệ nhất*: thiếu một ô là thiếu bằng chứng."""
    located = [tabs for tabs in found.values() if tabs]
    if not located:
        return "không dò được"
    if any(not (tabs & shortlist) for tabs in located):
        return "ngoài shortlist"
    if not loaded:
        return "không có df"
    if any(not (tabs & loaded) for tabs in located):
        return "ngoài df"
    return "đã nạp"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", help="chỉ chạy các câu này, cách nhau bởi dấu phẩy")
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

    tally: Counter[tuple[bool, str]] = Counter()
    detail: dict[str, list[int]] = defaultdict(list)
    for i in ids:
        found = locate(labels[i])
        record = run.get(i, {})
        shortlist = set(record.get("table_ids") or [])
        loaded = set((record.get("diag") or {}).get("evidence_tables") or [])
        group = classify(found, loaded, shortlist)
        hit = correct(submission[i].get("answer"), labels[i]["answer"])
        tally[(hit, group)] += 1
        detail[f"{'đúng' if hit else 'sai '} / {group}"].append(i)

    print(f"{len(ids)} câu chấm được, bằng chứng lấy từ {RUN.name}\n")
    print(f"{'':<20}{'sai':>6}{'đúng':>7}{'tổng':>7}")
    for g in GROUPS:
        bad, good = tally[(False, g)], tally[(True, g)]
        if bad or good:
            print(f"{g:<20}{bad:>6}{good:>7}{bad + good:>7}")
    bad = sum(v for (h, _), v in tally.items() if not h)
    good = sum(v for (h, _), v in tally.items() if h)
    print(f"{'tổng':<20}{bad:>6}{good:>7}{bad + good:>7}\n")
    for key in sorted(detail):
        print(f"  {key:<26} {sorted(detail[key])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
