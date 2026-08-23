"""Định giá fuzzy match ở bước codegen viết tham chiếu ô.

Giả thuyết: truy vấn sinh ra gõ tên cột lệch một chút so với tên cột thật
(`'31/12/2022 Triệu VND'` so với `'31/12/2022Triệu VND'`), hoặc gõ chỉ số `iloc`
ngoài phạm vi, nên chết ở bước chạy và câu đó về 0.0.

Vì sao đường này có hình dạng khác bốn đường trước: nó **chỉ nổ khi truy vấn hiện
tại đã lỗi**. Câu đang đúng không thể bị chạm, trừ trường hợp gold đúng bằng 0.0.
Nên phần thua bị chặn trên bằng kiến trúc, không phải bằng lập luận.

Mốc chốt trước khi chạy: **>=10 câu lật đúng trên 119 câu chấm được, <=2 câu lật
sai** (McNemar một phía p = 0.019), cùng mốc đã dùng cho bốn đường trước.

Ba phép đo:

1. **Chạy lại 1012 truy vấn đã nộp** trên đúng bảng bằng chứng của nó, phân loại lỗi.
2. **Trong số lỗi, bao nhiêu là lệch tên cột / lệch chỉ số hàng**, và fuzzy có
   khớp về đúng một cột không.
3. **Sửa rồi chấm trên 119 câu**: thắng bao nhiêu, thua bao nhiêu.

Dùng:
    PYTHONPATH=src:scripts .venv_bge/bin/python scripts/gate_cell_ref_fuzzy.py
"""

from __future__ import annotations

import ast
import difflib
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

from finance_qa.modules.data.table_store import load_frame
from finance_qa.modules.tools.python_exec import run_query
from score_clean_eval import as_float, correct, load_labels

SUBMISSION = Path("output/submission_v9_sign/submission.json")
CSV_PATH = re.compile(r"data/(?P<rid>.+)_table_(?P<pos>\d+)\.csv")
FUZZY_CUTOFF = 0.85


def norm(text: object) -> str:
    """Dạng so khớp: bỏ dấu, bỏ hoa thường, bỏ mọi ký tự không phải chữ số."""
    decomposed = unicodedata.normalize("NFD", str(text)).lower().replace("đ", "d")
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "", stripped)


def frames_of(rec: dict) -> dict:
    out = {}
    for ev in rec.get("evidence") or []:
        m = CSV_PATH.match(ev.get("csv_path") or "")
        if not m or not ev.get("variable"):
            continue
        try:
            out[ev["variable"]] = load_frame(f"{m.group('rid')}|{m.group('pos')}")
        except Exception:  # noqa: BLE001 - một CSV không đọc được không được giết phép đo
            continue
    return out


def string_literals(query: str) -> list[str]:
    """Mọi hằng chuỗi trong truy vấn, tức mọi tên cột/nhãn nó gõ ra."""
    try:
        tree = ast.parse(query, mode="eval")
    except SyntaxError:
        return re.findall(r"['\"]([^'\"]+)['\"]", query)
    # Bỏ giá trị của tham số có tên: `errors="coerce"` là chuỗi nhưng không phải
    # tên cột, và nó làm phồng mọi con số đếm "gõ sai tên cột".
    kwargs = {id(k.value) for n in ast.walk(tree) if isinstance(n, ast.Call) for k in n.keywords}
    return [
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in kwargs
    ]


def fuzzy_column(name: str, columns: list[str]) -> str | None:
    """Cột thật mà `name` có ý chỉ tới, hoặc None nếu không chắc.

    Hai bước, chặt trước lỏng sau: khớp sau khi chuẩn hóa (chỉ lệch dấu cách,
    hoa thường, dấu thanh), rồi tới `difflib` nếu có đúng một ứng viên vượt mốc.
    Nhiều hơn một ứng viên thì trả None: đoán giữa hai cột số liệu của hai năm
    khác nhau là cách chắc chắn nhất để biến một câu lỗi thành một câu sai.
    """
    exact = [c for c in columns if norm(c) == norm(name)]
    if len(exact) == 1:
        return exact[0]
    if exact:
        return None
    # Hình dạng lỗi áp đảo: tiêu đề hai tầng bị làm phẳng thành `ngoài | trong`, mà
    # mô hình chỉ gõ tầng ngoài (`'31/12/2020'` cho `'31/12/2020 | Triệu VND'`).
    # `difflib` không bắt được vì tầng trong dài hơn cả tầng ngoài. Chỉ nhận khi có
    # đúng một cột mang tiền tố đó: `'31/12/2016 | Giá gốc'` với
    # `'31/12/2016 | Dự phòng'` là hai con số khác nhau, đoán giữa chúng là biến một
    # câu lỗi thành một câu sai.
    prefixed = [c for c in columns if norm(str(c).split("|")[0]) == norm(name)]
    if len(prefixed) == 1:
        return prefixed[0]
    if prefixed:
        return None
    # `Unnamed: 4` -> `Unnamed: 0` đạt tỉ lệ 0.875 nên vượt mốc, mà `Unnamed: 0` là
    # cột nhãn chỉ tiêu, không phải cột số. Tên `Unnamed: N` không mang nghĩa gì để
    # so khớp, nên không so.
    if re.fullmatch(r"unnamed\d*", norm(name)):
        return None
    scored = [
        (difflib.SequenceMatcher(None, norm(name), norm(c)).ratio(), c)
        for c in columns
        if not re.fullmatch(r"unnamed\d*", norm(c))
    ]
    near = [c for r, c in scored if r >= FUZZY_CUTOFF]
    return near[0] if len(near) == 1 else None


# `df3['cột']` và `df3.iloc[2]['cột']`: biến nào đang bị đánh chỉ số bằng chuỗi nào.
# Phải gắn chuỗi với đúng biến của nó, không gom cột của mọi frame lại: hai bảng của
# hai năm thường có cùng tên cột, gom lại thì mọi tên đều "nhập nhằng" và không sửa
# được gì. Lần đo đầu tôi gom, và nó chính là lý do fuzzy chỉ sửa được 4/48.
_SUBSCRIPT = re.compile(
    r"(?P<var>df\d+)(?:\.iloc\[\d+\])?\s*\[\s*(?P<q>['\"])(?P<lit>.*?)(?P=q)\s*\]"
)


def repair(query: str, frames: dict) -> str | None:
    """Đổi tên cột gõ sai thành tên cột thật của chính biến đó.

    Chỉ sửa chuỗi, không sửa chỉ số `iloc`: một chỉ số ngoài phạm vi thì không có
    dấu hiệu nào nói hàng đúng là hàng nào.
    """
    changed = False

    def swap(m: re.Match) -> str:
        nonlocal changed
        df = frames.get(m.group("var"))
        if df is None:
            return m.group(0)
        columns = [str(c) for c in df.columns]
        literal = m.group("lit")
        if norm(literal) in {norm(c) for c in columns}:
            return m.group(0)
        target = fuzzy_column(literal, columns)
        if target is None or target == literal:
            return m.group(0)
        changed = True
        return m.group(0).replace(
            f"{m.group('q')}{literal}{m.group('q')}", f'"{target}"'
        )

    fixed = _SUBSCRIPT.sub(swap, query)
    return fixed if changed else None


def main() -> None:
    records = {str(r["id"]): r for r in json.loads(SUBMISSION.read_text(encoding="utf-8"))}
    gold = {str(k): v for k, v in load_labels().items()}

    def gold_of(qid: str):
        g = gold[qid]
        return g.get("answer") if isinstance(g, dict) else g

    scorable = {q for q in gold if q in records and as_float(gold_of(q)) is not None}
    print(f"{len(records)} câu đã nộp, {len(scorable)} câu chấm được\n")

    # 1. Chạy lại mọi truy vấn.
    kinds: Counter[str] = Counter()
    failed: list[tuple[str, str, dict, str]] = []   # qid, query, frames, tên lỗi
    for qid, rec in records.items():
        query = (rec.get("pandas_query") or "").strip()
        frames = frames_of(rec)
        if not query:
            kinds["truy vấn rỗng"] += 1
            failed.append((qid, query, frames, "empty"))
            continue
        try:
            run_query(query, dict(frames))
        except Exception as exc:  # noqa: BLE001 - đang phân loại lỗi
            kind = type(exc).__name__
            kinds[kind] += 1
            failed.append((qid, query, frames, kind))
            continue
        kinds["chạy được"] += 1

    print("=== 1. chạy lại 1012 truy vấn trên chính bảng bằng chứng của nó ===")
    for kind, n in kinds.most_common():
        print(f"  {kind}: {n}")
    n_fail = len(failed)
    print(f"  tổng lỗi: {n_fail} = {n_fail / len(records):.1%}\n")

    # 2. Lỗi vì lệch tên cột, và fuzzy có khớp về đúng một cột không.
    print("=== 2. hình dạng lỗi ===")
    bad_literal, out_of_range, repairable = 0, 0, []
    ambiguous = 0
    for qid, query, frames, kind in failed:
        all_columns = [str(c) for df in frames.values() for c in df.columns]
        exact = {norm(c) for c in all_columns}
        literals = [s for s in set(string_literals(query)) if norm(s) not in exact]
        if literals:
            bad_literal += 1
        # Tầng ngoài của tiêu đề hai tầng khớp nhiều hơn một cột con: `'31/12/2016'`
        # ứng với cả `| Giá gốc` và `| Dự phòng`. Không có cách so chuỗi nào chọn
        # giữa hai cột đó, vì cái chọn là câu hỏi, không phải tên cột.
        if any(
            len([c for c in (str(x) for df in frames.values() for x in df.columns)
                 if norm(c.split("|")[0]) == norm(s)]) > 1
            for s in literals
        ):
            ambiguous += 1
        idxs = [int(i) for i in re.findall(r"iloc\[(\d+)\]", query)]
        if any(i >= len(df) for i in idxs for df in frames.values()) and len(frames) == 1:
            out_of_range += 1
        fixed = repair(query, frames)
        if fixed is None:
            continue
        try:
            value = float(run_query(fixed, dict(frames)))
        except Exception:  # noqa: BLE001 - bản sửa cũng có quyền lỗi
            continue
        repairable.append((qid, query, fixed, value))
    print(f"  gõ một chuỗi không phải tên cột thật: {bad_literal}/{n_fail}")
    print(f"    trong đó tầng ngoài khớp >1 cột con: {ambiguous} (so chuỗi không giải được)")
    print(f"  chỉ số iloc ngoài phạm vi (bảng đơn):  {out_of_range}/{n_fail}")
    print(f"  fuzzy sửa được rồi chạy được:          {len(repairable)}/{n_fail}")
    # Với mục tiêu chấm "chạy lại truy vấn", bản sửa chỉ an toàn khi nó tái tạo
    # đúng con số đã nộp: nộp một truy vấn chạy được nhưng ra số khác thì hai thước
    # đo tự chống nhau.
    same = [
        qid for qid, _, _, v in repairable
        if (a := as_float(records[qid].get("answer"))) is not None
        and abs(v - a) <= max(1e-6, abs(a) * 1e-6)
    ]
    print(f"  trong đó tái tạo đúng đáp án đã nộp:   {len(same)}/{len(repairable)}\n")

    # 3. Chấm trên 119 câu.
    print("=== 3. chấm bản sửa trên tập eval sạch ===")
    fixed_by_id = {qid: (q, f, v) for qid, q, f, v in repairable}
    wins, losses, misses = [], [], []
    for qid in sorted(scorable, key=int):
        was = correct(records[qid].get("answer"), gold_of(qid))
        if qid not in fixed_by_id:
            continue
        _, fixed, value = fixed_by_id[qid]
        now = correct(value, gold_of(qid))
        if now and not was:
            wins.append((qid, value, gold_of(qid)))
        elif was and not now:
            losses.append((qid, records[qid].get("answer"), value, gold_of(qid)))
        else:
            misses.append((qid, value, gold_of(qid)))
    n_fail_scorable = sum(1 for qid, *_ in failed if qid in scorable)
    print(f"  câu chấm được mà truy vấn lỗi: {n_fail_scorable}")
    print(f"  trong đó fuzzy sửa chạy được:  "
          f"{sum(1 for qid in fixed_by_id if qid in scorable)}")
    print(f"  thắng: {len(wins)}   thua: {len(losses)}   sửa xong vẫn sai: {len(misses)}")
    for qid, value, g in wins:
        print(f"    thắng q{qid}: {value} vs gold {g}")
    for qid, old, value, g in losses:
        print(f"    thua  q{qid}: {old} -> {value}, gold {g}")
    for qid, value, g in misses[:10]:
        print(f"    vẫn sai q{qid}: {value} vs gold {g}")
    print(f"\n  → mốc đã chốt: >=10 thắng / <=2 thua. Kết quả: "
          f"{len(wins)} thắng / {len(losses)} thua.")

    # 4. Chọn nhầm cột mà không lỗi: cột khác của CHÍNH hàng đó có cho gold không?
    # Đây mới là hình dạng người dùng chỉ tới. Bắt buộc có đối chứng trên câu đang
    # đúng, vì một hàng có ~4 cột số × 7 hệ số là ~28 cơ hội trúng trong sai số 1%.
    # Không neo đầu chuỗi: 978/1012 truy vấn bọc trong `round(...)`, neo thì khớp 0 câu.
    single = re.compile(r"(?P<var>df\d+)\.iloc\[(?P<idx>\d+)\]\s*\[")
    factors = (1.0, 1e-3, 1e-6, 1e-9, 1e3, 1e6, 1e9)

    def other_column_hits_gold(rec: dict, g: float) -> bool | None:
        query = (rec.get("pandas_query") or "").strip()
        if len(re.findall(r"iloc\[", query)) != 1:
            return None
        m = single.search(query)
        if not m:
            return None
        frames = frames_of(rec)
        df = frames.get(m.group("var"))
        if df is None or int(m.group("idx")) >= len(df):
            return None
        row = df.iloc[int(m.group("idx"))]
        used = {norm(s) for s in string_literals(query)}
        for col in df.columns:
            if norm(col) in used:
                continue
            # `load_frame` đã đổi cột số sang float, nên thử float thẳng trước; chỉ
            # những ô còn là chuỗi mới cần bỏ dấu phân cách nghìn kiểu Việt.
            v = as_float(row[col])
            if v is None:
                v = as_float(str(row[col]).replace(".", "").replace(",", "").replace(" ", ""))
            if v is None:
                continue
            if any(abs(v * f - g) <= max(0.01, abs(g) * 0.01) for f in factors):
                return True
        return False

    print("\n=== 4. cột khác của chính hàng đã đọc có cho gold không ===")
    for name, ids in (
        ("v9 sai ", [q for q in scorable if not correct(records[q].get("answer"), gold_of(q))]),
        ("v9 đúng", [q for q in scorable if correct(records[q].get("answer"), gold_of(q))]),
    ):
        checked = [r for q in sorted(ids, key=int)
                   if (r := other_column_hits_gold(records[q], as_float(gold_of(q)))) is not None]
        n = len(checked)
        print(f"  {name}: {sum(checked)}/{n} = {sum(checked) / n:.0%}" if n else f"  {name}: 0 câu áp được")


if __name__ == "__main__":
    main()
