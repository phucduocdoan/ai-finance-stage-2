"""Recover `statement_type` for the rows tables_metadata_v2 still leaves "unknown".

Grounded against the real corpus (146,246 rows, see artifacts/audits) before
writing anything here:
- 2,669 rows carry statement_type == "unknown".
- None of them have a mau_tag nearby (0/2669) -- the Thong tu 200 form-code
  regex that classifies the *other* 97% of the corpus has zero yield here, so
  it is not part of this pass.
- 149 of them (5.6%) have the statement's own printed Vietnamese title
  ("BANG CAN DOI KE TOAN", ...) sitting in header_flat/context_page_text --
  an exact-substring match, asserted deterministically.
- The remaining ~94% are pages that are not a statement table at all (board
  bios, licences, cover letters, signature blocks) and need the LLM to read
  the same context a human reviewer would and pick the closest label.

This only ever touches rows already labelled "unknown" -- every other row's
statement_type (however sparse its other fields are) is left untouched.
Output is a patch file (one JSON record per reclassified row, keyed by the
table's csv_path), not a rewrite of tables_metadata_v2.jsonl -- merging back
is a separate, explicit step once the sample output has been reviewed.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from finance_qa.core.llm import get_chat_model
from finance_qa.core.paths import ARTIFACTS_DIR, TABLE_METADATA_PATH

StatementType = Literal[
    "balance_sheet", "income_statement", "cash_flow", "equity_change",
    "note", "entity_info", "unknown",
]

# Exact substring of the statement's own printed title. Order matters: check
# the longer/more specific titles before any that could be a substring of
# another.
TITLE_RULES: tuple[tuple[str, StatementType], ...] = (
    ("BẢNG CÂN ĐỐI KẾ TOÁN", "balance_sheet"),
    ("BÁO CÁO TÌNH HÌNH TÀI CHÍNH", "balance_sheet"),  # banks, VNM/PNJ, and everyone from ~2022
    ("BÁO CÁO KẾT QUẢ HOẠT ĐỘNG KINH DOANH", "income_statement"),
    ("BÁO CÁO KẾT QUẢ HOẠT ĐỘNG", "income_statement"),  # bank phrasing; must stay after the line above
    ("BÁO CÁO LƯU CHUYỂN TIỀN TỆ", "cash_flow"),
    ("BÁO CÁO THAY ĐỔI VỐN CHỦ SỞ HỮU", "equity_change"),
)

CLASSIFY_SYSTEM = """\
Bạn phân loại một bảng trong báo cáo tài chính doanh nghiệp Việt Nam vào đúng 1 nhãn.

Nhãn hợp lệ (chọn đúng 1):
- "balance_sheet"     : Bảng cân đối kế toán (tài sản / nguồn vốn)
- "income_statement"  : Báo cáo kết quả hoạt động kinh doanh
- "cash_flow"         : Báo cáo lưu chuyển tiền tệ
- "equity_change"     : Báo cáo thay đổi vốn chủ sở hữu
- "note"              : Thuyết minh báo cáo tài chính (bảng chi tiết một khoản mục)
- "entity_info"       : Thông tin chung về đơn vị (giấy phép, ban điều hành, địa chỉ, cổ đông, ...)
- "unknown"           : Không thuộc nhãn nào trên (báo cáo của ban giám đốc, ý kiến kiểm toán, trang bìa, ...)

Chỉ dựa vào nội dung được cung cấp. Nếu không chắc, chọn "unknown".
"""


class StatementTypeResult(BaseModel):
    statement_type: StatementType = Field(description="Nhãn phân loại đúng nhất cho bảng này.")


@dataclass(frozen=True)
class ClassifierPaths:
    meta_path: Path = TABLE_METADATA_PATH
    out_path: Path = ARTIFACTS_DIR / "audits" / "statement_type_reclassified.jsonl"


@dataclass(frozen=True)
class ClassifierConfig:
    limit: int | None = None          # cap how many "unknown" rows to process (sample runs)
    use_llm: bool = True              # fall back to the LLM for rows the title rule misses
    concurrency: int = 4              # LLM calls in flight at once
    thinking: bool = False


def title_rule(header_flat: str, context_page_text: str) -> StatementType | None:
    haystack = f"{header_flat} {context_page_text}".upper()
    for title, label in TITLE_RULES:
        if title in haystack:
            return label
    return None


def _llm_context(rec: dict) -> str:
    parts = [
        f"header_flat: {rec.get('header_flat', '')}",
        f"first_col_labels: {', '.join(rec.get('first_col_labels') or [])}",
        f"context_page_text: {rec.get('context_page_text', '')}",
    ]
    return "\n".join(parts)


async def classify_with_llm(rec: dict, *, thinking: bool) -> StatementType:
    result = await get_chat_model(
        thinking=thinking, max_tokens=256,
    ).with_structured_output(StatementTypeResult).ainvoke(
        [
            SystemMessage(content=CLASSIFY_SYSTEM),
            HumanMessage(content=_llm_context(rec)),
        ]
    )
    if not isinstance(result, StatementTypeResult):
        result = StatementTypeResult.model_validate(result)
    return result.statement_type


class StatementTypeClassifier:
    """Reclassify statement_type=="unknown" rows: title rule, then LLM fallback."""

    def __init__(self, paths: ClassifierPaths | None = None, config: ClassifierConfig | None = None) -> None:
        self.paths = paths or ClassifierPaths()
        self.config = config or ClassifierConfig()

    def _unknown_rows(self) -> list[dict]:
        rows = []
        with self.paths.meta_path.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                rec = json.loads(line)
                if rec.get("statement_type") == "unknown":
                    rows.append(rec)
                    if self.config.limit and len(rows) >= self.config.limit:
                        break
        return rows

    async def arun(self) -> list[dict]:
        rows = self._unknown_rows()
        patches: list[dict] = []
        llm_queue: list[dict] = []

        for rec in rows:
            label = title_rule(rec.get("header_flat", ""), rec.get("context_page_text", ""))
            if label is not None:
                patches.append({
                    "csv_path": rec["csv_path"],
                    "statement_type": label,
                    "statement_type_source": "title_regex",
                })
            elif self.config.use_llm:
                llm_queue.append(rec)

        if llm_queue:
            sem = asyncio.Semaphore(max(1, self.config.concurrency))

            async def _one(rec: dict) -> dict:
                async with sem:
                    label = await classify_with_llm(rec, thinking=self.config.thinking)
                return {
                    "csv_path": rec["csv_path"],
                    "statement_type": label,
                    "statement_type_source": "llm",
                }

            patches.extend(await asyncio.gather(*(_one(rec) for rec in llm_queue)))

        self.paths.out_path.parent.mkdir(parents=True, exist_ok=True)
        with self.paths.out_path.open("w", encoding="utf-8") as fh:
            for patch in patches:
                fh.write(json.dumps(patch, ensure_ascii=False) + "\n")

        by_source = {"title_regex": 0, "llm": 0}
        for patch in patches:
            by_source[patch["statement_type_source"]] += 1
        print(f"unknown rows seen: {len(rows)}")
        print(f"reclassified: {len(patches)} (title_regex={by_source['title_regex']}, llm={by_source['llm']})")
        print(f"wrote: {self.paths.out_path}")
        return patches

    def run(self) -> list[dict]:
        return asyncio.run(self.arun())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="cap how many unknown rows to process")
    parser.add_argument("--no-llm", action="store_true", help="title rule only, skip the LLM fallback")
    parser.add_argument("--concurrency", type=int, default=4, help="LLM calls in flight at once")
    parser.add_argument("--out", type=Path, default=None, help="output patch JSONL path")
    args = parser.parse_args(argv)

    paths = ClassifierPaths(out_path=args.out) if args.out else ClassifierPaths()
    config = ClassifierConfig(limit=args.limit, use_llm=not args.no_llm, concurrency=args.concurrency)
    StatementTypeClassifier(paths, config).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
