"""Deterministic gold-candidate resolver for an arbitrary list of question ids.

Given a qid, this:
  1. looks the question up in data/metadata/questions_enriched.jsonl,
  2. decomposes it into (ticker, year) CELLS -- the cross product of its
     tickers x years, scored and shortlisted independently, never as one
     blob score across the whole cross product,
  3. resolves each cell's ticker/year/doc_type to report_id(s) (both scopes
     kept when doc_type is "unknown"),
  4. enumerates every table of those report_id(s) from tables_metadata_v2.jsonl
     and scores each against the question's indicator phrases,
  5. ALWAYS includes the resolved reports' balance_sheet / income_statement /
     cash_flow tables regardless of score -- phrase matching alone misses
     these for derived-ratio questions (D/E, lãi vay coverage, ...) because
     the ratio's name never appears in the raw statement, only its
     components do. Confirmed empirically: without this rule, the gold-15
     acceptance test (qid363) missed 6/7 gt_tables groups at every
     threshold; with it, 15/15 questions / 36/36 groups hit at
     thresholds 88-95.
  6. for every shortlisted candidate, loads its CSV and attempts row+period
     matching to pre-extract {matched_row_label, column, value} -- entries
     whose value is empty / nan / "-" are dropped outright, a cell with no
     value cannot be evidence,
  7. flags a scope mismatch when the question states an explicit
     separate/parent-only scope ("BCTC riêng", "ngân hàng mẹ", ...) but the
     resolved doc_type/candidates ended up all-consolidated, or vice versa
     -- per commit 9fff2ca, this is a resolver bug to surface, not a
     labelling judgement call,
  8. caps qualifying (non-empty-value) tables accepted per report_id, across
     the WHOLE question (not per cell -- a report_id already encodes its own
     ticker+year, so the only way a per-cell cap under-counts a report is a
     question whose (ticker, year) cells aren't disjoint; capping once over
     the full question closes that regardless) at --max-per-report (locked
     at 10 -- a cap sweep 3/5/10/20/999 over the 15 acceptance qids saturates
     at 10, so it is no longer a user-facing threshold decision): a report
     tripping the cap is reject-and-flag-for-manual, never a silent top-N
     truncation, because exceeding it is itself the signature of
     over-enumeration (qid473/HPG: 14 "qualifying" tables, none of them
     actually net revenue or profit after tax -- picking a top-N by score
     would still be guessing which are right),
  9. splits accepted main statements by whether row/period matching actually
     located the fact inside them: an accepted main statement with a located
     value is evidence; one with none is only a candidate the resolver could
     not verify, and goes to `unverified_tables` instead of being asserted as
     gold -- an unverified main statement getting counted as gold is exactly
     how an unrelated table can earn "recall" credit by coincidence rather
     than by actually containing the fact,
  10. groups the remaining (value-backed) accepted candidates into
     evalset-compatible OR-groups (`gt_tables`: list of lists of table_id) by
     (matched phrase, extracted value) -- tables extracting the same value
     for the same fact are alternate/interchangeable evidence for it. This is
     a mechanical proxy, not a reconstruction of evalset.json's original
     hand-labelling: real evalset.json groups (qid100, qid605, qid752)
     already combine different table_pos within one report, so grouping by
     table_pos would be wrong,
  11. uses TWO phrase lists, not one: `score_table()` (step 4) gets the full
     expand_subphrases() fragment list, because broad recall only shifts
     ranking there; `extract_row_period_matches()` (step 6) gets only
     `maximal_phrases()`'s substring-free list, because there a loose 2-word
     fragment ("ngắn hạn", "lãi vay") doesn't just shift a rank -- it becomes
     an asserted (phrase, value) fact and a gt_tables group of its own.
     Sharing one list between both was traced as the cause of a 24x gt_tables
     inflation (882 groups emitted for 36 real, on these 15 questions); with
     `maximal_phrases()` that drops to 121, at a cost of 2 more questions
     losing their (previously spurious) only group -- see docs/HANDOFF.md.
  12. before row+period matching (step 6), promotes a genuine 2nd physical
     header row that `load_table_csv`'s `header=0` read left sitting in the
     first data row (`merge_second_header_row()`) -- confirmed corpus-wide
     (1061 of data/tables/*/*.csv match this shape), not just the
     FTS_financial_statements_2018/table_22.csv case (qid818) it was found
     from. Placement is structural (label-column-relative, or umbrella-token-
     relative when row 0 itself carries a period word), not a scored shift
     search -- a scored search was tried and rejected because adjacent
     monetary columns make several shifts score equally, and the tie-break
     would confidently place a period label on the wrong column.
  13. `col_content_stats()`'s `frac_numeric` excludes `SHORTCODE_RE` hits: a
     bare note-reference code ("33", roman numerals) matches the numeric
     regex just as well as a real monetary figure, so without the exclusion
     a note-code column always measures as "numeric" and never satisfies
     `assign_period_headers()`'s `looks_codey` check (bug #3, found on
     VIB_financial_statements_2020_consolidated|10 / qid40's "Thuyết minh"
     column). This alone is necessary but not always sufficient: the
     immediate-next-column's own header can itself carry an unrelated year
     mention (`header_has_period` firing on a stray "\\b(19|20)\\d{2}\\b"
     match rather than the asked anchor) and block the shift regardless --
     observed to depend on OCR whitespace ("2019 Triệu VND" blocks the
     shift, "2019Triệu VND" from the same bank's separate-scope report does
     not, purely because `\\b` needs a non-word char after the digits). Left
     unfixed: a same-shape chain-of-misplaced-headers case is a distinct,
     deeper defect in `assign_period_headers`'s single-hop design, not part
     of bug #3 as scoped, and risks a wrong-value shift if patched hastily.

No RAG pipeline involved anywhere in this file (no modules/rag/*, no BM25 /
dense / RRF / LLM judge) -- report/table resolution and row/period matching
are done directly against tables_metadata_v2.jsonl and data/tables/*.csv, so
the candidates this produces are usable as an independent check on that
pipeline rather than a restatement of it.

Read-only against data/metadata/tables_metadata_v2.jsonl and data/tables/*.csv.
Never reads or writes data/eval/evalset.json or scripts/build_evalset.py.

Output shape per question record: `gt_tables` (evalset-compatible OR-groups,
built only from accepted candidates with a located row/period value),
`accepted_table_ids` (flat union of those same value-backed candidates, for
volume/precision reporting), `unverified_tables` (accepted main statements
with no located value -- candidates, not gold, kept for a human to eyeball
rather than silently dropped), `flagged_for_manual` (reports over the
per-report cap, with reasons, excluded from `gt_tables`/`accepted_table_ids`),
and `cell_detail` (the full per-cell candidate list incl. main statements,
scores, and every row/period match, for manual review).

See scripts/gold_acceptance_test.py for recall AND accepted-table-volume
against the 15 known-gold qids -- do not treat a threshold as chosen from
recall alone (a run can hit every gt group while also accepting hundreds of
false-positive tables; recall-only scoring can't see that).

Usage:
  python scripts/build_gold_candidates.py --qids 1,17,40 --out /tmp/x.jsonl
  python scripts/build_gold_candidates.py --qids-file data/eval/gold100_manifest.json \
      --out data/eval/gold_candidates_raw.jsonl --max-per-report 3
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz

ROOT = Path(__file__).resolve().parent.parent
QUESTIONS_PATH = ROOT / "data/metadata/questions_enriched.jsonl"
META_PATH = ROOT / "data/metadata/tables_metadata_v2.jsonl"
TABLES_DIR = ROOT / "data/tables"

MAIN_STATEMENTS = {"balance_sheet", "income_statement", "cash_flow"}
DEFAULT_THRESHOLD = 95
DEFAULT_MAX_CANDIDATES = 15
# Locked at 10, not tuned further: a cap sweep (3/5/10/20/999) over the 15
# acceptance qids showed macro F2 rising 21.8% -> 24.1% up to cap=10, then
# 10/20/999 are byte-identical (635 accepted, 31/36 groups either way) -- the
# knob is already at its stop past 10, so raising it further is not a real
# lever and isn't a user-facing decision. Still a CLI flag (--max-per-report)
# for diagnostics, but the default shouldn't move again without a new sweep.
DEFAULT_MAX_PER_REPORT = 10

# Main statements (BS/IS/CF) are included "regardless of score" because a
# derived-ratio question (qid363: D/E, interest coverage) never states the
# underlying row label in its own text, so phrase-based row matching can't be
# the gate for them. That rule needs its own cap, not max_per_report's: most
# reports carry 4-16 main-statement tables (BS split across pages, IS, CF,
# equity-changes...) -- reusing max_per_report=3 would flag nearly every
# normal report. This catches only the genuine tail (DLG/DTK/HHS/OCB/SSI/VAB:
# 24-76 main-statement tables in one report, clearly a tagging outlier).
# Not final either -- same "build the knob" reasoning as max_per_report.
DEFAULT_MAX_MAIN_PER_REPORT = 20

# ---------------------------------------------------------------------------
# phrase extraction (from step2c_resolve_v2.py, validated against the gold-15
# acceptance test and against all 100 sampled questions in the earlier
# phrase-extraction pass -- zero total-loss cases)
# ---------------------------------------------------------------------------

PHRASE_STOPWORDS = [
    "công ty mẹ", "công ty cổ phần", "trách nhiệm hữu hạn",
    "tổng công ty", "tập đoàn", "ngân hàng thương mại cổ phần",
    "đầu năm", "cuối năm", "đầu kỳ", "cuối kỳ", "trong năm",
    "là bao nhiêu", "bao nhiêu phần trăm", "bao nhiêu triệu đồng",
    "bao nhiêu tỷ đồng", "bao nhiêu nghìn tỷ đồng",
    "báo cáo tài chính", "hợp nhất", "riêng lẻ", "mã cổ phiếu",
    "phần trăm",
]

STOPWORDS = set("""
là bao nhiêu đồng lần ngày tháng năm của các
tnhh cty ctcp trong vào đến từ và với so
sánh giữa theo tại ở trên dưới này đó khi mà có không được thì như thế nào
mức xét
""".split())

YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
DATE_RE = re.compile(r"\b\d{1,2}/\d{1,2}(/\d{2,4})?\b")
UNIT_PHRASE_RE = re.compile(
    r"(nghìn tỷ đồng|tỷ đồng|triệu đồng|nghìn đồng|phần trăm)", re.IGNORECASE
)
PUNCT_RE = re.compile(r"[()\"?,.:%;]")


def _strip_corporate_prefixes(s: str) -> str:
    for phrase in PHRASE_STOPWORDS:
        s = re.sub(phrase, " ", s, flags=re.IGNORECASE)
    tokens = [w for w in s.split() if w.lower() not in ("ctcp", "tnhh", "cty")]
    return " ".join(tokens).strip()


def extract_phrases(q_text: str, tickers: list[str], company_names: list[str]) -> list[str]:
    text = q_text
    for t in tickers:
        text = re.sub(rf"\b{re.escape(t)}\b", " | ", text)
    text = _strip_corporate_prefixes(text)
    for name in company_names:
        if name:
            core = _strip_corporate_prefixes(name)
            if core:
                text = re.sub(re.escape(core), " | ", text, flags=re.IGNORECASE)
    text = UNIT_PHRASE_RE.sub(" | ", text)
    text = DATE_RE.sub(" | ", text)
    text = YEAR_RE.sub(" | ", text)
    text = PUNCT_RE.sub(" | ", text)
    tokens = text.split()

    phrases = []
    cur: list[str] = []
    for tok in tokens:
        if tok == "|" or tok.lower() in STOPWORDS:
            if len(cur) >= 1:
                phrases.append(" ".join(cur))
            cur = []
        else:
            cur.append(tok)
    if cur:
        phrases.append(" ".join(cur))

    return [p for p in phrases if " " in p or len(p) >= 5]


def maximal_phrases(phrases: list[str]) -> list[str]:
    """Drop any phrase that is a literal substring of another phrase in the
    same list. score_table() wants expand_subphrases()'s full fragment list
    (broad recall only shifts ranking), but extract_row_period_matches() must
    not see it: a bare 2-word fragment like "ngắn hạn" or "lãi vay" matches
    dozens of unrelated row labels and each becomes its own asserted
    (matched_phrase, value) fact -- gt_tables group inflation traced to this
    exact cause (qid605: 1 real group, 77 emitted; qid363: 7 real, 83
    emitted -- see docs/HANDOFF.md). Applied to the pre-expansion phrase list,
    not the expanded one, so extraction only ever tests the question's own
    (multi-word) indicators."""
    out = []
    for i, p in enumerate(phrases):
        pl = p.lower()
        if any(i != j and pl in q.lower() for j, q in enumerate(phrases)):
            continue
        out.append(p)
    return out


def expand_subphrases(phrases: list[str]) -> list[str]:
    """Decompose phrases >3 words into all contiguous 2+-word sub-phrases, so
    an indicator phrase wrapped in calc-instruction or argmax scaffolding
    ("Tinh gia tri trung binh Trai phieu Chinh phu") still scores on its own
    regardless of where the scaffolding sits. Single-word substrings are
    excluded as too generic."""
    out = list(phrases)
    seen = set(out)
    for p in phrases:
        toks = p.split()
        n = len(toks)
        if n <= 3:
            continue
        for i in range(n):
            for j in range(i + 2, n + 1):
                if j - i >= n:
                    continue
                sub = " ".join(toks[i:j])
                if sub not in seen:
                    seen.add(sub)
                    out.append(sub)
    return out


# ---------------------------------------------------------------------------
# report resolution
# ---------------------------------------------------------------------------

def build_report_index(meta_path: Path):
    """(ticker, year) -> [(doc_type, report_id), ...]; report_id -> [table meta, ...]
    sorted by table_pos; ticker -> company_name."""
    ticker_year_reports = defaultdict(list)
    report_tables = defaultdict(list)
    ticker_company: dict[str, str] = {}
    with meta_path.open(encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            key = (d["ticker"], d["year"])
            entry = (d["doc_type"], d["report_id"])
            lst = ticker_year_reports[key]
            if entry not in lst:
                lst.append(entry)
            report_tables[d["report_id"]].append(d)
            ticker_company.setdefault(d["ticker"], d.get("company_name", ""))
    for rid in report_tables:
        report_tables[rid].sort(key=lambda d: d["table_pos"])
    return ticker_year_reports, report_tables, ticker_company


def resolve_reports(ticker: str, year: int, doc_type: str, ticker_year_reports) -> tuple[list[str], str]:
    """ticker+year+doc_type -> report_id(s). Both scopes are kept whenever
    doc_type isn't explicitly "separate"/"consolidated" -- an ambiguous scope
    must not silently drop half the candidate pool."""
    options = ticker_year_reports.get((ticker, year), [])
    if not options:
        return [], "no_report_for_ticker_year"
    if doc_type in ("separate", "consolidated"):
        exact = [rid for dt, rid in options if dt == doc_type]
        if exact:
            return exact, "exact_scope_match"
        return [rid for _, rid in options], "scope_fallback_all"
    return [rid for _, rid in options], "ambiguous_scope_all"


def blob_for_table(t: dict) -> str:
    parts = [
        t.get("header_flat", ""),
        " ".join(t.get("first_col_labels", []) or []),
        t.get("note_title", ""),
        t.get("section_title", ""),
        t.get("statement_subtype", ""),
        t.get("mau_tag", ""),
    ]
    return " ".join(p for p in parts if p)


def score_table(phrases: list[str], blob: str):
    """Per-phrase max(partial_ratio, token_set_ratio); a table's score is its
    best-matching phrase. token_set_ratio recovers Vietnamese word-order
    variants (question: "phải thu khác ngắn hạn", row label: "phải thu ngắn
    hạn khác") that partial_ratio alone misses.

    Also returns `specificity`: the word count of the longest phrase that
    actually matched (fz >= 90 or literal substring hit). expand_subphrases()
    means most real indicators also match on 1-2-word fragments of
    themselves ("cổ phần" out of "Tổng số lượng cổ phần"), and those short
    fragments coincidentally hit hundreds of unrelated tables -- ranking by
    best_fuzzy/n_sub_hits alone lets that noise crowd out the true match
    under a small per-cell cap. Ranking by specificity first fixes it: a
    table matching the full 5-word indicator outranks one matching only a
    generic 1-word fragment of it, regardless of how many short fragments
    the latter racks up.
    """
    blob_l = blob.lower()
    best_fuzzy, n_sub_hits, specificity = 0, 0, 0
    for p in phrases:
        pl = p.lower()
        sub_hit = pl in blob_l
        if sub_hit:
            n_sub_hits += 1
        fz = max(fuzz.partial_ratio(pl, blob_l), fuzz.token_set_ratio(pl, blob_l))
        best_fuzzy = max(best_fuzzy, fz)
        if sub_hit or fz >= 90:
            specificity = max(specificity, len(p.split()))
    return best_fuzzy, n_sub_hits, specificity


# ---------------------------------------------------------------------------
# scope-mismatch assertion (regex ported from
# src/finance_qa/agents/finance/understand.py's _SEPARATE_SCOPE, which is the
# authoritative fix for commit 9fff2ca -- 6 questions stating "BCTC riêng" /
# "ngân hàng mẹ" outright were retrieved as 100% consolidated because the
# understand LLM defaulted doc_type to "unknown" -> "consolidated". Duplicated
# rather than imported so this script stays free of any RAG-pipeline/LLM
# dependency.)
# ---------------------------------------------------------------------------

SEPARATE_SCOPE_RE = re.compile(
    r"(?:công ty|ngân hàng|tổng công ty)\s+mẹ"
    r"|(?:bctc|báo cáo tài chính|báo cáo)\s+riêng"
    r"|riêng lẻ",
    re.IGNORECASE,
)
CONSOLIDATED_SCOPE_RE = re.compile(r"hợp nhất", re.IGNORECASE)


def states_separate_scope(question: str) -> bool:
    return bool(SEPARATE_SCOPE_RE.search(question) and not CONSOLIDATED_SCOPE_RE.search(question))


def scope_warning(question: str, doc_type: str, candidate_scopes: set[str]) -> str | None:
    """None if consistent; otherwise a short description of the mismatch."""
    stated_separate = states_separate_scope(question)
    if stated_separate and doc_type != "separate":
        return "question states separate/parent scope but resolved doc_type != 'separate'"
    if stated_separate and candidate_scopes and candidate_scopes == {"consolidated"}:
        return "question states separate/parent scope but all shortlisted candidates are consolidated"
    return None


# ---------------------------------------------------------------------------
# row + period value extraction (from step4_verify_v2.py, validated while
# triaging the earlier hand-labelling pass's zero-accept questions)
# ---------------------------------------------------------------------------

ROW_MATCH_THRESHOLD = 90
LABEL_COL_SEARCH_WIDTH = 3

NUMERIC_RE = re.compile(r"^[\d.,()\-\s]+$")
SHORTCODE_RE = re.compile(r"^[IVXLCivxlc\d]{1,3}$|^[A-Za-z]{1,2}$")
BEGIN_RE = re.compile(r"đầu\s*(năm|kỳ)", re.IGNORECASE)
END_RE = re.compile(r"cuối\s*(năm|kỳ)", re.IGNORECASE)
REPORT_YEAR_RE = re.compile(r"_(\d{4})_")
DATE_ANCHOR_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")

# Closed vocabulary of note-table column headers that only ever appear as a
# WHOLE cell value, never inside a free-text row label -- used to recognize a
# second physical header row that load_table_csv's header=0 read left sitting
# in the first data row (bug #4, see merge_second_header_row()). Confirmed
# corpus-wide: 1061 of ~/data/tables/*/*.csv match this shape, not just
# FTS_financial_statements_2018/table_22.csv.
HEADER_CONTINUATION_RE = re.compile(
    r"^(tham chiếu|số đầu kỳ|số đầu năm|số cuối kỳ|số cuối năm|số dư đầu kỳ|"
    r"số dư cuối kỳ|số trích lập trong kỳ|số hoàn nhập trong kỳ|"
    r"số phát sinh trong kỳ|mã số|thuyết minh|chỉ tiêu)$",
    re.IGNORECASE,
)


def _is_empty_value(v) -> bool:
    """True for a cell value that carries no evidence: NaN, blank, or a bare
    dash/placeholder -- the exact failure mode in qid473's HPG candidates
    (several of the 14 accepted tables had value `nan` or `-`)."""
    if v is None:
        return True
    try:
        if pd.isna(v):
            return True
    except (TypeError, ValueError):
        pass
    return str(v).strip().lower() in ("", "-", "--", "nan", "none")


def load_table_csv(report_id: str, table_pos: int):
    path = TABLES_DIR / report_id / f"table_{table_pos}.csv"
    try:
        return pd.read_csv(path, dtype=str, header=0), None
    except Exception as e:  # noqa: BLE001 - a bad/missing CSV is data, not a crash
        return None, str(e)


def _is_header_continuation_row(row) -> bool:
    vals = [re.sub(r"\s+", " ", str(v).strip()) for v in row.tolist()
            if isinstance(v, str) and v.strip()]
    return len(vals) >= 2 and all(HEADER_CONTINUATION_RE.match(v) for v in vals)


def merge_second_header_row(df: pd.DataFrame, label_col: int) -> pd.DataFrame:
    """Promote a genuine second physical header row into df.columns when
    load_table_csv's header=0 read left it sitting in the first data row --
    bug #4 (FTS_financial_statements_2018/table_22.csv, qid818's whole 0/5),
    confirmed corpus-wide rather than a one-off: 1061 tables have a first
    data row that is entirely closed-vocabulary header words (see
    HEADER_CONTINUATION_RE).

    Placement is structural, not a scored/ambiguous search -- a shift search
    that scores "does this column look monetary" was tried and rejected:
    a table's monetary columns usually sit right next to each other, so
    several different shifts score equally and the tie-break silently picks
    a plausible-looking but WRONG column (e.g. reporting an "đầu kỳ"
    beginning balance as if it were "cuối kỳ" ending balance) -- a worse
    outcome than reporting no match at all. Two structural cases instead:

    - Row 0 carries no period-anchor token of its own (VIC/BAF/SSI/MWG-style:
      row 0 is just a title/unit row, e.g. "Đơn vị tính: triệu VND") -> row
      1's tokens are the only real header this table has; they start right
      after the content-detected label column (a label column carries no
      header of its own, by convention in this corpus).
    - Row 0 DOES carry period-anchor token(s) (FTS-style: row 0 already says
      "Số cuối năm" / "Số đầu năm", but that's a truncated single-row read of
      what is really a 2-row nested header) -> the second-to-last such token
      is the umbrella row 1's finer labels supersede (row 1's block starts at
      its column); the LAST such token is a genuinely separate trailing
      column and gets relocated to sit right after row 1's block. Verified
      against FTS table_22.csv by reconciling the resulting columns
      arithmetically: "đầu kỳ" + "trích lập trong kỳ" - "hoàn nhập trong kỳ"
      == "cuối kỳ" for every row.

    Tables with a 3rd nested header row (rarer) are not handled -- the first
    (only) merge still fires, the leftover row is inert leftover text, not a
    source of wrong values, so this is a no-worse-than-before residual case.
    """
    if df.shape[0] == 0 or not _is_header_continuation_row(df.iloc[0]):
        return df
    ncols = df.shape[1]
    row0_headers = [str(c) for c in df.columns]
    row1_tokens = [(i, re.sub(r"\s+", " ", str(v).strip()))
                   for i, v in enumerate(df.iloc[0].tolist())
                   if isinstance(v, str) and v.strip()]

    period_idxs = [i for i, h in enumerate(row0_headers) if BEGIN_RE.search(h) or END_RE.search(h)]
    new_headers = list(row0_headers)
    if len(period_idxs) >= 2:
        block_start = period_idxs[-2]
        trailing_idx = period_idxs[-1]
        new_headers[trailing_idx] = ""
        target = block_start + len(row1_tokens)
        if target < ncols:
            new_headers[target] = row0_headers[trailing_idx]
    elif len(period_idxs) == 1:
        block_start = period_idxs[0]
    else:
        block_start = label_col + 1

    for offset, (_, text) in enumerate(row1_tokens):
        j = block_start + offset
        if j < ncols:
            new_headers[j] = text

    out = df.iloc[1:].reset_index(drop=True).copy()
    out.columns = new_headers
    return out


def period_anchors(question_text: str, years: list[int]) -> set[str]:
    anchors: set[str] = set()
    for m in DATE_ANCHOR_RE.finditer(question_text):
        d, mo, y = m.groups()
        d, mo = d.zfill(2), mo.zfill(2)
        if y:
            y_full = y if len(y) == 4 else "20" + y
            anchors.add(f"{int(d)}/{int(mo)}/{y_full}")
            anchors.add(f"{d}/{mo}/{y_full}")
        else:
            for y_full in years:
                anchors.add(f"{int(d)}/{int(mo)}/{y_full}")
                anchors.add(f"{d}/{mo}/{y_full}")
    for y in years:
        anchors.add(f"31/12/{y}")
        anchors.add(f"01/01/{y}")
        anchors.add(f"1/1/{y}")
        anchors.add(str(y))
    if BEGIN_RE.search(question_text):
        anchors.add("đầu năm")
        anchors.add("đầu kỳ")
    if END_RE.search(question_text):
        anchors.add("cuối năm")
        anchors.add("cuối kỳ")
    return anchors


def header_has_period(header_text, anchors: set[str]) -> bool:
    h = str(header_text).lower().replace(" ", "")
    return any(a.lower().replace(" ", "") in h for a in anchors) or bool(YEAR_RE.search(str(header_text)))


def col_content_stats(df: pd.DataFrame, col_idx: int, n: int = 25) -> dict:
    vals = [v for v in df.iloc[:n, col_idx].tolist() if isinstance(v, str) and v.strip()]
    if not vals:
        return {"n": 0, "frac_numeric": 0.0, "frac_shortcode": 0.0, "frac_longtext": 0.0}
    # A bare note-reference code ("33", "24", roman numerals) matches NUMERIC_RE
    # just as well as a real monetary figure does, so exclude SHORTCODE_RE hits
    # from frac_numeric -- otherwise a note-code column always measures as
    # "numeric", masking it from the looks_codey check in assign_period_headers
    # (bug #3: VIB_financial_statements_2020_consolidated|10's "Thuyết minh"
    # column never triggered the header-shift fix because of this).
    n_num = sum(
        1 for v in vals
        if NUMERIC_RE.match(v.strip()) and any(c.isdigit() for c in v) and not SHORTCODE_RE.match(v.strip())
    )
    n_short = sum(1 for v in vals if SHORTCODE_RE.match(v.strip()))
    n_long = sum(1 for v in vals if len(v.strip()) >= 6 and sum(c.isalpha() for c in v) >= 3)
    n = len(vals)
    return {"n": n, "frac_numeric": n_num / n, "frac_shortcode": n_short / n, "frac_longtext": n_long / n}


def find_label_col(df: pd.DataFrame) -> int:
    """The column (among the first few) whose actual CONTENT looks most like
    row labels -- handles both plain (label is col 0) and leading-code-column
    (e.g. NLG: ['Mã số','TÀI SẢN','Thuyết minh',...] -- label is col 1)."""
    best_idx, best_score = 0, -1.0
    for i in range(min(LABEL_COL_SEARCH_WIDTH, df.shape[1])):
        stats = col_content_stats(df, i)
        if stats["n"] == 0:
            continue
        if stats["frac_longtext"] > best_score:
            best_score, best_idx = stats["frac_longtext"], i
    return best_idx


def assign_period_headers(df: pd.DataFrame, anchors: set[str]) -> list[str]:
    """Reassign a period header to the next column when the header column's
    own content is code-like (not monetary) and the next column's content is
    monetary and lacks its own period header -- the corpus-wide header/data
    column-shift bug confirmed in ACB/HDB/NAB bank statements."""
    ncols = df.shape[1]
    raw_headers = [str(c) for c in df.columns]
    effective = list(raw_headers)
    stats = [col_content_stats(df, i) for i in range(ncols)]
    for i in range(ncols - 1):
        if not header_has_period(raw_headers[i], anchors) or stats[i]["n"] == 0:
            continue
        looks_codey = stats[i]["frac_shortcode"] >= 0.4 and stats[i]["frac_numeric"] < 0.3
        if not looks_codey:
            continue
        nxt_has_own_period = header_has_period(raw_headers[i + 1], anchors)
        nxt_is_monetary = stats[i + 1]["n"] > 0 and stats[i + 1]["frac_numeric"] >= 0.4
        if nxt_is_monetary and not nxt_has_own_period:
            effective[i + 1] = raw_headers[i]
            effective[i] = ""
    return effective


def relative_year_anchors(report_id: str, years: list[int]) -> set[str]:
    """Map an asked year onto this report's own relative-period column labels.

    Two synonym pairs occur in the corpus for the exact same relationship
    (report's own year vs. its prior-year comparative): "năm nay"/"năm trước"
    and "Số cuối năm"/"Số đầu năm" -- the latter is the standard balance-sheet
    header (KBC, HDB, ABB, FTS, ...) and carries no literal year digit at all,
    so without this a balance-type row/period match is only found when the
    question text itself happens to say "đầu"/"cuối" (most lookup questions
    don't -- a balance is a cuối-năm figure by convention, not by wording).
    """
    m = REPORT_YEAR_RE.search(report_id)
    if not m:
        return set()
    report_year = int(m.group(1))
    extra = set()
    for y in years:
        if y == report_year:
            extra.add("năm nay")
            extra.add("cuối năm")
        elif y == report_year - 1:
            extra.add("năm trước")
            extra.add("đầu năm")
    return extra


def find_row_matches(df: pd.DataFrame, phrases: list[str], label_col: int):
    out = []
    for idx, raw_label in df.iloc[:, label_col].items():
        if not isinstance(raw_label, str) or not raw_label.strip():
            continue
        label_l = raw_label.lower()
        best_score, best_phrase = 0, None
        for p in phrases:
            s = fuzz.token_set_ratio(p.lower(), label_l)
            if s > best_score:
                best_score, best_phrase = s, p
        if best_score >= ROW_MATCH_THRESHOLD:
            out.append((idx, raw_label, best_score, best_phrase))
    return out


def find_period_cols(effective_headers: list[str], anchors: set[str], label_col: int) -> list[int]:
    hits = []
    for i, h in enumerate(effective_headers):
        if i == label_col:
            continue
        hl = str(h).lower().replace(" ", "")
        if any(a.lower().replace(" ", "") in hl for a in anchors):
            hits.append(i)
    return hits


def extract_row_period_matches(report_id: str, table_pos: int, phrases: list[str],
                                question_text: str, years: list[int]) -> list[dict]:
    """{row_label, column, value} tuples where a row matches an indicator
    phrase AND a column matches an asked period. Returns [] (not an error)
    when the table loads fine but nothing matches -- that's a normal outcome
    for an always-included main statement whose rows don't happen to answer
    this particular question."""
    df, err = load_table_csv(report_id, table_pos)
    if df is None or df.shape[1] < 2 or df.shape[0] == 0:
        return []
    anchors = period_anchors(question_text, years) | relative_year_anchors(report_id, years)
    label_col = find_label_col(df)
    df = merge_second_header_row(df, label_col)  # bug #4: promote a misread 2nd header row
    row_matches = find_row_matches(df, phrases, label_col)
    if not row_matches:
        return []
    effective_headers = assign_period_headers(df, anchors)
    col_idxs = find_period_cols(effective_headers, anchors, label_col)
    if not col_idxs:
        return []
    out = []
    for idx, row_label, score, phrase in row_matches:
        for ci in col_idxs:
            value = df.iat[idx, ci]
            if _is_empty_value(value):
                continue  # a cell with no value cannot be evidence
            out.append({
                "matched_row_label": row_label,
                "column": effective_headers[ci],
                "value": value,
                "row_score": score,
                "matched_phrase": phrase,
            })
    return out


def _cap_by_report(rows: list[dict], cap: int, reason_tpl: str) -> tuple[list[dict], list[dict]]:
    """Reject-and-flag-for-manual (not silent top-N truncation) whenever a
    single report exceeds `cap` -- a report tripping this is itself the
    signature of over-enumeration (qid473/HPG: 14 "qualifying" tables, none
    of them actually net revenue or profit after tax). Picking a top-N by
    score would still be guessing which ones are right.

    Module-level (not nested in build_cell_candidates) and called once per
    whole question, not once per cell -- a report_id already encodes its own
    ticker+year, so grouping by report_id across every cell the question
    touches is the correct scope for "how many tables did this ONE report
    contribute", not a per-cell slice of it."""
    by_report = defaultdict(list)
    for r in rows:
        by_report[r["report_id"]].append(r)
    kept, flagged = [], []
    for rid, group in by_report.items():
        if len(group) > cap:
            flagged.append({
                "report_id": rid,
                "reason": reason_tpl.format(cap=cap),
                "n_qualifying": len(group),
                "table_ids": [r["table_id"] for r in group],
            })
        else:
            kept.extend(group)
    return kept, flagged


def _report_ticker_year(report_id: str) -> tuple[str, int | None]:
    """report_id -> (ticker, year), parsed rather than threaded through as
    call-site state -- report_id already carries both, and the cap is now
    applied at the whole-question level where no single owning cell exists."""
    m = REPORT_YEAR_RE.search(report_id)
    return report_id.split("_", 1)[0], (int(m.group(1)) if m else None)


def _value_key(v) -> str:
    """Normalize a matched value for OR-group equivalence: two tables that
    extracted the *same number* for the *same period* are alternate
    locations of one fact (evalset.json does this itself -- e.g. qid100's
    single group spans three different table_pos in one report, qid605's
    spans two -- so grouping by literal table_pos is not the right rule;
    grouping by "same extracted value" is the mechanical proxy for "these
    tables are interchangeable evidence for this fact")."""
    s = str(v).strip()
    neg = s.startswith("(") and s.endswith(")")
    digits = re.sub(r"[^\d]", "", s)
    if digits:
        return ("-" if neg or s.startswith("-") else "") + digits.lstrip("0").rjust(1, "0")
    return s.lower()


# ---------------------------------------------------------------------------
# per-cell candidate shortlist
# ---------------------------------------------------------------------------

def build_cell_candidates(ticker: str, year: int, doc_type: str, question_text: str,
                           phrases: list[str], extraction_phrases: list[str],
                           ticker_year_reports, report_tables,
                           threshold: int, max_candidates: int) -> dict:
    """Shortlist + row/period extraction for one (ticker, year) cell -- NOT
    capped here. The per-report-per-question cap has to see every cell's
    candidates at once to guarantee "no report contributes more than N
    tables to this question" (see _cap_by_report's docstring), so capping is
    done once by the caller (build_candidates_for_question) over the union
    of all cells, not independently per cell.

    `phrases` (expand_subphrases' full fragment list) drives score_table();
    `extraction_phrases` (maximal_phrases' substring-free list) drives
    extract_row_period_matches() -- see maximal_phrases' docstring for why
    these must not be the same list."""
    report_ids, resolve_note = resolve_reports(ticker, year, doc_type, ticker_year_reports)
    if not report_ids:
        return {
            "ticker": ticker, "year": year, "report_ids": [], "resolve_note": resolve_note,
            "n_tables_total": 0, "candidates": [],
            "scored_qualifying": [], "main_candidates": [],
        }

    all_tables = []
    for rid in report_ids:
        all_tables.extend(report_tables.get(rid, []))

    scored = []
    main_stmt = []
    for t in all_tables:
        blob = blob_for_table(t)
        best_fuzzy, n_sub_hits, specificity = score_table(phrases, blob)
        row = {
            "table_id": f"{t['report_id']}|{t['table_pos']}",
            "report_id": t["report_id"],
            "table_pos": t["table_pos"],
            "doc_type": t.get("doc_type", ""),
            "statement_type": t.get("statement_type", ""),
            "note_title": t.get("note_title", ""),
            "section_title": t.get("section_title", ""),
            "best_fuzzy": best_fuzzy,
            "n_sub_hits": n_sub_hits,
            "specificity": specificity,
        }
        if t.get("statement_type") in MAIN_STATEMENTS:
            row["included_reason"] = "main_statement"
            main_stmt.append(row)
        elif best_fuzzy >= threshold or n_sub_hits >= 1:
            row["included_reason"] = "scored"
            scored.append(row)

    # Rank by specificity first (see score_table docstring): a table matching
    # the full multi-word indicator phrase outranks one matching only a
    # generic 1-2-word fragment of it, so the small per-cell cap below drops
    # noise before it drops a genuine match.
    scored.sort(key=lambda r: (-r["specificity"], -r["n_sub_hits"], -r["best_fuzzy"]))
    # max_candidates caps the *scored* bucket only -- main statements are
    # additive on top of it, never competing with scored candidates for the
    # same slots. Some reports (e.g. multi-page insurance BS/IS/CF) already
    # have more than max_candidates main-statement tables on their own; capping
    # the combined total would silently starve the scored bucket to zero and
    # drop the actual gold table, which is exactly what "regardless of score"
    # rules out.
    #
    # DEFAULT_MAX_CANDIDATES=15, not 12: bank loan/deposit notes are routinely
    # split into many genuinely-matching near-duplicate sub-tables (by sector,
    # by loan group, by counterparty type -- not noise, real siblings of the
    # same indicator). qid754/ABB's gold table ranked #13 behind 12 other
    # equally-specific sibling notes at threshold=95/cap=12, a real miss; 15
    # recovers it without reopening the ranking-dilution problem the
    # specificity sort fixed (these siblings tie on specificity, they aren't
    # short generic fragments crowding out a long one).
    shortlist = main_stmt + scored[:max_candidates]

    for row in shortlist:
        matches = extract_row_period_matches(
            row["report_id"], row["table_pos"], extraction_phrases, question_text, [year]
        )
        row["row_period_matches"] = matches

    # A *scored* candidate only counts as evidence once it has at least one
    # non-empty row+period match (requirement a already dropped the empty
    # ones inside extract_row_period_matches -- this is where "qualifying" is
    # decided). Main statements are a different case: they're included
    # "regardless of score" precisely for derived-ratio questions (qid363:
    # D/E, interest coverage) whose own text never states the underlying row
    # label, so phrase-based row matching can't be the gate for them -- an
    # unmatched main statement is still accepted, just capped separately
    # (max_main_per_report) instead of gated on row_period_matches.
    #
    # Not capped here -- see build_candidates_for_question, which caps once
    # over every cell's union so one report_id can't spread its tables
    # across a per-cell cap by appearing in more than one cell.
    scored_qualifying = [
        r for r in shortlist if r["included_reason"] == "scored" and r["row_period_matches"]
    ]
    main_candidates = [r for r in shortlist if r["included_reason"] == "main_statement"]

    return {
        "ticker": ticker, "year": year, "report_ids": report_ids,
        "resolve_note": resolve_note, "n_tables_total": len(all_tables),
        "candidates": shortlist,
        "scored_qualifying": scored_qualifying,
        "main_candidates": main_candidates,
    }


def build_candidates_for_question(q: dict, ticker_year_reports, report_tables, ticker_company,
                                   threshold: int = DEFAULT_THRESHOLD,
                                   max_candidates: int = DEFAULT_MAX_CANDIDATES,
                                   max_per_report: int = DEFAULT_MAX_PER_REPORT,
                                   max_main_per_report: int = DEFAULT_MAX_MAIN_PER_REPORT) -> dict:
    tickers = q.get("tickers") or ([q["ticker"]] if q.get("ticker") else [])
    years = q.get("years") or []
    doc_type = q.get("doc_type", "unknown")
    company_names = [ticker_company.get(t, "") for t in tickers]
    base_phrases = extract_phrases(q["question"], tickers, company_names)
    # score_table() gets the full fragment expansion (broad recall only shifts
    # ranking); extract_row_period_matches() gets only the maximal (non-
    # substring) phrases -- see maximal_phrases' docstring. Sharing one list
    # between both was the root cause of gt_tables group inflation (a bare
    # 2-word fragment becomes its own asserted fact for every row it happens
    # to fuzzy-match).
    phrases = expand_subphrases(base_phrases)
    extraction_phrases = maximal_phrases(base_phrases)

    cells = []
    for t in tickers:
        for y in years:
            cells.append(build_cell_candidates(
                t, y, doc_type, q["question"], phrases, extraction_phrases,
                ticker_year_reports, report_tables, threshold, max_candidates,
            ))

    all_report_ids = sorted({rid for c in cells for rid in c["report_ids"]})
    candidate_scopes = {
        cand["doc_type"] for c in cells for cand in c["candidates"] if cand.get("doc_type")
    }
    warning = scope_warning(q["question"], doc_type, candidate_scopes)

    # Cap once over the UNION of every cell's candidates, not per cell: a
    # report_id already encodes its own (ticker, year), so this is the scope
    # that actually answers "how many tables did this one report contribute
    # to this question" -- capping inside each cell independently would only
    # be equivalent if cells were guaranteed disjoint by report_id, which
    # isn't a property build_cell_candidates enforces.
    all_scored_qualifying = [r for c in cells for r in c["scored_qualifying"]]
    all_main_candidates = [r for c in cells for r in c["main_candidates"]]
    accepted_scored, flagged_scored = _cap_by_report(
        all_scored_qualifying, max_per_report, ">{cap} qualifying tables from one report"
    )
    accepted_main, flagged_main = _cap_by_report(
        all_main_candidates, max_main_per_report, ">{cap} main-statement tables from one report"
    )
    flagged_for_manual = [
        dict(f, ticker=_report_ticker_year(f["report_id"])[0], year=_report_ticker_year(f["report_id"])[1])
        for f in flagged_scored + flagged_main
    ]

    # A main statement is included "regardless of score" (see build_cell_candidates)
    # because derived-ratio questions never state the underlying row label in
    # their own text -- but "included as a candidate" and "asserted as gold"
    # are different claims. If the resolver never located the fact inside the
    # table (row_period_matches empty), it has no basis to assert the table
    # IS the evidence -- that used to become a gt_tables singleton anyway,
    # which is exactly how an unrelated main statement could earn "recall"
    # credit by coincidence (team-lead: qid40's VIB hit was luck, not signal).
    # scored_qualifying is already gated on non-empty matches by construction
    # (build_cell_candidates), so only main_candidates needs this split.
    verified_main = [r for r in accepted_main if r["row_period_matches"]]
    unverified_main = [r for r in accepted_main if not r["row_period_matches"]]
    accepted = accepted_scored + verified_main
    unverified_tables = sorted({r["table_id"] for r in unverified_main})

    # OR-group construction for the evalset-compatible gt_tables field: group
    # accepted candidates by (matched phrase, extracted value) -- tables that
    # extracted the same value for the same fact are alternate/interchangeable
    # evidence for it (see _value_key docstring for why this, not table_pos,
    # matches how evalset.json's own groups are actually shaped). Every
    # remaining member of `accepted` has at least one row_period_match (the
    # split above moved everything else into unverified_tables), so there is
    # no singleton case left -- a table with no located value is not gold,
    # full stop; it goes in unverified_tables for a human to eyeball instead.
    # Built from the whole-question accepted set (not concatenated per cell)
    # for the same reason the cap above is whole-question: a report's tables
    # are all one report_id regardless of which cell first surfaced them.
    fact_groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for r in accepted:
        for m in r["row_period_matches"]:
            key = (m["matched_phrase"].lower(), _value_key(m["value"]))
            if r["table_id"] not in fact_groups[key]:
                fact_groups[key].append(r["table_id"])
    gt_tables = list(fact_groups.values())
    accepted_table_ids = sorted({r["table_id"] for r in accepted})

    return {
        "qid": q["id"],
        "question": q["question"],
        "tickers": tickers,
        "years": years,
        "doc_type": doc_type,
        "phrases": phrases,
        "resolved_report_ids": all_report_ids,
        "resolved_report_count": len(all_report_ids),
        "scope_warning": warning,
        "gt_tables": gt_tables,
        "accepted_table_ids": accepted_table_ids,
        "n_unverified_tables": len(unverified_tables),
        "unverified_tables": unverified_tables,
        "n_flagged_for_manual": len(flagged_for_manual),
        "flagged_for_manual": flagged_for_manual,
        "cell_detail": cells,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def load_questions_by_id(path: Path) -> dict[int, dict]:
    out = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                d = json.loads(line)
                out[d["id"]] = d
    return out


def parse_qids(args) -> list[int]:
    if args.qids:
        return [int(x) for x in args.qids.split(",") if x.strip()]
    raw = Path(args.qids_file).read_text(encoding="utf-8")
    data = json.loads(raw)
    if isinstance(data, dict):
        if "qids" in data:
            return [int(x) for x in data["qids"]]
        if "questions" in data:
            return [int(r["qid"]) for r in data["questions"]]
        raise ValueError(f"unrecognized manifest shape in {args.qids_file}: keys={list(data)}")
    if isinstance(data, list):
        return [int(x["qid"] if isinstance(x, dict) else x) for x in data]
    raise ValueError(f"unrecognized qids-file format: {args.qids_file}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--qids", help="comma-separated question ids")
    grp.add_argument("--qids-file", help="JSON file: list of ids, {'qids':[...]}, or a manifest with 'questions'")
    ap.add_argument("--out", required=True, help="output JSONL path")
    ap.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD)
    ap.add_argument("--max-candidates", type=int, default=DEFAULT_MAX_CANDIDATES)
    ap.add_argument(
        "--max-per-report", type=int, default=DEFAULT_MAX_PER_REPORT,
        help="reject-and-flag (not truncate) a report's qualifying *scored* "
             "tables for a cell once it exceeds this count (default "
             "%(default)s; locked, a cap sweep saturates at 10 -- see "
             "module docstring)",
    )
    ap.add_argument(
        "--max-main-per-report", type=int, default=DEFAULT_MAX_MAIN_PER_REPORT,
        help="reject-and-flag a report's main-statement (BS/IS/CF) tables "
             "for a cell once it exceeds this count -- separate cap from "
             "--max-per-report because main statements are included "
             "unconditionally, not by phrase score (default %(default)s; "
             "not a final value, see module docstring)",
    )
    args = ap.parse_args()

    qids = parse_qids(args)
    questions = load_questions_by_id(QUESTIONS_PATH)
    ticker_year_reports, report_tables, ticker_company = build_report_index(META_PATH)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    n_warnings = 0
    report_counts = []
    accepted_counts = []
    max_per_report_counts = []  # per question: largest #accepted tables from any single report_id
    unverified_counts = []
    n_with_gold = 0  # questions with >=1 value-backed gt_tables group
    n_flagged_total = 0
    with out_path.open("w", encoding="utf-8") as fh:
        for qid in qids:
            q = questions.get(qid)
            if q is None:
                print(f"SKIP qid{qid}: not found in {QUESTIONS_PATH}")
                continue
            record = build_candidates_for_question(
                q, ticker_year_reports, report_tables, ticker_company,
                threshold=args.threshold, max_candidates=args.max_candidates,
                max_per_report=args.max_per_report,
                max_main_per_report=args.max_main_per_report,
            )
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            report_counts.append(record["resolved_report_count"])
            accepted_counts.append(len(record["accepted_table_ids"]))
            by_report: dict[str, int] = defaultdict(int)
            for tid in record["accepted_table_ids"]:
                by_report[tid.rsplit("|", 1)[0]] += 1
            max_per_report_counts.append(max(by_report.values()) if by_report else 0)
            unverified_counts.append(record["n_unverified_tables"])
            if record["gt_tables"]:
                n_with_gold += 1
            n_flagged_total += record["n_flagged_for_manual"]
            if record["scope_warning"]:
                n_warnings += 1
                print(f"SCOPE WARNING qid{qid}: {record['scope_warning']}")
            if record["n_flagged_for_manual"]:
                print(f"FLAGGED qid{qid}: {record['n_flagged_for_manual']} report(s) over max-per-report={args.max_per_report}")

    print(f"\nwrote {len(report_counts)} record(s) -> {out_path}")
    if report_counts:
        s = sorted(report_counts)
        n = len(s)
        print(f"resolved reports per question: min={s[0]} median={s[n // 2]} max={s[-1]} mean={sum(s) / n:.1f}")
    if accepted_counts:
        s = sorted(accepted_counts)
        n = len(s)
        print(f"accepted tables per question: min={s[0]} median={s[n // 2]} max={s[-1]} mean={sum(s) / n:.1f}")
    if max_per_report_counts:
        print(f"max accepted tables from one report (per question): {max(max_per_report_counts)} "
              f"(should be <= max_per_report + max_main_per_report = {args.max_per_report + args.max_main_per_report})")
    print(f"questions with >=1 value-backed gt_tables group: {n_with_gold}/{len(report_counts)}")
    if unverified_counts:
        s = sorted(unverified_counts)
        n = len(s)
        print(f"unverified (unmatched main-statement) tables per question: min={s[0]} "
              f"median={s[n // 2]} max={s[-1]} mean={sum(s) / n:.1f}  [total={sum(s)}]")
    print(f"scope warnings: {n_warnings}")
    print(f"reports flagged for manual review (>max-per-report): {n_flagged_total}")


if __name__ == "__main__":
    main()
