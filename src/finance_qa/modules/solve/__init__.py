"""Turn a retrieved table context into an answer.

pipeline/ wires the LangGraph nodes (the node functions live under
pipeline/nodes/) and routes each question to a solver. solvers/ holds the
solving strategies themselves: deterministic cell lookup, raw-table linking,
selection (argmax/argmin), fact-catalog lookups, and question decomposition.
Each solver answers by either querying facts/ — a deterministic, DuckDB-backed
metric catalog — or driving codegen/, where the model writes one pandas
expression that gets executed and repaired. common/ underlies all of it:
units, intent parsing, and the shared solution schema.

The design rule behind raw-table linking and codegen, still the core of the
package: the model sees table *contents*, not a schema, and only decides
which cells to read. Anything deterministic — unit detection, unit
conversion, execution — is code.
"""
