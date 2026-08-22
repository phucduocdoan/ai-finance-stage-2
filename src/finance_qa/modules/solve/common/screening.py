"""Screening-question detector: multi-company filter-then-aggregate.

Moved here from `scripts/gate_screening_class.py` so the solver
(`agents/finance/graph.py`) and the gates (`gate_screening_class.py`,
`gate_screening_run.py`, `gate_screening_evidence.py`,
`gate_selection_reasons.py`) share one definition instead of two copies
drifting apart. `gate_screening_class.py` now re-exports `is_screening` from
here; the other three gates import it from `gate_screening_class` unchanged.

Regexes copied verbatim from the gate. See its docstring for what they miss:
a heuristic on ticker count and a handful of Vietnamese group-scoping
phrases, which undercounts questions that name companies in full
("Tập đoàn Sao Mai") without a ticker or a matching phrase.
"""
from __future__ import annotations

import re

TICKER = re.compile(r"\b[A-Z]{3}[A-Z0-9]?\b")
PHRASE = re.compile(
    r"trong nhóm|trong các doanh nghiệp|xét các|xét phân nhóm"
    r"|phân khúc doanh nghiệp|trong số các",
    re.I,
)


def is_screening(question: str) -> bool:
    return len(set(TICKER.findall(question))) >= 3 or bool(PHRASE.search(question))


__all__ = ["PHRASE", "TICKER", "is_screening"]
