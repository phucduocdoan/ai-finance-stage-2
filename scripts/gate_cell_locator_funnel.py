"""Đo phễu cổng `cell_locator` trên 119 câu eval sạch, bằng diag của một run thật.

`cell_locator` (src/finance_qa/modules/solve/solvers/cell_locator.py) là solver đọc
một ô duy nhất. `build_request` (dòng 208-235) lọc câu qua năm điều kiện, rồi
`locate_single_cell` tìm hàng/cột thật và áp bốn điều kiện nữa trước khi nhận.

Bản đầu của script này KHÔNG đọc run nào: nó dựng lại state từ
`questions_enriched.jsonl` rồi tự gọi `build_request`/`locate_single_cell`. Cách đó
để lại một lỗ hổng đủ lớn để làm sai kết luận: state thật có `metric` từ LLM, proxy
đặt `metric=""`, mà `metric` chính là đầu vào chính của khâu tra hàng. Phễu proxy
báo S8 loại 5 câu và S9 loại 5 câu; phễu thật là S8 7 câu, S9 7 câu, trên những id
khác. Tôi đã một lần chốt ngưỡng dựa trên bộ số proxy đó, nên bản này đọc diag thật
thay vì giả lập.

Nguồn: `artifacts/runs/cell_locator_1012.jsonl`, run đủ 1012 câu, mỗi dòng có
`diag.cell_locator` gồm `reason` và (khi cổng bị chặn ở khâu chấm điểm) cả ô `best`
mà solver đã tính nhưng từ chối. Không gọi LLM, không chạy lại pipeline.

Hai điều cần đọc kỹ trước khi trích số:

  - Run này là 2026-08-16, KHÁC cấu hình v9: nó đúng 44/119, v9 đúng 49/119, và hai
    bên chỉ ra cùng đáp án ở 59/119. Nên phần "cho `best` đi qua thì được/mất bao
    nhiêu" là so ô `best` của run cũ với tính đúng/sai của submission truyền vào,
    một phép so lệch cấu hình. Đọc nó như dấu hiệu về hướng và độ lớn, đừng đọc như
    con số chính xác.
  - Ngược lại, cổng phạm vi ("needs exactly one ticker and one year") chỉ phụ thuộc
    `len(tickers)` và `len(years)`, và kết luận chặn/không chặn của state LLM trong
    run khớp `questions_enriched.jsonl` (rule-based, tất định) ở 119/119 câu. Phần
    đó không phụ thuộc phiên bản run.

Dùng:
    PYTHONPATH=src:scripts .venv_bge/bin/python scripts/gate_cell_locator_funnel.py \
        output/submission_v9_sign/submission.json
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from finance_qa.core.paths import QUESTION_METADATA_PATH, RAW_QUESTIONS_PATH  # noqa: E402
from finance_qa.modules.data.table_store import load_frame  # noqa: E402
from finance_qa.modules.tools.numeric import parse_number  # noqa: E402

from gate_type_split import level  # noqa: E402
from score_clean_eval import as_float, correct, load_labels, load_submission  # noqa: E402

RUN = Path("artifacts/runs/cell_locator_1012.jsonl")
LEVELS = ["L1", "L2", "L3", "L4", "L5", "L6"]

# Chuỗi `reason` y hệt cell_locator.py trả về, không viết lại. Thứ tự đúng thứ tự code.
STEP_LABEL: dict[str, str] = {
    "needs exactly one ticker and one year": "P1 đúng 1 mã + 1 năm",
    "multi-axis question": "P2 không multi-axis",
    "derived or comparison marker": "P3 không có dấu hiệu derived/so sánh",
    "not a lookup-shaped question": "P4 lookup-shaped",
    "no metric phrase": "P5 có cụm từ chỉ tiêu",
    "no candidate tables": "S6 có bảng ứng viên",
    "no located numeric cell": "S7 tìm được ô số",
    "below confidence threshold": "S8 vượt ngưỡng tin cậy 0.78",
    "ambiguous located cells": "S9 không mơ hồ (ambiguous)",
}


def load_jsonl(path: Path) -> dict[int, dict]:
    out: dict[int, dict] = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rec = json.loads(line)
                out[rec["id"]] = rec
    return out


def cell_value(best: dict) -> float | None:
    """Giá trị thô của ô `best`, hoặc None nếu không đọc được."""
    try:
        frame = load_frame(str(best["table_id"]))
        return parse_number(str(frame.iloc[int(best["row_position"])][best["column"]]))
    except Exception:  # noqa: BLE001 - ô không đọc được thì tính là không khớp
        return None


def matches_gold(best: dict, gold: float | None) -> bool:
    """Ô `best` có ra đúng đáp án, xét mọi luỹ thừa 10.

    `best` là ô trước khâu đổi đơn vị, nên so thẳng với gold sẽ trượt mọi câu hỏi
    "bao nhiêu tỷ đồng". Quét 10^k là cách tách "sai ô" khỏi "đúng ô, sai đơn vị";
    nó nới rộng về phía có lợi cho cell_locator, nên kết luận âm ở đây là kết luận chắc.
    """
    value = cell_value(best)
    if value is None or gold is None:
        return False
    return any(correct(value / 10**k, gold) for k in range(-3, 13))


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    labels = load_labels()
    sub = load_submission(sys.argv[1])
    name = Path(sys.argv[1]).parent.name
    questions = {q: r["question"] for q, r in load_jsonl(RAW_QUESTIONS_PATH).items()}
    enriched = load_jsonl(QUESTION_METADATA_PATH)
    run = load_jsonl(RUN)

    ids = sorted(q for q, lab in labels.items() if as_float(lab.get("answer")) is not None)
    print(f"tập eval sạch: {len(ids)} câu chấm được. phễu đọc từ {RUN}\n")

    def diag(qid: int) -> dict:
        return ((run.get(qid) or {}).get("diag") or {}).get("cell_locator") or {}

    def ok(qid: int) -> bool:
        return correct(sub.get(qid, {}).get("answer"), labels[qid].get("answer"))

    # Phễu: câu dừng ở bước nào, và trong đó bao nhiêu câu submission đang trả đúng.
    print(f"phễu (đúng thứ tự code; 'đang đúng' tính theo {name}):")
    alive = len(ids)
    stopped: dict[str, list[int]] = {}
    for reason, label in STEP_LABEL.items():
        hit = [q for q in ids if diag(q).get("reason") == reason]
        stopped[reason] = hit
        alive -= len(hit)
        note = f"(loại {len(hit)}, trong đó {sum(1 for q in hit if ok(q))} đang đúng)"
        print(f"  sau {label:<38}{alive:>4}   {note}")
    claimed = [q for q in ids if diag(q).get("done")]
    missing = [q for q in ids if not diag(q)]
    print(f"  cell_locator nhận (done=True)              {len(claimed):>4}   "
          f"(trong đó {sum(1 for q in claimed if ok(q))} đang đúng)")
    if missing:
        print(f"  không có diag trong run                    {len(missing):>4}")

    worst = max(stopped, key=lambda r: len(stopped[r]))
    print(f"\nbước loại nhiều nhất: {STEP_LABEL[worst]} ({len(stopped[worst])} câu)")

    # Cổng phạm vi chặn nhiều nhất, nên tách nó ra theo bậc: đây là chỗ quyết định
    # có nên cho cell_locator đọc nhiều ô hay không.
    blocked = stopped["needs exactly one ticker and one year"]
    print(f"\ncổng phạm vi, tách theo bậc ({len(blocked)} câu):")
    print(f"  {'bậc':<5}{'chặn':>6}{'đang đúng':>11}{'đang sai':>10}")
    for lvl in LEVELS:
        part = [q for q in blocked if level(questions[q]) == lvl]
        if part:
            good = sum(1 for q in part if ok(q))
            print(f"  {lvl:<5}{len(part):>6}{good:>11}{len(part) - good:>10}")

    # Tách theo số mã / số năm: "0 hoặc nhiều" là hai bài toán khác nhau, và số ô
    # cần đọc quyết định chi phí. Dùng enriched vì nó tất định (khớp run 119/119).
    print("\ncổng phạm vi, tách theo số mã / số năm (enriched, tất định):")
    print(f"  {'mã/năm':<12}{'số ô cần':>10}{'đang đúng':>11}{'đang sai':>10}")
    split: dict[tuple[int, int], list[int]] = defaultdict(list)
    for q in blocked:
        e = enriched.get(q, {})
        split[(len(e.get("tickers") or []), len(e.get("years") or []))].append(q)
    for (nt, ny), part in sorted(split.items(), key=lambda kv: (kv[0][0] * kv[0][1], kv[0])):
        good = sum(1 for q in part if ok(q))
        print(f"  {f'{nt} mã / {ny} năm':<12}{max(nt, 1) * max(ny, 1):>10}{good:>11}{len(part) - good:>10}")

    # Câu hỏi quyết định của việc nới ngưỡng: những câu cell_locator đã tính được ô
    # `best` rồi mới từ chối, nếu cho đi qua thì đổi được bao nhiêu câu.
    print(f"\nnới ngưỡng: cho mọi ô `best` bị từ chối đi qua (so với {name}):")
    print(f"  {'id':<7}{'đang':>6}  {'lý do từ chối':<30}{'conf':>8}{'best khớp gold':>16}")
    tally: Counter[str] = Counter()
    for q in ids:
        d = diag(q)
        best = d.get("best")
        if d.get("done") or not best:
            continue
        good, hit = ok(q), matches_gold(best, as_float(labels[q].get("answer")))
        tally["được" if (hit and not good) else "mất" if (good and not hit) else "không đổi"] += 1
        print(f"  q{q:<6}{'đúng' if good else 'sai':>6}  {str(d.get('reason')):<30}"
              f"{best.get('confidence'):>8}{('khớp' if hit else 'lệch'):>16}")
    print(f"\n  được {tally['được']}, mất {tally['mất']}, không đổi {tally['không đổi']}"
          f"  ->  ròng {tally['được'] - tally['mất']:+d} câu")
    print("  (lệch cấu hình: `best` từ run 16/08, đúng/sai từ submission truyền vào. "
          "xem docstring.)")


if __name__ == "__main__":
    main()
