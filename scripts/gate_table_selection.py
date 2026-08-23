"""Trục cuối chưa đo: bảng nào của báo cáo được đọc.

Ba trục của một tham chiếu ô đã có số. Báo cáo: `b411f8e`, 66/70 câu sai vốn đã có
đủ báo cáo gold. Dòng: `docs/row_match_2026-08-23.md`, vượt sàn nhiễu ~3 câu. Cột:
`docs/cell_ref_fuzzy_2026-08-23.md`, dưới sàn nhiễu. Còn lại: trong một báo cáo có
~75 bảng, v9 đọc bảng nào.

**Sàn nhiễu ở đây rất cao và phải nói trước.** Một báo cáo có ~75 bảng × ~50 dòng ×
~4 cột × 7 hệ số là hàng trăm nghìn cơ hội trúng gold trong sai số 1%. Nên phép đo
siết hai lần: chỉ nhận dòng mà **nhãn dòng được câu hỏi phủ >= 60% token** (hướng
ngược với `lookup._score`: ở đây câu hỏi dài, nhãn ngắn, nên đo nhãn được phủ chứ
không đo câu hỏi được phủ), và luôn chạy cùng phép đo trên câu v9 **đang đúng** làm
đối chứng.

Ba tầng, siết dần theo chỗ bảng nằm:

1. bảng v9 đã đọc (`evidence`) — đây là baseline, không phải khoảng trống
2. bảng có trong shortlist đã nộp (`relevant_tables`) mà v9 không đọc
3. bảng của báo cáo gold mà cả shortlist cũng không có

Tầng 2 là khoảng trống chọn bảng. Tầng 3 là khoảng trống shortlist.

Dùng:
    PYTHONPATH=src:scripts .venv_bge/bin/python scripts/gate_table_selection.py
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from finance_qa.core.paths import QUESTION_METADATA_PATH, TABLE_METADATA_PATH
from finance_qa.modules.data.table_store import load_frame
from finance_qa.modules.solve.common.lookup import _norm, label_column
from score_clean_eval import as_float, correct, load_labels

SUBMISSION = Path("output/submission_v9_sign/submission.json")
CSV_PATH = re.compile(r"data/(?P<rid>.+)_table_(?P<pos>\d+)\.csv")
FACTORS = (1.0, 1e-3, 1e-6, 1e-9, 1e3, 1e6, 1e9)
LABEL_COVERAGE = 0.6   # phần token của nhãn dòng phải có mặt trong câu hỏi
MIN_LABEL_TOKENS = 2   # nhãn một từ khớp bừa, không tính


def covered(label: str, question_tokens: set[str]) -> bool:
    tokens = _norm(label).split()
    if len(tokens) < MIN_LABEL_TOKENS:
        return False
    return sum(1 for t in tokens if t in question_tokens) / len(tokens) >= LABEL_COVERAGE


def yields_gold(table_id: str, question_tokens: set[str], gold: float) -> bool:
    """Bảng này có dòng nào câu hỏi gọi tên, mà một ô của dòng đó ra gold không?"""
    try:
        df = load_frame(table_id)
    except Exception:  # noqa: BLE001 - một CSV không đọc được không được giết phép đo
        return False
    if df.empty or df.shape[1] < 2:
        return False
    first = label_column(df)
    tol = max(0.01, abs(gold) * 0.01)
    for position, raw_label in enumerate(df[first]):
        if not covered(str(raw_label), question_tokens):
            continue
        row = df.iloc[position]
        for col in df.columns:
            if col == first:
                continue
            v = as_float(row[col])
            if v is None:
                v = as_float(str(row[col]).replace(".", "").replace(",", "").replace(" ", ""))
            if v is None:
                continue
            if any(abs(v * f - gold) <= tol for f in FACTORS):
                return True
    return False


def main() -> None:
    records = {str(r["id"]): r for r in json.loads(SUBMISSION.read_text(encoding="utf-8"))}
    gold_labels = {str(k): v for k, v in load_labels().items()}

    def gold_of(qid: str):
        g = gold_labels[qid]
        return g.get("answer") if isinstance(g, dict) else g

    tables_by_report: dict[str, list[str]] = defaultdict(list)
    for line in TABLE_METADATA_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            tables_by_report[d["report_id"]].append(f"{d['report_id']}|{d['table_pos']}")

    # Báo cáo gold suy ra từ metadata câu hỏi, không từ retrieval của v9: nếu lấy
    # theo v9 thì phép đo không thể phát hiện chính lỗi của v9.
    reports_of: dict[str, set[str]] = {}
    for line in QUESTION_METADATA_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        reports_of[str(d.get("id"))] = {
            rid
            for t in (d.get("tickers") or [])
            for y in (d.get("years") or [])
            for dt in ("consolidated", "separate")
            if (rid := f"{t}_financial_statements_{y}_{dt}") in tables_by_report
        }

    scorable = sorted(
        (q for q in gold_labels if q in records and as_float(gold_of(q)) is not None),
        key=int,
    )
    print(f"{len(scorable)} câu chấm được\n")

    # Số bảng ứng viên phải đếm cùng, không chỉ số câu trúng. Câu v9 sai dồn vào tier
    # nhiều công ty / nhiều năm, nên nó chạm nhiều báo cáo hơn, nên rổ "còn lại" của
    # nó to hơn, nên nó trúng gold ngẫu nhiên nhiều hơn. Không kiểm chỗ này thì tỉ lệ
    # 46% so với 35% đọc thành khoảng trống trong khi nó chỉ là rổ to hơn.
    tallies = {
        name: {"read": 0, "shortlist": 0, "report": 0, "n": 0,
               "n_read": 0, "n_shortlist": 0, "n_report": 0}
        for name in ("v9 sai ", "v9 đúng")
    }
    for qid in scorable:
        rec = records[qid]
        g = as_float(gold_of(qid))
        question_tokens = set(_norm(rec.get("question") or "").split())
        read = {
            f"{m.group('rid')}|{m.group('pos')}"
            for ev in (rec.get("evidence") or [])
            if (m := CSV_PATH.match(ev.get("csv_path") or ""))
        }
        shortlist = set(rec.get("relevant_tables") or []) - read
        rest = {t for rid in reports_of.get(qid, ()) for t in tables_by_report[rid]}
        rest -= read | shortlist
        if not read and not shortlist and not rest:
            continue
        bucket = tallies["v9 đúng" if correct(rec.get("answer"), gold_of(qid)) else "v9 sai "]
        bucket["n"] += 1
        for key, ids in (("read", read), ("shortlist", shortlist), ("report", rest)):
            bucket[f"n_{key}"] += len(ids)
            if any(yields_gold(t, question_tokens, g) for t in sorted(ids)):
                bucket[key] += 1

    print("Có dòng mà câu hỏi gọi tên, và một ô của dòng đó ra gold:\n")
    print(f"{'':9} {'n':>4} {'bảng đã đọc':>14} {'shortlist':>12} {'còn lại của bc':>16}")
    for name, t in tallies.items():
        n = t["n"] or 1
        print(f"{name:9} {t['n']:>4} "
              f"{t['read']:>7} {t['read'] / n:>6.0%} "
              f"{t['shortlist']:>5} {t['shortlist'] / n:>6.0%} "
              f"{t['report']:>9} {t['report'] / n:>6.0%}")
    print("\nSố bảng ứng viên trung bình mỗi câu (rổ to hơn thì trúng ngẫu nhiên nhiều hơn):")
    print(f"{'':9} {'đã đọc':>8} {'shortlist':>11} {'còn lại':>10}")
    for name, t in tallies.items():
        n = t["n"] or 1
        print(f"{name:9} {t['n_read'] / n:>8.1f} {t['n_shortlist'] / n:>11.1f}"
              f" {t['n_report'] / n:>10.1f}")

    print("\nTỉ lệ trúng trên mỗi bảng ứng viên, tức đã chuẩn hóa theo cỡ rổ:")
    for name, t in tallies.items():
        for key in ("read", "shortlist", "report"):
            per = t[key] / t[f"n_{key}"] if t[f"n_{key}"] else 0.0
            print(f"  {name} {key:>9}: {per:.4f}")

    print("\nCột 'shortlist' là khoảng trống chọn bảng; cột 'còn lại' là khoảng trống"
          " shortlist.\nSo hai dòng với nhau, không đọc con số tuyệt đối: dòng 'v9 đúng'"
          " là sàn nhiễu.")


if __name__ == "__main__":
    main()
