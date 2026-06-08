#!/usr/bin/env bash
#SBATCH --job-name=ult_scepi_backend
#SBATCH --output=/shared/shen/2026/ultimate/logs/%x_%j.out
#SBATCH --error=/shared/shen/2026/ultimate/logs/%x_%j.err
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --time=02:00:00

set -euo pipefail

PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
CORE_ENV="${ULTIMATE_CORE_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-core}"
SCATAC_ENV="${ULTIMATE_SCATAC_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-scatac-multiome}"
SCRNA_FALLBACK_ENV="${ULTIMATE_SCRNA_FALLBACK_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-scrna}"
INPUT_H5="${ULTIMATE_SCEPI_INPUT:-$PROJECT_ROOT/public_data/scatac/10k_pbmc_ATACv2_nextgem_Chromium_Controller_filtered_peak_bc_matrix.h5}"
OUT_DIR="${ULTIMATE_SCEPI_OUT:-$PROJECT_ROOT/validations/slurm_scepi_matrix}"

mkdir -p "$PROJECT_ROOT/logs" "$OUT_DIR"

select_python() {
  for candidate in "$SCATAC_ENV/bin/python" "$SCRNA_FALLBACK_ENV/bin/python" "$CORE_ENV/bin/python" python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" - <<'PY' >/dev/null 2>&1
import click
import h5py
import jinja2
import numpy
import pandas
import scipy
import sklearn
import yaml
PY
    then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

PYTHON_BIN="$(select_python || true)"
if [[ -z "${PYTHON_BIN:-}" ]]; then
  PYTHON_BIN="${CORE_ENV}/bin/python"
  if [[ ! -x "$PYTHON_BIN" ]]; then
    PYTHON_BIN="python"
  fi
fi

export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export MPLBACKEND=Agg

"$PYTHON_BIN" "$PROJECT_ROOT/01_tools/validate_scepi_public.py" \
  --output-dir "$OUT_DIR" \
  --input-h5 "$INPUT_H5" \
  --project-root "$PROJECT_ROOT" \
  --max-features "${ULTIMATE_SCEPI_MAX_FEATURES:-800}" \
  --max-cells "${ULTIMATE_SCEPI_MAX_CELLS:-240}" \
  > "$OUT_DIR/validate_scepi_public_stdout.json"
