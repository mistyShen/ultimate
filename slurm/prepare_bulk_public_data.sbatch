#!/usr/bin/env bash
#SBATCH --job-name=ult_bulk_data
#SBATCH --output=/shared/shen/2026/ultimate/logs/%x_%j.out
#SBATCH --error=/shared/shen/2026/ultimate/logs/%x_%j.err
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=01:00:00

set -euo pipefail

PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
CORE_ENV="${ULTIMATE_CORE_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-core}"
CONDA_SH="${CONDA_SH:-/share/home/nshen/miniconda3/etc/profile.d/conda.sh}"

mkdir -p "$PROJECT_ROOT/public_data/bulk_demo" "$PROJECT_ROOT/logs"
source "$CONDA_SH"
conda activate "$CORE_ENV"

ultimate init-project --type all --output-dir "$PROJECT_ROOT/public_data/bulk_demo/project" --demo-data
