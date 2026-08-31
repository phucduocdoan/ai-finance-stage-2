"""Bằng chứng đưa vào prompt có chứa đáp án không? Trần trên của mọi việc ở codegen.

Chín đường đã định giá. Tám đường đầu chết ở bước phát hiện. Đường thứ chín
(`docs/answer_type_2026-08-23.md`) phát hiện được thật, 51/1012 câu sai chứng minh
được không cần gold, nhưng chuyển đổi 0/7 vì với q432 bằng chứng chỉ có 4 ô số cho
một câu sàng lọc 10 công ty: **bằng chứng không chứa đáp án**, nên sinh lại truy vấn
không thể thắng.

Phép đo này hỏi thẳng câu đó trên cả 119 câu. Nếu phần lớn 70 câu sai không có cách
nào chạm gold từ các ô đã đọc, thì trần trên của *mọi* công việc ở codegen đã bị
chặn, và ngân sách phải chuyển sang truy hồi.

**Sàn nhiễu ở đây là vấn đề trung tâm, không phải chú thích.** Một câu có 191 ô số
là 36 nghìn cặp, nhân 7 hệ số, với dung sai 1%: chạm gold ngẫu nhiên gần như chắc
chắn. Và rổ ô của câu sai to hơn rổ của câu đúng, đúng cái confound đã giết trục
chọn bảng ở `docs/table_selection_2026-08-23.md`.

Nên đối chứng ở đây là **hoán vị**, không phải nhóm câu đúng: với mỗi câu, đo tỉ lệ
chạm gold *của chính nó* so với tỉ lệ chạm gold *của các câu khác* trên đúng rổ ô
đó. Sàn nhiễu vì thế tự mang cỡ rổ theo, nên hiệu số không thể đọc thành cỡ rổ nữa.

Ba dạng công thức, vì một ô đơn không thể ra một tỉ lệ:
  đơn : ô x hệ số 1e0/±3/±6/±9
  tỉ  : a/b và a/b*100
  hiệu: a-b x cùng bộ hệ số

Dùng:
    PYTHONPATH=src:scripts .venv_bge/bin/python scripts/gate_evidence_reachable.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np

from finance_qa.core.paths import QUESTION_METADATA_PATH
from finance_qa.modules.data.table_store import load_frame
from finance_qa.modules.solve.common.lookup import label_column
from score_clean_eval import as_float, correct, load_labels

SUBMISSION = Path("output/submission_v9_sign/submission.json")
CSV_PATH = re.compile(r"data/(?P<rid>.+)_table_(?P<pos>\d+)\.csv")
FACTORS = np.array([1.0, 1e-3, 1e-6, 1e-9, 1e3, 1e6, 1e9])

# Số gold của câu khác dùng làm sàn nhiễu cho mỗi câu. 30 là đủ để tỉ lệ nền ổn
# định mà vẫn giữ phép đo chạy trong vài phút trên rổ 200 ô.
N_PERMUTED = 30
# Rổ ô bị chặn để một câu 500 ô không chiếm hết thời gian; cắt thì chỉ làm phép đo
# *bảo thủ hơn* về phía "chạm được", nên nó không thể tạo ra kết luận sai chiều.
MAX_CELLS = 220


def evidence_cells(record: dict) -> np.ndarray:
    """Mọi ô số của các bảng mà truy vấn đã đọc, tức đúng những gì prompt thấy."""
    values: list[float] = []
    for ev in record.get("evidence") or []:
        m = CSV_PATH.match(ev.get("csv_path") or "")
        if not m:
            continue
        try:
            df = load_frame(f"{m.group('rid')}|{m.group('pos')}")
        except Exception:  # noqa: BLE001 - một CSV không đọc được không giết phép đo
            continue
        label = label_column(df)
        for col in df.columns:
            if col == label:
                continue
            for raw in df[col]:
                v = as_float(raw)
                if v is not None and v != 0.0:
                    values.append(v)
    return np.array(values[:MAX_CELLS], dtype=float)


def reachable(cells: np.ndarray, pair: np.ndarray | None, gold: float) -> str | None:
    """Dạng công thức đơn giản nhất chạm được gold, hay None nếu không dạng nào chạm."""
    tol = max(0.01, abs(gold) * 0.01)
    if np.any(np.abs(np.outer(cells, FACTORS) - gold) <= tol):
        return "đơn"
    if pair is None:
        return None
    a, b = pair
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = a / b
    if np.any(np.abs(ratio - gold) <= tol) or np.any(np.abs(ratio * 100 - gold) <= tol):
        return "tỉ"
    if np.any(np.abs(np.outer(a - b, FACTORS) - gold) <= tol):
        return "hiệu"
    return None


def main() -> None:
    records = {str(r["id"]): r for r in json.loads(SUBMISSION.read_text(encoding="utf-8"))}
    gold_labels = {str(k): v for k, v in load_labels().items()}
    shape = {}
    for line in QUESTION_METADATA_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            shape[str(d["id"])] = d.get("answer_shape")

    def gold_of(qid: str):
        g = gold_labels[qid]
        return g.get("answer") if isinstance(g, dict) else g

    scorable = sorted(
        (q for q in gold_labels if q in records and as_float(gold_of(q)) is not None),
        key=int,
    )
    golds = {q: as_float(gold_of(q)) for q in scorable}
    print(f"{len(scorable)} câu chấm được\n")

    groups: dict[str, list[tuple[str, bool, float, int, str | None]]] = {}
    for index, qid in enumerate(scorable):
        cells = evidence_cells(records[qid])
        if cells.size == 0:
            continue
        pair = None
        if cells.size <= MAX_CELLS:
            grid_a, grid_b = np.meshgrid(cells, cells, indexing="ij")
            pair = (grid_a.ravel(), grid_b.ravel())

        own = reachable(cells, pair, golds[qid])
        # Sàn nhiễu: gold của câu khác, trên đúng rổ ô này. Bước nhảy cố định để
        # phép đo lặp lại được, và bỏ chính câu đang xét.
        others = [
            scorable[(index + 1 + step * 7) % len(scorable)]
            for step in range(N_PERMUTED)
        ]
        noise = sum(
            1
            for other in others
            if other != qid and reachable(cells, pair, golds[other]) is not None
        )
        is_right = correct(records[qid].get("answer"), gold_of(qid))
        key = "v9 đúng" if is_right else "v9 sai "
        groups.setdefault(key, []).append(
            (qid, own is not None, noise / len(others), int(cells.size), own)
        )

    print("Gold có chạm được từ các ô đã đọc không, so với sàn nhiễu hoán vị:\n")
    print(f"{'nhóm':9} {'n':>4} {'chạm gold':>12} {'sàn hoán vị':>13} {'ô/câu':>7}")
    for key, rows in sorted(groups.items(), key=lambda kv: kv[0]):
        n = len(rows)
        hit = sum(1 for r in rows if r[1])
        floor = sum(r[2] for r in rows) / n
        cells_per = sum(r[3] for r in rows) / n
        print(f"{key:9} {n:>4} {hit:>5} {hit / n:>6.0%} {floor:>12.0%} {cells_per:>7.0f}")

    print("\nCùng phép đo, chỉ trên câu rổ nhỏ (< 40 ô), nơi sàn nhiễu còn thấp:")
    for key, rows in sorted(groups.items(), key=lambda kv: kv[0]):
        small = [r for r in rows if r[3] < 40]
        if not small:
            continue
        hit = sum(1 for r in small if r[1])
        floor = sum(r[2] for r in small) / len(small)
        print(f"  {key} n={len(small):>3}  chạm gold {hit:>3} = {hit / len(small):>4.0%}"
              f"   sàn hoán vị {floor:.0%}")

    # Lát cắt sạch nhất: chỉ dạng ô đơn, nơi sàn nhiễu là `ô x 7` chứ không phải
    # `ô^2 x 7`. Chỉ đọc trên câu tra cứu một ô, vì một tỉ lệ không thể là một ô.
    print("\nChỉ dạng ô đơn, chỉ câu answer_shape = single_cell:")
    for key in ("v9 đúng", "v9 sai "):
        rows = [
            (qid, cells_n, form)
            for qid, _, _, cells_n, form in groups.get(key, [])
            if shape.get(qid) == "single_cell"
        ]
        if not rows:
            continue
        hit = sum(1 for _, _, form in rows if form == "đơn")
        print(f"  {key} n={len(rows):>3}  chạm bằng một ô {hit:>3} = {hit / len(rows):>4.0%}")

    print("\nDạng công thức chạm được, trên câu sai:")
    forms: dict[str, int] = {}
    for qid, ok, _, _, form in groups.get("v9 sai ", []):
        forms[form or "không chạm"] = forms.get(form or "không chạm", 0) + 1
    for form, count in sorted(forms.items(), key=lambda kv: -kv[1]):
        print(f"  {form:>12}: {count}")

    print("\nCâu sai mà bằng chứng không chứa đáp án dưới bất kỳ dạng nào:")
    dead = [r for r in groups.get("v9 sai ", []) if not r[1]]
    print("  " + ", ".join(f"q{r[0]}({r[3]} ô)" for r in dead[:24]))
    print(f"  tổng {len(dead)} câu")
    print("\nSo cột 'chạm gold' với cột 'sàn hoán vị', không đọc con số tuyệt đối:"
          "\nsàn đã mang cỡ rổ theo, nên hiệu số không thể đọc thành cỡ rổ nữa.")


if __name__ == "__main__":
    main()
