"""Với các câu L3 (hai kỳ cùng chỉ tiêu) và L5 (gộp nhiều công ty/năm) sai trong tập
eval sạch, xem câu sai vì đâu khi bằng chứng đã có sẵn (68/70 câu sai của v9 đã có đủ
báo cáo gold trong `relevant_tables`, xem commit b411f8e) mà pipeline vẫn ra sai số.

Reuse triệt để, không viết lại: `CELL_RE`, `YEAR_RE`, `read_row_label`,
`report_available` từ `scripts/gate_l1_cell_cause.py`; `level`, `REPORT_ID` từ
`scripts/gate_type_split.py`; `as_float`, `correct`, `load_labels`, `load_submission`
từ `scripts/score_clean_eval.py`; `parse_number` (đọc số kiểu Việt Nam, dấu ngoặc =
âm) từ `finance_qa.modules.tools.numeric` -- không viết lại parser số.

CÁCH ĐO (bậc phân loại, kiểm theo thứ tự, câu nào khớp bậc nào thì dừng ở đó):

  0. "thiếu báo cáo gold": báo cáo nhãn nêu tên không có trong `relevant_tables`
     (dùng lại `report_available`, không đo lại).
  1. "sai số lượng ô/bảng": `pandas_query` có ít ô `dfN.iloc[i][col]` PHÂN BIỆT
     hơn một NGƯỠNG DƯỚI ước lượng từ nhãn -- ngưỡng dưới lấy max của: số báo cáo
     tách từ `report_id` (";", "/", "+", " và ", " so với ", " vs "), số phần tách
     tương tự trong `column_label`, trong `row_label`, và số "<số>(<năm>)" trong
     `raw_cell_value`. Đây LÀ NGƯỠNG DƯỚI, không phải số ô đúng: một câu cần 4 công
     ty x 2 dòng = 8 ô chỉ cho ngưỡng dưới 4 (max, không phải tích), nên bậc này chỉ
     bắt được thiếu hụt rõ ràng, không bắt được thiếu hụt bị ngưỡng dưới che khuất.
     `count_enumerated` không hiểu dạng ngoặc nhọn "TICKER_..._{2016,2017}_.." nên
     ngưỡng dưới của 3 câu đó (q894, q928, q947) tụt xuống 1; bậc 2 thì đã dùng
     `report_ids` nên bung được, và chính nhờ vậy q947 xếp đúng vào bậc 2 chứ không
     phải 3a như bản đầu.
  2. "đúng số ô, sai báo cáo/năm": số ô đủ, nhưng báo cáo suy ra từ đường dẫn csv
     của ô đã đọc không khớp mã + năm + biến thể (riêng/hợp nhất) với báo cáo nào
     trong `report_id` của nhãn.
  3a. "đúng báo cáo, sai ô trong bảng": có ô đọc được một số, nhưng số đó (kể cả
     nhân/chia luỹ thừa 10 và đổi dấu) không khớp bất kỳ số nào tách được từ
     `raw_cell_value` của nhãn -- tức bảng đúng nhưng hàng/cột trong bảng đó sai.
     Đây là bậc mà sáu nhóm team lead yêu cầu không có tên riêng; thêm vào theo
     đúng lời nhắc "thêm bucket trung thực, không ép vào nhóm không hợp".
  4. "đơn vị lệch giữa các ô": mọi ô đều khớp một số gold nào đó, nhưng không
     cùng một luỹ thừa 10 -- ô nọ khớp gold y hệt, ô kia khớp gold x10^k. Tức các
     bảng nguồn khai báo đơn vị khác nhau mà câu lệnh cộng/trừ/chia thẳng, không quy
     đổi.
  3b. "đúng ô, sai công thức": mọi ô khớp gold ở CÙNG một luỹ thừa 10, và có một
     tổ hợp số học khác (hiệu, tổng, tỷ lệ theo cả hai chiều, tăng trưởng %, trung
     bình, min/max -- xem `generate_candidates`) trên đúng các ô đó cho ra đáp án
     nhãn, còn công thức trong `pandas_query` thì không.
  5. "lệch luỹ thừa mười": mọi ô khớp gold, không tổ hợp nào ở mục 3b khớp, nhưng
     đáp án đã nộp / đáp án nhãn là một luỹ thừa 10 sạch (khác 1) -- công thức đúng
     hình dạng, chỉ sai hằng số quy đổi.
  6. "mọi thứ đều đúng, vẫn sai": qua hết các kiểm định trên mà vẫn không giải
     thích được vì sao sai -- bucket thật, không gán bừa.
  "không phân giải được": `pandas_query` không có `dfN.iloc[i][col]` nào bắt được
     (hằng số, `.sum()` trên slice, cú pháp khác), hoặc `evidence`/file/ô không tồn
     tại, hoặc `raw_cell_value` của nhãn không chứa số cụ thể nào để so.

KIỂM ĐỊNH TRÊN CÂU ĐÚNG (bắt buộc đọc trước khi tin số ở trên): chạy đúng các bậc
0, 1, 2, 3a, 4 (các kiểm định KHÔNG phụ thuộc câu đúng/sai, thuần cấu trúc) trên
các câu L3/L5 đã chấm ĐÚNG. Không chạy 3b/5/6 ở đó vì hai bậc này chỉ có nghĩa khi
đáp án đã biết là sai (một câu đúng thì "đáp án đã nộp" trùng "đáp án nhãn", nên
mọi phép thử tổ hợp số học sẽ khớp một cách tuần hoàn, không nói lên gì cả -- đưa
nó vào kiểm định sẽ tự tạo ra một tỷ lệ báo sai giả và làm loãng con số thật). Câu
đúng mà vẫn bị 0/1/2/3a/4 gắn cờ là báo sai oan thật, phải tính vào và không được
lờ đi.

GIỚI HẠN, đọc trước khi dùng số:
  - Ngưỡng dưới ở bậc 1 là suy từ VĂN BẢN nhãn (report_id/row_label/column_label),
    không phải từ cấu trúc tài chính thật, nên là chặn dưới lỏng, không phải số ô
    cần thật.
  - Bậc 3a/3b/4/5 chỉ chạy được nếu `raw_cell_value` của nhãn có ít nhất một số
    dạng có dấu chấm phân nghìn (`\\d{1,3}(\\.\\d{3})+`) -- số kiểu "0.81" (không
    phân nghìn) không được coi là "số gold" vì không phân biệt được với ngày/mã.
    Câu nào `raw_cell_value` chỉ là mô tả bằng lời (không có số) thì rơi vào
    "không phân giải được", không đoán.
  - Đây là công cụ đo, không phải bằng chứng tuyệt đối cho một câu cụ thể: mọi số
    ở bảng cuối đều có id kèm theo để tra lại tay.

Dùng:
    PYTHONPATH=src:scripts .venv_bge/bin/python scripts/gate_multi_cell_cause.py \
        output/submission_v9_sign/submission.json
"""

from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from finance_qa.modules.tools.numeric import parse_number  # noqa: E402

from gate_l1_cell_cause import CELL_RE, YEAR_RE, read_row_label, report_available  # noqa: E402
from gate_type_split import level, report_ids  # noqa: E402
from score_clean_eval import as_float, correct, load_labels, load_submission  # noqa: E402

QUESTIONS = Path("ViFinQA/questions/questions.jsonl")

# Số có phân nghìn kiểu Việt Nam: ít nhất một cụm ".ddd" -- loại được ngày
# ("30/9/2025" không có phân nghìn) và mã số ngắn ("313").
GROUPED_NUM_RE = re.compile(r"-?\(?\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?\)?")
# "<số phân nghìn> (<năm>)" -- hình chữ ký của raw_cell_value khi nhãn liệt kê
# nhiều năm, ví dụ "1.614.902.270.238 (2016); 526.610.104.869 (2017)".
YEAR_PAREN_RE = re.compile(r"\d{1,3}(?:[.,]\d{3})+\s*\(\s*(?:19|20)\d\d\s*\)")
# Bảo vệ ngày dạng dd/mm/yyyy khỏi bị tách nhầm thành 3 phần khi đếm liệt kê.
DATE_SLASH_RE = re.compile(r"\d{1,2}/\d{1,2}(?:/\d{2,4})?")
SEP_RE = re.compile(r";|/|\+| và | so với | vs ")


def count_enumerated(text: object) -> int:
    """Số phần được liệt kê trong một trường nhãn (report_id/row_label/column_label)."""
    t = str(text or "")
    if not t.strip():
        return 0
    t = DATE_SLASH_RE.sub(lambda m: m.group(0).replace("/", "@"), t)
    parts = [p.strip() for p in SEP_RE.split(t) if p.strip()]
    return len(parts)


def expected_floor(lab: dict) -> int:
    """Ngưỡng dưới số ô cần đọc, suy từ văn bản nhãn -- xem giới hạn trong docstring."""
    n_reports = count_enumerated(lab.get("report_id"))
    n_cols = count_enumerated(lab.get("column_label"))
    n_rows = count_enumerated(lab.get("row_label"))
    n_years = len(YEAR_PAREN_RE.findall(str(lab.get("raw_cell_value") or "")))
    return max(n_reports, n_cols, n_rows, n_years, 1)


def extract_gold_numbers(raw: object) -> list[float]:
    """Mọi số có phân nghìn trong raw_cell_value, đã đổi dấu theo dấu ngoặc."""
    text = str(raw or "")
    out = []
    for m in GROUPED_NUM_RE.finditer(text):
        v = parse_number(m.group(0))
        if v is not None:
            out.append(v)
    return out


def csv_report_id(name: str) -> str:
    return re.sub(r"_table_\d+\.csv$", "", name)


def report_plausible(actual: str, gold_reports: list[str]) -> bool:
    """`actual` (suy từ tên file csv đã đọc) có khớp mã + năm + biến thể một báo cáo nào
    trong danh sách `gold_reports` (tách từ report_id của nhãn) không."""
    if not gold_reports:
        return True  # nhãn không ghi nguồn cụ thể, không quy oan
    a_ticker = actual.split("_", 1)[0]
    a_year = next(iter(YEAR_RE.findall(actual)), None)
    a_variant = "consolidated" if "consolidated" in actual else "separate" if "separate" in actual else None
    for g in gold_reports:
        g_ticker = g.split("_", 1)[0]
        if a_ticker != g_ticker:
            continue
        g_year = next(iter(YEAR_RE.findall(g)), None)
        if a_year and g_year and a_year != g_year:
            continue
        g_variant = "consolidated" if "consolidated" in g else "separate" if "separate" in g else None
        if a_variant and g_variant and a_variant != g_variant:
            continue
        return True
    return False


def best_match(value: float, gold_numbers: list[float]) -> tuple[float, int, bool] | None:
    """Số gold gần `value` nhất (mod luỹ thừa 10 và dấu), ưu tiên luỹ thừa gần 0 nhất."""
    best = None
    for g in gold_numbers:
        if g == 0 or value == 0:
            continue
        ratio = abs(value) / abs(g)
        k_raw = math.log10(ratio)
        k = round(k_raw)
        if abs(k_raw - k) < 0.02:
            sign_flip = (value < 0) != (g < 0)
            if best is None or abs(k) < abs(best[1]):
                best = (g, k, sign_flip)
    return best


def generate_candidates(vals: list[float]) -> list[float]:
    """Mọi tổ hợp số học "chuẩn" có thể áp lên `vals`, để dò xem nhãn dùng phép nào."""
    n = len(vals)
    out: list[float] = []
    if n == 2:
        a, b = vals
        out += [a - b, b - a, a + b, (a + b) / 2, abs(a - b), abs(a - b) / 2]
        if b:
            out += [a / b, (a - b) / b * 100, (b - a) / b * 100]
        if a:
            out += [b / a, (a - b) / a * 100, (b - a) / a * 100]
    elif n >= 3:
        out += [
            sum(vals), sum(vals) / n, max(vals), min(vals), max(vals) - min(vals),
            sum(abs(v) for v in vals), sum(abs(v) for v in vals) / n,
        ]
    else:
        out += list(vals)
    return [c for c in out if c is not None and math.isfinite(c)]


def resolve_cell(dfvar: str, idx: int, col: str, evidence: list[dict], base_dir: Path, cache: dict) -> dict:
    ev = next((e for e in evidence or [] if e.get("variable") == dfvar), None)
    if ev is None:
        return {"error": f"evidence không có {dfvar}"}
    path = base_dir / ev["csv_path"]
    if path not in cache:
        cache[path] = pd.read_csv(path, dtype=str) if path.exists() else None
    df = cache[path]
    if df is None:
        return {"error": f"không thấy file {path}"}
    if idx < 0 or idx >= len(df) or col not in df.columns:
        return {"error": f"hàng {idx} hoặc cột {col!r} không tồn tại trong {path.name}"}
    row = df.iloc[idx]
    raw = row[col]
    num = parse_number(str(raw)) if pd.notna(raw) else None
    return {
        "report_id": csv_report_id(path.name),
        "table_id": path.name,
        "row_label": read_row_label(row, col),
        "raw": raw,
        "num": num,
    }


def classify(qid: int, lab: dict, item: dict, base_dir: Path, cache: dict, *, is_wrong: bool) -> dict:
    out = {"id": qid, "cause": None, "note": ""}

    if not report_available(lab.get("report_id"), item.get("relevant_tables") or []):
        out["cause"] = "0. thiếu báo cáo gold"
        return out

    query = item.get("pandas_query") or ""
    uniq_cells = sorted(set(CELL_RE.findall(query)))
    if not uniq_cells:
        out["cause"] = "không phân giải được"
        out["note"] = "pandas_query không có ô dfN.iloc[...] nào (hằng số hoặc công thức dạng khác)"
        return out

    evidence = item.get("evidence") or []
    resolved = {(v, int(i), c): resolve_cell(v, int(i), c, evidence, base_dir, cache) for v, i, c in uniq_cells}
    errs = sorted({r["error"] for r in resolved.values() if "error" in r})
    if errs:
        out["cause"] = "không phân giải được"
        out["note"] = "; ".join(errs)
        return out

    n_actual = len(uniq_cells)
    n_floor = expected_floor(lab)
    if n_actual < n_floor:
        out["cause"] = "1. sai số lượng ô/bảng"
        out["note"] = f"query đọc {n_actual} ô phân biệt, nhãn gợi ý cần tối thiểu {n_floor}"
        return out

    gold_reports = sorted(report_ids(lab.get("report_id")))
    actual_reports = sorted({r["report_id"] for r in resolved.values()})
    if gold_reports:
        bad = [a for a in actual_reports if not report_plausible(a, gold_reports)]
        if bad:
            out["cause"] = "2. đúng số ô, sai báo cáo/năm"
            out["note"] = f"đọc từ {bad}, nhãn cần một trong {gold_reports}"
            return out

    gold_numbers = extract_gold_numbers(lab.get("raw_cell_value"))
    if not gold_numbers:
        out["cause"] = "không phân giải được"
        out["note"] = "raw_cell_value không có số cụ thể (dạng mô tả bằng lời) để so"
        return out

    matches = {key: (best_match(r["num"], gold_numbers) if r["num"] is not None else None) for key, r in resolved.items()}
    unmatched = [k for k, m in matches.items() if m is None]
    if unmatched:
        out["cause"] = "3a. đúng báo cáo, sai ô trong bảng"
        vals = [(k, resolved[k]["num"], resolved[k]["row_label"]) for k in unmatched]
        out["note"] = f"ô không khớp số gold nào ({gold_numbers}): {vals}"
        return out

    ks = {m[1] for m in matches.values()}
    if len(ks) > 1:
        out["cause"] = "4. đơn vị lệch giữa các ô"
        out["note"] = f"các ô khớp gold ở luỹ thừa 10 khác nhau: {sorted(ks)}"
        return out

    if not is_wrong:
        # Câu đã biết đúng: dừng ở đây, không thử tổ hợp số học (xem docstring).
        out["cause"] = "đúng"
        return out

    vals = [resolved[key]["num"] for key in sorted(resolved)]
    candidates = generate_candidates(vals)
    gold_answer = as_float(lab.get("answer"))
    if gold_answer is not None and any(correct(c, gold_answer) for c in candidates):
        out["cause"] = "3b. đúng ô, sai công thức"
        return out

    sub_answer = as_float(item.get("answer"))
    if sub_answer and gold_answer:
        ratio = abs(sub_answer / gold_answer)
        k = round(math.log10(ratio))
        if abs(math.log10(ratio) - k) < 0.02 and k != 0:
            out["cause"] = "5. lệch luỹ thừa mười"
            out["note"] = f"đã nộp/nhãn = 10^{k}"
            return out

    out["cause"] = "6. mọi thứ đều đúng, vẫn sai"
    return out


def _load_questions() -> dict[int, str]:
    return {
        json.loads(line)["id"]: json.loads(line)["question"]
        for line in QUESTIONS.read_text().splitlines()
        if line.strip()
    }


def _print_causes(title: str, results: dict[int, dict]) -> None:
    causes = Counter(r["cause"] for r in results.values())
    print(f"  {title}")
    for c, n in causes.most_common():
        print(f"    {c:<36} {n:>3}")
    print(f"    {'TỔNG':<36} {len(results):>3}\n")


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    sub_path = Path(sys.argv[1])
    base_dir = sub_path.parent
    labels = load_labels()
    questions = _load_questions()
    sub = load_submission(str(sub_path))
    cache: dict = {}

    for lvl in ["L3", "L5"]:
        ids = [
            qid for qid, lab in sorted(labels.items())
            if as_float(lab.get("answer")) is not None and level(questions[qid]) == lvl
        ]
        wrong = [q for q in ids if not correct(sub.get(q, {}).get("answer"), labels[q].get("answer"))]
        right = [q for q in ids if q not in wrong]
        print(f"=== {lvl}: {len(ids)} câu ({len(right)} đúng / {len(wrong)} sai) ===\n")

        wrong_results = {q: classify(q, labels[q], sub.get(q, {}), base_dir, cache, is_wrong=True) for q in wrong}
        _print_causes(f"{lvl} -- nguyên nhân câu sai:", wrong_results)

        print(f"    {'id':>5}  {'nguyên nhân':<34}chú thích")
        for q in wrong:
            r = wrong_results[q]
            print(f"    {q:>5}  {r['cause']:<34}{str(r['note'])[:160]}")
        print()

        ctrl_results = {q: classify(q, labels[q], sub.get(q, {}), base_dir, cache, is_wrong=False) for q in right}
        _print_causes(f"{lvl} -- kiểm định trên câu ĐÚNG (báo sai oan?):", ctrl_results)
        false_flags = {q: r for q, r in ctrl_results.items() if r["cause"] not in ("đúng", "không phân giải được")}
        print(f"    câu ĐÚNG mà bị gắn cờ có lỗi (báo sai oan): {len(false_flags)}/{len(right)}")
        for q, r in false_flags.items():
            print(f"      q{q}: {r['cause']}  -- {r['note']}")
        print()


if __name__ == "__main__":
    main()
