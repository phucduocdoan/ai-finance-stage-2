"""Chấm một submission trên tập eval sạch (`artifacts/eval_clean/labels_*.jsonl`).

Tập này được rút ngẫu nhiên đều từ 891 câu không nằm trong file gold nào và không được
nhắc tên trong `src`/`tests`/`scripts`, rồi gán nhãn bởi các agent chỉ đọc OCR thô. Xem
`docs/leaderboard_and_strategy_2026-08-21.md` §9-§10.

**Con số tuyệt đối của tập này cao hơn leaderboard khoảng 0.11** vì nhãn do Claude tạo còn
gold của BTC do người lập, và hai bên lệch nhau ở đúng những câu mơ hồ. Dùng nó để so hai
phiên bản pipeline với nhau, đừng dùng để dự đoán điểm nộp.

Dùng:
    .venv_bge/bin/python scripts/score_clean_eval.py output/submission_v8_round2/submission.json
    .venv_bge/bin/python scripts/score_clean_eval.py A/submission.json B/submission.json
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

LABELS = Path("artifacts/eval_clean")
# Cùng dung sai với scripts/score_gold75.py, để hai bộ chấm so sánh được với nhau.
# Nhãn là năm thì đòi khớp tuyệt đối, xem `correct`.
TOL = 0.01


def load_labels() -> dict[int, dict]:
    out: dict[int, dict] = {}
    for p in sorted(LABELS.glob("labels_*.jsonl")):
        for line in p.read_text().splitlines():
            if line.strip():
                d = json.loads(line)
                out[d["id"]] = d
    return out


def load_submission(path: str) -> dict[int, dict]:
    data = json.loads(Path(path).read_text())
    return {int(it["id"]): it for it in data}


def as_float(x) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def is_year_label(gold: float) -> bool:
    """Nhãn là một cái năm, không phải một con số tiền."""
    return gold == int(gold) and 1990 <= gold <= 2100


def correct(sub_answer, gold_answer) -> bool:
    a, b = as_float(sub_answer), as_float(gold_answer)
    if a is None or b is None:
        return False
    # Dung sai tương đối vô nghĩa với nhãn phân loại: 2018 lệch 2019 đúng 0.05%, lọt hết.
    # Ba câu "năm nào" của tập này (866, 928, 842) đều bị chấm đúng dù trả sai năm.
    if is_year_label(b):
        return a == b
    if abs(a - b) <= TOL:
        return True
    scale = max(abs(a), abs(b))
    return scale > 0 and abs(a - b) / scale <= TOL


def bucket(label: dict, question: str) -> str:
    """Ba lớp câu hỏi, phân theo số tài liệu cần đọc.

    Lớp quyết định phần lớn kết quả: tra một ô thì pipeline làm được, sàng lọc nhiều công
    ty thì không (§10).
    """
    reports = len(set(re.findall(r"[A-Z0-9]{2,4}_financial_statements", str(label.get("report_id") or ""))))
    tickers = len(set(re.findall(r"\b[A-Z]{3}\b", question)))
    if tickers >= 3 or reports >= 3:
        return "sàng lọc nhiều công ty"
    if reports == 2 or tickers == 2:
        return "hai tài liệu"
    return "tra một ô"


def score(path: str, labels: dict[int, dict]) -> dict:
    sub = load_submission(path)
    scored = [i for i, g in labels.items() if g.get("answer") is not None and i in sub]
    hits = {i: correct(sub[i].get("answer"), labels[i]["answer"]) for i in scored}
    by_bucket: dict[str, list[int]] = defaultdict(list)
    by_conf: dict[str, list[int]] = defaultdict(list)
    for i in scored:
        by_bucket[bucket(labels[i], sub[i].get("question", ""))].append(i)
        by_conf[labels[i].get("confidence", "?")].append(i)
    return {"path": path, "scored": scored, "hits": hits, "bucket": by_bucket, "conf": by_conf}


def show(r: dict) -> None:
    n, k = len(r["scored"]), sum(r["hits"].values())
    se = (k / n * (1 - k / n) / n) ** 0.5 if n else 0
    print(f"\n{r['path']}")
    print(f"  tổng: {k}/{n} = {k/n:.3f}   (SE {se:.3f}, KTC 95% {k/n-1.96*se:.3f}..{k/n+1.96*se:.3f})")
    for name, groups in (("theo lớp", r["bucket"]), ("theo độ tin nhãn", r["conf"])):
        print(f"  {name}:")
        for key, ids in sorted(groups.items(), key=lambda x: -len(x[1])):
            g = sum(r["hits"][i] for i in ids)
            print(f"    {key:<24} {g:>3}/{len(ids):<3} = {g/len(ids):.0%}")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    labels = load_labels()
    print(f"tập eval sạch: {len(labels)} nhãn, {sum(1 for g in labels.values() if g.get('answer') is not None)} chấm được")
    results = [score(p, labels) for p in sys.argv[1:]]
    for r in results:
        show(r)
    if len(results) == 2:
        a, b = results
        common = sorted(set(a["scored"]) & set(b["scored"]))
        gained = [i for i in common if b["hits"][i] and not a["hits"][i]]
        lost = [i for i in common if a["hits"][i] and not b["hits"][i]]
        print(f"\nB so với A trên {len(common)} câu chung: +{len(gained)} / -{len(lost)} = {len(gained)-len(lost):+d}")
        print(f"  được: {gained}")
        print(f"  mất : {lost}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
