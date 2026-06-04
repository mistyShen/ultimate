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
OUTPUT_DIR="${ULTIMATE_VALIDATION_INDEX_OUTPUT:-$PROJECT_ROOT/reports/validation_index}"

mkdir -p "$PROJECT_ROOT/logs" "$OUTPUT_DIR"
cd "$PROJECT_ROOT"

PYTHONPATH="$PROJECT_ROOT/src" "$CORE_ENV/bin/python" -m ultimate.cli validation-index --root "$PROJECT_ROOT" --output-dir "$OUTPUT_DIR"
