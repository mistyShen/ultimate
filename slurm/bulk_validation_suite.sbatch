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
RNASEQ_PUBLIC_RUN="$PROJECT_ROOT/validations/slurm_rnaseq_airway_public"
TABULAR_PUBLIC_RUN="$PROJECT_ROOT/validations/slurm_tabular_airway_public"
METHYLATION_PUBLIC_RUN="$PROJECT_ROOT/validations/slurm_methylation_arrmdata_public"

mkdir -p "$PROJECT_ROOT/logs" "$PROJECT_ROOT/validations"
source "$CONDA_SH"
conda activate "$CORE_ENV"
cd "$PROJECT_ROOT"
export ULTIMATE_ALLOW_OVERWRITE=1

python "$PROJECT_ROOT/01_tools/validate_rnaseq_public.py" \
  --output-dir "$RNASEQ_PUBLIC_RUN" \
  --public-data-dir "$PROJECT_ROOT/public_data/rnaseq_airway"

python "$PROJECT_ROOT/01_tools/validate_tabular_public.py" \
  --output-dir "$TABULAR_PUBLIC_RUN" \
  --public-data-dir "$PROJECT_ROOT/public_data/rnaseq_airway"

python "$PROJECT_ROOT/01_tools/validate_methylation_public.py" \
  --output-dir "$METHYLATION_PUBLIC_RUN" \
  --public-data-dir "$PROJECT_ROOT/public_data/methylation_arrmdata"

ultimate init-project --type all --output-dir "$RUN_ROOT/project" --demo-data
ultimate preflight --config "$RUN_ROOT/project/config/project.yaml"
ultimate run --config "$RUN_ROOT/project/config/project.yaml"
