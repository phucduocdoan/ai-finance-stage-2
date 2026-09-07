#!/usr/bin/env bash
# Chạy cả pipeline từ câu hỏi tới file nộp, đúng thứ tự và đúng cờ.
#
# README mô tả cùng chuỗi này theo từng bước, nhưng thứ tự và cờ ở đây là bắt buộc
# chứ không phải tuỳ chọn:
#   - bước 4 và 5 phải chạy trước 7 và 8, vì hai bước sau sửa `answer` hoặc bọc
#     `pandas_query`, phát lại sau đó sẽ lệch;
#   - `--no-literal-on-error` ở bước đóng gói là bắt buộc. Thiếu nó thì truy vấn nào
#     chạy hỏng sẽ bị thay bằng `repr(answer)`, đúng dạng gán cứng mà luật chấm 0.
#
# Cần vLLM phục vụ model ở cổng 8990 trước khi chạy.
#
# Dùng:
#     bash scripts/run_submission.sh <tên-run> [workers]
# ví dụ:
#     bash scripts/run_submission.sh full1012_v38 8
set -euo pipefail

NAME="${1:?thiếu tên run, ví dụ full1012_v38}"
WORKERS="${2:-8}"
PY="PYTHONPATH=src .venv_bge/bin/python"
R="artifacts/runs/${NAME}"

run() { echo "+ $*" >&2; eval "$*"; }

run "$PY scripts/pipeline/run_graph.py --all --out ${R}.jsonl --workers ${WORKERS}"

n=$(grep -c . "${R}.jsonl")
if [ "$n" -ne 1012 ]; then
    echo "chỉ có ${n}/1012 câu: run bị đứt giữa chừng (thường là vLLM chết)." >&2
    echo "bật lại server rồi chạy tiếp bằng: $PY scripts/pipeline/run_graph.py --all --out ${R}.jsonl --resume --workers ${WORKERS}" >&2
    exit 1
fi

run "$PY scripts/pipeline/repair_fact_queries.py  ${R}.jsonl           ${R}_repaired.jsonl"
run "$PY scripts/pipeline/repair_cell_indices.py  ${R}_repaired.jsonl  ${R}_cells.jsonl"
run "$PY scripts/pipeline/rescale_below_floor.py  ${R}_cells.jsonl     ${R}_rescaled.jsonl"
run "$PY scripts/pipeline/recount_saturated.py    ${R}_rescaled.jsonl  ${R}_recounted.jsonl"
run "$PY scripts/pipeline/deliteralize_years.py   ${R}_recounted.jsonl ${R}_years.jsonl"
run "$PY scripts/pipeline/build_submission.py --run ${R}_years.jsonl --out output/${NAME} --no-literal-on-error"

run "$PY scripts/pipeline/check_no_hardcode.py output/${NAME}.zip"

git rev-parse HEAD > "${R}.commit"
printf '%s\n' "--all --workers ${WORKERS}" "(mặc định, không đặt biến SOLVE_* nào)" > "${R}.flags"
echo "xong: output/${NAME}.zip"
