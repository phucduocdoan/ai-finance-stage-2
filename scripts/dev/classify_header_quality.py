"""Corpus-wide 5-class header_flat quality: ok / fused / unitline / no_year / empty.

Companion measurement to `docs/retrieval_preprocessing_2026-08-21.md` §3.1's sample-based
(8,591-table) before/after table. That sample used a throwaway ~20-line flattener from the
sibling repo and was explicit that it was a stand-in, not a gate. This script defines its own
classifier (documented below) and applies it identically to v2's `header_flat` and v3's
`header_flat`, over the full 146,246-row corpus, so before/after are exactly comparable and
the classifier is auditable rather than inherited from code that no longer exists here.

Classes are mutually exclusive, checked in this order:
  1. empty     -- header_flat is blank.
  2. unitline  -- every non-empty ` | `-separated segment is itself a unit declaration
                  (`Đơn vị tính: ...`, `ĐVT: ...`); the whole field is boilerplate.
  3. fused     -- a currency/scale token is glued (no whitespace) to an adjacent
                  alphanumeric character, e.g. `2023VND`, `VNDNăm trước`,
                  `nămTriệu đồng`.
  4. no_year   -- no 4-digit year (1990-2035) anywhere in the field.
  5. ok        -- everything else: has a year, isn't unit boilerplate, isn't fused.

Also reports ok -> {no_year, empty} regressions (v2 was clean, v3 lost information) with
concrete examples, per the brief's explicit ask not to report a net number without them.

Run:
  PYTHONPATH=src .venv_bge/bin/python scripts/classify_header_quality.py
"""

import _bootstrap  # noqa: F401

import json
import re
from collections import Counter

from finance_qa.core.paths import METADATA_DIR, TABLE_METADATA_PATH


METADATA_V3_PATH = METADATA_DIR / "tables_metadata_v3.jsonl"

_YEAR_RE = re.compile(r"(?<!\d)(19|20)(\d{2})(?!\d)")
_UNITLINE_SEGMENT_RE = re.compile(r"^\s*(?:đơn\s*vị\s*t[íi]nh|đvt)\s*[:\-]?\s*[^|]*$", re.IGNORECASE)
_FUSED_RE = re.compile(
    r"[0-9A-Za-zÀ-ỹĐđ](?:vnđ|vnd|usd)"
    r"|(?:vnđ|vnd|usd)[0-9A-Za-zÀ-ỹĐđ]"
    r"|[a-zA-ZÀ-ỹĐđ](?:triệu|nghìn|tỷ)\s*đồng"
    r"|(?:triệu|nghìn|tỷ)\s*đồng[a-zA-ZÀ-ỹĐđ]",
    re.IGNORECASE,
)


def classify(header_flat: str) -> str:
    h = header_flat.strip()
    if not h:
        return "empty"
    segments = [s.strip() for s in h.split("|") if s.strip()]
    if segments and all(_UNITLINE_SEGMENT_RE.match(s) for s in segments):
        return "unitline"
    if _FUSED_RE.search(h):
        return "fused"
    y = int(_YEAR_RE.search(h).group(0)) if _YEAR_RE.search(h) else None
    if y is None or not (1990 <= y <= 2035):
        return "no_year"
    return "ok"


def load_header_flats(path) -> dict[tuple[str, int], str]:
    out = {}
    with path.open(encoding="utf-8") as fp:
        for line in fp:
            rec = json.loads(line)
            out[(rec["report_id"], rec["table_pos"])] = rec.get("header_flat", "")
    return out


def main() -> int:
    v2 = load_header_flats(TABLE_METADATA_PATH)
    v3 = load_header_flats(METADATA_V3_PATH)
    assert v2.keys() == v3.keys(), "v2/v3 key sets differ"
    n = len(v2)

    counts_v2 = Counter()
    counts_v3 = Counter()
    class_v2: dict[tuple[str, int], str] = {}
    class_v3: dict[tuple[str, int], str] = {}
    for key in v2:
        c2 = classify(v2[key])
        c3 = classify(v3[key])
        counts_v2[c2] += 1
        counts_v3[c3] += 1
        class_v2[key] = c2
        class_v3[key] = c3

    order = ["ok", "fused", "unitline", "no_year", "empty"]
    print(f"n = {n:,}\n")
    print(f"{'class':<10} {'v2 (before)':>14} {'v3 (after)':>14}")
    for c in order:
        b = counts_v2[c]
        a = counts_v3[c]
        print(f"{c:<10} {b:>7,} ({b / n:6.1%}) {a:>7,} ({a / n:6.1%})")

    regressions = Counter()
    examples: dict[str, list] = {"ok->no_year": [], "ok->empty": [], "ok->fused": [], "ok->unitline": []}
    for key in v2:
        c2, c3 = class_v2[key], class_v3[key]
        if c2 == "ok" and c3 != "ok":
            tag = f"ok->{c3}"
            regressions[tag] += 1
            if len(examples.get(tag, [])) < 5:
                examples.setdefault(tag, []).append((key, v2[key], v3[key]))

    print("\nRegressions (v2 was 'ok', v3 is not):")
    for tag in ["ok->no_year", "ok->empty", "ok->fused", "ok->unitline"]:
        print(f"  {tag}: {regressions[tag]}")
    total_ok_v2 = counts_v2["ok"]
    total_regressed = sum(regressions.values())
    print(f"  total: {total_regressed} / {total_ok_v2} v2-ok rows ({total_regressed / total_ok_v2:.1%} of v2-ok)")

    print("\nExamples:")
    for tag, exs in examples.items():
        if not exs:
            continue
        print(f"\n  -- {tag} --")
        for (rid, tpos), old, new in exs:
            print(f"    {rid}#{tpos}")
            print(f"      old: {old!r}")
            print(f"      new: {new!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
