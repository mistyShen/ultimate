#!/usr/bin/env bash
#SBATCH --job-name=ultimate
#SBATCH --output=logs/ultimate_%j.out
#SBATCH --error=logs/ultimate_%j.err
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=08:00:00

set -euo pipefail

CONFIG_PATH="${1:?Usage: ultimate_run.sbatch <config.yaml>}"
PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
ENV_PREFIX="${ULTIMATE_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-core}"

mkdir -p "$PROJECT_ROOT/logs"
source /share/home/nshen/miniconda3/etc/profile.d/conda.sh
conda activate "$ENV_PREFIX"
cd "$PROJECT_ROOT"
ultimate run --config "$CONFIG_PATH"
