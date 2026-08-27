# Artifact Manifest (Phase 7)

Muc tieu: liet ke artifact nao giu, artifact nao co the don, truoc khi xoa bat cu thu gi.
Khong file nao bi xoa boi doc nay - day chi la ban kiem ke. Xoa la buoc rieng, can xac nhan.

Snapshot luc viet doc nay: `output/` (~1.2G, 40 submission dirs + 40 zip),
`artifacts/runs/` (327M, 637 file), `sofier_AI_FINANCE_snapshot/` (3.1G),
`sofier_work/` (3.1G). Tong repo ~18G.

## Keep - submissions

Minimum keep set da ghi trong `docs/refactor_plan.md`:

- `output/submission_v17_unitfix/` + `.zip` - baseline truoc hybrid, dung de doi chieu regression.
- `output/submission_v22_hybrid_answer_retrieval_with_data/` + `.zip` - baseline hybrid hien tai,
  co dir `data/` day du (v18-v21 khong co).

## Keep - runs

- `artifacts/runs/full1012_v17_unitfix.jsonl` - reproduce truc tiep baseline v17_unitfix o tren.
- `artifacts/runs/full1012_t06.jsonl` (+ `.s0-s3.jsonl/.log`, `.commit`) - arm t=0.6 dang do,
  nhac toi trong `docs/final_week_plan_2026-08-23.md:886` la chua bau xong, chua duoc gop vao
  quyet dinh nao ca.
- `artifacts/runs/full1012_all_on_a.*`, `full1012_all_on_b.*` - cap do gan nhat lien quan toi
  quyet dinh v16/v17 (commit `027ff0d`, `c4cfc08`), giu cho toi khi t=0.6 co ket luan.
- `artifacts/runs/full1012_v16.jsonl` (+ `.commit`) - run dung de chon base v16 tren priors
  (commit `027ff0d`).

## Disposable - outputs (an toan, dung "Safe cleanup candidates" trong refactor_plan.md)

- `output/submission_probe*/` va `.zip` (18 dir: probeA..probeH2) - sweep/probe cu, da bi thay the
  boi cac v-series sau nay, khong con duoc tham chieu trong docs quyet dinh.
- `output/submission_v18_sofier_hybrid/`, `v19_sofier_hybrid/`, `v20_hybrid_best_gold73/`,
  `v21_hybrid_answer_retrieval/` (+ zip tuong ung) - da xac nhan **khong co `data/`**, chi co
  `submission.json` tro choi - zip "broken hybrid" ma refactor_plan.md noi toi, bi thay the boi v22.
- `__pycache__/` (51 thu muc ngoai `.venv*`) va `.pytest_cache/` (1 thu muc) - build cache, tu sinh
  lai khi chay lai test/import.

## Keep - snapshots

- `sofier_AI_FINANCE_snapshot/` (3.1G), `sofier_work/` (3.1G) - quyet dinh giu nguyen, khong dong
  (2026-08-27).

## Da archive

- `artifacts/runs_archive_2026-08-27.tar.gz` (26M, 602 file) - toan bo `artifacts/runs/*` ngoai
  danh sach "Keep - runs" o tren, nen lai va xoa ban goc ngay 2026-08-27. `artifacts/runs/` con
  lai 33 file, dung khop "Keep - runs".

## Ask before deleting

- Cac submission dir/zip day du con lai ngoai keep set: `submission_v2` .. `submission_v17` (tru
  `v17_unitfix`), `submission_v8_round2`, `submission_v9_sign`, `submission_v10_head`..`v16`,
  `submission_graph`..`_v5`, `submission_frozen`, `submission_patched`, `submission_solver_v7`,
  `submission_codegen_qwen35`, `cell_locator_1012_submission*` (4 bien the), `submission` (goc),
  `submission_v22_hybrid_answer_retrieval` (khong `_with_data`, trung ten voi v22 co data). Zip
  cua cac dir nay co the con huu ich de doi chieu score cu.

## Not covered by this manifest

- `docs/competition/`, `docs/feasibility/`, `scripts/probe_selection_plans.py`,
  `artifacts/eval_clean/*.json` - da xac nhan khong co code nao trong `src/`/`tests/`/`scripts/`
  phu thuoc vao chung; van con untracked/chua commit, khong thuoc pham vi Phase 7 nay.
