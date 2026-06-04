#!/usr/bin/env bash
#SBATCH --job-name=ult_tumor_raw
#SBATCH --output=/shared/shen/2026/ultimate/logs/%x_%j.out
#SBATCH --error=/shared/shen/2026/ultimate/logs/%x_%j.err
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --time=04:00:00

set -euo pipefail

PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
export ULTIMATE_TUMOR_SC_INPUT="${ULTIMATE_TUMOR_SC_INPUT:-/shared/shen/2026/nsclc_virtual_sc/02_processed_scRNA/Maynard_raw.h5ad}"
export ULTIMATE_TUMOR_SC_OUT="${ULTIMATE_TUMOR_SC_OUT:-$PROJECT_ROOT/validations/slurm_tumor_sc_maynard_raw_counts}"
export ULTIMATE_TUMOR_SC_MAX_CELLS="${ULTIMATE_TUMOR_SC_MAX_CELLS:-3000}"
export ULTIMATE_TUMOR_SC_RUN_COPYKAT="${ULTIMATE_TUMOR_SC_RUN_COPYKAT:-1}"
export ULTIMATE_TUMOR_SC_RUN_INFERCNV="${ULTIMATE_TUMOR_SC_RUN_INFERCNV:-1}"
export ULTIMATE_TUMOR_SC_GENE_ORDER_REF="${ULTIMATE_TUMOR_SC_GENE_ORDER_REF:-/shared/shen/2026/nsclc_virtual_sc/02_processed_scRNA/Lambrechts_all_harmonized.h5ad}"

bash "$PROJECT_ROOT/slurm/tumor_sc_validation.sbatch"
