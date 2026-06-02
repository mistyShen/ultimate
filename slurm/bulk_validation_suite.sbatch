#!/usr/bin/env bash
#SBATCH --job-name=ult_bulk_validate
#SBATCH --output=/shared/shen/2026/ultimate/logs/%x_%j.out
#SBATCH --error=/shared/shen/2026/ultimate/logs/%x_%j.err
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=06:00:00

set -euo pipefail

PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
CORE_ENV="${ULTIMATE_CORE_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-core}"
CONDA_SH="${CONDA_SH:-/share/home/nshen/miniconda3/etc/profile.d/conda.sh}"
RUN_ROOT="$PROJECT_ROOT/validations/bulk_demo_python"

mkdir -p "$PROJECT_ROOT/logs" "$PROJECT_ROOT/validations"
source "$CONDA_SH"
conda activate "$CORE_ENV"
cd "$PROJECT_ROOT"

ultimate init-project --type all --output-dir "$RUN_ROOT/project" --demo-data
ultimate preflight --config "$RUN_ROOT/project/config/project.yaml"
ultimate run --config "$RUN_ROOT/project/config/project.yaml"
