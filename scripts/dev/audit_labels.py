"""Kiểm tra nhãn của agent bằng chính OCR thô, thay vì tin lời agent.

Phép kiểm duy nhất đáng tin là: **con số agent khai có thật sự nằm trong file OCR không**.

Không kiểm chuỗi trích dẫn nguyên văn -- mỗi agent chuẩn hoá một kiểu (giữ HTML `<tr><td>`,
hay đổi sang tab), nên so chuỗi chỉ đo phong cách chứ không đo tính trung thực. Con số thì
không chuẩn hoá được: `1.097.119.148.438` phải có mặt trong file, hoặc agent đã bịa.

  R  mọi `report_id` khai ra đều trỏ tới file `_extracted.txt` có thật
  V  số dài nhất trong `raw_cell_value` xuất hiện trong một trong các file đó
  Q  mọi số trong `ocr_quote` đều xuất hiện trong một trong các file đó

Dùng: .venv_bge/bin/python scripts/audit_labels.py artifacts/eval_clean/labels_*.jsonl
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path("ViFinQA/financial_statements")
TICKER = re.compile(r"\b([A-Z0-9]{2,4})_financial_statements")
YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
# Số kiểu Việt Nam: nhóm nghìn bằng '.', thập phân bằng ','. Cần >=4 ký tự để bỏ qua
# mã chỉ tiêu ("110", "6.2") vốn trùng ngẫu nhiên với mọi thứ.
NUMBER = re.compile(r"\d[\d.,]{3,}")

_cache: dict[Path, str] = {}


def squeeze(s: str) -> str:
    """Bỏ mọi khoảng trắng: OCR hay chèn xuống dòng giữa các ô của một hàng."""
    return re.sub(r"\s+", "", s)


def resolve(report_id: str) -> tuple[set[str], list[Path]]:
    """Trả về (mã đã khai, các file OCR khớp).

    Agent khai `report_id` theo nhiều kiểu: một id, nhiều id ngăn bằng ';' hay '/',
    ngoặc nhọn nhiều năm (`VCB_financial_statements_{2018,2020}_separate`), thiếu hậu tố
    riêng/hợp nhất, hậu tố `_1` khi OCR tách file, và loại `_aggregated`. Thay vì cố khớp
    từng dạng, ta chỉ rút mã + năm + loại rồi tra thư mục.
    """
    s = str(report_id or "")
    tickers = set(TICKER.findall(s))
    years = set(YEAR.findall(s))
    kinds = [k for k in ("separate", "consolidated", "aggregated") if k in s]
    files: list[Path] = []
    for t in tickers:
        for y in years or [d.name for d in (ROOT / t).iterdir()] if (ROOT / t).is_dir() else []:
            for f in (ROOT / t / y).rglob("*_extracted.txt") if (ROOT / t / y).is_dir() else []:
                if not kinds or any(k in f.name for k in kinds):
                    files.append(f)
    return tickers, files


def text_of(files: list[Path]) -> str:
    for f in files:
        if f not in _cache:
            _cache[f] = squeeze(f.read_text(errors="ignore"))
    return "".join(_cache[f] for f in files)


def audit_one(d: dict) -> dict:
    r = {"id": d["id"], "answer": d.get("answer"), "conf": d.get("confidence")}
    tickers, files = resolve(d.get("report_id"))
    r["n_reports"] = len(files)
    r["R"] = bool(tickers) and bool(files)
    if not files or d.get("answer") is None:
        r["V"] = r["Q"] = None
        return r
    blob = text_of(files)

    def found(nums: list[str]) -> float | None:
        """Tỉ lệ số tra ngược được về OCR.

        Không đòi hết: câu nhiều công ty thường kèm cả tổng do agent tự cộng, và tổng đó
        theo định nghĩa không có trong file. Nhưng nếu **phần lớn** số khai ra không tìm
        thấy thì nhãn không truy ngược được, bất kể lý do.
        """
        nums = [n for n in nums if len(n) >= 5]
        return sum(squeeze(n) in blob for n in nums) / len(nums) if nums else None

    r["v"] = found(NUMBER.findall(str(d.get("raw_cell_value") or "")))
    r["q"] = found(NUMBER.findall(str(d.get("ocr_quote") or "")))
    r["V"] = None if r["v"] is None else r["v"] >= 0.5
    r["Q"] = None if r["q"] is None else r["q"] >= 0.5
    return r


def main() -> int:
    rows = []
    for p in sys.argv[1:]:
        for line in Path(p).read_text().splitlines():
            if line.strip():
                rows.append(audit_one(json.loads(line)))
    bad = [r for r in rows if False in (r["R"], r["V"], r["Q"])]
    if bad:
        print(f"{'id':>5} {'R':>6} {'%raw':>6} {'%quote':>7} {'#rp':>4} {'conf':>7}  answer")
        for r in sorted(bad, key=lambda x: x["id"]):
            pv = "-" if r.get("v") is None else f"{r['v']:.0%}"
            pq = "-" if r.get("q") is None else f"{r['q']:.0%}"
            print(f"{r['id']:>5} {str(r['R']):>6} {pv:>6} {pq:>7} "
                  f"{r['n_reports']:>4} {str(r['conf']):>7}  {r['answer']}")
    n = len(rows)
    print(f"\n{n} nhãn | sạch: {n - len(bad)} | cần soi tay: {len(bad)}")
    print(f"  R sai (report_id không tồn tại) : {sum(1 for r in rows if r['R'] is False)}")
    print(f"  V sai (số khai không có trong OCR): {sum(1 for r in rows if r['V'] is False)}")
    print(f"  Q sai (số trong trích dẫn không có): {sum(1 for r in rows if r['Q'] is False)}")
    print(f"  answer null                      : {sum(1 for r in rows if r['answer'] is None)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
