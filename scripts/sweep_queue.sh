#!/usr/bin/env bash
# Chạy nối đuôi một danh sách cấu hình trên đủ 1012 câu, mỗi cấu hình một file.
#
# Vì sao là hàng đợi chứ không phải chạy tay: model local nên mỗi lần chạy miễn
# phí về tiền và tốn ~1.5 giờ GPU đang rảnh, còn nút thắt là lượt nộp và sự chú
# ý của người. Xếp hàng thì GPU làm việc qua đêm.
#
# Dòng đầu của hàng đợi KHÔNG phải một đường mới: nó là lần chạy thứ hai của
# đúng cấu hình mặc định. Hai lần chạy giống nhau cho ra sàn nhiễu run-to-run,
# và không có con số đó thì mọi delta phía dưới không đọc được. Nó đo được mà
# không tốn lượt nộp nào và không cần nhãn: đếm số câu có đáp án khác nhau.
#
# Dùng:
#   nohup bash scripts/sweep_queue.sh > artifacts/runs/sweep_queue.log 2>&1 &
#
# Bỏ qua cấu hình đã chạy xong (đủ 1012 dòng), nên script này chạy lại được sau
# khi bị ngắt.

set -u
cd "$(dirname "$0")/.."

WORKERS=24
OUTDIR=artifacts/runs

# "tên|env" — env rỗng nghĩa là dùng mặc định trong code.
QUEUE=(
  "head_b|"
  "metric_hints|SOLVE_METRIC_HINTS=1"
  "table_profiles|SOLVE_TABLE_PROFILES=1"
  "metric_lookup|SOLVE_METRIC_LOOKUP=1"
  "repair_history|SOLVE_REPAIR_HISTORY=1"
  "ratio_groups|SOLVE_RAW_TABLE_LINKER_RATIO_GROUPS=1"
  "multi_company12|SOLVE_MAX_TABLES_MULTI_COMPANY=12"
  "sub_tables12|SOLVE_SUB_TABLES=12"
  "screening|SOLVE_SCREENING=1"
  "structured_facts|SOLVE_STRUCTURED_FACTS=1"
  "decompose|SOLVE_DECOMPOSE=1"
  "linker_thinking|SOLVE_RAW_TABLE_LINKER_PLANNER_THINKING=1"
  "no_verify|SOLVE_VERIFY_ANSWER=0"
  "tool_turns3|SOLVE_TOOL_TURNS=3"
)

for entry in "${QUEUE[@]}"; do
  name="${entry%%|*}"
  envs="${entry#*|}"
  out="$OUTDIR/full1012_$name.jsonl"

  if [ -f "$out" ] && [ "$(wc -l < "$out")" -ge 1012 ]; then
    echo "== bỏ qua $name: đã đủ 1012 dòng"
    continue
  fi

  echo "== $(date -Is) bắt đầu $name  env=[${envs:-mặc định}]"
  git rev-parse --short HEAD > "$OUTDIR/full1012_$name.commit"
  printf '%s\n' "$envs" > "$OUTDIR/full1012_$name.flags"

  # --resume để một lần bị ngắt không mất cả 1.5 giờ. Không có nó thì file bị
  # truncate, đúng cách v7/v8/v9 từng mất cả lần chạy.
  resume=""
  [ -f "$out" ] && resume="--resume"

  # shellcheck disable=SC2086
  env PYTHONPATH=src $envs .venv_bge/bin/python scripts/run_graph.py \
      --all --workers "$WORKERS" --out "$out" $resume \
      > "$OUTDIR/full1012_$name.log" 2>&1

  echo "== $(date -Is) xong $name: $(wc -l < "$out") dòng"
done

echo "== $(date -Is) hàng đợi xong"
