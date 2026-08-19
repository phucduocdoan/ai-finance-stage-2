# Context

Glossary for ViFinQA Stage 2. Terms only — no implementation detail, no measurements, no
decisions. Those live in `docs/HANDOFF.md` and `docs/DECISIONS.md`.

## Graph

Ambiguous on its own, and the ambiguity has already caused one wrong conclusion. Two different
answer flows have been called "the graph", split by 12/08:

- **Router graph** (through 11/08) — routed each question to one of three solvers
  (lookup / formula / repl), each with its own planner and repair stack.
- **Codegen graph** (from 12/08) — one path for every question, one LLM call writing one pandas
  expression. The router and its solvers are deleted.

Always say which one. A run file tells you: every record carries a `solver` field, and it reads
`codegen` for the codegen graph and `lookup`/`formula`/`repl` for the router graph.

**Solver** is a vestigial term. Under the codegen graph there is exactly one, so the field is a
provenance marker, not a choice the system makes.

## Run vs Submission

- **Run** — one JSONL, one record per question, written by the batch driver. Scoring happens
  here.
- **Submission** — a packaged zip built from a run, uploaded to the leaderboard.

Not interchangeable. A run can be scored freely against local gold; a submission costs one of a
fixed number of leaderboard attempts. "We ran X" never implies "we submitted X" — assuming it
did is what produced the mistaken belief that the codegen graph had been scored on the
leaderboard when only the router graph ever had.

## Gold Set

**Gold** means a human-verified answer, never a model-produced one.

- **The honest gold set** — the 73 scorable questions in `data/eval/`, held to confidence
  `medium` or better and deliberately disjoint from the question band the router graph was
  tuned against. This is the only local yardstick that carries an authoritative answer.
- **Gold table** — the specific table a human read to produce a gold answer. Present on 60 of
  the 73, and the reason a miss can be blamed on a named node instead of the system at large.

A **frozen fallback** is not gold: it is a cached result from an older run, reused when
retrieval fails.

## Question Shape

How many distinct cells an answer requires, and how they are spread. Reconstructed from
`multi_year` and `multi_company` on the enriched questions, giving four shapes: single cell,
temporal (one company, several years), cross-company (one year, several companies), and
multi-year × multi-company.

The informal **L1–L6** labels used in discussion are a finer cut of the same idea. They are not
a field on any record and nothing computes them — do not cite an L-number as if it were
measured data.

## Selection Class

A question whose answer is not a cell but the result of *choosing* which cell to read: compute a
ratio across several years or several companies, pick one by argmax / argmin / median, then read
or compute a second quantity there. "In the year KBC had the highest D/E over 2016–2020, what was
its interest coverage ratio?"

Distinct from **question shape** above, which counts how many cells an answer touches. A
selection question touches many cells, but the defining property is that the target cell is
*unknown until an intermediate computation resolves it*. Retrieval cannot be told which report to
fetch, because which report is the answer to the first step.

Identified by surface markers in the question text (`cao nhất`, `thấp nhất`, `trung vị`, `vượt`,
`nhiều nhất`, `ít nhất`). This is a lower bound, not a classifier — the marker is evidence, not a
field on any record.

## Understand vs Solve Plan

**Understand** is the coarse question-intent node. Its job is to recover retrieval-critical
scope: tickers, years, report scope, broad metric, operation, unit hint, and answer shape. It is
not a full reasoning plan.

**Solve plan** is the structured semantic plan needed by a deterministic executor. It must say
which candidates exist, what to select by, what filters apply, what answer expression to compute,
whether the answer is at the selected year/company or an offset, and what output unit is wanted.
This is the right place for Pydantic schema growth; do not push these semantics into regexes over
the raw question.

## Fact Layer

A **fact layer** is a normalized table that lets the system answer without showing raw CSV grids
to the LLM. The current one is `long_format.parquet`, also called `statement_facts` in the
structured solver. It covers clean main-statement facts from balance sheet, income statement, and
cash-flow tables that have VAS `Mã số` rows.

Fact layers are scoped, not universal. If a question needs notes, entity tables, bank-specific
layouts, or metrics outside the catalog, the structured path should fail validation and fall back
to raw-table codegen. Future coverage should be added as new fact layers (`note_facts`,
`bank_facts`, etc.) only when failure taxonomy shows the group is worth normalizing.

## Raw Table Linking

**Raw table linking** means selecting real CSV cells after retrieval has already fixed the report
scope. The linker builds bounded candidates from raw tables, exposes row labels, columns, units,
and compact table/note context, then either chooses candidate ids directly or fails closed.

The LLM's role in this path is semantic linking: map question wording to row/table wording and
choose from existing candidate ids. It does not write pandas or invent normalized facts. Python
validates slot coverage, candidate order, company/year/report scope, unit compatibility, and then
builds the submitted expression.

**Linking context** is the compact text attached to a table or candidate for this semantic match:
section title, note title, flattened headers, page-level OCR hints, first-column labels, and
profiled row labels. It is evidence for choosing among similar raw tables, not a complete copy of
the report.

**Raw selection** is raw table linking where the answer depends on an intermediate max/min choice:
for example choose the year whose note-table value is largest, then return that year or a value
from that winning slot. It differs from fixed-scope raw linking because every slot must be linked
before ranking. Single physical cells and component/group sums are separate candidate types.
Component/group sums must be built from bounded real-cell candidates and selected deterministically
per slot, or the branch fails closed to codegen.

## Detector

A signal in a run record that identifies a wrong answer **without consulting gold**. What makes
one useful is that it can be counted over all 1,012 questions, where gold covers 73.

Detector coverage is not accuracy. A detector says an answer is wrong; it does not say which
node made it wrong. Attributing a failure to a node requires the gold table.

## Score

Three unrelated numbers get called "the score". Name which one:

- **Gold accuracy** — fraction of the 73 gold questions matched within 1% relative tolerance.
  Local, free, repeatable.
- **Leaderboard answer accuracy** — the competition's number over all 1,012 questions. Costs a
  submission attempt.
- **Retrieval metrics** — the leaderboard's separate document/table F2 and MRR scores. High
  document-tier numbers coexist with low answer accuracy; they are not a proxy for it.
