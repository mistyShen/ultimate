#!/usr/bin/env bash
#SBATCH --job-name=ult_scdna
#SBATCH --output=/shared/shen/2026/ultimate/logs/%x_%j.out
#SBATCH --error=/shared/shen/2026/ultimate/logs/%x_%j.err
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=01:00:00

set -euo pipefail

PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
CORE_ENV="${ULTIMATE_CORE_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-core}"
CONDA_SH="${CONDA_SH:-/share/home/nshen/miniconda3/etc/profile.d/conda.sh}"
SOURCE_ROOT="${ULTIMATE_SCDNA_SOURCE:-/shared/shen/2026/0518}"
OUT_DIR="${ULTIMATE_SCDNA_OUT:-$PROJECT_ROOT/validations/slurm_scdna_0518}"

mkdir -p "$PROJECT_ROOT/logs" "$PROJECT_ROOT/validations"
source "$CONDA_SH"
conda activate "$CORE_ENV"

python "$PROJECT_ROOT/01_tools/validate_scdna_0518.py" \
  --source-root "$SOURCE_ROOT" \
  --output-dir "$OUT_DIR"
