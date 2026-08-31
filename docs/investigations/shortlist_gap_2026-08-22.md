# 11 câu "ngoài shortlist": đo xong, không phải lỗi retrieval

`gate_selection_vs_reading.py` chia 73 câu sai của v8 thành ba lớp rời nhau. Hai lớp đầu đã
đo kỹ (xem `docs/cell_ranking_2026-08-22.md`), lớp thứ ba chưa ai chạm:

```
                       sai   đúng   tổng
đã nạp                  23     43     66
ngoài df                33      0     33
ngoài shortlist         11      0     11
không có df              4      2      6
không dò được            2      1      3
```

11 câu đó là `[267, 306, 336, 523, 585, 596, 649, 714, 727, 769, 821]`: bảng gold không có
trong `table_ids`, nên bộ chấm ô có hoàn hảo cũng không cứu được. Giả thuyết vào đo là
"retrieval không với tới bảng gold". **Giả thuyết đó sai.**

## 1. Bảng gold ở đâu

`scripts/gate_shortlist_rank.py` dựng lại pool thật cho từng câu và tìm vị trí bảng gold ở
bốn chặng: lọc cứng (`pool.keys`), cắt kênh (`CHANNEL_K = 20` mỗi kênh BM25/dense), reranker
(`pool.ranked`), cửa sổ judge (`judge_top_n = 20`). Không gọi LLM, chỉ `build_pool`.

Scope đo hai lần. `--scope label` lấy mã/năm/loại từ `report_id` của nhãn, tức cho không
bước understand. `--scope run` gỡ lại scope production thật từ tập report của `table_ids`,
cần thiết vì nhãn câu nhiều năm chỉ ghi một report: nhãn q585 ghi STB_2022 còn production
mở 7 năm, 740 bảng qua lọc cứng.

| scope | ngoài keys | ngoài ranked | ngoài top-20 | judge bỏ |
|---|---:|---:|---:|---:|
| nhãn | 0 | 2 | 0 | 9 |
| production | 1 | 2 | 0 | 8 |

Chi tiết từng câu, hạng của bảng gold sau reranker (scope production):

| q | bảng gold | bm25 | dense | ranked | nhóm |
|---|---|---:|---:|---:|---|
| 267 | ACB_2020_separate\|55 | 1 | 3 | **0** | judge bỏ |
| 306 | EIB_2020_consolidated\|99 | 39 | 43 | — | ngoài ranked |
| 336 | HND_2025\|29 | 5 | 38 | 17 | judge bỏ |
| 523 | DCM_2024_separate\|14 | 9 | 6 | 3 | judge bỏ |
| 585 | STB_2022_separate\|74 | 5 | 3 | 3 | judge bỏ |
| 596 | VNM_2017_separate\|23 | 1 | 1 | 1 | judge bỏ |
| 649 | HSG_2025_consolidated\|19 | 8 | 49 | 11 | judge bỏ |
| 714 | HUT_2024_separate\|4 | — | — | — | ngoài keys |
| 727 | BVH_2019_separate\|63 | 0 | 0 | **0** | judge bỏ |
| 769 | VSC_2015_consolidated\|16 | 4 | 3 | **0** | judge bỏ |
| 821 | OCB_2020_separate\|32 | 186 | 327 | — | ngoài ranked |

Ba câu ở hạng **0** của `pool.ranked`, tức reranker xếp bảng gold lên đầu và judge vẫn không
chọn. Kể cả pool 740 bảng của q585 thì bảng gold cũng ở hạng 3. Retrieval làm đúng việc của
nó ở 8/11 câu.

## 2. Judge chọn bao nhiêu

`_evidence` trả về `picks + [báo cáo chính chưa được chọn]`. Tách hai phần ra bằng
`statement_types`:

| q | 267 | 306 | 336 | 523 | 585 | 596 | 649 | 714 | 727 | 769 | 821 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| picks | 1 | **0** | 1 | 5 | 4 | 2 | 3 | 1 | 1 | 1 | 3 |
| báo cáo chính thêm vào | 6 | 6 | 5 | 30 | 40 | 54 | 31 | 5 | 5 | 11 | 42 |

22 pick trên 11 câu, và q306 chọn **0**. `MAX_PICKS = 10`, nên không có trần nào chặn: judge
tự chọn ít. Phần lớn `table_ids` là báo cáo chính tự động thêm vào, không phải judge chọn.

Đáng ghi thêm: `judge_thinking = False` trong config, mà docstring của `Judge.apick` ghi
"without it the model fills the pick quota with junk (recall@15 69.3% vs 84-89%)". Con số đó
đo trên pipeline cũ chưa có reranker, nên chưa chắc còn đúng, nhưng đây là mâu thuẫn chưa ai
đo lại.

## 3. Bỏ judge thì sao

Thử thẳng: nếu `table_ids` lấy nguyên thứ tự reranker thì bảng gold vào top-K nhiều hơn hay
ít hơn? `scripts/gate_evidence_order.py`, 116 câu dò được bảng gold, scope production, không
gọi LLM. Phủ = **mọi** token gold có ít nhất một bảng trong K phần tử đầu.

| thứ tự | top-1 | top-3 | top-5 | top-12 |
|---|---:|---:|---:|---:|
| `gửi` (judge picks + báo cáo chính) | 45 | **68** | 75 | 90 |
| `ranked` (reranker) | 21 | 49 | 66 | 90 |
| `fused` (RRF, trước reranker) | 30 | 59 | 69 | 86 |
| `picks+ranked` (picks lên đầu, đuôi theo reranker) | 40 | 66 | 79 | 94 |

`codegen_max_tables = 3`, nên **cột top-3 là số khe evidence thật**.

Judge thắng đậm reranker ở top-3: 68 so với 49. Bỏ judge là mất 19 câu. Ý tưởng "judge kém
nên bỏ đi" bị số đo giết ngay, dù chính judge là chỗ nghẽn của 8 câu ở §1. Nó chọn ít nhưng
chọn đúng.

Hai lần chạy cùng gate lệch nhau ±1 ở hai ô (`ranked` top-1 22 rồi 21, top-12 89 rồi 90):
reranker qwen3-0.6b không xác định theo bit. Nên đọc chênh lệch 1-2 câu là nhiễu.

## 4. `picks+ranked` đổi 4 lấy 3

Đây là biến thể đáng nhất: giữ judge picks ở đầu, nhưng đuôi lấy nguyên thứ tự reranker thay
vì chỉ nhặt báo cáo chính. Sửa đúng một dòng ở `_evidence`. Ở top-3 nó ra 66 so với 68, nằm
trong nhiễu, nên phải xem từng câu:

- **được 4**: `[267, 596, 727, 769]`, cả 4 nằm trong 11 câu của §1, cả 4 đang sai
- **mất 6**: `[257, 332, 613, 641, 735, 919]`, trong đó **257, 332, 613 đang đúng**

Đổi bằng chứng của 3 câu đang đúng để lấy 4 câu đang sai, mà 4 câu đó có bằng chứng rồi vẫn
chưa chắc trả lời đúng. Không đáng. Ở top-5 thì phép đổi tốt hơn (được 7, mất 3, cả 3 đang
sai) nhưng top-5 đòi nâng `codegen_max_tables`, và chỗ đó đã bị đo chết.

## 5. Tại sao nâng trần bảng không phải đường ra

`config.py:211-219` đã đo và ghi: nâng `codegen_max_tables` từ 3 lên 10 làm số câu có đủ bộ
bảng gold tăng 37 → 47, prompt tăng 7.4k → 22.2k ký tự, **nhưng số câu đúng giảm 33 → 29**,
vì tỷ lệ sai trên chính những câu đó tăng 38% → 53%. Nguyên văn: "Coverage is not the binding
constraint; telling one table from nine like it is, is."

Bảng ở §3 nói cùng một chuyện từ phía khác: trần phủ ở top-12 là 90-94/116, còn hôm nay top-3
được 68. Có khoảng 22-26 câu mà bảng gold **có** trong `table_ids` nhưng nằm dưới khe thứ 3.
Chỗ đó nhìn như đất trống, nhưng đúng là đất mà `config.py` đã đào và thấy lỗ.

## 6. Kết luận

Lớp "ngoài shortlist" không phải một lớp. Nó là ba thứ khác nhau, và không thứ nào là một
hướng làm việc:

1. **8 câu: judge chọn thiếu.** Bảng gold ở hạng 0-17 của cửa sổ judge. Sửa được về lý
   thuyết, nhưng mọi cách xếp lại `table_ids` đều phải đi qua 3 khe evidence, và §4 cho thấy
   ở 3 khe thì được 4 mất 3.
2. **2 câu: kênh retrieval trượt thật.** q306 (bm25 39 / dense 43) và q821 (bm25 186 /
   dense 327). Nâng `channel_k` từ 20 lên ~50 với tới q306; q821 thì không, hạng 186 là quá
   sâu. 1 câu trên 119.
3. **1 câu: scope sai.** q714 "Kết quả thuần từ hoạt động tài chính của HUT năm 2024" không
   có chữ nào chỉ công ty mẹ, understand chọn `consolidated`, nhãn là `separate`. Không sửa
   được mà không đoán.

Nói thẳng: **đóng luôn hướng này.** Trần thật của nó là 1-2 câu, và cái giá là đi vào đúng
bức tường `config.py:211` đã dựng.

Đất còn lại, theo bảng đầu file: 23 câu **đã nạp đủ bằng chứng mà vẫn trả lời sai**. Đó là
lớp lớn nhất không bị chặn bởi coverage, bởi budget, hay bởi judge. Và nó khớp với chẩn đoán
của `config.py`: vấn đề là phân biệt bảng và đọc bảng, không phải tìm bảng.
