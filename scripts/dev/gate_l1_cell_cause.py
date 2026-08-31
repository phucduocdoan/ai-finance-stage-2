"""Với các câu L1 (đọc một ô) trong tập eval sạch, xem câu sai vì đọc nhầm hàng,
nhầm cột, cả hai, hay ô đúng nhưng đơn vị sai, hay báo cáo gold còn thiếu.

Chỉ đọc lại đúng những gì submission đã dùng: parse `pandas_query` để lấy
`dfN.iloc[i]['col']`, tra `evidence` để biết `dfN` trỏ tới file csv nào (đường dẫn
trong `evidence` là tương đối so với thư mục chứa `submission.json`, ví dụ
`output/submission_v9_sign/data/...csv`), rồi mở đúng file đó và đọc đúng dòng đó.
Không gọi LLM, không dựng lại retriever, không đoán bằng tay.

Bậc L1 lấy từ `scripts/gate_type_split.level()`, không định nghĩa lại ở đây.

Query chỉ được xử lý nếu nó khớp đúng dạng "đọc một ô":
`(round(|abs()* )dfN.iloc[i]['col']`, xuất hiện đúng một lần. Câu nào query đọc
nhiều ô (`.sum()`, nhiều `iloc`, `.loc[...]`), hoặc là một hằng số đã tính sẵn
(không có `dfN` nào), hoặc `evidence` không có biến `dfN` được dùng, hoặc file csv
không tồn tại -- rơi vào "không phân giải được". Không suy đoán thêm.

Khớp nhãn hàng là xấp xỉ, cẩn thận đọc, đừng tin tuyệt đối:
  - Nhãn hàng đọc được (`read_row_label`) là chuỗi chữ dài nhất trong đúng dòng đó,
    lấy từ MỌI cột (không riêng cột đầu) trừ cột bị query đọc, vì nhiều bảng có mã
    số/STT ở cột đầu và nhãn thật ở cột hai.
  - So khớp bằng cách chuẩn hoá (bỏ dấu, hạ chữ thường), bỏ phần trong ngoặc, bỏ số
    thứ tự đầu dòng ("9.", "XI.", "a"), rồi kiểm substring hai chiều. Cách này từ
    chối đúng cặp nhãn gần nghĩa nhưng khác chỉ tiêu (".. ngắn hạn" so với "..
    khác"), NHƯNG cũng từ chối oan một số hàng đúng mà bảng gọi tên khác gold (ví
    dụ "Lợi nhuận thuần phân bổ cho cổ đông" so với "Lợi nhuận sau thuế của công ty
    mẹ" -- cùng một dòng, chữ khác). Phần kiểm định ở cuối chạy đúng phép so này
    trên các câu ĐÃ ĐÚNG để đo tỷ lệ từ chối oan đó, đừng đọc "sai hàng" ở phần trên
    mà không nhìn số này.
  - Trước khi kết luận theo nhãn, script tìm `raw_cell_value` của gold (khi đó là
    một số đơn, không phải công thức nhiều số) trong TẤT CẢ các cột số của đúng
    dòng đã đọc. Nếu số đó nằm trong cột đã đọc -> ô đúng, chỉ đơn vị sai. Nếu nó
    nằm ở một cột KHÁC trong cùng dòng -> hàng đúng, cột sai, bất kể nhãn cột đọc
    được trông có giống gold hay không (bắt được các bảng bị lệch cột do OCR).

Khớp nhãn cột: chuẩn hoá, tách số dính chữ ("2024VND" -> "2024 vnd"), rồi so năm
(regex 19xx/20xx) trước -- năm khác là chắc chắn khác cột; sau đó so các từ khoá
đầu/cuối/kỳ/nay/trước còn lại sau khi bỏ đơn vị tiền (vnd/triệu/đồng/nghìn/tỷ).

Dùng:
    PYTHONPATH=src:scripts .venv_bge/bin/python scripts/gate_l1_cell_cause.py \
        output/submission_v9_sign/submission.json
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from finance_qa.modules.solve.common.intent import norm  # noqa: E402

from gate_type_split import level  # noqa: E402
from score_clean_eval import as_float, correct, load_labels, load_submission  # noqa: E402

QUESTIONS = Path("ViFinQA/questions/questions.jsonl")

CELL_RE = re.compile(r"(df\d+)\.iloc\[(-?\d+)\]\[\s*['\"](.+?)['\"]\s*\]")
YEAR_RE = re.compile(r"(?:19|20)\d\d")
ROMAN = {
    "i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x",
    "xi", "xii", "xiii", "xiv", "xv", "xvi", "xvii", "xviii", "xix", "xx",
}
CURRENCY_TOKENS = {"vnd", "trieu", "nghin", "ty", "dong"}
NUM_RE = re.compile(r"-?\d[\d.,]*")


def parse_single_cell(query: str) -> tuple[str, int, str] | None:
    """Trả (dfN, hàng, cột) nếu query khớp đúng dạng đọc một ô, else None."""
    matches = CELL_RE.findall(query)
    uniq = {(m[0], m[1], m[2]) for m in matches}
    if len(uniq) != 1:
        return None
    dfvar, idx, col = matches[0]
    return dfvar, int(idx), col


def strip_lead_number(tokens: list[str]) -> list[str]:
    while tokens and (tokens[0] in ROMAN or re.fullmatch(r"\d{1,3}", tokens[0]) or (len(tokens[0]) == 1 and tokens[0].isalpha())):
        tokens = tokens[1:]
    return tokens


def clean_label(raw: object) -> str:
    s = re.sub(r"\([^)]*\)", " ", str(raw or ""))
    tokens = norm(s).split()
    return " ".join(strip_lead_number(tokens))


def label_match(gold_raw: object, read_raw: object) -> bool:
    a, b = clean_label(gold_raw), clean_label(read_raw)
    if not a or not b:
        return False
    return a in b or b in a


def split_alnum(s: str) -> str:
    return re.sub(r"(?<=[0-9])(?=[^\W\d_])|(?<=[^\W\d_])(?=[0-9])", " ", s)


def clean_col(raw: object) -> str:
    s = re.sub(r"\([^)]*\)", " ", str(raw or ""))
    return norm(split_alnum(s))


def col_match(gold_raw: object, read_raw: object) -> bool:
    gy, ry = set(YEAR_RE.findall(str(gold_raw or ""))), set(YEAR_RE.findall(str(read_raw or "")))
    if gy and ry and gy.isdisjoint(ry):
        return False
    a = [t for t in clean_col(gold_raw).split() if t not in CURRENCY_TOKENS and not t.isdigit()]
    b = [t for t in clean_col(read_raw).split() if t not in CURRENCY_TOKENS and not t.isdigit()]
    if not a or not b:
        return True  # không còn gì để so, không phạt
    return bool(set(a) & set(b))


def read_row_label(row: pd.Series, target_col: str) -> str:
    """Chuỗi chữ dài nhất trong dòng, trừ cột bị query đọc."""
    best = ""
    for col, val in row.items():
        if col == target_col or pd.isna(val):
            continue
        text = str(val)
        if re.search(r"[a-zA-ZÀ-ỹà-ỹ]", text) and len(text) > len(best):
            best = text
    return best


def parse_gold_number(raw: object) -> float | None:
    """Số đơn của gold (không phải công thức nhiều số như '27.045.792 + 991.387')."""
    if raw is None:
        return None
    s = str(raw).strip()
    if any(op in s for op in ["+", "-", ";", "/"]) and NUM_RE.findall(s.replace("-", "", 1)) and len(NUM_RE.findall(s)) > 1:
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    s = s.replace(".", "").replace(",", ".")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def find_value_columns(row: pd.Series, target: float, tol: float = 1e-6) -> list[str]:
    hits = []
    for col, val in row.items():
        try:
            v = float(val)
        except (TypeError, ValueError):
            continue
        if abs(v) < 1e-9 and abs(target) < 1e-9:
            hits.append(col)
        elif target != 0 and abs(abs(v) - abs(target)) / max(abs(v), abs(target)) < tol:
            hits.append(col)
    return hits


def report_available(report_id: object, relevant_tables: list[str]) -> bool:
    """Báo cáo gold có nằm trong shortlist không, kiểm cả mã, năm và bản riêng/hợp nhất.

    Bỏ sót biến thể riêng/hợp nhất từng gây một ca sai (q714: shortlist toàn bản
    hợp nhất, gold cần bản riêng) -- nên đây kiểm cả ba, không chỉ mã và năm.
    """
    rid = str(report_id or "")
    if not rid:
        return True  # không có gì để kiểm, không quy oan
    tickers = set(re.findall(r"\b[A-Z]{2,5}\b", rid))
    years = set(YEAR_RE.findall(rid))
    text = " ".join(relevant_tables or [])
    if tickers and not any(t in text for t in tickers):
        return False
    if years and not any(y in text for y in years):
        return False
    variant = "consolidated" if "_consolidated" in rid else "separate" if "_separate" in rid else None
    if variant and variant not in text:
        return False
    return True


def classify(qid: int, lab: dict, item: dict, base_dir: Path) -> dict:
    out = {
        "id": qid,
        "gold_row": lab.get("row_label"),
        "gold_col": lab.get("column_label"),
        "read_row": None,
        "read_col": None,
        "cause": None,
        "note": "",
    }
    if not report_available(lab.get("report_id"), item.get("relevant_tables") or []):
        out["cause"] = "không có báo cáo gold"
        return out

    parsed = parse_single_cell(item.get("pandas_query") or "")
    if parsed is None:
        out["cause"] = "không phân giải được"
        out["note"] = "pandas_query không khớp dạng đọc một ô"
        return out
    dfvar, idx, col = parsed
    ev = next((e for e in item.get("evidence") or [] if e.get("variable") == dfvar), None)
    if ev is None:
        out["cause"] = "không phân giải được"
        out["note"] = f"evidence không có {dfvar}"
        return out
    path = base_dir / ev["csv_path"]
    if not path.exists():
        out["cause"] = "không phân giải được"
        out["note"] = f"không thấy file {path}"
        return out
    df = pd.read_csv(path, dtype=str)
    if idx < 0 or idx >= len(df) or col not in df.columns:
        out["cause"] = "không phân giải được"
        out["note"] = f"hàng {idx} hoặc cột {col!r} không tồn tại trong {path.name}"
        return out
    row = df.iloc[idx]
    out["read_row"] = read_row_label(row, col)
    out["read_col"] = col

    r_match = label_match(lab.get("row_label"), out["read_row"])
    c_match_label = col_match(lab.get("column_label"), col)

    gold_num = parse_gold_number(lab.get("raw_cell_value"))
    if gold_num is not None:
        hit_cols = find_value_columns(row, gold_num)
        if hit_cols:
            if col in hit_cols:
                out["cause"] = "đúng ô, sai đơn vị"
            else:
                out["cause"] = "sai cột"
                out["note"] = f"số gold nằm ở cột {hit_cols}, không phải {col!r}"
            return out

    if r_match and c_match_label:
        out["cause"] = "không phân giải được"
        out["note"] = "nhãn hàng và cột đều khớp nhưng giá trị vẫn sai (nghi trùng nhãn ở chỗ khác)"
    elif r_match and not c_match_label:
        out["cause"] = "sai cột"
    elif not r_match and c_match_label:
        out["cause"] = "sai hàng"
    else:
        out["cause"] = "sai cả hai"
    return out


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    sub_path = Path(sys.argv[1])
    base_dir = sub_path.parent
    labels = load_labels()
    questions = {
        json.loads(line)["id"]: json.loads(line)["question"]
        for line in QUESTIONS.read_text().splitlines()
        if line.strip()
    }
    sub = load_submission(str(sub_path))

    l1_ids = [
        qid for qid, lab in sorted(labels.items())
        if as_float(lab.get("answer")) is not None and level(questions[qid]) == "L1"
    ]
    right = [q for q in l1_ids if correct(sub.get(q, {}).get("answer"), labels[q].get("answer"))]
    wrong = [q for q in l1_ids if q not in right]

    print(f"L1 chấm được: {len(l1_ids)} câu ({len(right)} đúng / {len(wrong)} sai)\n")

    print("=== câu sai: nguyên nhân ===")
    results = {}
    for q in wrong:
        results[q] = classify(q, labels[q], sub.get(q, {}), base_dir)

    from collections import Counter
    causes = Counter(r["cause"] for r in results.values())
    for c, n in causes.most_common():
        print(f"  {c:<28} {n:>3}")
    print(f"  {'TỔNG':<28} {len(wrong):>3}\n")

    print(f"  {'id':>5}  {'nguyên nhân':<26}{'gold hàng':<45}{'đọc hàng':<45}{'gold cột':<28}{'đọc cột':<28}chú thích")
    for q in wrong:
        r = results[q]
        print(
            f"  {q:>5}  {r['cause']:<26}"
            f"{str(r['gold_row'])[:43]:<45}{str(r['read_row'])[:43]:<45}"
            f"{str(r['gold_col'])[:26]:<28}{str(r['read_col'])[:26]:<28}{r['note']}"
        )

    print("\n=== kiểm định trên câu đúng (matcher có từ chối oan không) ===")
    ctrl = {q: classify(q, labels[q], sub.get(q, {}), base_dir) for q in right}
    ctrl_causes = Counter(r["cause"] for r in ctrl.values())
    for c, n in ctrl_causes.most_common():
        print(f"  {c:<28} {n:>3}")
    n_flagged = sum(1 for r in ctrl.values() if r["cause"] not in (None,) and r["cause"] != "không phân giải được" and "đúng" not in r["cause"] and r["cause"] not in ("đúng ô, sai đơn vị",))
    # câu đúng mà matcher lại báo sai hàng/cột/cả hai/thiếu báo cáo là từ chối oan
    false_flag = [q for q, r in ctrl.items() if r["cause"] in ("sai hàng", "sai cột", "sai cả hai", "không có báo cáo gold")]
    print(f"\n  câu ĐÚNG nhưng matcher báo có lỗi (từ chối oan): {len(false_flag)}/{len(right)} -> {false_flag}")
    for q in false_flag:
        r = ctrl[q]
        print(f"    q{q}: {r['cause']}  gold_row={r['gold_row']!r}  read_row={r['read_row']!r}")


if __name__ == "__main__":
    main()
