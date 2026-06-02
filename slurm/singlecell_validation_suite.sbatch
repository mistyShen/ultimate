#!/usr/bin/env bash
#SBATCH --job-name=ult_sc_validate
#SBATCH --output=/shared/shen/2026/ultimate/logs/%x_%j.out
#SBATCH --error=/shared/shen/2026/ultimate/logs/%x_%j.err
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=12:00:00

set -euo pipefail

PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
CORE_ENV="${ULTIMATE_CORE_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-core}"
SCRNA_ENV="${ULTIMATE_SCRNA_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-scrna}"
SCRNA_FALLBACK_ENV="${ULTIMATE_SCRNA_FALLBACK_ENV:-/shared/shen/2026/singlecell_workbench/.conda/envs/scw-py311}"
SCATAC_ENV="${ULTIMATE_SCATAC_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-scatac-py}"
SPATIAL_ENV="${ULTIMATE_SPATIAL_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-spatial-py}"
GENOME_ENV="${ULTIMATE_GENOME_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-genome-mtdna}"
CONDA_SH="${CONDA_SH:-/share/home/nshen/miniconda3/etc/profile.d/conda.sh}"

mkdir -p "$PROJECT_ROOT/logs" "$PROJECT_ROOT/audits" "$PROJECT_ROOT/validations"
source "$CONDA_SH"

write_skip_manifest() {
  local out_dir="$1"
  local status="$2"
  local reason="$3"
  mkdir -p "$out_dir/reports"
  python - "$out_dir" "$status" "$reason" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

out = Path(sys.argv[1])
status = sys.argv[2]
reason = sys.argv[3]
manifest = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "output_dir": str(out),
    "status": status,
    "skip_reason": reason,
}
(out / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
(out / "reports" / "report.md").write_text(f"# 验证跳过\n\n状态：`{status}`\n\n原因：{reason}\n", encoding="utf-8")
(out / "reports" / "report.html").write_text(f"<html><body><h1>验证跳过</h1><p>{reason}</p></body></html>", encoding="utf-8")
PY
}

run_initial_audit() {
  conda activate "$CORE_ENV"
  cd "$PROJECT_ROOT"
  ultimate audit-singlecell \
    --root "$PROJECT_ROOT" \
    --output-dir "$PROJECT_ROOT/audits/singlecell_slurm_initial"
}

run_scrna_validation() {
  local out_dir="$PROJECT_ROOT/validations/slurm_scrna_nsclc_lambrechts"
  local input_h5ad="/shared/shen/2026/nsclc_virtual_sc/02_processed_scRNA/Lambrechts_all_harmonized.h5ad"
  if [[ -x "$SCRNA_ENV/bin/python" ]]; then
    "$SCRNA_ENV/bin/python" "$PROJECT_ROOT/01_tools/validate_scrna_nsclc.py" \
      --input-h5ad "$input_h5ad" \
      --output-dir "$out_dir" \
      --max-cells "${ULTIMATE_SCRNA_MAX_CELLS:-6000}"
  elif [[ -x "$SCRNA_FALLBACK_ENV/bin/python" ]]; then
    "$SCRNA_FALLBACK_ENV/bin/python" "$PROJECT_ROOT/01_tools/validate_scrna_nsclc.py" \
      --input-h5ad "$input_h5ad" \
      --output-dir "$out_dir" \
      --max-cells "${ULTIMATE_SCRNA_MAX_CELLS:-6000}"
  else
    write_skip_manifest "$out_dir" "partial:dependency_required" "未找到 ultimate-scrna 或现有 singlecell_workbench scRNA Python 环境。"
  fi
}

run_mtdna_validation() {
  local out_dir="$PROJECT_ROOT/validations/slurm_mtdna_0518"
  if [[ -x "$GENOME_ENV/bin/python" ]]; then
    "$GENOME_ENV/bin/python" "$PROJECT_ROOT/01_tools/validate_mtdna_0518.py" \
      --source-root "/shared/shen/2026/0518" \
      --output-dir "$out_dir"
  else
    conda activate "$CORE_ENV"
    python "$PROJECT_ROOT/01_tools/validate_mtdna_0518.py" \
      --source-root "/shared/shen/2026/0518" \
      --output-dir "$out_dir"
  fi
}

run_vdj_validation() {
  local out_dir="$PROJECT_ROOT/validations/slurm_vdj_10x_pbmc"
  local input_dir="$PROJECT_ROOT/public_data/vdj"
  if [[ ! -s "$input_dir/filtered_contig_annotations.csv" || ! -s "$input_dir/clonotypes.csv" ]]; then
    write_skip_manifest "$out_dir" "partial:data_required" "未找到 public_data/vdj 下的 10x VDJ filtered_contig_annotations.csv 和 clonotypes.csv；请先通过 Slurm 运行 download_public_singlecell_data.sbatch。"
    return 0
  fi
  conda activate "$CORE_ENV"
  python "$PROJECT_ROOT/01_tools/validate_vdj_public.py" \
    --input-dir "$input_dir" \
    --output-dir "$out_dir"
  if [[ -x "$PROJECT_ROOT/.conda/envs/ultimate-vdj/bin/python" ]]; then
    LD_PRELOAD="$PROJECT_ROOT/.conda/envs/ultimate-vdj/lib/libgomp.so.1" \
      "$PROJECT_ROOT/.conda/envs/ultimate-vdj/bin/python" - <<'PY'
import scirpy as ir

adata = ir.io.read_10x_vdj(
    "/shared/shen/2026/ultimate/public_data/vdj/filtered_contig_annotations.csv",
    filtered=True,
)
print({"scirpy_vdj_cells": int(adata.n_obs)})
PY
  fi
}

run_scatac_validation() {
  local out_dir="$PROJECT_ROOT/validations/slurm_scatac_10x_pbmc"
  local input_h5="$PROJECT_ROOT/public_data/scatac/10k_pbmc_ATACv2_nextgem_Chromium_Controller_filtered_peak_bc_matrix.h5"
  if [[ ! -s "$input_h5" ]]; then
    write_skip_manifest "$out_dir" "partial:data_required" "未找到 public_data/scatac 下的 10x scATAC filtered peak matrix；请先运行公开数据下载。"
    return 0
  fi
  if [[ -x "$SCATAC_ENV/bin/python" ]]; then
    "$SCATAC_ENV/bin/python" "$PROJECT_ROOT/01_tools/validate_scatac_public.py" \
      --input-h5 "$input_h5" \
      --output-dir "$out_dir" \
      --public-data-dir "$PROJECT_ROOT/public_data/scatac"
  elif [[ -x "$SCRNA_FALLBACK_ENV/bin/python" ]]; then
    "$SCRNA_FALLBACK_ENV/bin/python" "$PROJECT_ROOT/01_tools/validate_scatac_public.py" \
      --input-h5 "$input_h5" \
      --output-dir "$out_dir" \
      --public-data-dir "$PROJECT_ROOT/public_data/scatac"
  else
    write_skip_manifest "$out_dir" "partial:dependency_required" "未找到可读取 10x H5 的 scATAC Python 环境。"
  fi
}

run_multiome_validation() {
  local out_dir="$PROJECT_ROOT/validations/slurm_multiome_10x_pbmc"
  local input_h5="$PROJECT_ROOT/public_data/multiome/10k_PBMC_Multiome_nextgem_Chromium_Controller_filtered_feature_bc_matrix.h5"
  if [[ ! -s "$input_h5" ]]; then
    write_skip_manifest "$out_dir" "partial:data_required" "未找到 public_data/multiome 下的 10x Multiome filtered feature matrix；请先运行公开数据下载。"
    return 0
  fi
  if [[ -x "$SCATAC_ENV/bin/python" ]]; then
    "$SCATAC_ENV/bin/python" "$PROJECT_ROOT/01_tools/validate_multiome_public.py" \
      --input-h5 "$input_h5" \
      --output-dir "$out_dir" \
      --public-data-dir "$PROJECT_ROOT/public_data/multiome"
  elif [[ -x "$SCRNA_FALLBACK_ENV/bin/python" ]]; then
    "$SCRNA_FALLBACK_ENV/bin/python" "$PROJECT_ROOT/01_tools/validate_multiome_public.py" \
      --input-h5 "$input_h5" \
      --output-dir "$out_dir" \
      --public-data-dir "$PROJECT_ROOT/public_data/multiome"
  else
    write_skip_manifest "$out_dir" "partial:dependency_required" "未找到可读取 10x Multiome H5 的 Python 环境。"
  fi
}

run_spatial_validation() {
  local out_dir="$PROJECT_ROOT/validations/slurm_spatial_squidpy_visium"
  if [[ -x "$SPATIAL_ENV/bin/python" ]]; then
    "$SPATIAL_ENV/bin/python" "$PROJECT_ROOT/01_tools/validate_spatial_public.py" \
      --output-dir "$out_dir" \
      --public-data-dir "$PROJECT_ROOT/public_data/spatial"
  else
    write_skip_manifest "$out_dir" "partial:dependency_required" "未找到 ultimate-spatial-py 环境，无法运行 Squidpy Visium 验证。"
  fi
}

run_final_audit() {
  conda activate "$CORE_ENV"
  cd "$PROJECT_ROOT"
  ultimate audit-singlecell \
    --root "$PROJECT_ROOT" \
    --output-dir "$PROJECT_ROOT/audits/singlecell_slurm_post_validation"
}

run_initial_audit
run_scrna_validation
run_mtdna_validation
run_vdj_validation
run_scatac_validation
run_multiome_validation
run_spatial_validation
run_final_audit
