"""Single source of truth for Vietnamese question-intent vocabulary.

`formula_facts.py`, `raw_table_linker.py`, and `raw_selection_linker.py` each
independently re-implemented "what operation does this question ask for" as
their own private list of diacritic-stripped regexes. Nothing forced those
vocabularies to agree, and it already caused a real defect: a missing `\b` in
one module's selection pattern made `cong ty con` and `dong nam cong ty me`
read as selection intent, so a whole cluster of questions never reached the
linker (see `SELECTION_MARKER` below). This module centralizes the shared
vocabulary so solver modules import from here instead of drifting apart again.

Where two modules genuinely used different patterns for the same concept, this
module keeps both under distinct names rather than picking one -- merging them
would be a silent behavior change. Each such case is called out in a comment.

This only consolidates *vocabulary*. The `should_attempt_*` gates that consult
it stay in their own modules.
"""
from __future__ import annotations

import re
import unicodedata

_NON_WORD = re.compile(r"[^a-z0-9]+")


def norm(text: object) -> str:
    """Lowercase, strip diacritics/đ, collapse non-`[a-z0-9]` runs to spaces.

    Shared verbatim by raw_table_linker, raw_selection_linker, cell_locator,
    and structured_facts (formula_facts's `_norm` comes from structured_facts).
    selection_facts keeps its own copy that also preserves `%`, since its
    filter regex captures a trailing percent sign; that is a real divergence,
    not an oversight, so it is not replaced with this one.
    """
    decomposed = unicodedata.normalize("NFD", str(text)).lower().replace("đ", "d")
    without_marks = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return _NON_WORD.sub(" ", without_marks).strip()


# `Tổng Công ty Phát triển Đô thị Kinh Bắc` is a legal form, not a request for
# a total, and `Tập đoàn`/`Ngân hàng TMCP` are not sums either. Intent
# detection reads the question with these removed. (raw_table_linker.py:70-73)
_ENTITY_FORM = re.compile(
    r"\b(?:tong\s+cong\s+ty|cong\s+ty\s+co\s+phan|cong\s+ty\s+tnhh|"
    r"ngan\s+hang\s+tmcp|ngan\s+hang\s+thuong\s+mai\s+co\s+phan|tap\s+doan)\b"
)


def intent_norm(question: str) -> str:
    """`norm()` plus legal-entity-form wording removed (raw_table_linker._intent_norm)."""
    return _ENTITY_FORM.sub(" ", norm(question))


# --- formula_facts.py:66-69: main-statement growth/diff/avg/median cues -----
# raw_table_linker.py has no growth or median concept, so these have no
# raw-table counterpart.
GROWTH_CUE = re.compile(r"\btang\s+truong\b|\btoc\s+do\s+tang\b", re.I)
MEDIAN_CUE = re.compile(r"\btrung\s+vi\b", re.I)

# formula_facts.py's diff cue requires "hieu so" as one phrase and has no
# "kem"/"so voi" alternatives; raw_table_linker.py's is looser (bare "hieu",
# plus "kem" and "so voi"). These read different sets of questions, so they
# stay separate rather than merging onto one vocabulary.
DIFF_CUE_STRICT = re.compile(r"\bchenh\s+lech\b|\bhieu\s+so\b|\bhon\b", re.I)  # formula_facts._DIFF_CUE
DIFF_CUE_LOOSE = re.compile(r"\b(?:chenh\s+lech|hieu(?:\s+so)?|hon|kem|so\s+voi)\b")  # raw_table_linker._DIFF

# formula_facts._AVG_CUE and raw_table_linker._AVG were written as two
# separate regexes (`a|b` vs `(?:a|b)`, with/without re.I) but match the exact
# same set of normalized (already-lowercase) text, so this is a genuine merge,
# not a choice between two different behaviors.
AVG_CUE = re.compile(r"\btrung\s+binh\b|\bbinh\s+quan\b")

# --- raw_table_linker.py:52-57: raw-table-only operation cues ---------------
# No formula_facts equivalent (main-statement facts do not need sum/ratio-of-
# components detection).
SUM_CUE = re.compile(
    r"\b(?:tong\s+so\s+du|tong\s+so\s+tien|tong\s+gia\s+tri|tong\s+doanh\s+thu|"
    r"tong\s+du\s+no|tong\s+cong)\b"
)
RATIO_CUE = re.compile(r"\b(?:ty\s+le|ty\s+trong|ty\s+so|tren\s+tong|trong\s+tong|bao\s+phu)\b")
MULTIPLIER_RATIO_CUE = re.compile(r"\bgap\b.{0,80}\blan\b|\bbao\s+nhieu\s+lan\b")

# --- Selection ("cao nhat/thap nhat/...") gates -----------------------------
# raw_table_linker.py:58-64. Fixed to require a right boundary after `co` so
# `cong ty con` and `dong nam cong ty me` do not read as selection intent
# (previously broke a whole cluster of questions before they ever reached the
# linker). Applied to `intent_norm(question)`.
SELECTION_MARKER = re.compile(
    r"cao\s+nhat|thap\s+nhat|lon\s+nhat|nho\s+nhat|nhieu\s+nhat|it\s+nhat|"
    r"nam\s+co\b|cong\s+ty\s+co\b|doanh\s+nghiep\s+co\b|tai\s+nam\s+co\b|vao\s+nam\s+co\b"
)
CONDITIONAL_FILTER_CUE = re.compile(r"\bco\b.{0,80}\b(?:lon\s+hon|nho\s+hon|vuot|duoi)\b")

# formula_facts.py:70-75. Matches directly against the *raw* (non-normalized)
# question via accented character classes, and its `nam co`/`cong ty co`
# alternatives have no trailing `\b` -- the same missing-boundary shape as the
# bug fixed in SELECTION_MARKER above, just never fixed here. That is a
# genuine, currently-live divergence between the two modules, not something
# this consolidation is authorized to fix (formula_facts's gate behavior is
# out of scope; see task notes), so it is preserved byte-for-byte and still
# applied to the unnormalized question, exactly as before.
SELECTION_MARKER_ACCENTED = re.compile(
    r"cao\s+nh[aấ]t|th[aấ]p\s+nh[aấ]t|l[ớo]n\s+nh[aấ]t|nh[oỏ]\s+nh[aấ]t|"
    r"nhi[eề]u\s+nh[aấ]t|[íi]t\s+nh[aấ]t|n[aă]m\s+c[oó]|c[oô]ng\s+ty\s+c[oó]|"
    r"doanh\s+nghi[ệe]p\s+c[oó]|v[aà]o\s+n[aă]m\s+.*c[oó]",
    re.I,
)

# --- raw_selection_linker.py:37-58 ------------------------------------------
# selection_facts.py:29-30 defines byte-identical MAX_MARKER/MIN_MARKER
# regexes (verified against normalized text in both modules); merged here.
MAX_MARKER = re.compile(r"cao\s+nhat|lon\s+nhat|nhieu\s+nhat")
MIN_MARKER = re.compile(r"thap\s+nhat|nho\s+nhat|it\s+nhat")
FILTER_MARKER = re.compile(
    r"\b(?:lon\s+hon|tren|cao\s+hon|vuot|thap\s+hon|nho\s+hon|duoi)\s+"
    r"-?\d+(?:[,.]\d+)?\s*%?"
)
YEAR_ANSWER_MARKER = re.compile(r"\bnam\s+nao\b|\bvao\s+nam\s+nao\b")
TICKER_ANSWER_MARKER = re.compile(r"\b(?:cong\s+ty|doanh\s+nghiep|ngan\s+hang)\s+nao\b")


__all__ = [
    "AVG_CUE",
    "CONDITIONAL_FILTER_CUE",
    "DIFF_CUE_LOOSE",
    "DIFF_CUE_STRICT",
    "FILTER_MARKER",
    "GROWTH_CUE",
    "MAX_MARKER",
    "MEDIAN_CUE",
    "MIN_MARKER",
    "MULTIPLIER_RATIO_CUE",
    "RATIO_CUE",
    "SELECTION_MARKER",
    "SELECTION_MARKER_ACCENTED",
    "SUM_CUE",
    "TICKER_ANSWER_MARKER",
    "YEAR_ANSWER_MARKER",
    "intent_norm",
    "norm",
]
