"""Grounded pandas code generation: read the grids, write one query, run it.

Two steps, after retrieval:
    retrieve (existing) -> generate_pandas -> execute_and_repair

There is no selection step. `generate_pandas` is handed the head of retrieval's
ranking and shows the model every one of those tables in full; picking among them
is part of writing the query, because that is the only point where the contents
are visible. Slicing to 3 tables beforehand was measured worse — see the pipeline
docstring.

The design rule for the whole package: the model sees table *contents*, not a
schema, and it only decides which cells to read. Anything deterministic — unit
detection, unit conversion, execution — is code.
"""
from finance_qa.modules.solve.codegen import PandasSolution, agenerate
from finance_qa.modules.solve.execute import aexecute

__all__ = ["PandasSolution", "aexecute", "agenerate"]
