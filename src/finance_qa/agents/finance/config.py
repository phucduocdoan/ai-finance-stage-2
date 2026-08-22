"""Configuration for the finance QA agent.

A leaf module (imports only the LLM default model) so both ``graph`` (the
topology builder + default-config ``run_question``) and ``agent`` (the
configurable class API) can import it without an import cycle.

Defaults reproduce the previously-hardcoded node behavior.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from finance_qa.core.llm import MODEL


def _flag(name: str, default: bool) -> bool:
    """Boolean default read from the environment, for A/B runs of one node."""
    raw = os.environ.get(name)
    return default if raw is None else raw.strip().lower() not in {"0", "false", "no", ""}


def _count(name: str, default: int) -> int:
    """Integer default read from the environment, for A/B runs of one node."""
    raw = os.environ.get(name)
    return default if raw is None or not raw.strip().isdigit() else int(raw)


@dataclass(frozen=True)
class FinanceAgentConfig:
    llm_model: str = MODEL
    understand_thinking: bool = False    # understand node: enable_thinking
    reranker: str | None = "qwen3-0.6b"  # retrieve node: cross-encoder reranker
    judge_top_n: int = 20                # retrieve node: tables shown to the judge
    # Which dense index the retrieve node reads. `bge-m3-dense-text` is the same encoder over
    # `dense_text` (= doc_text minus header_flat); BM25 keeps the full doc_text either way,
    # because an unmatched token is free for BM25 and not for a bi-encoder.
    #
    # "bge-m3", and measured — but read the config it was measured in. Over 154 gold questions
    # `dense_text` is worth top-3 +7 / top-10 +4 with **the reranker off**
    # (docs/retrieval_preprocessing_2026-08-21.md §10.4). That win is in the *fused order*, and
    # `_arerank` re-scores the whole pool and replaces `pool.ranked` wholesale, so with the
    # default reranker the fused order is thrown away and the dense channel can only act
    # through pool membership. Measured on membership alone (which the reranker does not
    # change, so this is exact for production): pools differ on 150/154 questions by a median
    # 5 tables of ~36, and gold-in-pool goes 150 -> 149 — one loss (q166), zero gains.
    #
    # Measured the rest of the chain too, rather than inferring it. With the reranker on, the
    # two backends tie at top-20 (148 each), which is the window `judge_top_n` cuts. End to end
    # through `_evidence` (scripts/gate_retrieval_full.py), DOCS F2 is identical to three
    # decimals — `relevant_docs` comes from the hard filter via primary expansion, not from
    # ranking — and TABLES F2 sits inside the churn floor: the same `doc_text` config scored
    # top-3 23 then 26 on unbiased60 across two runs, against dense_text's 26. The one cell
    # outside that band is unbiased60 recall, 0.867 -> 0.804, i.e. worse. So the +7 is real and
    # unreachable: the rerank replaces the fused order and the judge re-picks after it.
    # This is the right default only for a reranker-off config, or once the reranker preserves
    # rather than replaces the order it was given (§9.3: `_ordered()` throws the scores away,
    # so there is no threshold-to-reject variant yet).
    #
    # The end-to-end half of that was taken against the checkpoint the local server had loaded
    # at the time (Qwen3.5-9B-Opus-Distilled-v2), which is not the one it serves now, and the
    # judge is a large part of that measurement. The membership and top-20 halves do not depend
    # on the judge at all, so they still hold; the DOCS-tier result holds for a stronger reason
    # than any model — `relevant_docs` never sees the ranking.
    dense_backend: str = "bge-m3"        # retrieve node: dense index / text view
    # The judge's own docstring recommends thinking (recall@15 69.3% vs 84-89%), but
    # that was measured with no reranker over the whole pool, where the judge had to
    # re-sort a noisy list itself. With qwen3-0.6b reranking and judge_top_n=20 the
    # input is already ordered: measured on the 59 gold questions that name their
    # table, thinking=False here beats the base run's thinking=True at every K
    # (MRR 0.714 vs 0.611, top-3 81.4% vs 71.2%) and costs ~15x less latency.
    #
    # Two further reasons on the current checkpoint (Qwen3.5-9B), docs §10.8. First, True is
    # not merely worse, it is inert: `enable_thinking=True` leaves `<think>` open in the
    # template, this model reasons in plain prose and never emits `</think>`, so vLLM's parser
    # buffers the whole budget and returns content=None / finish_reason=length at 256 through
    # 16384 tokens alike. Every question would get zero picks. Second, the variant that *does*
    # run -- thinking off, prompt asking for a rationale before the JSON, max_tokens 1536 --
    # measures worse: top-3 124 -> 114 over 154 gold questions against a churn floor of 1-2
    # questions, because reasoning makes the judge more selective (median picks 3 -> 2, recall
    # 0.892 -> 0.827) and F2 weights recall four times precision. Being choosier is the wrong
    # direction for this stage; `scripts/gate_retrieval_full.py --arms reasoning` is the probe.
    judge_thinking: bool = False         # retrieve node: judge enable_thinking
    frozen_fallback: bool = True         # retrieve node: use frozen cache on failure

    # Structured fact solver over data/derived/long_format.parquet. This is the
    # candidate replacement for the hard derived-selection block: the LLM emits a
    # bounded JSON plan, while DuckDB/Python resolve VAS ma_so facts and formulae.
    # It is opt-in until scored against the gold94 gate because long_format covers
    # the main BS/IS/CF statements only; notes/entity/equity still need codegen.
    #
    # False, and measured: the conservative v1 branch (selection questions only)
    # scored 44/94 against base1/base2 at 42/42 and tool lookup at 43. Paired with
    # base1 it had 4 structured-only wins (q363/q371/q387/q390) and 2 losses, so
    # it is a real but small gain. Keep opt-in until the planner/executor can stop
    # mis-specifying the remaining hard selection cases.
    structured_facts: bool = field(
        default_factory=lambda: _flag("SOLVE_STRUCTURED_FACTS", False)
    )
    # Treatment arm for the structured plan emitter only. The executor remains
    # deterministic; this just lets the model spend reasoning tokens before it
    # emits the bounded StructuredPlan schema.
    #
    # False, and measured on the 12 structured-targeted qids: with a 2048-token
    # planner budget every item failed with LengthFinishReasonError before JSON.
    # A q363 probe needed 8192 tokens to parse, and still emitted an invalid
    # selection plan (`operation=lookup`, filters over ticker/year). Keep this as
    # an explicit diagnostic flag, not a default.
    structured_facts_planner_thinking: bool = field(
        default_factory=lambda: _flag("SOLVE_STRUCTURED_FACTS_PLANNER_THINKING", False)
    )
    # ── the measured solver stack ───────────────────────────────────────────────
    # The five flags below default True as of 2026-08-21, and these numbers are why.
    # Measured over the 73 hand-labeled gold questions (`scripts/score_gold75.py`),
    # checkpoint Qwen3.5-9B, against a churn floor of 2 questions -- the 08-18 run
    # scored 54 and then 52 on a byte-identical config, so 2 is what noise alone buys:
    #
    #   all five off (codegen only)                     39/73    codegen 73
    #   + cell_locator, formula_facts,
    #     raw_table_linker, selection_facts             47/73    rtl 9, cl 7, ff 6, sf 2
    #   + raw_table_linker_planner                      52/73    rtl 17, cl 8, ff 6, sf 2
    #
    # Head to head that is 10 better / 2 worse for the first step and 6 better / 1
    # worse for the second: both clear the floor several times over.
    #
    # The gap between the last two rows is worth recording, because it is not a
    # routing decision. `capability_router` emits an identical verdict in both arms
    # (`raw_table_linker: {"enabled": true, "attempt": true}`); the linker *tries* and
    # fails closed, printing "ratio raw linker requires planner" (q355, 663, 685, 693,
    # 955) or "slot-wise top candidates are not strong enough" (q744, 754, 833, 856).
    # Turning the planner on returns all nine to the linker.
    #
    # Each of these was measured on its own and left False "while measured", which
    # added up to a default run scoring 39/73 while the good numbers lived only in
    # whichever shell had the env vars exported. That is the failure this flip fixes,
    # not any new evidence. `SOLVE_<NAME>=0` still gives every A/B its control arm.
    # Artifacts: gold73_qwen35.jsonl, gold73_qwen35_flagson.jsonl,
    # gold73_qwen35_planner.jsonl; docs/leaderboard_and_strategy_2026-08-21.md §2.
    #
    # Deterministic direct-cell arm for L1-shaped questions. It consumes the
    # semantic fields from `understand`, then verifies row/column/unit against
    # the actual tables. A low-confidence miss falls back to codegen rather than
    # silently replacing it, which is what makes it safe as a default.
    cell_locator: bool = field(default_factory=lambda: _flag("SOLVE_CELL_LOCATOR", True))
    # Deterministic non-selection formula solver over long_format facts. The
    # planner emits only a small schema; Python executes catalog formulae. Its own
    # flag so Type 2/3/4/5 coverage can be measured independently from the existing
    # selection-focused structured_facts branch. Fires on 6 of the 73 gold questions.
    formula_facts: bool = field(default_factory=lambda: _flag("SOLVE_FORMULA_FACTS", True))
    formula_facts_planner_thinking: bool = field(
        default_factory=lambda: _flag("SOLVE_FORMULA_FACTS_PLANNER_THINKING", False)
    )
    # Raw-table linker for fixed-scope arithmetic whose facts are not in
    # long_format: note tables, bank layouts without ma_so, movement tables, and
    # other detail tables. The default path is deterministic and fail-closed:
    # choose top-ranked real cell candidates only when the slot evidence is
    # strong; Python validates scope/unit and builds the pandas expression.
    # The widest of the five: 17 of the 73 gold questions, with the planner on.
    raw_table_linker: bool = field(
        default_factory=lambda: _flag("SOLVE_RAW_TABLE_LINKER", True)
    )
    # LLM semantic linker. It emits phrase constraints over bounded candidates;
    # Python still validates slot coverage, unit kind, ambiguity, and builds the
    # expression -- the model never writes a number. Worth 47 -> 52 of 73 on its
    # own: without it the deterministic path fails closed on every ratio question
    # ("ratio raw linker requires planner") and nine questions fall to codegen.
    raw_table_linker_planner: bool = field(
        default_factory=lambda: _flag("SOLVE_RAW_TABLE_LINKER_PLANNER", True)
    )
    raw_table_linker_planner_thinking: bool = field(
        default_factory=lambda: _flag("SOLVE_RAW_TABLE_LINKER_PLANNER_THINKING", False)
    )
    # Experimental candidate enrichment for ratio questions. This exposes
    # column-group candidates built from recovered raw headers. Keep disabled
    # until prompt/validation probes show broad benefit without latency regressions.
    raw_table_linker_ratio_groups: bool = field(
        default_factory=lambda: _flag("SOLVE_RAW_TABLE_LINKER_RATIO_GROUPS", False)
    )
    # Deterministic selection over the structured fact catalog. This is narrower
    # than `structured_facts`: it has no LLM planner and only runs when one axis
    # and selector/answer metrics are explicitly anchored in the question. Narrow
    # by construction, and the measurement agrees -- 2 of the 73 gold questions.
    selection_facts: bool = field(
        default_factory=lambda: _flag("SOLVE_SELECTION_FACTS", True)
    )
    # Raw-table selection for note/detail metrics that are outside the structured
    # fact catalog. The planner only chooses bounded candidate ids; Python
    # performs max/min and builds the final pandas expression.
    #
    # True for reproducibility, not for performance -- and unlike the five above that
    # is *not* a measurement, it is the absence of one. `artifacts/runs/full1012_v7.flags`
    # records `SOLVE_RAW_SELECTION_LINKER=1`, so both submissions that produced the best
    # leaderboard numbers (v7 0.3043, v8 0.3261) ran with this branch on while the code
    # default was off. A plain run then reproduced neither submission, which is the same
    # divergence the five flips above fixed.
    #
    # It stays unmeasured, and neither eval set can settle it. gold73 said 53/73 against
    # the arm's 52 -- inside the churn floor of 2 -- and that set is contaminated anyway
    # (27 of its 75 ids are hardcoded in `src`/`tests`; docs §8). The clean 120-question
    # set is uncontaminated but underpowered here: the branch fired on 30 of 1,012
    # questions, so ~4 of the 120. Measuring it needs a targeted run over the questions
    # it actually claims, not either eval set. `SOLVE_RAW_SELECTION_LINKER=0` is the
    # control arm.
    raw_selection_linker: bool = field(
        default_factory=lambda: _flag("SOLVE_RAW_SELECTION_LINKER", True)
    )

    # solve_qa pipeline (grounded codegen). Retrieval hands the solver 14 tables at
    # the median and 79 at worst, so codegen reads the head of that list.
    #
    # 3, and measured: more tables buy coverage and lose accuracy. Over the 73 gold
    # questions, raising this from 3 to 10 does put every needed table in front of
    # the model more often (37 -> 47 questions hold the full gold set) and grows the
    # prompt from 7.4k to 22.2k chars (p50) — but the share of those questions the
    # model then gets wrong rises from 38% to 53%, and the total falls 33 -> 29. The
    # extra grids are mostly near-duplicates of the right one (same company, same
    # year, different note), and the failures they cause are literal: a column name
    # taken from df2 used to index df5. Coverage is not the binding constraint;
    # telling one table from nine like it is, is.
    codegen_max_tables: int = 3          # generate_pandas: tables shown to the model
    # The paragraph above is a measurement on the gold set, which is 78% questions
    # that name one year. It does not transfer to the ones that name a period: a
    # question like "in the year KBC had the highest D/E over 2016-2020, what was
    # its interest coverage" needs five years and three slots cannot hold them, so
    # only 19% of those 196 questions have the years they need in front of the
    # model, and they answer 2/34 correct on gold against 37/60 for the rest.
    # 5 rather than 10 because the near-duplicate confusion above is real and this
    # buys almost nothing past 5 once `year_round_robin` interleaves: 42% of those
    # questions covered at 5 tables, 44% at 12, 44% for the whole pool.
    codegen_max_tables_multi_year: int = 5
    # False, and measured: the vLLM server on 8990 now serves Qwen/Qwen3.5-9B under
    # the old alias, and with enable_thinking=True it returns an empty reply at every
    # budget tried (2048/4096/8192 completion tokens, finish_reason=length, both
    # `content` and `reasoning_content` empty) — the qwen3 reasoning parser never sees
    # the block close. thinking=False answers the same prompt in 66 tokens.
    codegen_thinking: bool = False       # generate_pandas: enable_thinking
    # Add a deterministic formula/row-label block to the codegen prompt for
    # ratios whose names do not exist as table rows: D/E -> "Nợ phải trả" and
    # "Vốn chủ sở hữu", quick ratio -> current assets/inventory/current
    # liabilities, and so on. `SOLVE_METRIC_HINTS=1` is the treatment arm.
    #
    # False, and measured: the intended 22/94 questions that matched a hint did
    # not move at all (base1 1/22, metricdict 1/22, zero treatment-only wins).
    # The 94-question score was 38 against 42/42 for the two baselines, and the
    # run_graph gold subset was 9/34 against 10/34. The four total-score losses
    # were on questions that received no hint, so they are not evidence about the
    # mapping itself; the target readout is simply empty. A dictionary of formula
    # names in the prompt is not enough to make the model find the right rows.
    codegen_metric_hints: bool = field(
        default_factory=lambda: _flag("SOLVE_METRIC_HINTS", False)
    )
    # Add deterministic table profiles beside each evidence grid: label/code/
    # numeric column roles, inferred year/unit, row positions and catalog metric
    # candidates. This is prompt context only; it does not change execution.
    # Keep behind a flag until measured because extra structure can also distract
    # the model on already-easy single-cell questions.
    codegen_table_profiles: bool = field(
        default_factory=lambda: _flag("SOLVE_TABLE_PROFILES", False)
    )
    # Post-solve diagnostic only: parse the final pandas query, map every .iloc
    # cell through TableProfile, and record year/row/unit/table-shape warnings in
    # diag["profile_validate"]. It does not change answer/query/evidence. Kept
    # behind a separate flag because the first gate is precision of the warnings,
    # not score movement.
    profile_validate: bool = field(
        default_factory=lambda: _flag("SOLVE_PROFILE_VALIDATE", False)
    )
    # Expand literal `find_rows` searches for derived metric names into primitive
    # row labels. Example: a tool call for D/E searches "Tổng nợ phải trả" and
    # "Vốn chủ sở hữu" instead of only the non-existent ratio label.
    # `SOLVE_METRIC_LOOKUP=1` is the treatment arm, normally measured with
    # `SOLVE_TOOL_TURNS=3`.
    #
    # False, and measured: with tool turns set to 3 it scored 44/94 against the
    # plain tool loop at 43/94 and base1 at 42/94. The paired readout was only
    # 3 metric-lookup-only wins vs 2 tool-only wins, and 4 vs 2 against base1, so
    # this is a small noisy gain rather than a default-worthy fix. The run_graph
    # scored subset was 11/34. Keep it as an opt-in probe for derived-metric row
    # searches; the selection block still needs a different instrument.
    codegen_metric_lookup: bool = field(
        default_factory=lambda: _flag("SOLVE_METRIC_LOOKUP", False)
    )
    # Lookup turns `generate_pandas` may spend before it must answer. The 3 grids
    # above are the head of a ~106-table shortlist chosen by a reranker and a judge
    # that never read a cell; measured on the 60 cell-truth questions, 21 of the 30
    # wrong answers had the gold table on screen and still missed — most often by
    # reading a component row where the question wanted the total. `find_rows`
    # reaches the other ~103 tables by label without paying prompt budget for them.
    # 0 disables the loop and restores the single pre-tool call byte for byte.
    #
    # 0, and measured: it did not work. On the 94-question gold set the loop scored
    # 43 against 42/42 for two baseline runs whose own churn was 2 questions, so the
    # gain is inside the noise — and the pre-registered mechanism did not move. The
    # 6 questions whose gold table was cut by the table cap stayed exactly as they
    # were (4 wrong, 3 of those after spending all 3 lookups), and on the 60
    # cell-truth questions the share of queries reading the gold table (43 vs 46/43)
    # and the gold *row* (33 vs 33/30) is flat. The tool itself works — 72% of the
    # 143 lookups returned rows — but 30 of the 46 questions that exhausted the
    # budget are the argmax/median class, which searches for derived ratios
    # ("Tỷ số nợ trên vốn chủ sở hữu") that are not row labels in any table. A row
    # lookup is the wrong instrument for them. Cost was 3x latency (13s -> 40s).
    codegen_tool_turns: int = field(default_factory=lambda: _count("SOLVE_TOOL_TURNS", 0))
    # The other half of that experiment, and the one the failure above points at:
    # bucket A is 10 questions that had the right table on screen next to a wrong
    # one and picked the wrong one, which is noise, not missing reach. False shows
    # each table's header — identity, declared unit, column names, year legend —
    # and no rows, so the only cells the model can read are the ones it looked up.
    # Ignored unless `codegen_tool_turns > 0`: hiding the grids with no way to get
    # the cells back would just blind the model.
    #
    # True, and measured: hiding them is much worse, 25 of 94 against 42. Every one
    # of the 94 questions did call `find_rows`, so the loss is not a refusal to use
    # the tool — it is that rows returned one at a time are not a substitute for
    # seeing the table. On the 60 cell-truth questions the query read the gold table
    # 34 times against 46, and the gold row 23 times against 33. A label lookup
    # cannot tell a component row from the total above it, cannot show that the
    # metric is split across two sections, and returns nothing at all when the table
    # words the label differently from the question — all three of which the grid
    # answers by being visible. Bucket A is real, but the grids are not its cause.
    codegen_show_grids: bool = field(default_factory=lambda: _flag("SOLVE_SHOW_GRIDS", True))
    # Fan a selection question out over its axis — one sub-question per year or
    # per company — instead of asking for one expression that spans all of them.
    # Fires only when a surface marker is present *and* the axis has at least two
    # elements: 31 of the 94 gold questions, and the other 63 keep a byte-identical
    # path. `SOLVE_DECOMPOSE=0` is the control arm.
    #
    # The block this aims at has never risen above 3 of 34 across seven measured
    # configurations, and the reason is not retrieval: 28 of the 31 have every
    # element of their axis in the submitted `table_ids`, but only 17 still have
    # them after the `codegen_max_tables_multi_year` slice, and even those hand the
    # model a job one expression cannot hold. Pre-registered readout: activation
    # rate (expect ~30/31), whether the chosen element is the right one, and the
    # block itself against 2/3 — signal at >= 8. Guardrail: the other 60 must stay
    # >= 39 (base runs 40 and 39), and since they never enter this branch, any
    # movement there is a leak and is itself the reason to stop.
    #
    # False, and measured: the mechanism runs and the score does not move. It fired
    # on 34 of 94 and on none of the other 60, completed 30 (2 aborted with under
    # two live elements, 1 with an uncomputable filter), and scored 3 of 34 against
    # 2 and 3 for the baselines — the noise band, not the >= 8 the readout asked
    # for. The ranking half is not the problem: q363's D/E ranks (0.700 / 0.746 /
    # 0.719) are plausible, and on the 3 questions whose gold answer is the winning
    # year itself the fan-out picked the right year twice. The final step is. Of
    # the 30 completed, 9 answers are off by >= 1000x and 14 are the right order of
    # magnitude but wrong — one year of one company is still the same derived-ratio
    # codegen the baseline was already failing, so fanning out replaces one hard
    # question with N of them and then makes the N-th one the answer. Two known
    # holes, neither large enough to reach the gate: "năm nào ... lớn nhất" wants
    # the label and this always runs an answer sub-call over it (2 of 3 discarded a
    # correct winner), and a dropped degenerate element silently narrows the argmax
    # (q363 ranked 3 of 5 years). The guardrail also broke — the untouched 60 went
    # 40/39 -> 37 — but the branch fires on none of them and their queries differ
    # from base1 as often as base2's do (38 vs 42 of 60 identical); the three flips
    # are a sign inversion and two iloc slips, i.e. server nondeterminism, on a
    # churn floor of 1 measured between the baselines.
    selection_decompose: bool = field(default_factory=lambda: _flag("SOLVE_DECOMPOSE", False))
    # Tables shown to one sub-question. Wider than `codegen_max_tables` on purpose:
    # extraction splits a Vietnamese balance sheet into a TÀI SẢN table and a
    # NGUỒN VỐN table, so every ratio bridging the two halves needs both, and they
    # do not sit next to each other in retrieval's ranking — on q363 the 2019
    # NGUỒN VỐN table is 5th of 7, and with three slots the model was handed the
    # assets half plus two income tables and answered `x / x` for four of five
    # years. The measurement behind 3 (10 tables scores worse) was taken on the
    # parent prompt, where the extra tables are near-duplicates from *other years
    # and other companies*; after the fan-out the candidate set is already one
    # company and one year, so `df2` and `df5` can no longer be the same statement
    # from different years. Elements hold 8 tables at the median.
    selection_sub_tables: int = _count("SOLVE_SUB_TABLES", 6)
    max_repairs: int = 2                 # execute_and_repair: retries after an error
    # Show the repair call every query it has already tried, not just the last one.
    # `_arepair` built a fresh two-message prompt per attempt, so attempt 2 could
    # not know it was re-emitting attempt 1 — and measured on the gold94 runs it
    # does: of the questions that enter the loop, the error is byte-identical
    # across every attempt for 5 of 8 (base1), 5 of 7 (base2), 4 of 7 (fanout),
    # q381 and q396 three times over. `REPAIR_TEMPERATURE = 0.3` was added against
    # that same symptom on the reading that it was a sampling problem; the numbers
    # above are what noise alone buys, so this flag also drops the temperature to
    # 0 — with real history the prompt changes between attempts on its own.
    #
    # The ceiling is small and known in advance: only 8 of 94 questions reach the
    # repair loop at all, because it fires on an *exception* and the dominant
    # failure (right order of magnitude, wrong number) executes cleanly. So the
    # pre-registered gate is the mechanism, not the score: questions whose error
    # repeats byte-for-byte must fall from 5 to <= 1. Guardrail: total >= 40/94.
    # `SOLVE_REPAIR_HISTORY=1` is the treatment arm, 0 the control.
    repair_history: bool = field(default_factory=lambda: _flag("SOLVE_REPAIR_HISTORY", False))
    # The check costs one call on every question plus two on the ones it rejects,
    # so it is a flag: `SOLVE_VERIFY_ANSWER=0` turns the node into a pass-through
    # and gives the A/B its control arm without a second code path.
    verify_answer: bool = field(default_factory=lambda: _flag("SOLVE_VERIFY_ANSWER", True))
