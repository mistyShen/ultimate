#!/usr/bin/env bash
#SBATCH --job-name=ult_sc_data
#SBATCH --output=/shared/shen/2026/ultimate/logs/%x_%j.out
#SBATCH --error=/shared/shen/2026/ultimate/logs/%x_%j.err
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=08:00:00

set -euo pipefail

PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
CORE_ENV="${ULTIMATE_CORE_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-core}"
CONDA_SH="${CONDA_SH:-/share/home/nshen/miniconda3/etc/profile.d/conda.sh}"

mkdir -p "$PROJECT_ROOT/public_data" "$PROJECT_ROOT/logs"
source "$CONDA_SH"
conda activate "$CORE_ENV"

python "$PROJECT_ROOT/01_tools/prepare_public_singlecell_manifests.py" \
  --root "$PROJECT_ROOT" \
  --mode "${ULTIMATE_PUBLIC_DATA_MODE:-download}"

ultimate audit-singlecell \
  --root "$PROJECT_ROOT" \
  --output-dir "$PROJECT_ROOT/audits/singlecell_after_public_data_manifest"
