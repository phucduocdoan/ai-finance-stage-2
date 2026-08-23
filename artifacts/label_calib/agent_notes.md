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

## Q714
The specific line the question implies ("net financial result") does not exist as an explicit line in this income-statement format — the row at that position is actually a sub-item ("Trong đó: chi phí lãi vay") with its own column-shift bug (missing label, values shifted one column right). Reconstructed the intended figure as Doanh thu tài chính minus Chi phí tài chính instead, since no single reported line answers the question directly.

## Q764
Required checking whether an apparently "no-change year" (identical current/prior-year values for one balance-sheet line) was a genuine flat year or a fresh shift-bug artifact. Confirmed genuine by checking that the immediately neighboring rows in the same table have properly distinct values across the two year-columns.

## Q774
Simple two-company balance-sheet lookup, but the question's "chênh lệch" (difference) has no stated sign convention — I report VIB minus SHB (negative), flagged as medium confidence since the intended answer could instead be the absolute value.

## Q836
No single, explicit "trích lập trong năm" (gross provision addition, excluding reversals) line exists for two of the four requested years (2017, 2019) — those years' notes only disclose the aging schedule, not a rollforward. Used the SG&A note's "Dự phòng phải thu khó đòi" net expense line as the most directly-labeled available proxy across all 4 years; the identified highest year (2019) is far enough ahead of the others that the conclusion is robust to this methodological substitution.

## Q853
Straightforward three-company equity/total-assets ratio average for one year. No shift-bugs encountered; all three parent balance sheets were clean.

## Q894
Straightforward five-year average of one cash-flow line for a single company. Cross-validated every adjacent-year pair (each year's comparative column matched the neighboring report's current-year column exactly), so I'm confident in the values despite pulling from five separate report years.

## Q968
Required identifying which note table represented the currency split of long-term loans specifically (as opposed to total loans including short-term) — resolved by summing the USD+VND currency-split table and confirming it matches the separately-disclosed "Vay dài hạn" total in a different, messily-parsed sub-table of the same note. This cross-check is somewhat indirect, hence medium confidence.

---

## Least-sure questions (top candidates for human review)

1. **Q267** (LOW) — Three real, differently-scoped "tiền gửi ngoại tệ" figures exist for ACB at end-2020 (interbank asset, interbank liability, customer deposits), and the question doesn't specify which. This is the single most likely-to-be-wrong answer in the set; a human should check which note the gold label actually points to.
2. **Q968** (MEDIUM) — The USD/VND currency split table for POW's loans was matched to the "dài hạn" total via a cross-table sum-check rather than an explicit note label confirming it's long-term-only; worth a second look at the raw table.
3. **Q836** (MEDIUM) — No dedicated gross "trích lập" rollforward note exists for 2017/2019 for TTF; I substituted the SG&A note's net "dự phòng" expense line. The highest-year conclusion (2019) is likely right, but the exact number depends on which accounting concept the question intends.

Other medium-confidence items (452, 483, 572, 774) all rest on either the well-cross-validated header/cash-flow shift-bug correction pattern (which has proven reliable every time I could independently verify it against an adjacent year) or a sign-convention judgment call on "chênh lệch" (774) — I consider these lower-risk than the three above.

## Systematic data obstacles observed

- **Header-shift bug type A** (balance sheets, e.g. HHV/VSC 2024): a stray year-label string leaks into row 0 of the primary label column, and the column with the real date header actually holds the current year while an "Unnamed" column holds the true comparative year.
- **Header-shift bug type B** (cash flow statements, e.g. GEE/GEX 2022–2024, DCM/DPM 2019–2020): label leaks into the first/"CHỈ TIÊU" column, mã-số code leaks into an adjacent column, and the true current-year value ends up sitting in the "Mã số" column while "Năm nay" actually holds the true prior-year value.
- **Column-merge shift bugs in income statements** (e.g. HUT 2024, DCM 2019/2020): a sub-item's label goes missing entirely and its values shift one column to the right, landing the true "Năm nay" value under "Thuyết minh" (or similar).
- **The single most reliable tool against all of the above** was continuity/consistency validation: a given year's reported figure should exactly equal the same line item's comparative-column figure in the adjacent year's own report. Every time I could run this check, it either confirmed the correction or (in the one non-shift case, Q764) confirmed that an apparent "flat year" was genuine rather than a fresh artifact.
- **Genuine multi-reading ambiguity** (Q267, and to a lesser extent Q774's sign convention) is a distinct failure mode from the shift bugs above — no amount of cross-validation resolves it, because multiple real, correctly-reported figures satisfy the question's wording equally well. These are the cases most worth flagging to a human rather than trying to algorithmically resolve.
- **Missing/non-uniform note structures across years** (Q836, Q968): the same company doesn't always disclose the same breakdown (e.g. gross provision rollforward vs. only an aging schedule; currency-split vs. maturity-split loan notes) in every year's report, forcing a judgment call about which alternative data source best approximates the question's intent.
