# REPL Redesign

The current graph REPL is a fallback solver that lets the model call a single
`run_code` tool. It is broad, but it is not the right long-term production shape.

## Current Behavior

```text
question + selected tables
  -> model writes pandas code
  -> Python executes in a persistent namespace
  -> model repairs from stdout/errors
  -> final answer comes from result
```

Strengths:

- Can recover from some planner failures.
- Sees real execution errors and table outputs.
- Handles cases outside the canonical formula registry.

Problems:

- Schema text for many tables consumes too much context.
- The model must discover labels, formulas, units, and control flow at once.
- Raw pandas errors are weak repair signals.
- Free-form code makes provenance and invariant checks hard.

## Target Role

REPL should become a typed tool orchestrator:

```text
question
  -> understand
  -> retrieve/load
  -> canonical formula solver
  -> typed REPL solver
       Pydantic OperationPlan
       deterministic tool executor
       structured repair loop
  -> Python REPL escape hatch
```

The model decides intent and operation order. Python owns data access, arithmetic,
unit conversion, validation, and evidence.

## Operation Plan

```python
class SourceRef(BaseModel):
    ticker: str | None = None
    year: int | None = None
    table_var: str | None = None


class Operation(BaseModel):
    id: str
    op: Literal[
        "get_metric",
        "find_row",
        "filter_rows",
        "rank",
        "compute",
        "convert_unit",
        "round",
    ]
    args: dict[str, Any]


class OperationPlan(BaseModel):
    unsupported: bool = False
    operations: list[Operation]
    answer_ref: str
```

## Typed Tools

Start with read-only operations:

| Tool | Purpose |
|---|---|
| `get_metric(metric_id, ticker, year)` | Read canonical statement metrics. |
| `find_row(table, label_query, value_column, disambiguation=None)` | Locate note/detail rows. |
| `compute(expression, refs)` | Arithmetic over named previous results. |
| `convert_unit(value_ref, unit)` | Convert money/ratio/count units. |

Then add:

| Tool | Purpose |
|---|---|
| `filter_rows(input_ref, conditions)` | CFO positive, median filters, threshold filters. |
| `rank(input_ref, metric_ref, direction)` | Max/min selection over companies or years. |
| `round(value_ref, digits)` | Output formatting when required. |

Each tool should return:

```python
class ToolResult(BaseModel):
    id: str
    value: float | list[dict[str, Any]]
    unit_kind: Literal["money", "ratio", "count", "unknown"]
    provenance: list[EvidenceRef]
    diagnostics: list[str] = []
```

## Repair Loop

Pass structured failures back to the model:

| Error | Repair payload |
|---|---|
| `UnknownMetric` | Valid metric ids and aliases. |
| `AmbiguousRow` | Top row candidates and their source tables. |
| `MissingYear` | Available years for ticker/table. |
| `UnitMismatch` | Current unit and allowed conversions. |
| `EmptyFilter` | Candidate counts before and after each filter. |

This is more useful than asking the model to debug pandas exceptions.

## Migration Plan

1. Keep the current Python REPL unchanged as an escape hatch.
2. Add typed REPL for simple non-canonical lookup/note questions.
3. Implement `get_metric`, `find_row`, `compute`, and `convert_unit`.
4. Add filters/ranking after the simple path is green.
5. Route a small evaluated slice through typed REPL and compare against graph/current REPL.

Success metric: fewer free-form REPL calls, lower mean latency, and fewer failures caused by
schema truncation or repeated code loops.
