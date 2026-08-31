# P11 — Submission Source-Code Cleanup Manifest (2026-08-31)

Investigation only. **Nothing in this repo was deleted or moved by this pass.** Every
recommendation below is a proposal for a human/lead-agent decision, given the ~2h
runway to the `final_submission.md` deadline (17h30 VN time, 2026-08-31).

## 1. What `sofier_AI_FINANCE_snapshot/` and `sofier_work/` actually are

**Confirmed, not a guess — a decision about these two directories was already made and
documented on 2026-08-27**, in `docs/artifact_manifest.md` ("Keep - snapshots" section)
and commit `3b600846` ("Record the decision to keep the sofier_* snapshots untouched").
That commit moved them out of "ask before deleting" into "keep, don't touch."

Structural evidence for what they are:

- Unix user `sofier` (uid 1009) exists on this machine (`getent passwd sofier` resolves).
  `sofier_AI_FINANCE_snapshot/` is still owned on-disk by `sofier:sofier`; `sofier_work/`
  has the same file set/sizes but is owned by `ding:ding` (a copy `ding` pulled in,
  mtimes run a few days later — Aug 27 vs Aug 23/24 — i.e. `sofier_work` is a slightly
  more refreshed copy of the same tree).
- Both dirs are **an entirely separate, self-contained codebase for the same
  competition** (`cuocthi.md` inside them is the identical "AI_FINANCE Text-to-Pandas"
  contest brief), with its own `src/graph.py`, `src/agent.py`, `src/node.py`,
  `src/answer/pandas_gen.py`, `src/rag/`, its own `ViFinQA/` raw-dataset copy (379M),
  and `out/` run outputs (2.7G — this is where essentially all of the 3.1G per dir
  lives; `src/` itself is only ~160K). Neither dir contains a `.git/`, so provenance
  can't be traced via history, but the architecture (LangGraph-style `graph.py`/
  `node.py`/`agent.py`) is structurally distinct from this repo's own
  `src/finance_qa/` (module/service-based, no such files) — ruling out "this is a
  backup of this repo."
- Conclusion: **a teammate's (or ding's own, under the `sofier` account) separate/
  parallel implementation attempt of the same contest**, kept around for reference/
  comparison. This is settled, not open — no need to re-ask the user.

Practical upshot: these are correctly excluded from "source code of the product" — they
are not this repo's product. They were never git-tracked and don't need to be; the
existing decision to leave them alone on disk (not delete) still stands and this task
doesn't change that.

## 2. Keep / exclude table for a submission "source code" export

| Path | Recommendation | Reason |
|---|---|---|
| `src/finance_qa/**` | **Keep** | The actual product source. |
| `scripts/*.py`, `scripts/sweep_queue.sh` (tracked, ~80 files incl. `gate_*`/`probe_*`/`diag_*`) | **Keep** | Already the repo's established convention — most diagnostic/gate scripts are git-tracked, not scratch. Not asked to be reduced; only genuinely one-off items called out separately below. |
| `scripts/probe_selection_plans.py` (untracked, new) | **Keep, `git add`** | Same genre as ~15 already-tracked `gate_*.py`/`probe_*.py` scripts (diagnostic tool with a documented docstring, run via `PYTHONPATH=... python scripts/probe_selection_plans.py`). Analyzes the *current* `selection_facts`/`StatementFactStore` architecture, not stale/deleted code — unlike the scripts already excluded by name in `.gitignore` (`audit_tier1.py`, `classify_ops.py`, `demo_option_b.py`, `prototype_repl.py`, etc., which are explicitly called out there as referencing the *deleted* planner/IR/REPL architecture). Not load-bearing for the pipeline, but not noise by this repo's own standard either. |
| `tests/**` | **Keep** | Deterministic test suite. |
| `pyproject.toml`, `README.md`, `CONTEXT.md`, `.gitignore` | **Keep** | Root project files. |
| `docs/*.md` (tracked, ~30 files: `DECISIONS.md`, `HANDOFF.md`, dated investigation notes like `answer_signatures_2026-08-22.md`, `cell_ranking_2026-08-22.md`, etc.) | **Keep** | Already the established convention in this repo. |
| `docs/feasibility/*.md` (p1–p9, untracked) | **Keep** | Same genre as the already-tracked dated docs above — dense engineering/feasibility analysis, not scratch notes. `p8_submission_deliverables_gap.md` and `p9_hardcoded_query_compliance_audit.md` in particular directly document compliance with `final_submission.md`'s own rules (no-hardcoded-result audit, deliverables checklist) — genuine evidence of rigor an organizer would want, not noise. |
| `docs/gold73_23fail_rca_2026-08-29.md`, `docs/regression_bisect_2026-08-30.md` (untracked) | **Keep** | Same pattern as already-tracked docs like `docs/multiyear_failures_2026-08-22.md` / `docs/shortlist_gap_2026-08-22.md` — root-cause-analysis writeups tied to specific commits, consistent with existing convention, not a new kind of clutter. |
| `docs/readability_review/*.md` (untracked, 7 files) | **Keep, lower priority** | Internal code-readability audit notes (per-module: `agent_graph.md`, `core_tools.md`, etc.). Useful engineering-quality evidence but the most "internal" of the untracked docs; safe to drop first if the docs folder needs trimming for size/noise, but not actively harmful to include. |
| `docs/competition/*.pdf`, `docs/competition/data_source.txt`, `docs/competition/submission_rule.txt` | **Keep (already tracked convention)**, exclude the *new* untracked duplicate PDF from the zip | `.gitignore` already special-cases `docs/competition/*.pdf` as trackable (global `*.pdf` rule is overridden there). The new untracked `docs/competition/_2026__AIGuru___Finance_Tabular_QA 1.pdf` looks like a copy of competition reference material, not source code — fine either way, but not required in a "mã nguồn" zip. |
| `final_submission.md` (repo root, untracked) | **Exclude from source zip** | This is the organizers' own instructions text pasted into the repo as a working note, not source code or product documentation. Keep it in the working tree for reference; don't ship it as "our source code." |
| `sofier_AI_FINANCE_snapshot/`, `sofier_work/` | **Exclude** | Not this product's source — see §1. Already never git-tracked. |
| `artifacts/**` (tracked and untracked alike — `audits/`, `eval_clean/`, `l3_pair/`, `label_calib/`, `relabel/`, `reports/`, `runs/`, `runs_archive_2026-08-27.tar.gz`) | **Exclude** | Debug/eval run output, not source code, regardless of git-tracked status. `artifacts/runs/` and `output/` are already `.gitignore`d as "regeneratable, large"; the fact that some `artifacts/` subfolders (`audits/`, `eval_clean/`, etc.) are individually tracked is a historical accident of the team keeping specific analysis snapshots, not a signal they belong in a product-source zip. The three newly untracked files (`artifacts/audits/gold73_23fail_detail.json`, `artifacts/eval_clean/multiyear_failures.json`, `artifacts/eval_clean/unit_blast.json`) are the same kind of debug output as their already-tracked siblings — exclude them the same way. |
| `data/`, `ViFinQA/`, `output/`, `.venv_bge/`, `.v1arm/`, `.lavish/`, `.pytest_cache/`, `__pycache__/` | **Exclude** | Already `.gitignore`d — data/venv/build-cache/rendered-report scratch, not source. |
| Root stray files: `_2026__R2AI___Stage2___Finance_Tabular_QA___Aug21 (1).pdf`, the two `.jpg`s, `"SKILL (3).md"` | **Exclude** | Already handled by existing `.gitignore` rules (global `*.pdf`/`*.jpg` excludes, and an explicit named-exclusion comment for `SKILL (3).md`: "unrelated file that ended up at repo root, not part of this project"). No action needed — these were never going to end up in a tracked-files export. |

Currently modified-but-uncommitted tracked files (`README.md`, `pyproject.toml`,
`scripts/build_submission.py`, `src/finance_qa/modules/solve/solvers/raw_table_linking/request.py`)
are active in-progress work, not cleanup targets — they just need to be committed
before packaging so the export reflects the final state.

## 3. Recommended export command (for the lead to review and run — not executed here)

The safest and simplest option is **`git archive` scoped to the source-relevant
top-level paths**, since it automatically includes only git-tracked files (skips all
untracked scratch/debug output with zero risk of a stray file leaking in) and, by
listing paths explicitly, also skips the tracked-but-not-source `artifacts/` folder
entirely — matching the scope `docs/feasibility/p8_submission_deliverables_gap.md`
(item 8) already proposed on 2026-08-31.

```bash
# 1. commit or stash the in-progress tracked-file edits and `git add` the two
#    "keep" items called out above (do this deliberately, not blindly):
#      scripts/probe_selection_plans.py
#      docs/feasibility/*.md docs/gold73_23fail_rca_2026-08-29.md \
#        docs/regression_bisect_2026-08-30.md docs/readability_review/*.md
#      (this manifest itself: docs/feasibility/p11_submission_cleanup_manifest.md)
#
# 2. produce the source-code archive from the tracked tree only:
git archive --format=zip -o /tmp/submission_source.zip HEAD -- \
  src scripts tests pyproject.toml README.md CONTEXT.md docs

# 3. sanity check what actually went in before submitting:
unzip -l /tmp/submission_source.zip | tail -5
unzip -l /tmp/submission_source.zip | grep -i sofier   # must be empty
unzip -l /tmp/submission_source.zip | grep "artifacts/" # must be empty
```

If step 1's `git add` for the new docs/scripts is skipped or deferred past the
deadline, `git archive HEAD` will simply omit them (since it only ever includes
committed content) — safe by default, just means those files won't be in the zip
until they're committed. An alternative that doesn't require committing first is a
plain `zip`/`tar` over the same explicit path list run directly against the working
tree, but that loses the "tracked-only" safety net and would need the exclusions in
§2 applied by hand (`-x 'artifacts/*' -x 'sofier_*' ...`) — `git archive` is
recommended over it for that reason.
