"""Probe: recover `note_title` by walking a report's OCR headings in document order.

Throwaway measurement, not a pipeline step. Validates the rule against the
reports that already *have* titles before any staging artifact is built.

    PYTHONPATH=src .venv_bge/bin/python scripts/probe_note_title.py
"""

from __future__ import annotations

import collections
import json
import re
import sys
import unicodedata

from finance_qa.core.paths import TABLE_METADATA_PATH
from finance_qa.modules.data.preprocessing.offline.metadata_enrichment import (
    TABLE_PATTERN,
    report_id_to_ocr_path,
)

# A note heading is a bare number at the start of a line followed by a title on
# the same line: "19 CÁC KHOẢN PHẢI TRẢ VÀ CÔNG NỢ KHÁC", "14 Phải trả người bán".
HEADING = re.compile(r"^\s*(\d{1,2})\s*[.)]?\s+(\S.*)$")
# Running page furniture, repeated verbatim on every page of the notes. Left in,
# it would overwrite the real heading on every page break.
FURNITURE = re.compile(
    r"^(?:mau\s+so|thuyet\s+minh\s+bao\s+cao|cho\s+nam\s+tai\s+chinh|"
    r"cong\s+ty|ngan\s+hang|tap\s+doan|tong\s+cong\s+ty|ban\s+hanh\s+theo|"
    r"cac\s+thuyet\s+minh|don\s+vi|muc\s+luc|bang\s+can\s+doi|bao\s+cao)"
)
CONT = re.compile(r"\s*\(?\s*(?:ti[eế]p\s*theo|ti[eế]p|continued)\s*\)?\s*$", re.I)
LETTERS = re.compile(r"[A-Za-zÀ-ỹĐđ]")
PAGE_MARKER = re.compile(r"^=====\s*PAGE\s+\d+\s*=====\s*$")

MIN_TITLE_LEN = 6
MAX_TITLE_LEN = 200
MAX_NOTE_ID = 60


def norm(text: object) -> str:
    d = unicodedata.normalize("NFD", str(text)).lower().replace("đ", "d")
    d = "".join(c for c in d if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", d).strip()


def is_heading(line: str) -> tuple[str, str] | None:
    m = HEADING.match(line)
    if not m:
        return None
    note_id, title = m.group(1), CONT.sub("", m.group(2)).strip(" .:-*()")
    if int(note_id) > MAX_NOTE_ID:
        return None
    if not (MIN_TITLE_LEN <= len(title) <= MAX_TITLE_LEN):
        return None
    # "1 2 3 4 5 ..." page rails, and any title that is mostly not words.
    if len(LETTERS.findall(title)) < MIN_TITLE_LEN:
        return None
    if FURNITURE.match(norm(title)):
        return None
    return note_id, title


def walk(report_text: str) -> dict[int, tuple[str, str]]:
    """`table_pos` (1-based) -> the (note_id, note_title) heading in force there."""
    marked = TABLE_PATTERN.sub("\n\x00TABLE\x00\n", report_text)
    out: dict[int, tuple[str, str]] = {}
    pos = 0
    current = ("", "")
    for line in marked.splitlines():
        line = line.strip()
        if not line or PAGE_MARKER.match(line):
            continue
        if line == "\x00TABLE\x00":
            pos += 1
            out[pos] = current
            continue
        hit = is_heading(line)
        if hit:
            current = hit
    return out


def main() -> int:
    per: dict[str, list[dict]] = collections.defaultdict(list)
    with TABLE_METADATA_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            if rec.get("statement_type") == "note":
                per[rec["report_id"]].append(rec)

    stride = int(sys.argv[1]) if len(sys.argv) > 1 else 37
    titled = sorted(r for r in per if any((x.get("note_title") or "").strip() for x in per[r]))
    dead = sorted(r for r in per if not any((x.get("note_title") or "").strip() for x in per[r]))

    exact = contained = disagree = blank = 0
    misses: list[tuple] = []
    for rid in titled[::stride]:
        path = report_id_to_ocr_path(rid)
        if not path.exists():
            continue
        headings = walk(path.read_text(encoding="utf-8", errors="replace"))
        for rec in per[rid]:
            gold = (rec.get("note_title") or "").strip()
            if not gold:
                continue
            _, got = headings.get(rec["table_pos"], ("", ""))
            g, t = norm(gold), norm(got)
            if not t:
                blank += 1
            elif g == t:
                exact += 1
            elif g in t or t in g:
                contained += 1
            else:
                disagree += 1
                if len(misses) < 12:
                    misses.append((rid, rec["table_pos"], gold, got))
    total = exact + contained + disagree + blank
    print(f"validation on reports that already have titles: {total:,} note tables")
    print(f"  exact (normalized)      : {exact:,} ({exact/total*100:.1f}%)")
    print(f"  one contains the other  : {contained:,} ({contained/total*100:.1f}%)")
    print(f"  disagree                : {disagree:,} ({disagree/total*100:.1f}%)")
    print(f"  rule found no heading   : {blank:,} ({blank/total*100:.1f}%)")
    for rid, tp, gold, got in misses:
        print(f"    {rid}|{tp}\n      v1  : {gold[:100]!r}\n      rule: {got[:100]!r}")

    filled = n_dead = 0
    for rid in dead:
        path = report_id_to_ocr_path(rid)
        if not path.exists():
            continue
        headings = walk(path.read_text(encoding="utf-8", errors="replace"))
        for rec in per[rid]:
            n_dead += 1
            if headings.get(rec["table_pos"], ("", ""))[1]:
                filled += 1
    print(f"\nthe {len(dead)} reports with no titles at all: {n_dead:,} note tables")
    print(f"  rule recovers a title for: {filled:,} ({filled/n_dead*100:.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
