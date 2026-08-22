"""Chấm một run JSONL trên các câu sàng lọc của tập eval sạch, theo hình dạng câu hỏi.

`gate_screening_class.py` đã đo cả lớp sàng lọc gộp một cục: đúng 4/29 trong khi phần
còn lại đúng 45/90. Con số đó không nói câu nào cần lọc theo mốc của cả nhóm, câu nào
lọc theo một điều kiện tuyệt đối của từng công ty, câu nào chỉ chọn max/min rồi hỏi
thêm một chỉ số khác, và câu nào không có điều kiện gì mà chỉ gộp thẳng qua nhiều công
ty. Bốn dạng đó cần cách sửa khác nhau, nên gate này tách lớp sàng lọc thành bốn hình
dạng và so từng hình dạng giữa một run mới với baseline, để thấy ngay một solver mới
ăn được hình dạng nào và làm hỏng hình dạng nào.

Không gọi LLM. Nhãn và hàm chấm lấy từ `score_clean_eval.py`, câu sàng lọc lấy từ
`is_screening` trong `gate_screening_class.py`, không viết lại logic đó ở đây.

Đáp số của run đọc từ `record["item"]["answer"]` trong run JSONL (field này do
`run_graph.py` ghi qua `submission_item()`), rồi làm tròn 2 chữ số và thế 0.0 khi
thiếu, đúng như hai bước duy nhất quyết định số nộp thật: `build_submission.build_item`
(0.0 khi record không có `item` hợp lệ) và `build_submission.round_final`.

Baseline thì đọc từ **submission đã nộp**, không phải từ run JSONL, và đây là cái bẫy
đắt nhất trong gate này. `artifacts/runs/full1012_v7.jsonl` là run v7, còn bài đang
trên leaderboard là v9: `scripts/patch_sign_submission.py` đã vá 23 đáp án sau run đó
bằng luật độ lớn. q894 là một trong 23 câu, và nó là câu sàng lọc có nhãn, nên lấy đáp
án của nó từ run record thì baseline mất một câu mà bài nộp đang được tính đúng. Rộng
hơn: mọi run mới đều đã có luật dấu trong code, nên so run mới với run cũ là tặng
không 23 câu cho solver mới. Vì thế `--baseline` trỏ vào submission, và văn bản câu
hỏi đi theo cờ riêng `--questions`.

Một câu có trong baseline nhưng không có trong --run không phải lỗi, nó chỉ bị bỏ qua
khỏi phần chấm của run và được đếm riêng, vì --run thường là một run cục bộ trên vài
chục câu, không phải cả 1012.

Chỉ 29 câu sàng lọc có nhãn, nên mẫu từng hình dạng chỉ 3 đến 12 câu. Gate này dùng để
thấy một solver mới ăn hay làm hỏng đúng những câu nó nhận, không phải để đọc tỉ lệ
từng hình dạng như một con số ổn định.

Dùng:
    PYTHONPATH=src:scripts .venv_bge/bin/python scripts/gate_screening_run.py \
        --run artifacts/runs/screening_probe.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from score_clean_eval import correct, load_labels  # type: ignore

sys.path.insert(0, "scripts")
from gate_screening_class import is_screening  # noqa: E402

# Bốn cụm khớp theo thứ tự ưu tiên: mốc của cả nhóm trước (so với trung vị/trung bình
# cả nhóm), rồi điều kiện tuyệt đối của từng công ty, rồi chọn max/min. Câu không khớp
# cụm nào là gộp thẳng, không có điều kiện.
GROUP_REL = re.compile(r"trung vị|trung binh nhóm|trung bình của nhóm|trung bình cả", re.I)
PRED = re.compile(r"có .{0,60}(dương|âm|cao hơn|thấp hơn|tăng|giảm|trên \d|dưới)", re.I)
ARGMAX = re.compile(r"cao nhất|thấp nhất|lớn nhất|nhỏ nhất", re.I)

BUCKETS = [
    "lọc theo mốc của nhóm",
    "lọc theo điều kiện tuyệt đối",
    "chọn max/min rồi hỏi chỉ số khác",
    "gộp thẳng, không có điều kiện",
]


def shape_of(question: str) -> str:
    """Hình dạng câu hỏi sàng lọc, theo thứ tự ưu tiên GROUP_REL > PRED > ARGMAX."""
    text = " ".join(question.split())
    if GROUP_REL.search(text):
        return BUCKETS[0]
    if PRED.search(text):
        return BUCKETS[1]
    if ARGMAX.search(text):
        return BUCKETS[2]
    return BUCKETS[3]


def load_run(path: Path) -> dict[int, dict]:
    """id -> bản ghi cuối cùng của nó trong file, bỏ dòng cuối bị cắt nếu có."""
    records: dict[int, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            break  # một dòng cuối bị ghi dở khi tiến trình bị giết
        records[int(row["id"])] = row
    return records


def _coerce_float(value) -> float:
    """Bản chép của `build_submission._coerce_float`: chỉ tin số thật."""
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def answer_of(record: dict | None) -> float:
    """Đáp số như bài nộp cuối cùng sẽ mang.

    Khớp hai bước duy nhất quyết định số nộp: `build_submission.build_item` (record
    không có `item` hợp lệ thì answer là 0.0) và `build_submission.round_final` (làm
    tròn 2 chữ số). Không bao giờ trả None nên không cần chỗ gọi nào tự đoán giá trị
    thiếu. Record thiếu hay answer null đều thành 0.0, giống submission thật.
    """
    item = (record or {}).get("item")
    raw = item.get("answer") if isinstance(item, dict) else None
    return round(_coerce_float(raw), 2)


def load_baseline(path: Path) -> dict[int, float]:
    """id -> đáp án đã nộp. Đọc submission, không đọc run record (xem docstring)."""
    items = json.loads(path.read_text(encoding="utf-8"))
    # Số trong submission đã qua `round_final` lúc đóng gói, không làm tròn lại.
    return {int(it["id"]): _coerce_float(it.get("answer")) for it in items}


def question_of(qid: int, questions: dict[int, dict], run: dict[int, dict]) -> str | None:
    """Văn bản câu hỏi, ưu tiên --questions vì nó là run đầy đủ 1012 câu."""
    record = questions.get(qid) or run.get(qid)
    return str(record["question"]) if record and record.get("question") else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", type=Path, required=True, help="run JSONL cần chấm")
    ap.add_argument(
        "--baseline", type=Path, default=Path("output/submission_v9_sign/submission.json"),
        help="submission đối chứng (đáp án đã nộp)",
    )
    ap.add_argument(
        "--questions", type=Path, default=Path("artifacts/runs/full1012_v7.jsonl"),
        help="run JSONL lấy văn bản câu hỏi và tập câu sàng lọc",
    )
    args = ap.parse_args()

    labels = load_labels()
    baseline = load_baseline(args.baseline)
    questions = load_run(args.questions)
    run = load_run(args.run)

    labelled = [i for i, g in labels.items() if g.get("answer") is not None]
    screening = sorted(
        qid for qid in labelled
        if (question := question_of(qid, questions, run)) is not None and is_screening(question)
    )
    skipped = [qid for qid in screening if qid not in run]

    rows = []
    for qid in screening:
        question = question_of(qid, questions, run) or ""
        shape = shape_of(question)
        gold = labels[qid]["answer"]
        in_run = qid in run
        base_ans = baseline.get(qid, 0.0)
        run_ans = answer_of(run.get(qid)) if in_run else None
        rows.append({
            "id": qid,
            "shape": shape,
            "gold": gold,
            "base_ans": base_ans,
            "run_ans": run_ans,
            "base_ok": correct(base_ans, gold),
            "run_ok": correct(run_ans, gold) if in_run else False,
            "in_run": in_run,
        })

    def run_bucket_counts() -> dict[str, int]:
        """Số câu sàng lọc theo hình dạng, tính trên toàn bộ --run (không riêng câu có nhãn)."""
        counts = {b: 0 for b in BUCKETS}
        for record in run.values():
            question = str(record.get("question") or "")
            if is_screening(question):
                counts[shape_of(question)] += 1
        return counts

    n_in_run = run_bucket_counts()

    print(f"\n{len(screening)} câu sàng lọc có nhãn, {len(skipped)} không có trong --run (bỏ qua)\n")
    print(f"  {'hình dạng':<34}{'n(run)':>7}   {'run':>9}   {'baseline':>9}")
    total_n = total_run_ok = total_run_tot = total_base_ok = total_base_tot = 0
    for bucket in BUCKETS:
        in_bucket = [r for r in rows if r["shape"] == bucket]
        run_scored = [r for r in in_bucket if r["in_run"]]
        run_ok = sum(1 for r in run_scored if r["run_ok"])
        base_ok = sum(1 for r in in_bucket if r["base_ok"])
        total_n += n_in_run[bucket]
        total_run_ok += run_ok
        total_run_tot += len(run_scored)
        total_base_ok += base_ok
        total_base_tot += len(in_bucket)
        print(
            f"  {bucket:<34}{n_in_run[bucket]:>7}   "
            f"{run_ok:>3}/{len(run_scored):<5}   {base_ok:>3}/{len(in_bucket):<5}"
        )
    print(
        f"  {'TỔNG':<34}{total_n:>7}   "
        f"{total_run_ok:>3}/{total_run_tot:<5}   {total_base_ok:>3}/{total_base_tot:<5}"
    )

    print("\ntừng câu có nhãn và có trong --run:")
    print(
        f"  {'id':<6}{'hình dạng':<34}{'base':<5}{'run':<5}"
        f"{'nhãn':>18}  {'base_ans':>18}  {'run_ans':>18}  đổi"
    )
    for r in rows:
        if not r["in_run"]:
            continue
        if r["run_ok"] and not r["base_ok"]:
            mark = "được"
        elif r["base_ok"] and not r["run_ok"]:
            mark = "mất"
        else:
            mark = ""
        base_s = "đúng" if r["base_ok"] else "sai"
        run_s = "đúng" if r["run_ok"] else "sai"
        print(
            f"  q{r['id']:<5}{r['shape']:<34}{base_s:<5}{run_s:<5}"
            f"{r['gold']:>18}  {r['base_ans']:>18}  {r['run_ans']:>18}  {mark}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
