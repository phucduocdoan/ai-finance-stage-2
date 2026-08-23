# Agent labeling notes — blind_tasks.jsonl (24 questions)

For each question: what made it easy/hard, and what data-quality issue (if any) had to be resolved.

## Q7
Straightforward balance-sheet lookup (mã số 322, "Số cuối năm"). No doc_type qualifier stated in the question, defaulted to consolidated. No shift-bug encountered.

## Q142
Straightforward balance-sheet lookup (mã số 262, "Số cuối năm"), defaulted to consolidated since no "công ty mẹ" qualifier was present. Clean table, no ambiguity.

## Q180
Required going into a note (Tiền và các khoản tương đương tiền) to split "Tiền" (mã số 111) into "Tiền mặt" and "Tiền gửi ngân hàng". Verified the split sums back to the balance-sheet line exactly, which resolved any doubt about pulling the right sub-items.

## Q214
Easy once "Các khoản giảm trừ doanh thu" was confirmed to be 0 for this company/year — this eliminated the usual gross-vs-net revenue ambiguity for "Doanh thu".

## Q257
Bank cash-flow statement line lookup, "Năm nay" = the requested year. No separate/parent qualifier in the question, defaulted to consolidated.

## Q267 — LOW CONFIDENCE, flagged for human review
Genuine 3-way ambiguity. ACB's separate financial statements have three distinct "tiền gửi ... bằng ngoại tệ" figures at 31/12/2020: an asset-side interbank-deposit note (3,372,600 triệu), a liability-side interbank-deposit note (993,314 triệu), and a customer-deposits note (340,063 triệu). The question gives no scoping qualifier to disambiguate which one is meant. I picked the customer-deposits reading as the most natural default for a generic "tiền gửi" question about a bank, but this is a guess among three real candidates, not a data-quality artifact — a human should decide which note the gold answer intends.

## Q310
Separate (công ty mẹ) income statement explicitly requested and present. Clean, single-source read.

## Q313
Note breakdown of short-term prepaid expenses, "Số cuối năm". No ambiguity.

## Q452
Multi-company/multi-year screening: had to compute current ratios for 4 tickers to find the below-median subset, then compute gross margins on the qualifying subset. HHV and VSC's 2024 balance sheets both have the recurring header-shift bug where a stray year-label string leaks into row 0 of the label column — resolved using the standard pattern (the column with the real date header holds the current year).

## Q483
Screening question requiring cross-year continuity checks: DCM and DPM's 2019/2020 income-statement and cash-flow tables both have a column-shift bug where the label leaks into one column and the true current-year value lands in what looks like the "prior year" column (or vice versa). Resolved by checking that each year's true figure matches the same line item's comparative-column value in the adjacent year's own report — this matched exactly for both tickers, which is what gives me confidence in the correction despite the messy source tables.

## Q492
Multi-company ratio screening (CFO/operating-profit) to identify the outlier (PLX), then a simple net-margin computation on that company. Clean data for all three companies, no shift-bug encountered.

## Q544
Multi-year screening (net margin threshold) followed by a tie-break rule (lower revenue year) and a CFO/short-term-debt ratio computation. Cross-validated the underlying DCM revenue/profit figures against the next year's report and found an exact match, so no residual shift-bug doubt for the target year.

## Q552
Multi-company, multi-year "all positive" screening across three years for four tickers. Two of the four had a real net loss in one of the screened years (NKG in 2022, MSR in 2023), which excludes them — this is a substantive filtering step, not a data artifact, but it changes the answer nontrivially versus including all four companies naively.

## Q571
Growth-rate screening (revenue growth) followed by an SG&A growth-rate computation on the winning company. All source data was clean.

## Q572
Screening question with the same GEE/GEX cash-flow shift bug seen elsewhere (label/mã số leak, true current-year value lands in the "Mã số" column). Resolved via the same adjacent-year continuity check. SAM was excluded on a genuine negative-CFO year, not a data artifact.

## Q613
Separate (công ty mẹ) cash flow statements explicitly requested; simple difference between two years' CFF lines. Clean data.

## Q701
Required mapping a full Vietnamese company name to its ticker (IJC), then a straightforward separate income-statement ratio. Confirmed the name-to-ticker match via the company_name metadata field.

## Q714 — CORRECTED mid-session, doc_type metadata is swapped
The specific line the question implies ("net financial result") does not exist as an explicit line in either HUT income-statement table — the row at that position is a sub-item ("Trong đó: chi phí lãi vay"), not a net-result line. Reconstructed the intended figure as Doanh thu tài chính minus Chi phí tài chính instead. More importantly: I initially read this off the folder tagged `doc_type=consolidated` (table_pos 3, giving 238.89 tỷ), but that folder actually holds the separate/parent-only statement (revenue ~318.7 tỷ, no minority-interest line). The folder tagged `doc_type=separate` (table_pos 4) is the true consolidated statement (revenue ~30.2 nghìn tỷ, has the "Lợi nhuận sau thuế của công ty mẹ / của cổ đông không kiểm soát" split that only a genuine consolidated filing has, confirmed via `section_title`="BÁO CÁO KẾT QUẢ HOẠT ĐỘNG KINH DOANH HỢP NHẤT"). Corrected final answer: 168.735345447 tỷ đồng, sourced from the "separate"-tagged folder's table_pos 4.

## Q764 — CORRECTED mid-session, doc_type metadata is ambiguous
Required checking whether an apparently "no-change year" (identical current/prior-year values for one balance-sheet line) was a genuine flat year or a fresh shift-bug artifact — ruled out, since neighboring rows in the same table have properly distinct values across the two year-columns. Separately, and more consequentially: DPM's 2015 report_id (tagged `doc_type=consolidated` throughout) actually bundles two different balance sheets — table_pos 5 (`section_title`="Báo cáo tài chính riêng", i.e. actually separate) and table_pos 64 (`section_title`="Báo cáo tài chính hợp nhất", the true consolidated one). My first pass read table_pos 5 (Quỹ đầu tư phát triển = 3,444,814,857,841, giving a difference of 2.99248 nghìn tỷ đồng); the correct source is table_pos 64 (3,498,666,363,829), giving a corrected difference of 2.938629265001 nghìn tỷ đồng against GVR's 6,437,295,628,830.

## Q774
Simple two-company balance-sheet lookup, but the question's "chênh lệch" (difference) has no stated sign convention — I report VIB minus SHB (negative), flagged as medium confidence since the intended answer could instead be the absolute value.

## Q836 — CORRECTED mid-session, two plausible source notes
A dedicated gross-provision rollforward note *does* exist for all four years after all (I initially missed it for 2017/2019, where it's embedded as a continuation of the "Phải thu khách hàng" note rather than broken out as its own note the way 2021/2025 are); it has a row literally named "Dự phòng trích lập trong năm" ("Cộng: ..." in 2021), which is the most literal match to the question's wording. Magnitudes: 2017=2,761,917,100; 2019=280,535,703,178 (max, by a wide margin); 2021=6,121,138,679; 2025=6,608,661,779. Corrected final answer: 280.535703178 tỷ đồng (2019). This is a different, smaller number than an earlier draft's 289.365668908 tỷ, which came from a different note (the SG&A/"Chi phí quản lý doanh nghiệp" breakdown's "Dự phòng phải thu khó đòi" line — a net P&L charge, not the gross amount provisioned). Both notes agree that 2019 is the peak year; they disagree on the exact figure, so I kept confidence at medium.

## Q853
Straightforward three-company equity/total-assets ratio average for one year. No shift-bugs encountered; all three parent balance sheets were clean.

## Q894
Straightforward five-year average of one cash-flow line for a single company. Cross-validated every adjacent-year pair (each year's comparative column matched the neighboring report's current-year column exactly), so I'm confident in the values despite pulling from five separate report years.

## Q968 — CORRECTED mid-session, scope of the currency-split table clarified
Initially worried the USD/VND currency-split note might cover only long-term ("dài hạn") loans rather than total borrowings, and flagged medium confidence on an indirect cross-check. Re-verified directly against the 2017 balance sheet: the note's total (15,661,786,300,389) equals mã số 320 (vay ngắn hạn, 4,056,955,004,030) plus mã số 338 (vay dài hạn, 11,604,831,296,359) exactly, confirming the note covers total borrowings, not a long-term-only subset. USD share of total borrowings at each year-end 2017-2025: 2017=82.69% (max), 2018=79.14%, 2019=72.05%, 2020=61.19%, 2021=36.63%, 2022=26.05%, 2023=42.48%, 2024=58.98%, 2025=80.63%. Final answer unchanged (82.6867139287576%, year 2017), but confidence raised to high now that the scope is confirmed directly rather than inferred.

---

## Least-sure questions (top candidates for human review)

1. **Q267** (LOW) — Three real, differently-scoped "tiền gửi ngoại tệ" figures exist for ACB at end-2020 (interbank asset, interbank liability, customer deposits), and the question doesn't specify which. This is the single most likely-to-be-wrong answer in the set; a human should check which note the gold label actually points to.
2. **Q836** (MEDIUM) — Two different notes both carry a "dự phòng phải thu khó đòi"-style line for TTF: a gross rollforward note ("Dự phòng trích lập trong năm" = 280.54 tỷ for 2019, which I used) and a net SG&A charge line (~289.37 tỷ for 2019). The peak year (2019) is right either way; the exact magnitude depends on which concept the question intends.
3. **Q714 and Q764** (MEDIUM each) — Both answers are now correct, but only because I caught that `doc_type` metadata is unreliable for these two report_ids (HUT_financial_statements_2024 has its "consolidated"/"separate" tags swapped; DPM_financial_statements_2015_consolidated bundles a separate and a consolidated balance sheet under one tag, disambiguated only by `section_title`). I'm confident in the numbers given the correct table, less confident that a downstream pipeline relying on `doc_type` alone would reproduce this.
4. **Q774** (MEDIUM) — magnitude is solid; only the sign convention ("chênh lệch giữa A và B" as A minus B, reading order) is a judgment call.

Other medium-confidence items (452, 483, 572) rest on the well-cross-validated header/cash-flow shift-bug correction pattern, which has proven reliable every time I could independently verify it against an adjacent year — I consider these lower-risk than the four above. Q968 was originally flagged medium for an indirect cross-check but is now resolved to high confidence (see its section above).

## Systematic data obstacles observed

- **`doc_type` metadata can be wrong, and not just occasionally.** Two of the 24 questions (714, 764) landed directly on report_ids where the consolidated/separate tag is either swapped (HUT_financial_statements_2024) or ambiguous because one report_id bundles both statement types under a single tag (DPM_financial_statements_2015_consolidated). The only reliable disambiguator I found was `section_title` (or the presence/absence of a minority-interest split line), never `doc_type` alone. Any pipeline that filters on `doc_type` without a secondary check will silently get these wrong, and I'd expect more instances elsewhere in the corpus that this 24-question sample didn't happen to surface.
- **Vietnamese-locale number formatting: the dot is a thousands separator, not a decimal point.** A cell already denominated in "triệu VND" reading `340.063` is the plain integer 340,063, not 340.063. I made this exact mistake myself in an early draft for ids 267 and 774 before catching it on cross-check — an easy, silent failure mode for any parser assuming en-US formatting.
- **Header-shift bug type A** (balance sheets, e.g. HHV/VSC 2024): a stray year-label string leaks into row 0 of the primary label column, and the column with the real date header actually holds the current year while an "Unnamed" column holds the true comparative year.
- **Header-shift bug type B** (cash flow statements, e.g. GEE/GEX 2022–2024, DCM/DPM 2019–2020): label leaks into the first/"CHỈ TIÊU" column, mã-số code leaks into an adjacent column, and the true current-year value ends up sitting in the "Mã số" column while "Năm nay" actually holds the true prior-year value.
- **Column-merge shift bugs in income statements** (e.g. HUT 2024, DCM 2019/2020): a sub-item's label goes missing entirely and its values shift one column to the right, landing the true "Năm nay" value under "Thuyết minh" (or similar).
- **The single most reliable tool against all of the above** was continuity/consistency validation: a given year's reported figure should exactly equal the same line item's comparative-column figure in the adjacent year's own report. Every time I could run this check, it either confirmed the correction or (in the one non-shift case, Q764's flat-year check) confirmed that an apparent "flat year" was genuine rather than a fresh artifact.
- **Genuine multi-reading ambiguity** (Q267, Q836's two-notes problem, and Q774's sign convention) is a distinct failure mode from the shift bugs and mislabeling above — no amount of cross-validation resolves it, because multiple real, correctly-reported figures satisfy the question's wording equally well. These are the cases most worth flagging to a human rather than trying to algorithmically resolve.
- **Missing/non-uniform note structures across years** (Q968's currency-split vs. maturity-split loan notes, now resolved by a direct balance-sheet cross-check): the same company doesn't always disclose the same breakdown in every year's report, forcing a judgment call — or, ideally, a direct arithmetic cross-check like the one used for Q968 — about which alternative data source actually answers the question.
