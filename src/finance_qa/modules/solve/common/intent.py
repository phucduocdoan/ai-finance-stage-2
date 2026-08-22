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

# --- cell_locator.py:64-71: does a signed cell answer as a magnitude? --------
# Expense and provision rows are printed negative -- or parenthesised, which
# parses to negative -- in Vietnamese statements, while a question asking "chi
# phi ... la bao nhieu" wants the amount. These two read the *raw* question, not
# `norm()` output, so they carry both spellings of each vowel; that is how
# cell_locator has always applied them and normalising here would be a silent
# behavior change.
MAGNITUDE_METRIC = re.compile(
    r"chi\s+ph[ií]|d[uự]\s+ph[oò]ng|hao\s+m[oò]n|kh[aấ]u\s+hao|l[aã]i\s+vay",
    re.I,
)
SIGNED_METRIC = re.compile(
    r"l[uư]u\s+chuy[eể]n|d[oò]ng\s+ti[eề]n|l[aã]i\s*/\s*l[oỗ]|l[oỗ]\b|ch[eê]nh\s+l[ệe]ch",
    re.I,
)
# Money that has already left the company ("thue TNDN da nop", "co tuc da tra")
# is printed negative in the cash-flow statement, and a question asking for it
# wants the amount. `MAGNITUDE_METRIC` above misses these entirely: none of its
# five words appear in "thue TNDN da nop" (q894). One question in the
# 1,012-question run answers negative on this wording, and gold is positive.
PAID_OUT = re.compile(r"\bda\s+(?:nop|tra|chi)\b")
# Any year mentioned in the question. Used to tell a difference *between two
# companies in one period* from a difference *across periods*: `norm()` keeps
# digits, so counting these on normalized text works.
YEAR_MENTION = re.compile(r"\b(?:19|20)\d\d\b")

# Cues that keep the sign even when `MAGNITUDE_METRIC` fires, for callers that
# read arithmetic questions `SIGNED_METRIC` was never written for. It covers
# only what `DIFF_CUE_LOOSE` and `GROWTH_CUE` miss: measured on the 1,012-question
# run, "tru di" (q778) and "ty le tang" (q639) are the two subtraction/growth
# wordings that reach an expense metric without any diff or growth cue.
MAGNITUDE_BLOCK = re.compile(r"\btru\s+di\b|\bty\s+le\s+tang\b")

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

# --- Candidate-filter forms other than a literal threshold ------------------
# `FILTER_MARKER` above only reads "lon hon 5" / "duoi 10%". Measured over the
# 72 two-stage questions the selection_facts gate declines, a literal threshold
# is the *rarest* form (5); the group median (30) and the sign of a metric (45)
# dominate. The executor already runs both -- `value_source="median"` resolves
# the candidate-set median in `_execute_selection`, and a sign filter is just
# `value=0` -- so these two patterns are what the emitter was missing.
#
# `MEDIAN_FILTER_CUE` deliberately requires the comparator to sit immediately
# before "trung vi", which is what separates a *filter* ("thap hon trung vi cua
# nhom") from the median as the *answer* ("lay trung vi ty trong hang ton kho").
MEDIAN_FILTER_CUE = re.compile(
    r"\b(?P<cmp>lon\s+hon|cao\s+hon|tren|vuot|thap\s+hon|nho\s+hon|duoi)\s+"
    r"(?:muc\s+|gia\s+tri\s+)?trung\s+vi\b"
)
# "duong"/"am" as a sign predicate on the quantity named just before it.
# This matches the bare token on purpose: `duong` is also a company-name token
# ("Duong Quang Ngai", "Dai Duong"), and the disambiguation belongs to the
# caller, which only emits a filter when a *catalog metric* occurs immediately
# before the match -- the same anchoring `_FILTER_RE` already relies on.
SIGN_FILTER_CUE = re.compile(r"\b(?P<sign>duong|am)\b")

# --- Aggregating a filtered group -------------------------------------------
# `RATIO_CUE` cannot be reused for a group share: it fires on ratio *metrics*
# ("ty le no phai tra tren tong tai san") just as readily. What distinguishes a
# share of the group is the explicit reference back to the whole group, so that
# reference is required rather than the ratio wording alone.
GROUP_SHARE_CUE = re.compile(
    # "dong gop bao nhieu phan tram vao tong loi nhuan ..."
    r"\b(?:dong\s+gop|chiem|chiem\s+ty\s+le)\b[^?]{0,60}?\bvao\s+tong\b"
    # "... chiem bao nhieu phan tram tong no phai tra cua ca nhom"
    r"|\b(?:ty\s+trong|chiem|tren\s+tong|so\s+voi\s+tong)\b[^?]{0,90}?"
    r"\b(?:ca\s+nhom|toan\s+nhom|cua\s+nhom|ca\s+\d+\s+doanh\s+nghiep|"
    r"toan\s+bo\s+nhom|ca\s+ro|nhom\s+nay|nhom\s+sau\s+loc)\b"
    # A bare "ty trong X" is a group share only when X is not itself stated as a
    # ratio: `inventory_to_assets` is spelled "ty trong hang ton kho tren tong
    # tai san" in the catalog, and reading that as a share would hijack every
    # question that merely averages a ratio metric.
    # `(?<!cong )` is not optional: "co bao nhieu cong ty trong so ..." contains
    # the token pair "ty trong" purely because "cong ty" is followed by "trong".
    r"|(?<!cong )\bty\s+trong\b(?![^?]{0,45}?\b(?:tren|trong)\s+tong\b)"
)

# A hypothetical adjustment to the reported figures ("neu doanh thu dong loat
# giam 10%", "sau khi giam 50% gia tri hang ton kho"). A plan that does not
# carry the adjustment would answer the unadjusted question instead, so callers
# that cannot express it must fail closed rather than silently drop the clause.
SCENARIO_CUE = re.compile(
    r"\bdong\s+loat\s+(?:giam|tang)\b|\bsau\s+khi\s+(?:giam|tang|dieu\s+chinh)\b|"
    r"\bgiu\s+nguyen\b|\bkich\s+ban\b|\bgia\s+dinh\b|"
    r"\bneu\b[^?]{0,60}?\b(?:giam|tang)\s+\d+(?:[,.]\d+)?\s*%"
)
GROUP_COUNT_CUE = re.compile(
    r"\bbao\s+nhieu\s+(?:cong\s+ty|doanh\s+nghiep|ngan\s+hang|ma|nam)\b|\bso\s+luong\b"
)

# --- What a filter -> aggregate plan cannot express --------------------------
# A plan that drops a clause answers a *different* question with full
# confidence, which is strictly worse than declining. These four cues mark the
# clauses this shape has no slot for, and callers use them to fail closed.
#
# `ARITHMETIC_CONNECTOR` sits between two catalog metric mentions when the
# question names a composite the catalog does not ("hang ton kho / no ngan han",
# "tai san ngan han tru hang ton kho roi chia cho no ngan han"). Anchoring a
# filter on either operand silently changes the condition, so a connector with
# no alias spanning it means the metric is unnameable. Note `/` never survives
# normalisation -- it is stripped to a space -- hence the empty alternative.
ARITHMETIC_CONNECTOR = re.compile(
    r"^\s*(?:tren|chia\s+cho|so\s+voi|tru|cong|nhan|roi\s+chia\s+cho|va)?\s*$"
)
# A comparator that no filter form consumed. "tai san ngan han thap hon no ngan
# han" compares two metrics to each other, which is not a threshold, a median or
# a sign. Bare `tren` is excluded: it is the ratio connector far more often than
# a comparator.
UNCONSUMED_COMPARATOR_CUE = re.compile(
    r"\b(?:lon\s+hon|cao\s+hon|thap\s+hon|nho\s+hon|vuot)\b"
)
# The answer is a difference -- between two metrics, or between the surviving
# subgroup and its complement. Either needs an expression or a second group.
SUBGROUP_DIFF_CUE = re.compile(
    r"\bchenh\s+lech\b|\bkhac\s+biet\b|\bnhom\s+con\s+lai\b|\bphan\s+nhom\b"
)
# The denominator of a group share is itself restricted ("tong loi nhuan sau
# thue cua cac doanh nghiep co lai"). `share` divides by the whole group, so a
# restricted total would be answered against the wrong denominator.
CONDITIONED_TOTAL_CUE = re.compile(
    r"\b(?:co\s+lai|bi\s+lo|duong|am|sau\s+loc|thoa\s+man|dap\s+ung)\b"
)


__all__ = [
    "ARITHMETIC_CONNECTOR",
    "AVG_CUE",
    "CONDITIONAL_FILTER_CUE",
    "CONDITIONED_TOTAL_CUE",
    "DIFF_CUE_LOOSE",
    "DIFF_CUE_STRICT",
    "FILTER_MARKER",
    "GROUP_COUNT_CUE",
    "GROUP_SHARE_CUE",
    "GROWTH_CUE",
    "MAGNITUDE_BLOCK",
    "MAGNITUDE_METRIC",
    "MAX_MARKER",
    "MEDIAN_CUE",
    "MEDIAN_FILTER_CUE",
    "MIN_MARKER",
    "MULTIPLIER_RATIO_CUE",
    "PAID_OUT",
    "RATIO_CUE",
    "SCENARIO_CUE",
    "SELECTION_MARKER",
    "SELECTION_MARKER_ACCENTED",
    "SIGNED_METRIC",
    "SIGN_FILTER_CUE",
    "SUBGROUP_DIFF_CUE",
    "SUM_CUE",
    "TICKER_ANSWER_MARKER",
    "UNCONSUMED_COMPARATOR_CUE",
    "YEAR_ANSWER_MARKER",
    "YEAR_MENTION",
    "intent_norm",
    "norm",
]
