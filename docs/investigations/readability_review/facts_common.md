# Readability review: structured-facts pipeline + common helpers

Scope: `facts/{execute,metrics,planner,profile_validate,schema,store,
structured_facts,table_profile}.py` and
`common/{columns,context,intent,lookup,metric_hints,screening,solution,units}.py`.

No behavior/accuracy issues flagged, per review scope; findings below are
onboarding/readability-only, ordered by impact. `structured_facts` being off
by default and not-yet-proven per `docs/config_flags.md` is known/intentional
and not flagged as an issue on its own.

1. **Two independently maintained Vietnamese alias catalogs for the same
   ratios** — `facts/metrics.py:96-166` (`DERIVED_ALIASES`, drives
   `canonical_metric`/execution) and `common/metric_hints.py:54-233`
   (`_HINTS[*].aliases`, drives prompt hints) both enumerate wording for the
   same ~11 ratios (D/E, quick/current ratio, ROE, ROA, CFO/LNST, inventory
   days, etc.), with overlapping but non-identical phrase lists and no
   cross-reference between them. A newcomer adding a new phrasing for "ROE"
   would have no signal that it needs updating in two files.

2. **`_norm()` copy-pasted verbatim in five files** instead of reusing the
   one place documented as canonical — `facts/metrics.py:11-14`,
   `facts/profile_validate.py:91-94`, `facts/table_profile.py:33-36`,
   `common/lookup.py:54-58`, `common/metric_hints.py:18-21` all define the
   identical NFD-normalize/strip-diacritics/collapse-non-word function, while
   `common/intent.py:27-38` explicitly says it's meant to be the "single
   source of truth" for this exact normalization and is already reused that
   way by `facts/store.py`. Five near-identical private copies obscure that
   they're the same function.

3. **Three separate reimplementations of "which period does this
   column/label represent"** with diverging keyword coverage:
   `facts/store.py:_period_kind` (`295-306`, operates on the long-format
   `period` field), `common/columns.py:_CURRENT`/`_PRIOR` (`34-36`, operates
   on wide-CSV headers), and `facts/table_profile.py:_profile_year` (`80-90`,
   also wide-CSV headers but a third word list). The latter two solve the
   literal same problem — "does this column header say current or prior
   period" — with two independent regex/keyword sets.

4. **`facts/store.py` bundles two unrelated responsibilities** — the generic
   DuckDB-backed `StatementFactStore` (`110-186`) and a ~130-line
   bank-statement CSV fallback subsystem (`_bank_label_matches`,
   `_bank_label_column`, `_bank_period_columns`, `_read_bank_label_rows`,
   `_bank_label_fallback_rows`, lines `41-91` and `204-285`) that bypasses
   the DuckDB view entirely and re-reads raw CSVs. A new engineer scanning
   "the fact store" has to wade through an entirely separate CSV-parsing
   path to find the 30 lines that are the actual store. Suggest a separate
   module (e.g. `facts/bank_fallback.py`).

5. **`execute.py:_metric_value` (lines 52-100)** is a 50-line if/elif chain,
   one branch per derived metric key. It works, but a dict of small
   callables keyed by canonical metric name would let a reader scan it like
   a formula table rather than trace a chain of returns to find one metric.

6. **`_metric_value` vs `_measure_value` naming** (`execute.py:50, 103`) — one
   word apart, but materially different in scope: `_metric_value` handles
   catalog metrics only, `_measure_value` handles a catalog metric or a
   whitelisted expression and is the one most call sites should use. Easy to
   grab the wrong one; a rename (e.g. `_catalog_metric_value` /
   `_measure_or_expression_value`) or at least a one-line comment at
   `_metric_value`'s definition would help.

7. **`_execute_selection`'s per-candidate loop duplicates `_element_values`**
   — `execute.py:549-569` hand-rolls the same ticker/year resolution and
   `missing_policy`/try-except pattern that's already extracted into
   `_element_values` (`461-489`), just without `_element_values`'s
   non-finite check. A future change to missing-policy handling would need
   to be made in both places, and it's not obvious from reading
   `_execute_selection` that this loop is a near-duplicate rather than
   something genuinely different.

8. **`schema.py`: unused and duplicate `Literal` aliases** — `PlannerMetric`
   (`schema.py:59`) and `PlannerMeasure` (`61`) are defined but never
   referenced anywhere else in the file. `PlannerFilterMeasure` (`63`) and
   `PlannerMeasureNoEmpty` (`62`) are two different names for the exact same
   definition `Literal[*METRIC_KEYS, *EXPRESSION_KEYS]`, which reads as
   though they encode different constraints when they don't.

9. **Inconsistent import boundary within `facts/`** —
   `facts/profile_validate.py:19-25` and `facts/table_profile.py:22` import
   shared names through the compatibility facade `facts/structured_facts.py`,
   while `facts/execute.py`, `facts/planner.py`, and `facts/store.py` import
   directly from `facts/metrics.py`. `structured_facts.py`'s own docstring
   (`8-12`) frames itself as a facade "so existing imports... keep working
   unchanged" for external callers — internal `facts/` modules routing
   through it makes the real dependency graph harder to see.

10. **`schema.py:StructuredSelectionPlan.to_structured_plan` filter
    comprehension has an undocumented rule** — lines `253-270` drop a filter
    when two separately compound, unexplained conditions hold (`value is
    None and value_source=="literal" and metric==selector_metric`, and
    `metric==selector_metric and relation=="eq"`). Given this codebase's
    otherwise strong habit of commenting every non-obvious rule with its
    "why," this is the one place in `schema.py` where a real behavioral
    decision has no explanation attached.

11. **`execute.py:_target_unit` is a same-signature forwarding wrapper**
    (`158-164`) around `_resolved_target_unit`, called from exactly one site
    (`274`), while `_supported_answer_unit` calls `_resolved_target_unit`
    directly a few lines later — a reader has to check both call sites to
    confirm they're equivalent. Minor, but an easy one-line simplification.

## Overall impression

The design is coherent and the heavy "why" commenting (measured tradeoffs,
question-id-linked bug history) is genuinely useful and should stay as-is.
The main onboarding friction isn't inside any single function — most
functions are reasonably sized and the planner/schema/execute/store split is
sensible — it's that the same small pieces of domain logic (Vietnamese text
normalization, ratio-name vocabulary, period/year wording) got reimplemented
independently across `facts/` and `common/` several times over, so a new
engineer can't tell by reading one file whether they're looking at *the*
implementation or *a* copy.

**If only one change could be made:** consolidate the five identical
`_norm()` copies onto the one already-documented canonical implementation in
`common/intent.py` (item 2) — it's mechanical, zero behavior risk, and
immediately cuts down the "wait, is this the same function I just read in
another file?" tax that shows up repeatedly across this review.
