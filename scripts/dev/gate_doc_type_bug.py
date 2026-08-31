"""Định giá lỗi thẻ `doc_type`: bao nhiêu báo cáo hỏng, và nó làm sai bao nhiêu câu.

Manh mối từ lượt gán nhãn B (`docs/label_calibration_2026-08-23.md`): có báo cáo gộp cả
bản riêng lẫn bản hợp nhất dưới một thẻ, và có báo cáo bị đảo thẻ. Trên q764 lỗi này gây
ra lỗi thật của pipeline.

Ba phép đo, theo thứ tự siết dần:

1. **Đếm báo cáo hỏng.** Dấu hiệu KHÔNG dùng: số bảng cùng loại. Một bảng cân đối bị OCR
   cắt qua hai trang cũng sinh nhiều bảng cùng loại, nên đếm bảng thổi phồng gấp ba
   (15% so với 5%). Dấu hiệu dùng: **nhãn dòng có lặp giữa hai bảng cùng loại không**.
   Gộp hai bộ thì nhãn lặp; cắt trang thì nhãn rời.
2. **Phơi nhiễm.** v9 có tệ hơn trên câu chạm báo cáo hỏng không.
3. **Cơ chế.** Trong câu v9 sai, có bao nhiêu câu mà một *bản sao khác của chính dòng đã
   dùng* lại cho ra gold, và bao nhiêu câu đang đúng sẽ bị một luật như thế đe dọa.

Phép đo 3 mới là phép quyết định; 1 và 2 chỉ khoanh vùng.

Dùng:
    PYTHONPATH=src:scripts .venv_bge/bin/python scripts/gate_doc_type_bug.py
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from finance_qa.core.paths import QUESTION_METADATA_PATH, TABLE_METADATA_PATH
from finance_qa.modules.data.table_store import load_frame
from score_clean_eval import as_float, correct, load_labels

SUBMISSION = Path("output/submission_v9_sign/submission.json")
DUP_THRESHOLD = 0.6  # giao nhãn dòng / tập nhỏ hơn
FACTORS = (1.0, 1e-3, 1e-6, 1e-9, 1e3, 1e6, 1e9)
CSV_PATH = re.compile(r"data/(?P<rid>.+)_table_(?P<pos>\d+)\.csv")
MINORITY = re.compile(
    r"c[oổ]\s*[đd][oô]ng\s+kh[oô]ng\s+ki[eể]m\s*so[aá]t"
    r"|l[oợ]i\s*[íi]ch\s+c[uủ]a\s+c[oổ]\s*[đd][oô]ng",
    re.I,
)
STATEMENTS = ("balance_sheet", "income_statement", "cash_flow")


def norm(s) -> str:
    return " ".join(str(s).lower().split())


def row_labels(table: dict) -> set[str]:
    """Nhãn dòng đủ dài để phân biệt; nhãn ngắn hay trùng ngẫu nhiên."""
    return {n for x in (table.get("first_col_labels") or []) if len(n := norm(x)) > 8}


def dup_ratio(tables: list[dict]) -> float | None:
    """Tỉ lệ nhãn dòng lặp lớn nhất giữa hai bảng cùng loại; None nếu không kiểm được."""
    sets = [s for t in tables if len(s := row_labels(t)) >= 5]
    if len(sets) < 2:
        return None
    best = 0.0
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            smaller = min(len(sets[i]), len(sets[j]))
            if smaller:
                best = max(best, len(sets[i] & sets[j]) / smaller)
    return best


def used_row_labels(rec: dict) -> tuple[set[str], set[tuple[str, int]]]:
    """Nhãn dòng mà `pandas_query` thật sự chạm, tra ngược từ chỉ số iloc."""
    idxs = [int(x) for x in re.findall(r"iloc\[(\d+)\]", rec.get("pandas_query") or "")]
    labels: set[str] = set()
    sources: set[tuple[str, int]] = set()
    for ev in rec.get("evidence") or []:
        m = CSV_PATH.match(ev.get("csv_path") or "")
        if not m:
            continue
        rid, pos = m.group("rid"), int(m.group("pos"))
        sources.add((rid, pos))
        try:
            frame = load_frame(f"{rid}|{pos}")
        except Exception:
            continue
        for i in idxs:
            if i < len(frame):
                labels.add(norm(frame.iloc[i, 0]))
    return labels, sources


def main() -> None:
    by_report: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for line in TABLE_METADATA_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            by_report[d["report_id"]][d.get("statement_type")].append(d)
    n_tables = sum(len(v) for by in by_report.values() for v in by.values())
    print(f"{n_tables} bảng, {len(by_report)} báo cáo\n")

    # 1. Đếm báo cáo hỏng.
    duplicated, split, unchecked = set(), 0, 0
    for rid, by_type in by_report.items():
        ratios = [r for st in STATEMENTS if (r := dup_ratio(by_type.get(st, []))) is not None]
        if not ratios:
            unchecked += 1
        elif max(ratios) >= DUP_THRESHOLD:
            duplicated.add(rid)
        else:
            split += 1
    checkable = len(duplicated) + split
    print("=== 1. báo cáo chứa hai bản của cùng một loại báo cáo ===")
    print(f"  kiểm được: {checkable}   không kiểm được: {unchecked}")
    print(f"  lặp nhãn >={DUP_THRESHOLD:.0%} → gộp hai bộ: {len(duplicated)}"
          f" = {len(duplicated) / checkable:.0%}")
    print(f"  nhãn rời → chỉ là cắt trang:  {split}")

    swapped = [
        rid for rid in by_report
        if rid.endswith("_consolidated")
        and (sib := rid.replace("_consolidated", "_separate")) in by_report
        and any(MINORITY.search(lbl) for t in sum(by_report[sib].values(), []) for lbl in row_labels(t))
        and not any(MINORITY.search(lbl) for t in sum(by_report[rid].values(), []) for lbl in row_labels(t))
    ]
    print(f"  thẻ hợp nhất/riêng bị đảo (bản riêng có dòng cổ đông thiểu số, bản hợp nhất"
          f" không): {len(swapped)} {swapped}\n")

    # 2. Phơi nhiễm.
    gold = {str(k): v for k, v in load_labels().items()}
    sub = {str(r["id"]): r for r in json.loads(SUBMISSION.read_text(encoding="utf-8"))}
    exposed = set()
    n_q = 0
    for line in QUESTION_METADATA_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        n_q += 1
        cands = {f"{t}_financial_statements_{y}_{dt}"
                 for t in (d.get("tickers") or []) for y in (d.get("years") or [])
                 for dt in ("consolidated", "separate")}
        if cands & duplicated:
            exposed.add(str(d.get("id")))

    def gold_of(qid: str):
        g = gold[qid]
        return g.get("answer") if isinstance(g, dict) else g

    def is_right(qid: str) -> bool:
        return correct((sub.get(qid) or {}).get("answer"), gold_of(qid))

    scorable = [q for q in gold if as_float(gold_of(q)) is not None]
    hit = [q for q in scorable if q in exposed]
    rest = [q for q in scorable if q not in exposed]
    print("=== 2. phơi nhiễm có dự báo được lỗi không ===")
    print(f"  câu chạm báo cáo hai-bản: {len(exposed)}/{n_q} = {len(exposed) / n_q:.0%}")
    a, b = sum(map(is_right, hit)), sum(map(is_right, rest))
    print(f"  v9 đúng khi chạm:       {a}/{len(hit)} = {a / len(hit):.0%}")
    print(f"  v9 đúng khi không chạm: {b}/{len(rest)} = {b / len(rest):.0%}\n")

    # 3. Cơ chế: bản sao khác của chính dòng đã dùng có cho ra gold không?
    def alternates(labels: set[str], sources: set[tuple[str, int]]):
        for rid, pos in sources:
            for t in sum(by_report.get(rid, {}).values(), []):
                if t["table_pos"] == pos or not (row_labels(t) & labels):
                    continue
                try:
                    frame = load_frame(f"{rid}|{t['table_pos']}")
                except Exception:
                    continue
                for i in range(len(frame)):
                    if norm(frame.iloc[i, 0]) not in labels:
                        continue
                    for c in range(1, frame.shape[1]):
                        v = as_float(str(frame.iloc[i, c]).replace(",", "").replace(" ", ""))
                        if v is not None:
                            yield rid, t["table_pos"], v

    print("=== 3. bản sao khác của dòng đã dùng có cho ra gold không ===")
    wrong = [q for q in scorable if not is_right(q)]
    checked, recoverable = 0, []
    for qid in sorted(wrong, key=int):
        labels, sources = used_row_labels(sub[qid])
        if not labels:
            continue
        checked += 1
        g = as_float(gold_of(qid))
        for rid, pos, v in alternates(labels, sources):
            if any(abs(v * f - g) <= max(0.01, abs(g) * 0.01) for f in FACTORS):
                recoverable.append((qid, sub[qid].get("answer"), g, rid, pos, v))
                break
    print(f"  v9 sai, chấm được: {len(wrong)}   dò được nhãn dòng: {checked}")
    print(f"  có bản sao khác cho đúng gold: {len(recoverable)}")
    for qid, got, g, rid, pos, v in recoverable:
        print(f"    q{qid}: v9={got} gold={g}  bản sao {rid}|{pos} = {v}")

    right = [q for q in scorable if is_right(q)]
    checked_r, at_risk = 0, 0
    for qid in right:
        labels, sources = used_row_labels(sub[qid])
        if not labels:
            continue
        checked_r += 1
        if next(alternates(labels, sources), None) is not None:
            at_risk += 1
    print(f"\n  v9 ĐÚNG, dò được nhãn dòng: {checked_r}")
    print(f"  trong đó dòng đã dùng còn có bản sao ở bảng khác: {at_risk}")
    print(f"\n  → đổi nhiều nhất {len(recoverable)} câu thắng lấy rủi ro trên {at_risk}"
          f" câu đang đúng. Mốc đã chốt là 10 thắng / 2 thua.")


if __name__ == "__main__":
    main()
