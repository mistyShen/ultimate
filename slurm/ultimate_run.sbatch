#!/usr/bin/env bash
#SBATCH --job-name=ultimate
#SBATCH --output=/shared/shen/2026/ultimate/logs/ultimate_%j.out
#SBATCH --error=/shared/shen/2026/ultimate/logs/ultimate_%j.err
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=08:00:00

set -euo pipefail

CONFIG_PATH="${1:?Usage: ultimate_run.sbatch <config.yaml>}"
PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
ENV_PREFIX="${ULTIMATE_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-core}"
CONDA_SH="${CONDA_SH:-/share/home/nshen/miniconda3/etc/profile.d/conda.sh}"
CONFIG_PATH="$(readlink -f "$CONFIG_PATH")"

mkdir -p "$PROJECT_ROOT/logs"
source "$CONDA_SH"
conda activate "$ENV_PREFIX"
cd "$PROJECT_ROOT"
PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}" python -m ultimate.cli run --config "$CONFIG_PATH"
