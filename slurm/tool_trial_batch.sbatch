#!/usr/bin/env bash
#SBATCH --job-name=ult_tool_trial
#SBATCH --output=/shared/shen/2026/ultimate/logs/%x_%j.out
#SBATCH --error=/shared/shen/2026/ultimate/logs/%x_%j.err
#SBATCH --cpus-per-task=6
#SBATCH --mem=32G
#SBATCH --time=08:00:00

set -euo pipefail

BATCH="${1:-${ULTIMATE_TRIAL_BATCH:-scrna_core}}"
PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
CORE_ENV="${ULTIMATE_CORE_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-core}"
CONDA_SH="${CONDA_SH:-/share/home/nshen/miniconda3/etc/profile.d/conda.sh}"
CONDARC_PATH="${ULTIMATE_CONDARC:-$PROJECT_ROOT/config/condarc.mirrors.tuna.yml}"
INSTALL="${ULTIMATE_TRIAL_INSTALL:-0}"

mkdir -p "$PROJECT_ROOT/logs" "$PROJECT_ROOT/audits/tool_trials/$BATCH" "$PROJECT_ROOT/.conda/pkgs"
source "$CONDA_SH"
export CONDA_PKGS_DIRS="$PROJECT_ROOT/.conda/pkgs"
if [[ -f "$CONDARC_PATH" ]]; then
  export CONDARC="$CONDARC_PATH"
fi

conda activate "$CORE_ENV"
cd "$PROJECT_ROOT"

ultimate audit-tools \
  --root "$PROJECT_ROOT" \
  --output-dir "$PROJECT_ROOT/audits/tools_before_${BATCH}_${SLURM_JOB_ID:-manual}"

if [[ "$INSTALL" == "1" ]]; then
  ultimate trial-tools \
    --root "$PROJECT_ROOT" \
    --project-root "$PROJECT_ROOT" \
    --batch "$BATCH" \
    --install \
    --output-dir "$PROJECT_ROOT/audits/tool_trials/$BATCH/${SLURM_JOB_ID:-manual}"
else
  ultimate trial-tools \
    --root "$PROJECT_ROOT" \
    --project-root "$PROJECT_ROOT" \
    --batch "$BATCH" \
    --no-install \
    --output-dir "$PROJECT_ROOT/audits/tool_trials/$BATCH/${SLURM_JOB_ID:-manual}"
fi

ultimate audit-tools \
  --root "$PROJECT_ROOT" \
  --output-dir "$PROJECT_ROOT/audits/tools_after_${BATCH}_${SLURM_JOB_ID:-manual}"
