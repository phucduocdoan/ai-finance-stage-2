"""Find a row by its Vietnamese label across every shortlisted table.

Why this exists. Retrieval hands the solver ~106 tables that pass the hard
ticker/year/doc_type filter, and `generate_pandas` shows the model 3 of them.
Which 3 is decided by a reranker and a judge that read titles and label
previews — never a cell. Measured on the 60 cell-truth questions: the gold table
survives the hard filter 60/60 and reaches the model 49/60, and of the 30 wrong
answers 21 had the gold table *on screen* and still missed, most often by taking
a component row where the question wanted the total ("Chi phí thuế TNDN hiện
hành của Ngân hàng" instead of "Tổng chi phí thuế TNDN hiện hành (Ngân hàng +
công ty con)").

So the fix is not more grids in the prompt — `codegen_max_tables=3` is measured,
and 10 scores worse. It is a way to reach the other 103 tables *by name*, one
lookup at a time, paying prompt budget only for the rows that come back.

Cheap enough to be boring: tables are 8 rows at p50 and 21 at p90, and
`load_frame` is 6.6 ms, so scanning a whole shortlist costs ~0.7 s and needs no
index. Nothing here is persisted, so none of the protected artifacts in
`docs/DECISIONS.md` §8 are involved.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

import pandas as pd

from finance_qa.modules.data.table_store import load_frame
from finance_qa.modules.solve.context import meta_for
from finance_qa.modules.solve.metric_hints import metric_search_labels
from finance_qa.modules.solve.units import detect_table_unit

# Share of the query's tokens a row label must carry. Low enough that asking for
# "tổng chi phí thuế thu nhập doanh nghiệp hiện hành" still reaches a row printed
# "Chi phí thuế TNDN hiện hành" (6 of 10 tokens), high enough that a single
# common word like "chi" does not return the corpus.
MIN_SCORE = 0.5

# Rows returned to the model per call. The point of the tool is a short answer;
# a caller that needs the whole grid asks for the grid instead.
DEFAULT_LIMIT = 20

_NON_WORD = re.compile(r"[^a-z0-9]+")
_LABEL_COLUMN = re.compile(
    r"ch[iỉ]\s*ti[eê]u|kho[aả]n\s*m[uụ]c|n[oộ]i\s*dung|di[eễ]n\s*gi[aả]i|t[eê]n",
    re.I,
)
_AUX_COLUMN = re.compile(r"^(?:stt|so\s*thu\s*tu|ma\s*so|thuyet\s*minh|tm)$", re.I)


def _norm(text: object) -> str:
    """Lowercase, accent-free, punctuation-free form used for matching."""
    decomposed = unicodedata.normalize("NFD", str(text)).lower().replace("đ", "d")
    without_marks = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return _NON_WORD.sub(" ", without_marks).strip()


@dataclass(frozen=True)
class RowHit:
    """One matching row, with everything needed to write `.iloc` against it."""

    table_id: str
    position: int          # the `.iloc` position, i.e. the number printed in the grid
    label: str             # the row label VERBATIM and untruncated
    values: dict[str, str] = field(default_factory=dict)   # column name -> printed value
    table_summary: str = ""
    score: float = 0.0


def _summary(table_id: str, df: pd.DataFrame) -> str:
    """Identity line for a table: who, when, which statement, what unit."""
    meta = meta_for(table_id)
    unit, _ = detect_table_unit(df, meta.get("context_page_text") or "")
    parts = [
        f"{meta.get('ticker') or '?'} {meta.get('year') or '?'} {meta.get('doc_type') or '?'}",
        meta.get("statement_type") or "unknown",
        f"đơn vị khai báo: {unit or 'không tìm thấy'}",
    ]
    if meta.get("note_title"):
        parts.append(str(meta["note_title"]))
    return " | ".join(parts)


def _keeps(table_id: str, ticker: str | None, year: int | None, statement_type: str | None) -> bool:
    meta = meta_for(table_id)
    if ticker and str(meta.get("ticker") or "").upper() != ticker.upper():
        return False
    if year is not None and str(meta.get("year") or "") != str(year):
        return False
    if statement_type and str(meta.get("statement_type") or "") != statement_type:
        return False
    return True


def _score(query_tokens: Sequence[str], normalized_label: str) -> float:
    if not query_tokens:
        return 0.0
    label_tokens = set(normalized_label.split())
    matched = sum(1 for token in query_tokens if token in label_tokens)
    score = matched / len(query_tokens)
    if score and " ".join(query_tokens) in normalized_label:
        score += 0.25   # the label contains the phrase, not just its words
    return score


def label_column(df: pd.DataFrame):
    """Column that carries row labels.

    The first physical column is not always the label. Bank statements often
    repair to ``STT | Chỉ tiêu | Thuyết minh | ...``; scanning ``STT`` finds row
    codes like ``I``/``II`` instead of the financial metric. Prefer explicit
    label-ish names, then the string column whose cells look most like prose.
    """
    best_col = df.columns[0]
    best_score = float("-inf")
    for index, col in enumerate(df.columns):
        name = str(col).strip()
        norm_name = _norm(name)
        series = df[col].head(40).astype(str).str.strip()
        filled = [str(value) for value in series if str(value) and str(value).lower() != "nan"]
        if not filled:
            continue
        token_counts = [len(_norm(value).split()) for value in filled]
        prose = sum(1 for count in token_counts if count >= 2) / len(filled)
        avg_tokens = sum(token_counts) / len(token_counts)
        score = prose + min(avg_tokens / 8.0, 1.5)
        if _LABEL_COLUMN.search(name):
            score += 3.0
        if _AUX_COLUMN.fullmatch(norm_name):
            score -= 3.0
        if index == 0:
            score += 0.25
        if score > best_score:
            best_score = score
            best_col = col
    return best_col


def search_rows(
    table_ids: Iterable[str],
    label: str,
    *,
    ticker: str | None = None,
    year: int | None = None,
    statement_type: str | None = None,
    limit: int = DEFAULT_LIMIT,
    expand_metrics: bool = False,
) -> list[RowHit]:
    """Rows whose first-column label matches `label`, best first.

    Matching ignores accents, case and punctuation, so the model may type the
    metric the way the question words it rather than the way extraction printed
    it. A table that will not load is skipped: a lookup is a convenience, and
    taking the question down over one unreadable CSV is not.
    """
    labels = metric_search_labels(label) if expand_metrics else []
    labels = labels or [label]
    per_label = max(4, limit // len(labels))
    hits_by_row: dict[tuple[str, int], RowHit] = {}
    for query_label in labels:
        for hit in _search_rows_once(
            table_ids,
            query_label,
            ticker=ticker,
            year=year,
            statement_type=statement_type,
            limit=per_label,
        ):
            key = (hit.table_id, hit.position)
            if key not in hits_by_row or hit.score > hits_by_row[key].score:
                hits_by_row[key] = hit
    hits = list(hits_by_row.values())
    hits.sort(key=lambda h: (-h.score, len(h.label), h.table_id, h.position))
    return hits[:limit]


def _search_rows_once(
    table_ids: Iterable[str],
    label: str,
    *,
    ticker: str | None = None,
    year: int | None = None,
    statement_type: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> list[RowHit]:
    """The literal label search behind ``search_rows``."""
    query_tokens = _norm(label).split()
    if not query_tokens:
        return []

    hits: list[RowHit] = []
    for table_id in dict.fromkeys(table_ids):
        if not _keeps(table_id, ticker, year, statement_type):
            continue
        try:
            df = load_frame(table_id)
        except Exception:  # noqa: BLE001 - one bad CSV must not fail the lookup
            continue
        if df.empty or df.shape[1] == 0:
            continue
        summary = ""
        first_col = label_column(df)
        for position, raw_label in enumerate(df[first_col]):
            score = _score(query_tokens, _norm(raw_label))
            if score < MIN_SCORE:
                continue
            summary = summary or _summary(table_id, df)
            row = df.iloc[position]
            hits.append(
                RowHit(
                    table_id=table_id,
                    position=position,
                    label=str(raw_label),
                    values={str(col): str(row[col]) for col in df.columns if col != first_col},
                    table_summary=summary,
                    score=score,
                )
            )
    # Shorter labels first among equal scores: "Tổng chi phí thuế TNDN" beats the
    # same phrase buried in a longer sentence, and the model still sees both.
    hits.sort(key=lambda h: (-h.score, len(h.label), h.table_id, h.position))
    return hits[:limit]


def render_hits(hits: Sequence[RowHit], variables: Mapping[str, str]) -> str:
    """Hits as prompt text, grouped by table, with each table's bound variable.

    `variables` maps table_id -> variable name, so the model can write
    `df7.iloc[12]["Năm nay"]` straight from what it reads here. Values are
    printed with their column names verbatim because the column name is what the
    query must copy character for character.
    """
    if not hits:
        return "Không tìm thấy hàng nào khớp."
    lines: list[str] = []
    current = ""
    for hit in hits:
        if hit.table_id != current:
            current = hit.table_id
            var = variables.get(hit.table_id, "?")
            lines.append(f"\n### {var} = {hit.table_id}\n{hit.table_summary}")
        cells = " | ".join(f"{col}: {value}" for col, value in hit.values.items())
        lines.append(f"  [{hit.position}] {hit.label}" + (f"  ->  {cells}" if cells else ""))
    return "\n".join(lines).strip()


__all__ = ["DEFAULT_LIMIT", "MIN_SCORE", "RowHit", "label_column", "render_hits", "search_rows"]
