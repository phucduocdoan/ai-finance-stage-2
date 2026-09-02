# Spec bảo trì và bàn giao

Bản này gộp bốn luồng khảo sát chỉ-đọc chạy ngày 2026-09-01 (E1 seam bất định, E2 kiểm kê mã
chết, E4 kiểm kê tham số, E6 acceptance test) thành một danh sách việc có thứ tự.

Phạm vi do người dùng chốt: **chỉ để bảo trì và nộp bài**. Không API, không UI, không Docker,
không hai mode. Mọi hạng mục dưới đây tồn tại để người tiếp theo hiểu và chạy lại được repo
này, không phải để thêm tính năng.

## Điều kiện biên

Vòng private chấm lại chính 1012 đáp án đã nộp, không hỏi câu mới. `docs/HANDOFF.md` mục
"Post-Processing Levers That Are Closed" đã đóng mọi đòn bẩy hậu xử lý còn lại. Nên:

**Refactor này không thể kiếm thêm điểm. Việc duy nhất của nó là không làm mất điểm nào.**

Hệ quả trực tiếp: mọi hạng mục phải qua được acceptance test ở P0 trước khi merge, và hạng mục
nào không qua thì bỏ, không sửa test cho vừa.

## Phát hiện gốc

Bốn luồng khảo sát độc lập nhau cùng chỉ về một nguyên nhân: **không có sidecar ghi lại đầu
vào của mỗi lần chạy.** Nó lộ ra ở ba tầng khác nhau.

| tầng | biểu hiện | nguồn |
|---|---|---|
| file run | `full1012_v17_unitfix.jsonl` trộn hai cấu hình (707 câu bật `structured_facts` + `selection_decompose`, 305 câu tắt) mà không ghi lại trộn từ đâu | E4, tôi xác nhận |
| bước hậu xử lý | `fill_from_arms.py:81` nhận danh sách arm từ `sys.argv[3:]`, không ghi lại đã dùng arm nào | E6 |
| tài liệu | README §134-142 tả v27 nhưng được đọc như tả v28 | tôi |

Tầng thứ hai đã được gỡ bằng cách bỏ bước đó khỏi chuỗi, xem "Quyết định: bỏ
`fill_from_arms`" bên dưới. Còn lại hai tầng, cả hai đều là thiếu ghi chép.

## Quyết định: bỏ `fill_from_arms` khỏi chuỗi nộp bài

Chốt ngày 2026-09-01. Chuỗi chính thức dừng ở `repair_fact_queries` →
`repair_cell_indices` → `build_submission`, tức đúng bản v27.

Số đo: trên base `full1012_v17_unitfix.jsonl`, bước này đổi đúng 3 ô (481, 555, 773) và
điểm private không đổi một chữ số nào. `ANSWER_ACCURACY` 0,3893 × 1012 = 394 câu đúng ở
cả v17 lẫn v28, nên 3 ô đó sai ở cả hai bản.

Soi kỹ hơn thì hai trong ba ô lấp ra rác. `pandas_query` của 481 và 555 là ép kiểu
boolean, `float((đk1 and đk2 and đk3) * 1e-0)`, trả về `True` thành 1.0, trong khi câu hỏi
đòi doanh thu thuần tính bằng tỷ đồng. Bộ lọc "chắc chắn sai" không bắt được vì
`FLOOR["tỷ"]` và `FLOOR["nghìn tỷ"]` đều bằng 0,1 nên 1.0 lọt qua cả sàn lẫn trần. Nó chỉ
xét thang đo, không xét dấu vết boolean trong query.

Docstring của script nói arm "không có mặt âm". Đúng theo lập luận bất đối xứng, nhưng
chưa đủ chặt: có 3 trên 1012 đáp án vàng thật sự bằng 0, và số đo hậu thuẫn chỉ là 29 câu
có nhãn qua rổ với 0 lần đúng thành sai, tức chặn trên 95% của tỷ lệ hỏng vẫn khoảng 10%.
Người sau đừng đọc docstring đó như một bảo đảm.

Không xoá `scripts/fill_from_arms.py`. Chỉ bỏ nó khỏi chuỗi được ghi trong README và khỏi
mọi hướng dẫn dựng lại bài nộp.

Ba hệ quả kéo theo:

- P0.2 hết ràng buộc loại trừ. Acceptance test giờ phủ 100% chuỗi chính thức.
- P1.2 (bắt `fill_from_arms` tự ghi arm) biến mất khỏi spec.
- README §134-142 vốn tả đúng v27. Nó trở lại thành đúng, chỉ cần thêm một dòng ghi nhận
  v28 từng tồn tại và lệch 3 ô.

Việc trộn không phải tai nạn. Truy trong `artifacts/runs_archive_2026-08-27.tar.gz` thấy cả
dòng dõi `head` (0 bật) → `all_on` (1012 bật) → `voted` → `v12` (75 bật) → `v13` (793 bật) →
`v14`/`v15` → `v17` (710 bật) → `v17_unitfix` (707 bật). Bước nhảy v12 → v13 đúng là thứ
`src/finance_qa/core/llm.py:45-46` ghi: bầu chéo cấu hình đáng +20 câu trên leaderboard. Chiến
lược cố ý, chỉ là công thức chưa bao giờ được viết ra.

Cha trực tiếp của file đã nộp là `full1012_v17.jsonl` trong archive, khớp 707/707 nhóm bật và
302/305 nhóm tắt theo cặp `(solver, seconds)`.

## P0. Lưới an toàn

Phải xong trước khi động vào bất cứ dòng mã nào. Không có lưới thì không phân biệt được lỗi
refactor với nhiễu batching.

### P0.1 Sao lưu file run đã nộp

`artifacts/runs/full1012_v17_unitfix.jsonl` (9,7 MB, mtime 08-24 09:43) là gốc của toàn bộ bài
nộp. Nó nằm trong `.gitignore` và **không có bản sao nào ở đâu cả**. Ba file dữ liệu dẫn xuất
được bảo vệ đều có bản Drive ghi trong `docs/DATA.md`; file này thì không.

Việc: đẩy nó lên cùng chỗ Drive với ba file kia, ghi đường dẫn vào `docs/DATA.md`. Kèm theo
`full1012_v17.jsonl` rút từ archive, vì đó là cha trực tiếp.

Nghiệm thu: `docs/DATA.md` có mục cho hai file, tải về đối chiếu sha256 khớp.

### P0.2 Acceptance test cho phần đuôi tất định

Phần đuôi hậu xử lý là tất định thật. E6 chạy ba lần, tôi chạy độc lập lần thứ tư, cả bốn ra
cùng một hash:

```
repair_fact_queries -> repair_cell_indices -> build_submission
  trên artifacts/runs/full1012_v17_unitfix.jsonl
  -> submission.json sha256 c778c10285fb261b49706d5cda6abcb7f5b8908e62d2a72cb0599d05c7d39159
```

Việc: thêm `tests/test_submission_reproducibility.py` ghim đúng hash trên, theo lối script của
`tests/test_query_execution.py`. Thời gian chạy đo được khoảng 106 giây.

Sau quyết định bỏ `fill_from_arms`, chuỗi trên chính là chuỗi chính thức, nên test phủ trọn
vẹn chứ không còn phần bị loại trừ. Hash trên đã kiểm là trùng từng byte với
`output/submission_v27/submission.json`.

Hai ràng buộc bắt buộc, đều có lý do đo được:

- So `submission.json` chứ không so file zip. `zipfile.ZipInfo.from_file` nhét mtime của file
  nguồn vào entry, nên hai lần dựng ra byte zip khác nhau dù nội dung y hệt.
- Không so với `output/submission_v28/` trên đĩa. v28 là bản có `fill_from_arms` nên lệch đúng
  3 câu (481, 555, 773). Mốc đối chiếu là v27.

Nghiệm thu: test chạy xanh hai lần liên tiếp trên máy sạch `.pytest_cache`.

### P0.3 Sửa test đang hỏng

`tests/test_screening_compose.py` hiện **đang fail**, không phải sẽ fail:

```
tests/test_screening_compose.py:37: from gate_screening_class import is_screening
ModuleNotFoundError: No module named 'gate_screening_class'
```

Tôi từng nói hai test này pass trên máy này. Sai, E2 kiểm trực tiếp và đúng.

Module khôi phục được: `git show b7d487e^:scripts/dev/gate_screening_class.py`. Đây là sửa một
lệnh, không phải xoá test.

`tests/test_score_comparators.py` là ca khác: nó hard-import `score_clean_eval` từ
`scripts/dev/` đang bị gitignore, nên pass ở đây và fail trên clone mới. Cùng file đó đã dùng
`pytest.importorskip("score_gold75")` cho một phụ thuộc tương tự, nên cách sửa nhất quán là
dùng `importorskip` cho `score_clean_eval` luôn.

Nghiệm thu: `pytest tests/ -q` chạy hết, và số fail đúng bằng 2 nợ cũ đã biết trong
`tests/test_query_execution.py`, không hơn.

## P1. Ghi lại xuất xứ

### P1.1 Sidecar bắt buộc cho mọi file run

Mỗi `artifacts/runs/*.jsonl` phải đi kèm `<tên>.provenance.json` ghi:

```json
{
  "commit": "...",
  "flags": {"SOLVE_STRUCTURED_FACTS": "1", "...": "..."},
  "llm": {"endpoint": "...", "model": "...", "temperature": 0.0, "seed": null},
  "merged_from": ["full1012_v17.jsonl", "..."],
  "merge_rule": "mô tả luật chọn record nào thắng"
}
```

`scripts/run_graph.py` ghi nó tự động. Script nào trộn hoặc bầu thì phải điền `merged_from` và
`merge_rule`.

Nếp cũ để lại nợ: `full1012_v16.jsonl` cũng trộn (69 bật / 943 tắt). Không cần truy ngược mọi
file cũ, nhưng nên viết lại dòng dõi đã truy được ở mục "Phát hiện gốc" vào
`docs/artifact_manifest.md`.

### P1.2 Sửa README và config_flags

- README §134-142 tả đúng v27, và v27 giờ là chuỗi chính thức. Giữ nguyên mô tả, thêm một dòng
  ghi nhận v28 từng được nộp, lệch 3 ô, điểm y hệt, và vì sao bước đó bị bỏ.
- `docs/config_flags.md` ghi `structured_facts` mặc định tắt. Đúng với mã, nhưng 70% đáp án đã
  nộp được tính khi nó bật. Thêm một dòng cảnh báo, **không đổi mặc định**.
- README hiện nói "chạy lại các bước này trên file đó tái tạo được bài nộp". Đúng cho phần
  đuôi, sai cho `full1012_v*` nào cũng vậy vì chúng là bản trộn. Tách hai câu ra.

## P2. Vệ sinh cây nguồn

Chỉ di chuyển và xoá thứ đã có bằng chứng, không viết lại gì.

### P2.1 Gom script dev về một chỗ

29 trong 46 file `scripts/*.py` không nằm trong git, nhưng 27 trong số đó nằm phẳng cạnh 17
script pipeline thật, chỉ phân biệt bằng việc có tên trong `.gitignore` hay không. Ai mở thư
mục cũng không thấy được ranh giới đó.

Việc: chuyển 24 file diagnostic/probe/prototype (`.gitignore` dòng 57-80) và 3 file WIP chưa
từng vào git (`.gitignore` dòng 28-30) vào `scripts/dev/`, rồi thu 27 mục `.gitignore` riêng lẻ
về đúng một luật `scripts/dev/` đã có sẵn ở dòng 101.

Hai test đã trỏ sẵn `sys.path` vào `scripts/dev/`, nên không phải sửa test.

Không xoá gì trong nhóm này. `.gitignore` đã ghi rõ lý do giữ từng file, bằng lời của chính
tác giả, kèm ngày. Đó là bằng chứng tốt hơn bất cứ suy luận nào từ đồ thị import.

Một chỗ cần cẩn thận: `scripts/dev/rescale_below_floor.py` trùng tên với
`scripts/rescale_below_floor.py` nhưng khác nội dung. Bản dev là bản đo cũ có
`import score_clean_eval` để đọc nhãn gold; bản `scripts/` là bản đã gỡ gold. Tách là đúng, chỉ
cần đổi tên bản dev (ví dụ `rescale_below_floor_measure.py`) để nó không tranh chỗ trên
`sys.path`.

### P2.2 Xoá hai module mồ côi

| file | bằng chứng |
|---|---|
| `src/finance_qa/core/types.py` | 12 dòng, chỉ có 4 TypeAlias. Chuỗi `core.types` và `core import types` xuất hiện 0 lần trong `src/`, `scripts/`, `tests/`, `docs/`. |
| `src/finance_qa/modules/data/metadata/` | thư mục chỉ có `__init__.py`. `data.metadata` và `data import metadata` xuất hiện 0 lần. |

Đây là hai trường hợp duy nhất trong 119 file của `src/`. Phần còn lại đều với tới được.

### P2.3 Không làm

Cấu trúc `src/` khớp đúng phần Repository Layout của README. Không gom lại, không đổi tên
package, không tách module. Ba nhóm file trùng tên bên trong `src/` (`schema.py`, `planner.py`,
`execute.py`, ...) là trùng tên trong package khác nhau, import đầy đủ đường dẫn, không phải
xung đột.

## P3. `config.yml`

Việc này nhỏ hơn vẻ ngoài: cả 23 cờ `SOLVE_*` đã nằm gọn sau một hàm `_flag` duy nhất trong
`src/finance_qa/agents/finance/config.py`.

Nguyên tắc chia mục: chỉ tham số **có số đo đứng sau** hoặc thuần vận hành (endpoint, model)
mới lên mục chính. Phần còn lại xuống mục `deprecated`, giữ nguyên giá trị, không xoá. Bản
nháp đầy đủ E4 đã dựng, gồm `llm`, `retrieval`, `solver_production`, `codegen_production`,
`verification`, `postprocessing`, `deprecated`, `channel_defaults`.

Bí mật vẫn chỉ nằm ở biến môi trường: `LLM_API_KEY`, `DEEPINFRA_API_KEY`. Không đưa vào YAML.

Bốn mâu thuẫn mã/tài liệu E4 tìm ra, nên vá cùng lúc vì chúng là bẫy cho người đọc sau:

- `Judge.__init__` mặc định `thinking=True`, còn `FinanceAgentConfig.judge_thinking=False` và
  số đo nghiêng về False (MRR 0.714 so với 0.611). Production luôn truyền tường minh nên không
  ảnh hưởng, nhưng ai gọi `Judge()` trần sẽ dính.
- Chú thích trong `candidates.py` gọi `judge_top_n=None` là "the measured policy", trong khi
  `agents/finance/retrieve.py:19-23` luôn truyền `judge_top_n=20`. Chú thích cũ hơn số đo mới.
- Ba ngưỡng "có tái tạo đúng đáp án không" khác nhau mà không chỗ nào giải thích:
  `build_submission.py` dùng `rel_tol=1e-6`, `repair_cell_indices.py` dùng `1e-4`.
- `scripts/diag_pool_variants.py` ghim `CHANNEL_K=50`, giá trị trước khi đo, còn production
  dùng 20.

Nghiệm thu: đọc `config.yml` xong dựng lại được đúng `FinanceAgentConfig` mặc định, và
acceptance test P0.2 vẫn xanh.

## P4. Seam ghi/phát lại LLM

Chỉ làm nếu P0-P3 xong và còn thời gian. Đây là thứ duy nhất có thể biến `run_graph.py` thành
tất định, nhưng nó là hạng mục lớn nhất và ít cấp bách nhất.

Hình dạng: 23 điểm gọi LLM, trong đó 1 đi qua `achat()` ở `core/llm.py:95` dùng httpx trần, 22
đi qua `get_chat_model()` ở `core/llm.py:130` dùng `langchain_openai.ChatOpenAI`. `ChatOpenAI`
nhận `http_async_client: httpx.AsyncClient` tiêm vào, nên **một lớp transport duy nhất phủ được
cả 23**.

Chặn đường: artifact hiện có không bootstrap được. `diag` trung bình 6.262 B/câu và chỉ chứa
quyết định đã parse; `scripts/run_graph.py:100` nói rõ `codegen_prompt` cố ý không ghi. Phải
chạy một lượt capture mới, ước tính 15-80 MB (suy từ `max_tokens` và cách dựng prompt, chưa đo
thật).

## Thứ tự và ước lượng

| hạng mục | chặn cái gì | ghi chú |
|---|---|---|
| P0.1 sao lưu | mọi thứ | rủi ro cao nhất, chi phí thấp nhất |
| P0.2 acceptance test | P1-P4 | ~106 s mỗi lần chạy |
| P0.3 sửa test hỏng | P2 | một lệnh `git show` |
| P1 xuất xứ | P3 | |
| P2 vệ sinh | | thuần di chuyển |
| P3 config.yml | | |
| P4 seam | | tuỳ chọn |

## Rủi ro đã biết

- Test P0.2 là integration test trên 9.647 bảng thật, không hermetic. Sửa
  `data/metadata/tables_metadata_v2.jsonl` cũng làm đổi hash, và test không phân biệt được
  "dữ liệu đổi" với "mã hỏng".
- `set()` trong `build_submission.py:131,214` và `modules/tools/python_exec.py:241,254,274` hiện
  đều hoặc chỉ kiểm tra thành viên, hoặc đã bọc `sorted()`. Ai bỏ `sorted()` khi refactor sẽ
  tái sinh phụ thuộc `PYTHONHASHSEED` mà không có lỗi nào báo, chỉ có một test chập chờn.
- Hash P0.2 gắn với đúng một phiên bản pandas. Nâng pandas major có thể đổi repr số thực và
  làm test đỏ mà không có lỗi thật.
- `rescale_below_floor` là no-op trên đầu vào này (0/1012 đổi), nên P0.2 không kiểm được logic
  rescale. Muốn phủ thì cần fixture tổng hợp riêng, là một test khác và nhỏ hơn.

## Việc nằm ngoài quyền tôi

- Xoay `DEEPINFRA_API_KEY`. Nó đã bị in ra transcript ở một phiên trước.
- `chmod 600 /home/ding/.config/last30days/.env` (đang 644).
