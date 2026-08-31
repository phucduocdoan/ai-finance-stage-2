# Mô hình sử dụng

> **Không có checkpoint tự huấn luyện.** Cả 3 mô hình dưới đây đều là mô hình public trên
> HuggingFace, dùng nguyên bản (không fine-tune). "Checkpoint" ở đây = chính bản public đó, nên
> yêu cầu "checkpoint cần được chia sẻ qua link" được đáp ứng bằng link HuggingFace công khai —
> **không có tệp trọng số nào cần upload lên Drive/OneDrive**. Không có mô hình nào bị pin cứng
> theo revision/commit hash cụ thể trong code; mỗi lần tải sẽ lấy bản mới nhất (`main`) trên Hub
> trừ khi người dùng tự chỉ định `revision=`.

## Tổng quan

| Mô hình | Vai trò | Nơi gọi trong code | Cách phục vụ |
|---|---|---|---|
| `Qwen/Qwen3.5-9B` | LLM sinh câu trả lời / hiểu câu hỏi / sinh pandas / xác minh | `src/finance_qa/core/llm.py` | vLLM cục bộ (mặc định) hoặc DeepInfra hosted |
| `BAAI/bge-m3` | Dense embedding cho retrieval | `src/finance_qa/modules/rag/indexing/dense.py` | Cục bộ, `transformers` |
| `Qwen/Qwen3-Reranker-0.6B` | Rerank ứng viên bảng trước khi đưa cho judge | `src/finance_qa/modules/rag/rerankers/deepinfra.py` | DeepInfra hosted API |

## 1. Mô hình chat/sinh câu trả lời — `Qwen/Qwen3.5-9B`

- **Link HuggingFace**: https://huggingface.co/Qwen/Qwen3.5-9B
- **Vai trò**: mọi node trong graph trừ phần chấm điểm BM25/dense của node `retrieve` đều gọi
  mô hình này qua endpoint OpenAI-compatible trong `core/llm.py` — cụ thể là node `understand`
  (trích ticker/năm/metric), `generate_pandas` (sinh biểu thức pandas), `execute_and_repair`
  (sửa lỗi khi thực thi), `verify_answer` (xác minh lại kết quả), và `judge.py` trong
  `retrieve` (chọn bảng cuối cùng). Xem sơ đồ mermaid trong README, mục "Answer Flow".
- **Phiên bản/checkpoint**: bản public mới nhất trên Hub (`main`), không fine-tune, không pin
  commit hash trong code (`MODEL = os.environ.get("LLM_MODEL", "Qwen/Qwen3.5-9B")` trong
  `core/llm.py`, dùng đúng tên repo HF đầy đủ, không dùng alias).
- **Hướng dẫn tải và phục vụ (serving)** — README (mục "LLM backend") đã có sẵn 2 lựa chọn,
  không lặp lại chi tiết ở đây:
  - **vLLM cục bộ (mặc định của repo)**: phục vụ `Qwen/Qwen3.5-9B` trên cổng `8990`. Cách khởi
    động server vLLM không nằm trong README hiện tại của repo này — dùng lệnh vLLM chuẩn, ví dụ:
    ```bash
    vllm serve Qwen/Qwen3.5-9B --port 8990
    ```
    (vLLM sẽ tự tải checkpoint từ HuggingFace Hub vào cache cục bộ ở lần chạy đầu tiên.)
  - **DeepInfra hosted (không cần server cục bộ)**: dùng `LLM_MODEL=Qwen/Qwen3-14B` qua API —
    xem chi tiết biến môi trường ở mục "Hướng dẫn sử dụng" bên dưới.
- **Hướng dẫn sử dụng (biến môi trường, từ `core/llm.py`)**:

  | Biến | Mặc định | Ý nghĩa |
  |---|---|---|
  | `LLM_ENDPOINT` | `http://127.0.0.1:8990/v1/chat/completions` | URL endpoint chat, dạng OpenAI-compatible |
  | `LLM_MODEL` | `Qwen/Qwen3.5-9B` | Tên model gửi trong request body — phải khớp đúng ID mà server đang phục vụ báo cáo tại `/v1/models` |
  | `LLM_API_KEY` | rỗng | Bearer token, chỉ cần khi dùng backend hosted (DeepInfra) |
  | `LLM_TEMPERATURE` | tắt (-1) | Ghi đè temperature cho các lệnh gọi mặc định 0.0 |
  | `LLM_SEED` | không đặt | Seed cho backend vLLM cục bộ (không áp dụng khi gọi DeepInfra) |

  Ví dụ 2 cấu hình (giống README):
  ```bash
  # vLLM cục bộ
  export LLM_ENDPOINT=http://127.0.0.1:8990/v1/chat/completions
  export LLM_MODEL=Qwen/Qwen3.5-9B

  # DeepInfra hosted
  export LLM_ENDPOINT=https://api.deepinfra.com/v1/openai/chat/completions
  export LLM_MODEL=Qwen/Qwen3-14B
  export LLM_API_KEY=$DEEPINFRA_API_KEY
  ```

## 2. Mô hình embedding dense — `BAAI/bge-m3`

- **Link HuggingFace**: https://huggingface.co/BAAI/bge-m3
- **Vai trò**: kênh dense của bước retrieval (`CandidateRetriever.aselect()` trong
  `modules/rag/candidates.py`) — mã hoá câu hỏi và văn bản mô tả bảng (`doc_text`) thành vector
  1024 chiều để tính độ tương đồng, kết hợp (RRF fuse) với kênh BM25. Đây là backend mặc định
  (`dense_backend: str = "bge-m3"` trong `agents/finance/config.py`).
- **Kiến trúc/cách dùng**: XLM-R large + CLS pooling + L2-normalize, nạp thẳng bằng
  `transformers.AutoModel`/`AutoTokenizer` (không dùng `FlagEmbedding`/`sentence-transformers`
  — xem docstring đầu `modules/rag/indexing/dense.py` để tránh xung đột phiên bản `torch`).
- **Phiên bản/checkpoint**: bản public mới nhất trên Hub, không fine-tune. Tên model hard-code
  trong `dense.py` (`MODEL = "BAAI/bge-m3"`), không có biến môi trường ghi đè, không pin
  revision.
- **Hướng dẫn tải**: `transformers` tự tải và cache khi gọi lần đầu — không cần bước thủ công:
  ```python
  from transformers import AutoModel, AutoTokenizer
  tok = AutoTokenizer.from_pretrained("BAAI/bge-m3")
  model = AutoModel.from_pretrained("BAAI/bge-m3")
  ```
- **Hướng dẫn sử dụng**: chạy trong virtualenv `.venv_bge` của repo (README, mục "Setup") — môi
  trường conda gốc không thấy được GPU với driver CUDA-12.6 của máy. Không có biến môi trường
  cấu hình riêng; thiết bị (GPU/CPU) được tự chọn dựa trên VRAM còn trống
  (`_pick_device()` trong `dense.py`, ngưỡng 3 GB) và tự chuyển sang CPU nếu hết bộ nhớ GPU khi
  đang chạy.
- **Lưu ý**: index dense (`data/indexes/tables_dense.npy`, xem `docs/DATA.md`) là vector đã
  encode sẵn bằng đúng mô hình này — không thể trộn với vector từ mô hình khác.
- **Backend embedding thay thế (tắt mặc định)**: `Qwen/Qwen3-Embedding-4B` qua DeepInfra hosted
  API (`modules/rag/indexing/deepinfra.py`), bật bằng `dense_backend="qwen3-4b"`, cần
  `DEEPINFRA_API_KEY`. Không phải cấu hình production, chỉ liệt kê để đầy đủ.

## 3. Mô hình reranker — `Qwen/Qwen3-Reranker-0.6B`

- **Link HuggingFace**: https://huggingface.co/Qwen/Qwen3-Reranker-0.6B
- **Vai trò**: bước cuối trong `CandidateRetriever.aselect()` trước khi giao cho LLM judge —
  chấm điểm lại (cross-encoder) danh sách bảng ứng viên đã được BM25+dense hợp nhất, để sắp xếp
  lại thứ tự trước khi cắt còn `judge_top_n=20` bảng đưa vào prompt của judge. Đây là reranker
  mặc định trong cấu hình production (`reranker: str | None = "qwen3-0.6b"` trong
  `agents/finance/config.py`).
- **Cách phục vụ**: **không chạy cục bộ** — gọi qua DeepInfra hosted inference API
  (`RERANK_MODEL = "Qwen/Qwen3-Reranker-0.6B"` trong `modules/rag/rerankers/deepinfra.py`, POST
  tới `https://api.deepinfra.com/v1/inference/Qwen/Qwen3-Reranker-0.6B`). Không có trọng số nào
  tải về máy đội — vì vậy không có tệp checkpoint cần upload cho mô hình này.
- **Phiên bản/checkpoint**: bản public DeepInfra đang phục vụ dưới ID trên, không fine-tune.
  Đội không kiểm soát version cụ thể phía DeepInfra host (không có tham số revision).
- **Hướng dẫn sử dụng**: cần biến môi trường `DEEPINFRA_API_KEY` (đọc trong
  `modules/rag/deepinfra_client.py:api_key()` — có thể đặt qua biến môi trường hoặc trong tệp
  `.env` ở gốc repo). Không có endpoint/model khác để cấu hình — URL và tên model cố định
  trong code.
  ```bash
  export DEEPINFRA_API_KEY=<khoá API DeepInfra của bạn>
  ```
  **Lưu ý README**: mục "LLM backend" hiện tại của README chỉ nói về `LLM_ENDPOINT`/
  `LLM_MODEL`/`LLM_API_KEY` cho mô hình chat; không đề cập `DEEPINFRA_API_KEY` là bắt buộc cho
  cấu hình reranker mặc định. Người chạy lại lần đầu theo đúng README có thể không biết cần
  khoá này — nên bổ sung một dòng vào README trỏ tới tài liệu này (việc bổ sung README không
  nằm trong phạm vi 2 tài liệu này, ghi chú lại để làm sau nếu còn thời gian).

## Việc cần làm thủ công (không thể tự động hoá)

- Không có — cả 3 mô hình đều public, chỉ cần link HuggingFace ở trên. Nếu muốn chắc chắn hơn
  cho việc tái lập kết quả, có thể cân nhắc ghim `revision=` cụ thể khi tải `Qwen/Qwen3.5-9B` và
  `BAAI/bge-m3` (hiện code dùng `main` mới nhất), nhưng đây không phải yêu cầu bắt buộc của
  `final_submission.md`.
