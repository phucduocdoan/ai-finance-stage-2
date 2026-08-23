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

# ## Vì sao xếp chồng chứ không phải mỗi cờ một arm
#
# So sánh theo cặp: nếu churn run-to-run là `C` câu thì SE của hiệu ròng là ~`sqrt(C)`.
# Quy tắc §11.2 nói một đường điển hình đáng +8 câu trên 1012 (+3/119 trên eval sạch đã
# ra +0.79pp). Nên:
#
#   một cờ đơn lẻ   +8 câu   SE ~9.9   z = 0.8   -> không đọc được
#   chồng 5 cờ      +40 câu  SE ~11.4  z = 3.5   -> đọc được
#
# 13 arm đơn lẻ tốn 41 giờ rồi vẫn không kết luận được gì, tức lặp lại đúng cái đã giết
# chín đường trước, chỉ đổi thước đo. Chồng thắng thì bisect theo nửa chỉ tốn thêm ~2 lần.
#
# Các "tiên nghiệm âm" trước đây KHÔNG đủ để loại một cờ khỏi chồng, và chỗ này tôi đã
# tự mâu thuẫn một lần: `metric_hints` 38 so với 42 là chênh 4 câu trên 94, `screening`
# 2/29 so với 4/29 là chênh 2 câu. Đó đúng cỡ mẫu mà lập luận trên vừa nói là không phân
# giải nổi ±8 câu. Nên chúng là nhiễu, không phải bằng chứng âm. Ngoại lệ duy nhất là
# `screening`, vì nó có lập luận CẤU TRÚC độc lập với n: truy vấn sàng lọc đọc 6-12 ô,
# mỗi ô cần đúng dòng, đúng cột, đúng đơn vị, nên ở 51% một ô thì `0.51^8` ~ 0.5%.
#
# Vì thế arm thứ hai là BẬT HẾT, không phải một chồng đã lọc: nó là arm tín hiệu mạnh
# nhất và giá chỉ là một lần chạy. Bật hết mà ngang sàn nhiễu thì cả không gian cờ này
# vô giá trị và dừng; thắng đậm thì bisect theo nửa.
#
# Ba núm thinking để ngoài, và lý do đọc được từ code chứ không cần probe: chúng làm LỖI
# chứ không làm điểm thấp.
#
#   raw_table_linker.py:1601/1633/1827  thinking=cờ, max_tokens=768   <- không nâng
#   raw_table_linker.py:1670            thinking=cờ, max_tokens=1024  <- không nâng
#   formula_facts.py:433                thinking=cờ, max_tokens=768   <- không nâng
#   structured_facts.py:1553-1554       thinking=cờ, max_tokens=8192 khi bật
#
# Chỉ chỗ cuối nâng ngân sách. Và bằng chứng đã ghi là structured_facts bản thinking chết
# bằng LengthFinishReasonError ở 2048 token trên cả 12 câu, cần tới 8192 mới parse được,
# rồi vẫn ra selection plan sai. Nên hai cờ kia bật lên là lỗi mọi lần gọi: chúng VỠ SẴN,
# không phải "chưa đo". Sửa được bằng 2 dòng nâng max_tokens, nhưng đó là thay đổi code
# chứ không phải bật cờ, nên nó không thuộc arm này.
#
# "tên|env" — env rỗng nghĩa là dùng mặc định trong code.
QUEUE=(
  # 1. Sàn nhiễu. Không phải một đường. Mọi dòng dưới vô nghĩa nếu thiếu nó.
  "head_b|"
  # 2. Bật hết: 12 cờ đang False, cộng ba số nâng lên. Trừ ba núm thinking (xem trên) và
  #    trừ `screening` (lập luận cấu trúc). `SOLVE_VERIFY_ANSWER` giữ nguyên True vì tắt
  #    nó là bỏ một bước, không phải bật một cờ.
  "all_on|SOLVE_METRIC_HINTS=1 SOLVE_METRIC_LOOKUP=1 SOLVE_TABLE_PROFILES=1 SOLVE_PROFILE_VALIDATE=1 SOLVE_RAW_TABLE_LINKER_RATIO_GROUPS=1 SOLVE_REPAIR_HISTORY=1 SOLVE_STRUCTURED_FACTS=1 SOLVE_DECOMPOSE=1 SOLVE_MAX_TABLES_MULTI_COMPANY=12 SOLVE_SUB_TABLES=12 SOLVE_TOOL_TURNS=3"
  # 3-4. Bisect theo nửa, chỉ chạy nếu all_on lệch khỏi sàn nhiễu. Chia theo TẦNG chứ
  #      không chia bừa: nửa A đổi thứ prompt được nhìn thấy, nửa B đổi cách giải.
  "all_on_a|SOLVE_METRIC_HINTS=1 SOLVE_METRIC_LOOKUP=1 SOLVE_TABLE_PROFILES=1 SOLVE_PROFILE_VALIDATE=1 SOLVE_MAX_TABLES_MULTI_COMPANY=12 SOLVE_SUB_TABLES=12 SOLVE_TOOL_TURNS=3"
  "all_on_b|SOLVE_RAW_TABLE_LINKER_RATIO_GROUPS=1 SOLVE_REPAIR_HISTORY=1 SOLVE_STRUCTURED_FACTS=1 SOLVE_DECOMPOSE=1"
  # 5. Arm đối chứng, đứng riêng vì nó TẮT một bước: verify có đáng độ trễ của nó không.
  "no_verify|SOLVE_VERIFY_ANSWER=0"
  # 6. Lập luận cấu trúc nói nó sẽ chết, nhưng giá bây giờ là một lần chạy nên vẫn đo.
  "screening|SOLVE_SCREENING=1"
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
