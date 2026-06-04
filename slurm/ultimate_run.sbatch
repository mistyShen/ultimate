#!/usr/bin/env bash
#SBATCH --job-name=ultimate
#SBATCH --output=/shared/shen/2026/ultimate/logs/ultimate_%j.out
#SBATCH --error=/shared/shen/2026/ultimate/logs/ultimate_%j.err
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=08:00:00

set -euo pipefail

CONFIG_PATH="${1:?Usage: ultimate_run.sbatch <config.yaml> [production_approval.json]}"
PRODUCTION_APPROVAL="${2:-}"
PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
ENV_PREFIX="${ULTIMATE_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-core}"
CONDA_SH="${CONDA_SH:-/share/home/nshen/miniconda3/etc/profile.d/conda.sh}"
CONFIG_PATH="$(readlink -f "$CONFIG_PATH")"

mkdir -p "$PROJECT_ROOT/logs"
CONFIG_DIR="$(dirname "$CONFIG_PATH")"
if [[ "$(basename "$CONFIG_DIR")" == "config" ]]; then
  JOB_DIR="$(dirname "$CONFIG_DIR")"
else
  JOB_DIR=""
fi
if [[ -n "$JOB_DIR" && "$JOB_DIR" == "$PROJECT_ROOT"/jobs/* ]]; then
  JOB_LOG_DIR="$JOB_DIR/logs"
else
  JOB_LOG_DIR="$PROJECT_ROOT/logs"
fi
mkdir -p "$JOB_LOG_DIR"
JOB_LOG_PREFIX="${SLURM_JOB_ID:-manual}_ultimate"
exec > >(tee -a "$JOB_LOG_DIR/${JOB_LOG_PREFIX}.out") 2> >(tee -a "$JOB_LOG_DIR/${JOB_LOG_PREFIX}.err" >&2)
cat > "$JOB_LOG_DIR/${JOB_LOG_PREFIX}_slurm_context.json" <<JSON
{
  "slurm_job_id": "${SLURM_JOB_ID:-}",
  "slurm_job_name": "${SLURM_JOB_NAME:-}",
  "slurm_submit_dir": "${SLURM_SUBMIT_DIR:-}",
  "slurm_cpus_per_task": "${SLURM_CPUS_PER_TASK:-}",
  "slurm_job_nodelist": "${SLURM_JOB_NODELIST:-}",
  "config_path": "$CONFIG_PATH",
  "job_dir": "$JOB_DIR",
  "project_root": "$PROJECT_ROOT"
}
JSON
source "$CONDA_SH"
conda activate "$ENV_PREFIX"
cd "$PROJECT_ROOT"
if [[ -n "$PRODUCTION_APPROVAL" ]]; then
  PRODUCTION_APPROVAL="$(readlink -f "$PRODUCTION_APPROVAL")"
  PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}" python -m ultimate.cli run --config "$CONFIG_PATH" --production-approval "$PRODUCTION_APPROVAL"
else
  PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}" python -m ultimate.cli run --config "$CONFIG_PATH"
fi
