"""Đo xem mở `cell_locator` sang câu L3 hai kỳ thì bắn được bao nhiêu, và cần sửa gì.

Bối cảnh. `cell_locator.build_request` (cell_locator.py:213) chặn mọi câu không phải
"đúng 1 mã + 1 năm". Trên 119 câu eval sạch cổng đó chặn 70 câu, 50 trong đó v9 trả
sai, và L3 (cùng chỉ tiêu, hai kỳ) là lớp gần nhất với thứ solver này làm tốt: chỉ cần
gọi nó hai lần, cùng cụm chỉ tiêu, khác năm, rồi trừ hoặc chia.

Vì sao script này tồn tại thay vì đo bằng điểm eval. Eval sạch có 119 câu, 1 sigma sai
số lấy mẫu là 4.5 điểm, nên nó không phân biệt được thay đổi nhỏ hơn ~10 câu lật (kiểm
McNemar: 8 lên/2 xuống mới ra p = 0.055). Lớp L3 hai kỳ có 52 câu trong 1012 nhưng chỉ
6 câu có nhãn, và trong 15 câu cơ chế mới bắn thì chỉ 2 câu có nhãn. Nên script này đo
thứ **không cần nhãn**: tỉ lệ bắn. Đó là mốc nghiệm thu chốt trước khi chạy:

    tỉ lệ bắn >= 12%  ->  mô hình thành phần đứng, làm tiếp
    tỉ lệ bắn <  5%   ->  bỏ, vì tỉ lệ nhận 42%/ô không chuyển được sang lớp mới

Hai phát hiện của lần chạy đầu, cả hai đều đổi thiết kế:

  1. Cụm chỉ tiêu bị dính động từ so sánh, và điều đó một mình đủ giết cơ chế.
     `direct_metric_phrases` rút được cụm cho 52/52 câu, nhưng ra "Tính tăng trưởng lãi
     tiền gửi có kỳ hạn" và "Chênh lệch vốn chủ sở hữu giữa". `lookup._score` là recall
     trên token truy vấn, nên token thừa pha loãng: hàng đúng "Lãi tiền gửi có kỳ hạn"
     khớp 6/8 token = 0.75, không được thưởng cụm, và
         confidence = 0.75 * 0.58 + 1.0 * 0.34 = 0.775
     trượt ngưỡng 0.78 **dù hàng và cột đều đúng**. Cắt động từ so sánh đưa tỉ lệ bắn
     từ 17% lên 29%. `_LEADING_TIME` của cell_locator cũng không cắt dạng "Đến ngày
     31/12/2022," nên mốc ngày dẫn đầu phải cắt thêm.

  2. Hai năm tương quan mạnh, nên đừng định giá bằng phép nhân độc lập. Tỉ lệ nhận mỗi
     ô là 34%, nếu độc lập thì bắn cả cặp chỉ 0.34^2 = 12%; đo thật ra 29%. Cụm chỉ
     tiêu chạy cho năm này thì hầu như chạy cho năm kia, vì cùng một họ báo cáo. Tôi đã
     một lần định giá cơ chế này bằng 0.42^2 và kết luận sai rằng nó vô giá trị.

Ba chỗ phải đọc kỹ trước khi trích số:

  - `state` thật có `metric` do LLM sinh, script này đặt `metric=""` vì
    `questions_enriched.jsonl` không có cột đó. `metric` chỉ thêm alias, không phải
    nguồn cụm chính, nên mọi tỉ lệ bắn ở đây là **chặn dưới**. (Đây đúng là cái bẫy đã
    làm sai một phễu trước: xem docstring của gate_cell_locator_funnel.py.)
  - Shortlist bảng ứng viên lấy từ `artifacts/runs/cell_locator_1012.jsonl`, run
    2026-08-16, khác cấu hình v9. Shortlist là đầu ra của retrieval nên ít phụ thuộc
    solver, và đã đo được 68/70 câu sai của v9 vẫn có đủ báo cáo gold, nhưng cột
    "v9 đúng/sai" thì là so lệch cấu hình.
  - Phần chấm độ đúng chỉ có n = 2. Nó không chứng minh gì; nhãn cho 15 câu bắn đang
    được gán riêng ở `artifacts/l3_pair/`.

Dùng:
    PYTHONPATH=src:scripts .venv_bge/bin/python scripts/gate_l3_pair_fire.py \
        output/submission_v9_sign/submission.json
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from finance_qa.core.paths import QUESTION_METADATA_PATH, RAW_QUESTIONS_PATH  # noqa: E402
from finance_qa.modules.data.table_store import load_frame  # noqa: E402
from finance_qa.modules.solve.common.lookup import search_rows  # noqa: E402
from finance_qa.modules.solve.common.units import unit_from_hint  # noqa: E402
from finance_qa.modules.solve.solvers.cell_locator import (  # noqa: E402
    CellRequest,
    _hit_to_cell,
    direct_metric_phrases,
    period_intent,
    value_transform,
)
from finance_qa.modules.tools.numeric import parse_number  # noqa: E402

from gate_type_split import level  # noqa: E402
from score_clean_eval import as_float, correct, load_labels, load_submission  # noqa: E402

RUN = Path("artifacts/runs/cell_locator_1012.jsonl")
THRESHOLD = 0.78

# Mốc ngày dẫn đầu câu: "Đến ngày 31/12/2022, giá trị còn lại ...". `_LEADING_TIME` của
# cell_locator chỉ cắt "năm YYYY" và "cuối năm YYYY".
_LEAD_DATE = re.compile(r"^\s*(?:[đd][eế]n|t[aạ]i|v[aà]o)\s+ng[aà]y\s+[\d/\.\-]+\s*,?\s*", re.I)
# Động từ so sánh dẫn đầu cụm. Đây chính là thứ `_DERIVED_MARKER` dùng để từ chối câu,
# nên với đường hai kỳ nó là dấu hiệu mong đợi, không phải lý do loại.
_PAIR_VERB = re.compile(
    r"^\s*(?:t[íi]nh\s+|x[aá]c\s*[đd][iị]nh\s+)?(?:ph[aầ]n\s*tr[aă]m\s+)?(?:t[oố]c\s*[đd][oộ]\s+)?"
    r"(?:m[uứ]c\s+|t[ỷy]\s*l[ệe]\s+)?(?:t[aă]ng\s*tr[uư][ởo]ng|ch[eê]nh\s*l[ệe]ch|hi[eệ]u\s*s[oố]|"
    r"bi[eế]n\s*[đd][oộ]ng|thay\s*[đd][oổ]i)\s+",
    re.I,
)
# Giới từ còn treo lại sau khi cắt đuôi câu: "... vốn chủ sở hữu giữa".
_DANGLING = re.compile(r"\s+(?:gi[uữ]a|t[uừ]|c[uủ]a|trong|so)\s*$", re.I)
# Câu hỏi muốn phần trăm tăng trưởng, không phải hiệu số tuyệt đối.
_GROWTH = re.compile(
    r"t[aă]ng\s*tr[uư][ởo]ng|t[oố]c\s*[đd][oộ]|bao\s+nhi[eê]u\s*%|ph[aầ]n\s*tr[aă]m|t[ỷy]\s*l[ệe]",
    re.I,
)


def clean_phrase(phrase: str) -> str:
    """Cụm chỉ tiêu sau khi bỏ mốc ngày và động từ so sánh dẫn đầu.

    Lặp vì ba mẫu có thể lồng nhau: "Đến ngày 31/12/2022, mức tăng trưởng X của" cần
    cả ba lượt cắt.
    """
    for _ in range(3):
        before = phrase
        phrase = _DANGLING.sub("", _PAIR_VERB.sub("", _LEAD_DATE.sub("", phrase)))
        if phrase == before:
            break
    return phrase.strip(" ,;:")


def load_jsonl(path: Path) -> dict[int, dict]:
    out: dict[int, dict] = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rec = json.loads(line)
                out[rec["id"]] = rec
    return out


def locate(
    question: str,
    enriched: dict,
    phrases: list[str],
    year: int,
    ranked: list[str],
    *,
    threshold: float = THRESHOLD,
):
    """Ô mà `cell_locator` sẽ nhận cho đúng một năm, hoặc (None, lý do).

    Sao lại nguyên phần sau `build_request` của `locate_single_cell`: cùng ngưỡng, cùng
    phép dedupe, cùng phép kiểm mơ hồ. Chỉ khác ở chỗ `request` được dựng sẵn với một
    năm cụ thể thay vì đi qua cổng phạm vi.

    `threshold` mở ra được vì đường hai kỳ có một tín hiệu mà đường một ô không có:
    hai năm phải rơi vào cùng một nhãn hàng. Xem `gate_l3_pair_agree`.
    """
    request = CellRequest(
        metric_phrases=phrases,
        ticker=str(enriched["tickers"][0]),
        year=year,
        doc_type=str(enriched.get("doc_type") or "unknown"),
        period=period_intent(question),
        value_transform=value_transform(question, phrases),
        target_unit=unit_from_hint(str(enriched.get("unit_hint") or ""))
        or unit_from_hint(question)
        or "unknown",
    )
    cells = []
    for phrase in phrases:
        for hit in search_rows(ranked, phrase, ticker=request.ticker, year=year, limit=12):
            cell = _hit_to_cell(hit, phrase, request, ranked)
            if cell is not None:
                cells.append(cell)
    if not cells:
        return None, "S7 không ra ô số"
    deduped: dict[tuple[str, int, str], object] = {}
    for cell in cells:
        key = (cell.table_id, cell.row_position, cell.column)
        if key not in deduped or cell.confidence > deduped[key].confidence:
            deduped[key] = cell
    ordered = sorted(
        deduped.values(),
        key=lambda h: (-h.confidence, -h.row_score, -h.column_score, h.table_id, h.row_position),
    )
    best = ordered[0]
    if best.confidence < threshold:
        return None, f"S8 dưới ngưỡng ({best.confidence})"
    if len(ordered) > 1 and best.confidence - ordered[1].confidence < 0.04 and (
        best.table_id != ordered[1].table_id
        or best.row_position != ordered[1].row_position
        or best.column != ordered[1].column
    ):
        return None, "S9 mơ hồ"
    return best, ""


def cell_value(cell) -> float | None:
    try:
        return parse_number(str(load_frame(cell.table_id).iloc[cell.row_position][cell.column]))
    except Exception:  # noqa: BLE001 - ô không đọc được thì coi như không có
        return None


def phrases_for(question: str, *, cleaned: bool) -> list[str]:
    raw = direct_metric_phrases(question, "")
    out = [clean_phrase(p) if cleaned else p for p in raw]
    return [p for p in dict.fromkeys(out) if len(p.split()) >= 2]


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    labels = load_labels()
    sub = load_submission(sys.argv[1])
    name = Path(sys.argv[1]).parent.name
    questions = {q: r["question"] for q, r in load_jsonl(RAW_QUESTIONS_PATH).items()}
    enriched = load_jsonl(QUESTION_METADATA_PATH)
    run = load_jsonl(RUN)

    l3 = [q for q, text in questions.items() if level(text) == "L3"]
    shapes = Counter(
        (len(enriched.get(q, {}).get("tickers") or []), len(enriched.get(q, {}).get("years") or []))
        for q in l3
    )
    pair = [
        q
        for q in l3
        if len(enriched.get(q, {}).get("tickers") or []) == 1
        and len(enriched.get(q, {}).get("years") or []) == 2
        and run.get(q, {}).get("table_ids")
    ]
    print(f"L3 trên {len(questions)} câu: {len(l3)}")
    print(f"  hình dạng (mã, năm) hay gặp: {dict(sorted(shapes.items(), key=lambda kv: -kv[1])[:6])}")
    print(f"  đúng 1 mã + 2 năm, có shortlist: {len(pair)} câu\n")

    fired: dict[int, tuple[list[int], list]] = {}
    for cleaned in (False, True):
        both = 0
        only_one = 0
        cell_ok = 0
        cell_n = 0
        stops: Counter[str] = Counter()
        for qid in pair:
            phrases = phrases_for(questions[qid], cleaned=cleaned)
            if not phrases:
                stops["P5 hết cụm sau khi cắt"] += 1
                continue
            years = sorted(int(y) for y in enriched[qid]["years"])
            results = [
                locate(questions[qid], enriched[qid], phrases, y, run[qid]["table_ids"])
                for y in years
            ]
            cell_n += len(results)
            cell_ok += sum(1 for cell, _ in results if cell is not None)
            got = [cell for cell, _ in results if cell is not None]
            if len(got) == len(years):
                both += 1
                if cleaned:
                    fired[qid] = (years, got)
            elif got:
                only_one += 1
            else:
                stops[next(r for _, r in results if r)] += 1
        tag = "cụm đã cắt   " if cleaned else "cụm thô      "
        print(
            f"{tag} bắn cả 2 ô {both:>3}/{len(pair)} = {both / len(pair):>4.0%}"
            f" | chỉ 1 ô {only_one:>2} | mỗi-ô nhận {cell_ok}/{cell_n} = {cell_ok / cell_n:.0%}"
        )
        for reason, count in stops.most_common(4):
            print(f"     dừng vì {reason:<28}{count:>3}")

    scorable = [q for q in pair if as_float(labels.get(q, {}).get("answer")) is not None]
    print(f"\nchấm độ đúng: {len(pair)} câu trong lớp, {len(scorable)} có nhãn, "
          f"{sum(1 for q in fired if q in scorable)} vừa bắn vừa có nhãn.")
    print("  (n này quá nhỏ để kết luận; xem docstring)")
    print(f"  {'id':<7}{'phép':<9}{'gold':>13}{'cặp tính ra':>15}{'khớp':>7}{name[:12]:>13}")
    for qid in sorted(fired):
        if qid not in scorable:
            continue
        years, cells = fired[qid]
        gold = as_float(labels[qid].get("answer"))
        values = [cell_value(c) for c in cells]
        if any(v is None for v in values):
            print(f"  q{qid:<6}{'?':<9}{gold:>13.4g}{'ô không đọc được':>15}")
            continue
        old, new = values[0], values[-1]
        if _GROWTH.search(questions[qid]):
            got = (new - old) / abs(old) * 100 if old else None
            hit = got is not None and correct(got, gold)
            kind = "tăng %"
        else:
            got = new - old
            # Cặp ô là giá trị thô trước khâu đổi đơn vị, nên quét 10^k để tách "sai ô"
            # khỏi "đúng ô, sai đơn vị".
            hit = any(correct(got / 10**k, gold) for k in range(-3, 13))
            kind = "hiệu"
        v9_ok = correct(sub.get(qid, {}).get("answer"), labels[qid].get("answer"))
        print(
            f"  q{qid:<6}{kind:<9}{gold:>13.4g}{got:>15.4g}"
            f"{('khớp' if hit else 'lệch'):>7}{('đúng' if v9_ok else 'sai'):>13}"
        )


if __name__ == "__main__":
    main()
