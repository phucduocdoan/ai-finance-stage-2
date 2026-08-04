"""Audit Tier 1 (rule-based) enrichment fields.

Outputs:
- artifacts/reports/audit_tier1.md: summary report
- artifacts/reports/audit_tier1_sample.jsonl: manual-verify sample
- artifacts/reports/audit_tier1_violations.jsonl: invariant violations

Checks:
  A. Automated invariants (no manual review):
     - Per (report_id, doc_type): ≤1 BS assets, ≤1 BS liab-equity, ≤1 IS main, ≤1 CF main
     - note_id monotonicity within report (should not decrease abruptly)
     - note_id_inherited=True → previous non-inherited note_id equals inherited note_id
  B. Coverage / distribution stats.
  C. Stratified sample for human-eyeball verification.
  D. Failure pattern mining (statement_type=unknown top OCR patterns, empty first_col_labels causes).
"""

from __future__ import annotations

import json
import random
import re
from collections import Counter, defaultdict

import _bootstrap  # noqa: F401

from finance_qa.paths import REPORTS_DIR, TABLE_METADATA_PATH


V2_JSONL = TABLE_METADATA_PATH
REPORT_MD = REPORTS_DIR / "audit_tier1.md"
SAMPLE_JSONL = REPORTS_DIR / "audit_tier1_sample.jsonl"
VIOL_JSONL = REPORTS_DIR / "audit_tier1_violations.jsonl"

MAIN_STMTS = {"balance_sheet", "income_statement", "cash_flow"}
SEED = 42


def load_records() -> list[dict]:
    rows: list[dict] = []
    with V2_JSONL.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def group_by_report(records: list[dict]) -> dict[tuple, list[dict]]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in records:
        key = (r.get("report_id", ""), r.get("doc_type", ""))
        groups[key].append(r)
    for k in groups:
        groups[k].sort(key=lambda x: x.get("table_pos", 0))
    return groups


# ---------- A. INVARIANT CHECKS ----------

def check_duplicate_main_statements(groups) -> list[dict]:
    """Each (report_id, doc_type) should have at most 1 of each main-statement kind."""
    violations = []
    for (report_id, doc_type), tables in groups.items():
        by_type = Counter()
        for t in tables:
            st = t.get("statement_type", "")
            subt = t.get("statement_subtype", "")
            if st == "balance_sheet":
                key = f"bs::{subt or '?'}"
            elif st in MAIN_STMTS:
                key = st
            else:
                continue
            by_type[key] += 1

        for key, cnt in by_type.items():
            if cnt > 1:
                offending = [
                    (t["table_pos"], t["page_number"], t.get("mau_tag", ""),
                     t.get("statement_subtype", ""), t.get("header_preview", "")[:60])
                    for t in tables
                    if (t.get("statement_type") == "balance_sheet"
                        and f"bs::{t.get('statement_subtype') or '?'}" == key)
                    or t.get("statement_type") == key
                ]
                violations.append({
                    "kind": "duplicate_main_statement",
                    "report_id": report_id,
                    "doc_type": doc_type,
                    "statement_kind": key,
                    "count": cnt,
                    "offending": offending,
                })
    return violations


def check_inheritance_correctness(groups) -> dict:
    """For each inherited note_id, verify the anchor note_id matches."""
    total_inherited = 0
    inherit_ok = 0
    inherit_bad = 0
    bad_samples = []

    for (report_id, doc_type), tables in groups.items():
        # walk in table_pos order; track last explicit (non-inherited) note_id
        last_explicit = ""
        for t in tables:
            st = t.get("statement_type")
            note_id = t.get("note_id", "")
            inh = t.get("note_id_inherited", False)
            if st == "note" and note_id and not inh:
                last_explicit = note_id
            elif st in MAIN_STMTS:
                last_explicit = ""
            if inh:
                total_inherited += 1
                if note_id == last_explicit and last_explicit:
                    inherit_ok += 1
                else:
                    inherit_bad += 1
                    if len(bad_samples) < 20:
                        bad_samples.append({
                            "report_id": report_id,
                            "doc_type": doc_type,
                            "table_pos": t["table_pos"],
                            "page": t["page_number"],
                            "inherited_note_id": note_id,
                            "last_explicit_before": last_explicit,
                        })
    return {
        "total_inherited": total_inherited,
        "consistent": inherit_ok,
        "inconsistent": inherit_bad,
        "bad_samples": bad_samples,
    }


def check_note_id_monotonicity(groups) -> dict:
    """note_id should be non-decreasing within a report block of note-tables.
    Big drops signal bogus regex matches (e.g. '1.' from prose)."""
    weird_drops = []
    for (report_id, doc_type), tables in groups.items():
        prev = 0
        for t in tables:
            if t.get("statement_type") != "note":
                prev = 0
                continue
            nid = t.get("note_id", "")
            try:
                cur = int(nid)
            except (ValueError, TypeError):
                continue
            if prev and cur < prev - 5:  # drop of >5 = suspicious
                weird_drops.append({
                    "report_id": report_id,
                    "doc_type": doc_type,
                    "table_pos": t["table_pos"],
                    "page": t["page_number"],
                    "note_id": nid,
                    "prev": prev,
                    "inherited": t.get("note_id_inherited", False),
                    "note_title": t.get("note_title", "")[:80],
                })
            prev = cur
    return {"count": len(weird_drops), "samples": weird_drops[:20]}


# ---------- B. COVERAGE ----------

def coverage_stats(records: list[dict]) -> dict:
    n = len(records)
    st_counter = Counter(r.get("statement_type", "") for r in records)
    doc_counter = Counter(r.get("doc_type", "") for r in records)

    have_note_id = sum(1 for r in records if r.get("note_id"))
    inherited = sum(1 for r in records if r.get("note_id_inherited"))
    have_mau = sum(1 for r in records if r.get("mau_tag"))
    have_ma_so = sum(1 for r in records if r.get("has_ma_so_column"))
    have_labels = sum(1 for r in records if r.get("first_col_labels"))
    have_context = sum(1 for r in records if r.get("context_page_text"))
    empty_labels = n - have_labels

    return {
        "n_total": n,
        "statement_type": st_counter,
        "doc_type": doc_counter,
        "have_note_id": have_note_id,
        "inherited": inherited,
        "have_mau_tag": have_mau,
        "have_ma_so": have_ma_so,
        "empty_first_col_labels": empty_labels,
        "empty_context_page_text": n - have_context,
    }


# ---------- C. STRATIFIED SAMPLE ----------

def stratified_sample(records, per_cell=3, seed=SEED) -> list[dict]:
    """Sample per_cell tables for each (doc_type, statement_type) cell."""
    random.seed(seed)
    buckets: dict[tuple, list[dict]] = defaultdict(list)
    for r in records:
        key = (r.get("doc_type", ""), r.get("statement_type", ""))
        buckets[key].append(r)
    sample = []
    for key, items in sorted(buckets.items()):
        picked = random.sample(items, min(per_cell, len(items)))
        for p in picked:
            sample.append({"_stratum": f"{key[0]}|{key[1]}", **p})
    return sample


def inheritance_sample(records, n=30, seed=SEED) -> list[dict]:
    random.seed(seed + 1)
    inh = [r for r in records if r.get("note_id_inherited")]
    return random.sample(inh, min(n, len(inh)))


# ---------- D. FAILURE PATTERNS ----------

def unknown_type_patterns(records) -> Counter:
    """Look at header_preview and first_col_labels[0] for unknown-typed tables."""
    unknowns = [r for r in records if r.get("statement_type") == "unknown"]
    keys = Counter()
    for r in unknowns:
        hp = (r.get("header_preview") or "").strip()[:40]
        fcl = r.get("first_col_labels") or []
        first = (fcl[0] if fcl else "").strip()[:40]
        keys[f"hdr='{hp}' | fcl0='{first}'"] += 1
    return keys


def empty_labels_causes(records) -> dict:
    empties = [r for r in records if not r.get("first_col_labels")]
    by_type = Counter(r.get("statement_type", "") for r in empties)
    by_doc = Counter(r.get("doc_type", "") for r in empties)
    return {"by_statement_type": by_type, "by_doc_type": by_doc,
            "n": len(empties)}


# ---------- REPORT ----------

def make_slim(rec: dict) -> dict:
    """Slim view for manual eyeballing."""
    fcl = rec.get("first_col_labels") or []
    return {
        "report_id": rec.get("report_id"),
        "table_pos": rec.get("table_pos"),
        "page": rec.get("page_number"),
        "csv_path": rec.get("csv_path"),
        "doc_type": rec.get("doc_type"),
        "statement_type": rec.get("statement_type"),
        "statement_subtype": rec.get("statement_subtype"),
        "mau_tag": rec.get("mau_tag"),
        "note_id": rec.get("note_id"),
        "note_id_inherited": rec.get("note_id_inherited"),
        "note_title": rec.get("note_title"),
        "label_col": rec.get("label_col"),
        "header_preview": rec.get("header_preview"),
        "first_col_labels_preview": fcl[:5],
        "stratum": rec.get("_stratum"),
    }


def fmt_counter(c: Counter, top=20) -> str:
    total = sum(c.values()) or 1
    lines = ["| Key | Count | Pct |", "|---|---:|---:|"]
    for k, v in c.most_common(top):
        pct = 100.0 * v / total
        lines.append(f"| `{k}` | {v:,} | {pct:.1f}% |")
    return "\n".join(lines)


def main():
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    print("Loading v2 metadata...")
    records = load_records()
    print(f"  {len(records):,} rows")

    print("Grouping by report...")
    groups = group_by_report(records)
    print(f"  {len(groups):,} (report_id, doc_type) groups")

    print("Checking invariants...")
    dup_viol = check_duplicate_main_statements(groups)
    inh_stat = check_inheritance_correctness(groups)
    mono_stat = check_note_id_monotonicity(groups)

    print("Coverage stats...")
    cov = coverage_stats(records)

    print("Sampling for manual verify...")
    sample = stratified_sample(records, per_cell=3)
    inh_spot = inheritance_sample(records, n=30)
    print(f"  {len(sample)} stratified + {len(inh_spot)} inheritance spot-checks")

    print("Failure pattern mining...")
    unk_patterns = unknown_type_patterns(records)
    empty_causes = empty_labels_causes(records)

    # ---- write violation jsonl
    with VIOL_JSONL.open("w") as f:
        for v in dup_viol:
            f.write(json.dumps(v, ensure_ascii=False) + "\n")
        for v in mono_stat["samples"]:
            f.write(json.dumps({"kind": "note_id_drop", **v},
                               ensure_ascii=False) + "\n")
        for v in inh_stat["bad_samples"]:
            f.write(json.dumps({"kind": "inherit_inconsistent", **v},
                               ensure_ascii=False) + "\n")

    # ---- write sample jsonl
    with SAMPLE_JSONL.open("w") as f:
        for r in sample:
            f.write(json.dumps(make_slim(r), ensure_ascii=False) + "\n")
        for r in inh_spot:
            slim = make_slim(r)
            slim["stratum"] = "INHERIT_SPOTCHECK"
            f.write(json.dumps(slim, ensure_ascii=False) + "\n")

    # ---- write report md
    n = cov["n_total"]
    lines: list[str] = []
    lines.append("# Audit Tier 1 (rule-based fields)\n")
    lines.append(f"- Rows: **{n:,}**")
    lines.append(f"- Groups (report_id × doc_type): **{len(groups):,}**\n")

    lines.append("## A. Invariant violations (automated)\n")
    lines.append(f"### Duplicate main statements per report")
    lines.append(f"- Total groups with ≥1 duplicate: **{len(dup_viol):,}**")
    if dup_viol:
        by_kind = Counter(v["statement_kind"] for v in dup_viol)
        lines.append("")
        lines.append("| statement_kind | Groups affected |")
        lines.append("|---|---:|")
        for k, c in by_kind.most_common():
            lines.append(f"| `{k}` | {c:,} |")
        lines.append("")
        lines.append("Sample 5 offenders:")
        for v in dup_viol[:5]:
            lines.append(f"- **{v['report_id']}** / `{v['doc_type']}` / `{v['statement_kind']}` (×{v['count']})")
            for pos, pg, mau, sub, hp in v["offending"][:4]:
                lines.append(f"  - pos={pos} page={pg} mau=`{mau}` sub=`{sub}` hdr=`{hp}`")
    lines.append("")

    lines.append(f"### Inheritance consistency")
    total_inh = inh_stat["total_inherited"]
    if total_inh:
        pct_ok = 100.0 * inh_stat["consistent"] / total_inh
    else:
        pct_ok = 0.0
    lines.append(f"- Total inherited tables: **{total_inh:,}**")
    lines.append(f"- Consistent with prior anchor: **{inh_stat['consistent']:,}** ({pct_ok:.2f}%)")
    lines.append(f"- Inconsistent: **{inh_stat['inconsistent']:,}**")
    if inh_stat["bad_samples"]:
        lines.append("\nInconsistent samples:")
        for s in inh_stat["bad_samples"][:5]:
            lines.append(
                f"- `{s['report_id']}` pos={s['table_pos']} page={s['page']} "
                f"inherited=`{s['inherited_note_id']}` prev=`{s['last_explicit_before']}`"
            )
    lines.append("")

    lines.append(f"### note_id monotonicity")
    lines.append(f"- Suspicious drops (>5) within a note block: **{mono_stat['count']:,}**")
    for s in mono_stat["samples"][:5]:
        lines.append(
            f"- `{s['report_id']}` pos={s['table_pos']} page={s['page']} "
            f"note=`{s['note_id']}` prev=`{s['prev']}` inh={s['inherited']} title=`{s['note_title']}`"
        )
    lines.append("")

    lines.append("## B. Coverage\n")
    lines.append(f"- Have `mau_tag`: **{cov['have_mau_tag']:,}** ({100*cov['have_mau_tag']/n:.1f}%)")
    lines.append(f"- Have `note_id`: **{cov['have_note_id']:,}** ({100*cov['have_note_id']/n:.1f}%)")
    lines.append(f"- Inherited `note_id`: **{cov['inherited']:,}** ({100*cov['inherited']/n:.1f}%)")
    lines.append(f"- Have `has_ma_so_column`=True: **{cov['have_ma_so']:,}** ({100*cov['have_ma_so']/n:.1f}%)")
    lines.append(f"- Empty `first_col_labels`: **{cov['empty_first_col_labels']:,}** ({100*cov['empty_first_col_labels']/n:.1f}%)")
    lines.append(f"- Empty `context_page_text`: **{cov['empty_context_page_text']:,}** ({100*cov['empty_context_page_text']/n:.1f}%)\n")

    lines.append("### statement_type distribution\n")
    lines.append(fmt_counter(cov["statement_type"]))
    lines.append("\n### doc_type distribution\n")
    lines.append(fmt_counter(cov["doc_type"]))
    lines.append("")

    lines.append("## C. Failure patterns\n")
    lines.append(f"### Top `unknown` header/first-col patterns (top 20)\n")
    lines.append(fmt_counter(unk_patterns, top=20))
    lines.append("")

    lines.append(f"### Empty `first_col_labels` — {empty_causes['n']:,} tables\n")
    lines.append("By statement_type:\n")
    lines.append(fmt_counter(empty_causes["by_statement_type"], top=10))
    lines.append("\nBy doc_type:\n")
    lines.append(fmt_counter(empty_causes["by_doc_type"], top=10))
    lines.append("")

    lines.append("## D. Manual-verify sample\n")
    lines.append(f"- Stratified (per doc_type × statement_type × 3): **{len(sample)}** tables → `audit_tier1_sample.jsonl`")
    lines.append(f"- Inheritance spot-check: **{len(inh_spot)}** tables (also in sample file, stratum=`INHERIT_SPOTCHECK`)")
    lines.append("")
    lines.append("Open each `csv_path` and verify that:")
    lines.append("- `statement_type` matches what the CSV actually is")
    lines.append("- `note_id`/`note_title` matches the section heading on that page")
    lines.append("- `label_col` picks the column containing text labels (not numbers)")
    lines.append("")
    lines.append(f"Violations file: `audit_tier1_violations.jsonl`")

    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {REPORT_MD}")
    print(f"Wrote {SAMPLE_JSONL} ({len(sample)+len(inh_spot)} rows)")
    print(f"Wrote {VIOL_JSONL}")


if __name__ == "__main__":
    main()
