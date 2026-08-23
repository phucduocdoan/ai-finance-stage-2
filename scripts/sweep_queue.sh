#!/usr/bin/env bash
# Chạy nối đuôi một danh sách cấu hình trên đủ 1012 câu, mỗi cấu hình một file.
#
# Vì sao là hàng đợi chứ không phải chạy tay: model local nên mỗi lần chạy miễn
# phí về tiền và chỉ tốn GPU đang rảnh, còn nút thắt là lượt nộp và sự chú ý của
# người. Xếp hàng thì GPU làm việc qua đêm.
#
# Dòng đầu của hàng đợi KHÔNG phải một đường mới: nó là lần chạy thứ hai của
# đúng cấu hình mặc định. Hai lần chạy giống nhau cho ra sàn nhiễu run-to-run,
# và không có con số đó thì mọi delta phía dưới không đọc được. Nó đo được mà
# không tốn lượt nộp nào và không cần nhãn: đếm số câu có đáp án khác nhau.
#
# ## Vì sao chia nhiều process
#
# Đo trên 722 câu của lần chạy HEAD, ba con số khớp nhau:
#
#   thread chính  98% của MỘT core, liên tục cả 2.2 giờ
#   CPU mỗi câu   10.8s  -> trần một core = 5.5 câu/phút
#   quan sát      5.4 câu/phút, với đồng thời thực tế 23.7/24 slot
#
# Tức 24 worker đều đang bận nhưng xếp hàng sau một core, còn GPU thì rảnh. Nên
# tăng `--workers` không chữa được, mà phải chia process: mỗi shard một event
# loop trên một core riêng. Máy có 32 core và chỉ đang dùng 1.
#
# Chia SO LE theo `id % N`, không theo dải id liền nhau: id 0-399 lẫn nhiều câu
# `single_cell` (trung vị ~125s) còn id 400+ là 100% `derived` (trung vị 292-524s),
# nên dải liền nhau sẽ lệch tải gấp 3 và shard nhanh phải ngồi chờ shard chậm.
#
# Mỗi shard vẫn giữ workers=24, không phải 24/N: một câu mất ~263s wall nhưng chỉ
# 10.8s CPU, tỉ lệ 24:1, nên cần ~24 câu đồng thời mới nuôi đủ một core.
#
# Dùng:
#   nohup bash scripts/sweep_queue.sh > artifacts/runs/sweep_queue.log 2>&1 &
#
# Bỏ qua cấu hình đã chạy xong (đủ 1012 dòng), nên script này chạy lại được sau
# khi bị ngắt.

set -u
cd "$(dirname "$0")/.."

WORKERS=24
SHARDS=${SHARDS:-4}
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

shard_ids() {  # shard_ids <k> <n>
  .venv_bge/bin/python - "$1" "$2" <<'PY'
import json, sys
k, n = int(sys.argv[1]), int(sys.argv[2])
ids = []
with open("data/metadata/questions_enriched.jsonl", encoding="utf-8") as fh:
    for line in fh:
        if line.strip():
            ids.append(int(json.loads(line)["id"]))
print(",".join(str(i) for i in sorted(ids) if i % n == k))
PY
}

for entry in "${QUEUE[@]}"; do
  name="${entry%%|*}"
  envs="${entry#*|}"
  out="$OUTDIR/full1012_$name.jsonl"

  if [ -f "$out" ] && [ "$(wc -l < "$out")" -ge 1012 ]; then
    echo "== bỏ qua $name: đã đủ 1012 dòng"
    continue
  fi

  echo "== $(date -Is) bắt đầu $name  env=[${envs:-mặc định}]  shards=$SHARDS"
  git rev-parse --short HEAD > "$OUTDIR/full1012_$name.commit"
  printf '%s\n' "$envs" > "$OUTDIR/full1012_$name.flags"

  pids=()
  for k in $(seq 0 $((SHARDS - 1))); do
    sout="$OUTDIR/full1012_$name.s$k.jsonl"
    # --resume để một lần bị ngắt không mất cả lần chạy. Không có nó thì file bị
    # truncate, đúng cách v7/v8/v9 từng mất cả lần chạy.
    resume=""
    [ -f "$sout" ] && resume="--resume"

    # shellcheck disable=SC2086
    env PYTHONPATH=src $envs .venv_bge/bin/python scripts/run_graph.py \
        --ids "$(shard_ids "$k" "$SHARDS")" --workers "$WORKERS" \
        --out "$sout" $resume \
        > "$OUTDIR/full1012_$name.s$k.log" 2>&1 &
    pids+=($!)
  done
  wait "${pids[@]}"

  # Gộp lại; compare_runs.py và score_clean_eval.py đọc theo id nên thứ tự dòng
  # không quan trọng.
  cat "$OUTDIR/full1012_$name".s*.jsonl > "$out"
  echo "== $(date -Is) xong $name: $(wc -l < "$out") dòng"
done

echo "== $(date -Is) hàng đợi xong"
