"""Offline/one-off enrichment scripts, not wired into `data_pipeline.py`.

Each module here has its own CLI entry point under `scripts/` and is run
by hand when its output is needed, unlike `document_text.py`,
`extract_tables.py`, `long_format.py`, and `questions.py` one directory up,
which `data_pipeline.py` imports and runs as the live pipeline.
"""
