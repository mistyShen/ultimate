#!/usr/bin/env bash
#SBATCH --job-name=ult_raw_qc_style
#SBATCH --output=/shared/shen/2026/ultimate/logs/%x_%j.out
#SBATCH --error=/shared/shen/2026/ultimate/logs/%x_%j.err
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=02:00:00

set -euo pipefail

PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
CONFIG_PATH="${ULTIMATE_CONFIG:-$PROJECT_ROOT/projects/raw_qc_style_demo/config/project.yaml}"
ENV_PREFIX="${ULTIMATE_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-core}"

mkdir -p "$PROJECT_ROOT/logs"
source /share/home/nshen/miniconda3/etc/profile.d/conda.sh
conda activate "$ENV_PREFIX"
cd "$PROJECT_ROOT"
ultimate run --config "$CONFIG_PATH"
