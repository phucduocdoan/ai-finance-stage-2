"""Rule-classify each question into an `op` bucket to test hybrid feasibility.

Ops:
  lookup   — single cell readout
  growth   — % change year-over-year
  diff     — absolute difference (2 entities or 2 years)
  ratio    — margin / proportion (metric_a / metric_b × 100)
  sum      — sum over multiple years/items
  avg      — average over multiple years/items
  argmax   — pick year/entity with max/min value
  count    — count things
  complex  — nested / multi-step (L6-style)

Rules are ordered — first match wins.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict

import _bootstrap  # noqa: F401

from finance_qa.paths import RAW_QUESTIONS_PATH, REPORTS_DIR


QUESTIONS = RAW_QUESTIONS_PATH
OUT = REPORTS_DIR / "ops_report.md"

RULES: list[tuple[str, re.Pattern]] = [
    # Complex — nested / conditional. Check FIRST because these keywords
    # can co-occur with argmax/sum/etc.
    ("complex", re.compile(
        r"(năm mà|trong số các năm mà|"
        r"trong số các .+ (có|đạt).+ (lớn nhất|cao nhất|thấp nhất|nhỏ nhất)|"
        r"gấp bao nhiêu lần .+ trong năm đó|"
        r"trong năm đó|"
        r"trong nhóm .+ nào)",
        re.IGNORECASE,
    )),
    # Argmax / argmin — pick the entity/year
    ("argmax", re.compile(
        r"(năm nào .+ (lớn nhất|cao nhất|nhỏ nhất|thấp nhất)|"
        r"(công ty|doanh nghiệp|ngân hàng) nào .+ (lớn nhất|cao nhất|nhỏ nhất|thấp nhất)|"
        r"(lớn nhất|cao nhất|nhỏ nhất|thấp nhất) (trong|ở) (các năm|năm nào|giai đoạn)|"
        r"đứng (đầu|thứ|cuối))",
        re.IGNORECASE,
    )),
    # Growth
    ("growth", re.compile(
        r"(tăng|giảm) (bao nhiêu (phần trăm|%)|so với)|"
        r"tăng trưởng|"
        r"thay đổi bao nhiêu (phần trăm|%)|"
        r"biến động bao nhiêu (phần trăm|%)",
        re.IGNORECASE,
    )),
    # Ratio / percentage of X over Y
    ("ratio", re.compile(
        r"tỷ (suất|trọng|lệ|số)|"
        r"biên lợi nhuận|"
        r"hệ số|"
        r"\bROE\b|\bROA\b|\bROIC\b|\bEPS\b|"
        r"chiếm bao nhiêu (phần trăm|%)|"
        r"trên tổng .+ là bao nhiêu (%|phần trăm)|"
        r"gấp bao nhiêu lần|"
        r"vòng quay",
        re.IGNORECASE,
    )),
    # Average
    ("avg", re.compile(
        r"trung bình (cộng|của|hàng năm)|bình quân",
        re.IGNORECASE,
    )),
    # Sum
    ("sum", re.compile(
        r"tổng .+ (trong (giai đoạn|các năm)|từ năm .+ đến năm)|"
        r"tổng cộng .+ (trong (giai đoạn|các năm)|từ năm .+ đến năm)|"
        r"cộng dồn",
        re.IGNORECASE,
    )),
    # Diff — absolute difference between 2 items
    ("diff", re.compile(
        r"chênh lệch bao nhiêu|"
        r"nhiều hơn|ít hơn|kém|hơn|"
        r"khác biệt bao nhiêu",
        re.IGNORECASE,
    )),
    # Count
    ("count", re.compile(
        r"có bao nhiêu (công ty|người|thành viên|đơn vị|khoản|dòng|loại|nhân viên)|"
        r"số lượng .+ là bao nhiêu",
        re.IGNORECASE,
    )),
]


def classify(q: str) -> str:
    for op, pattern in RULES:
        if pattern.search(q):
            return op
    return "lookup"  # default: single-cell readout


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    questions = []
    with QUESTIONS.open(encoding="utf-8") as fp:
        for line in fp:
            if line.strip():
                questions.append(json.loads(line))

    counts: Counter[str] = Counter()
    samples: dict[str, list[dict]] = defaultdict(list)
    for q in questions:
        op = classify(q["question"])
        counts[op] += 1
        if len(samples[op]) < 5:
            samples[op].append(q)

    total = len(questions)
    lines = [
        "# Distribution of `op` across 1012 questions",
        "",
        f"Total: **{total}**",
        "",
        "| op | count | share |",
        "|---|---:|---:|",
    ]
    for op, c in counts.most_common():
        lines.append(f"| `{op}` | {c} | {100.0*c/total:.1f}% |")

    lines += ["", "## Samples per op (first 5)", ""]
    for op, _ in counts.most_common():
        lines.append(f"### `{op}`")
        for q in samples[op]:
            lines.append(f"- #{q['id']}: {q['question']}")
        lines.append("")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT}")
    print("\nDistribution:")
    for op, c in counts.most_common():
        print(f"  {op:10s} {c:4d}  {100.0*c/total:5.1f}%")


if __name__ == "__main__":
    main()
