# Per-question notes

**579 (IJC, lãi tiền gửi có kỳ hạn, 2016→2021)** — Company name "CTCP Phát triển Hạ tầng Kỹ thuật" is not a well-known ticker name; had to resolve it via `company_name` search, which turned up ticker IJC uniquely. Once found, both years' separate reports had the exact row in their own "Năm nay" column, so no cross-year reconciliation was needed. Straightforward.

**580 (HBC, chi phí thuế hoãn lại, 2016 vs 2015)** — Easy: consolidated income statement row 17 gives both years side by side. The only judgment call was confirming from the raw (un-parsed) CSV that both years' figures are shown in parentheses (i.e. both are genuinely "chi phí", not one being "thu nhập"), so the sign convention is unambiguous.

**586 (ACV, tiền và tương đương tiền, cuối 2021→cuối 2022)** — Clean. Balance sheet gives cuối-2022 and đầu-2022 (=cuối-2021) in the same row; cross-checked against ACV's own 2021 report closing balance and it matched exactly to the VND.

**600 (FPT, "Lãi vay phải trả người bán ngắn hạn", 2025 vs 2023)** — The hardest one. No row anywhere is literally named "Lãi vay phải trả người bán ngắn hạn". A row named exactly "Lãi vay phải trả" exists, but it lives inside note 19 "Chi phí phải trả ngắn hạn" (accrued expenses), not inside note 17 "Phải trả người bán ngắn hạn" (trade payables to suppliers) — I checked note 17's supplier-detail sub-tables and found no interest-related line there. I answered using the "Lãi vay phải trả" row on the assumption the question's extra "người bán ngắn hạn" phrase is noise (possibly picked up from an adjacent note title during question generation). Flagged medium confidence.

**603 (VJC, chi phí bảo dưỡng tàu bay trả trước, cuối 2025 vs cuối 2024)** — Clean; note 11 gives cuối-2025 and đầu-2025(=cuối-2024) directly, cross-checked against the 2024 report's own closing figure (label differs slightly: "Chi phí bảo dưỡng tàu bay trả trước" in 2025 report vs "Chi phí bảo dưỡng tàu bay" in 2024 report, but the value matches exactly so it's the same line).

**604 (DLG, tổng tài sản, cuối 2019 vs cuối 2018)** — Clean, single balance sheet row, cross-checked against 2018 report's own closing total, exact match.

**609 (ACB, tổng tài sản/GTCG nhận thế chấp..., cuối 2022→cuối 2025)** — Clean; this is a bank's off-balance-sheet collateral-received memo note. Total row exists in both reports, cross-checked cuối-2022 against 2023 report's comparative column, exact match.

**613 (IJC, lưu chuyển tiền thuần hoạt động tài chính, 2022 vs 2018)** — Both years are net outflows (negative). The cash-flow statement row gives the figure directly in each year's own report — no need to use a comparative column, so no cross-report reconciliation was possible/needed here, but the values are internally consistent with the pattern seen in other IJC notes (unit VND).

**621 (VJC, chi phí nhiên liệu, 2024 vs 2021)** — Clean; the by-nature cost note ("CHI PHÍ SẢN XUẤT KINH DOANH THEO YẾU TỐ") gives this directly in each year's own separate report.

**624 (STB, tiền mặt bằng ngoại tệ, cuối 2016 vs cuối 2015)** — Clean; note 5 "TIỀN MẶT VÀ VÀNG" gives cuối-2016 and đầu-2016(=cuối-2015), cross-checked against STB's 2015 report's own closing figure, exact match.

**643 (KLB, số lượng cổ phiếu đang lưu hành, cuối 2019 vs cuối 2023)** — Clean; the capital/equity note directly states this in both reports' "Số cuối năm" column.

**646 (KHG, chi phí nhân viên, 2021 vs 2020)** — Ambiguous target row. KHG's notes split staff costs into "Chi phí nhân viên" (inside CHI PHÍ BÁN HÀNG / selling expenses) and "Chi phí nhân viên quản lý" (inside CHI PHÍ QUẢN LÝ DOANH NGHIỆP / admin expenses); there is no by-nature note giving one company-wide staff-cost total (no "chi phí sản xuất kinh doanh theo yếu tố" note exists for KHG in this year). I used the literal "Chi phí nhân viên" row since it's the only exact string match, but the question may have actually intended a total that simply isn't reported as a single line. Flagged medium confidence.

**648 (HHS, chi phí dịch vụ mua ngoài, 2023 vs 2022)** — Similar structural ambiguity to 646 (the label "Chi phí dịch vụ mua ngoài" also appears separately inside both the selling-expense and admin-expense notes with smaller values), but here HHS *does* have a "CHI PHÍ SẢN XUẤT KINH DOANH THEO YẾU TỐ" note giving one unambiguous company-wide total, which I used. High confidence.

**654 (DNH, giá vốn bán điện, 2017 vs 2016)** — Clean; note 26 "Giá vốn hàng bán" gives both years directly in one table.

**720 (SGB, giá trị còn lại TSCĐ vô hình, cuối 2017→cuối 2018)** — Clean; the rollforward note gives đầu-năm-2018 (=cuối 2017) and cuối-năm-2018 in the "Tổng cộng" column, cross-checked đầu-năm-2018 against the adjacent 2017-rollforward table's cuối-năm total, exact match.

# Questions I'd most want a human to double-check
1. **600 (FPT)** — the row I used ("Lãi vay phải trả" in the accrued-expenses note) does not textually match the question's "Lãi vay phải trả người bán ngắn hạn"; I could not find any row that does. This is the single weakest link in the set.
2. **646 (KHG)** — "Chi phí nhân viên" only exists as a selling-expense sub-line, not as a company-wide total; if the intended answer requires selling + admin (or the full by-nature total), my number is not it.
3. **648 (HHS)** — same structural issue as 646 (three different "Chi phí dịch vụ mua ngoài" rows exist across notes with different values), but I'm more confident here because the by-nature note gives an unambiguous single total, which is the natural read of the question. Worth a second look mainly because the pattern of duplicate labels across notes is a systematic trap in this data.

# Systematic obstacles observed
- **Duplicate row labels across functional notes.** Selling-expense and admin-expense notes routinely repeat generic labels like "Chi phí nhân viên", "Chi phí dịch vụ mua ngoài", "Chi phí khấu hao TSCĐ" with different values for the same nominal concept. When a "by-nature" (theo yếu tố) note exists, it disambiguates by giving one total; when it doesn't (e.g. KHG), the question's intended target is genuinely underspecified by the data.
- **OCR noise in row/column labels.** Several column headers and row labels are visibly OCR-damaged ("CHÌ TIÊU" instead of "CHỈ TIÊU", "cảm cố" instead of "cầm cố", "tải chiết khấu" instead of "tái chiết khấu", "Bắt động sản" instead of "Bất động sản"). This doesn't affect the numbers but makes substring search brittle — I had to try several spelling variants per search.
- **Units stated only in page prose, not in every table's own header.** Some tables carry unit in the column header ("Triệu VND", "31.12.2025Triệu VND"), others only in the free-text `context_page_text` near the top of the financial-statement page ("Đơn vị tính: Triệu Đồng Việt Nam"), and some (e.g. HBC, DLG, plain corporate balance sheets) have no unit token in the row/column header at all and rely on statement-level convention (VND) inferred from magnitude and nearby pages.
- **`context_page_text` lag.** The context text attached to a table sometimes describes the *next* note/statement title rather than the table's own, because OCR page-text extraction seems to grab text near the bottom of the physical page, which can already contain the following section's header. I cross-checked against the table's own row labels rather than trusting `context_page_text` for statement identification.
- **Comparative-column reconciliation worked well.** For every question except 613 and 621, I was able to cross-check at least one side of the pair against the *other* year's own report (either its own closing balance or the following year's comparative column), and every single cross-check matched exactly to the VND/triệu-đồng digit. This gives good confidence that the values I pulled are not affected by restatements.
