#!/usr/bin/env bash
#SBATCH --job-name=ult_val_index
#SBATCH --output=/shared/shen/2026/ultimate/logs/%x_%j.out
#SBATCH --error=/shared/shen/2026/ultimate/logs/%x_%j.err
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=00:30:00

set -euo pipefail

PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
CORE_ENV="${ULTIMATE_CORE_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-core}"
CONDA_SH="${CONDA_SH:-/share/home/nshen/miniconda3/etc/profile.d/conda.sh}"
OUTPUT_DIR="${ULTIMATE_VALIDATION_INDEX_OUTPUT:-$PROJECT_ROOT/reports/validation_index}"

mkdir -p "$PROJECT_ROOT/logs" "$OUTPUT_DIR"
source "$CONDA_SH"
conda activate "$CORE_ENV"
cd "$PROJECT_ROOT"

ultimate validation-index --root "$PROJECT_ROOT" --output-dir "$OUTPUT_DIR"

