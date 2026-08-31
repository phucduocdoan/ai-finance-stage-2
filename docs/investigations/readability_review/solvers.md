# Readability review: deterministic solvers

Scope: `solvers/{capability_router,cell_locator,decompose,formula_facts,
raw_selection_linker,raw_table_linker,selection_facts}.py`, and the
`raw_table_linking/` and `table_linking/` sub-packages (21 files total).

Comments explaining measured tradeoffs / historical bug fixes (e.g. the
q848/862/915/922/964/1003 comment in `raw_table_linking/request.py`, the
fan-out gold-set numbers in `decompose.py`'s docstring, the `%`-preserving
`_norm` comment in `selection_facts.py`) are treated as an asset, not flagged.

1. **`solvers/raw_table_linker.py:1` and `solvers/raw_table_linking/__init__.py`**
   — Nothing in either name signals that the singular file is a
   backward-compat facade over the plural package's real implementation
   (confirmed: `build_request` at line 113 is a 3-line delegate to
   `raw_table_linking/request.py:174`, and dozens of lines like
   `decision_from_semantic_plan = _decision.decision_from_semantic_plan` are
   bare re-exports). Rename the file to something like
   `raw_table_linker_facade.py`/`raw_table_linker_api.py`, or fold its public
   surface directly into `raw_table_linking/__init__.py` and delete the shim.

2. **`solvers/table_linking/` vs `solvers/raw_table_linking/`** — Two
   packages with a one-character-prefix-difference name hold two halves of
   the same feature's type model (`table_linking/schema.py:67` defines
   `RawCellCandidate`/`RawLinkRequest`, which `raw_table_linking/schema.py`
   imports `RawOperation` from, and `raw_table_linking/candidates.py` imports
   the rest from) plus profiling utilities (`table_linking/columns.py`,
   `table_linking/rows.py`). This is a genuine, not imagined, naming
   collision and should be resolved by renaming `table_linking/` to
   something that names its actual job, e.g. `table_profiles/` or
   `raw_table_model/` (it builds column/row profiles and the shared
   candidate schema, it doesn't "link" anything).

3. **`raw_table_linking/prepare.py:23-46`** — `aprepare_raw_table_linker`'s
   signature injects 18 separate `*_func` keyword-default callables, making
   the actual call graph unreadable from the signature alone and forcing a
   reader to open 6 other files to know what each default really does —
   collapse the DI surface into one `deps`/`ops` dataclass or drop the
   override capability for internals that are never actually swapped outside
   tests.

4. **`raw_selection_linker.py:831-987`** — `aprepare_raw_selection_linker` is
   a 156-line function that sequentially inlines candidate building, search
   planning, semantic decision, row-group decision, flow decision, and LLM
   planner fallback all in one body — split each decision-cascade stage into
   a named helper so the control flow is scannable at a glance.

5. **`raw_selection_linker.py:267-330` vs `raw_table_linking/render.py:24-52`**
   — `_candidate_table_ids`, `_candidate_first_cell`, and `_candidate_query`
   are near-verbatim duplicated (same isinstance branching over
   `RawCellCandidate`/`RawGroupCandidate`) between the two files instead of
   one importing the other — have `raw_selection_linker.py` import these
   three from `raw_table_linking/render.py` (or a shared module), since it
   already imports many other symbols from `raw_table_linker`.

6. **`raw_selection_linker.py:261`, `raw_table_linker.py:470`,
   `raw_table_linking/ratio_options.py:25`** — `_unit_kind` (the
   `unit in MONEY_SCALE or unit == "unknown" -> "money"` classifier) is
   independently defined three times instead of once — move it to
   `raw_table_linking/ratio_options.py` (or a shared units helper) and have
   the other two import it, exactly as `raw_table_linker.py:470` already does
   today for its own copy.

7. **`cell_locator.py:304` vs `raw_table_linking/scoring.py:118`** —
   `_rank_bonus` (rank<3→0.08, rank<10→0.04, else 0.0) is duplicated
   verbatim between the two modules with no shared import — extract to a
   shared scoring util (e.g. `common/scoring.py`) since both call sites use
   it identically.

8. **`cell_locator.py:208`, `raw_table_linker.py:113`,
   `raw_table_linking/request.py:174`, `raw_selection_linker.py:115`** — the
   name `build_request` is reused for four functions with entirely different
   signatures and return types (`CellRequest` vs `RawLinkRequest` vs a
   raw_selection-specific variant) across sibling solver modules. Fine
   within each module in isolation but makes cross-file grep/navigation
   ambiguous; renaming at least the raw_selection_linker.py one to
   `build_selection_request` (mirroring its own domain) would remove the last
   remaining collision once item 1's facade is resolved.

9. **`raw_selection_linker.py:707` vs `raw_table_linking/decision.py:140`** —
   two different functions named `decision_from_semantic_plan` exist in
   files that already import from each other (`raw_selection_linker.py`
   imports `raw` which re-exports
   `raw_table_linking.decision.decision_from_semantic_plan` at
   `raw_table_linker.py:477`), so a reader following the name from one
   module can land on the wrong implementation — rename the
   `raw_selection_linker.py` variant, e.g.
   `decision_from_selection_semantic_plan`.

10. **`raw_selection_linker.py:361-469`** — `_row_phrase_group_candidates` is
    a 108-line function combining filtering, group construction, and scoring
    in one body — split into a filter step, a construct step, and a score
    step so each piece can be read/tested independently.

11. **`cell_locator.py:262-354`** — `_column_choice` (dense multi-factor
    scoring, ~35 lines) and `_hit_to_cell` (~40 lines combining scoring,
    value extraction, and transform application) are both doing multiple
    distinct jobs in one function body — separate "score candidates" from
    "materialize the winning hit into a CellHit."

12. **`formula_facts.py:215-260`** (deterministic_formula_plan, ~45 lines) —
    the ratio/lookup/growth/diff/avg/median operation-shape branching is a
    long flat if/elif chain with no dispatch table, making it hard to see
    which shape maps to which handler at a glance — consider a dict-based
    dispatch keyed by operation shape, or at minimum group the branches with
    a short comment banner per operation family.

13. **`selection_facts.py:409-488`** — `_unexpressible` (~78 lines of
    sequential, well-commented but unrelated checks) is doing too many
    distinct jobs in a single function even though each individual check is
    justified — extract each check into a small named predicate (e.g.
    `_has_ambiguous_scope`, `_missing_required_axis`), preserving each
    existing WHY-comment on its own predicate.

14. **`raw_table_linking/candidates.py:40`** — `_candidate_rows` (~100 lines)
    combines frame loading, profile building, and table/column/row scoring,
    and per-cell candidate construction inline — split frame/profile setup
    from the per-row scoring loop.

15. **`table_linking/rows.py:1` and `table_linking/columns.py:1`** — minor
    naming asymmetry worth folding into the item 2 rename discussion: these
    two files are genuinely well-scoped and well-commented (the OCR
    section-header docstring in `rows.py` is an especially good example of
    the "measured WHY" convention), so if `table_linking/` is renamed, keep
    these two files' content/structure untouched — this is a naming-only
    fix, not a code fix.

## Overall impression

The deterministic-solver code itself is generally well-factored at the
statement level — Vietnamese regex constants are named clearly, WHY-comments
are used exactly as intended, and most individual functions are short and
single-purpose. The accretion problem is almost entirely at the
module/package-boundary layer: two packages sharing the substring
"table_linking" with an inverted-implication relationship
(`raw_table_linking/` depends on `table_linking/`, not the other way a
newcomer would guess), plus a same-named flat file (`raw_table_linker.py`)
that turns out to be a compatibility shim over the package with the same
stem, plus a small cluster of independently-reinvented helpers (`_unit_kind`
x3, `_rank_bonus` x2, the `_candidate_*` trio x2).

**If only one change could be made:** rename `table_linking/` to a name that
reflects what it actually is (a shared candidate schema + column/row
profiling toolkit), and rename or merge `raw_table_linker.py`'s facade role
explicitly — this single naming fix would make the dependency direction
between the two packages self-evident to a newcomer without reading a single
line of implementation.
