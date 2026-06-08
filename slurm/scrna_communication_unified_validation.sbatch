#!/usr/bin/env bash
#SBATCH --job-name=ult_scrna_comm_run
#SBATCH --output=/shared/shen/2026/ultimate/logs/%x_%j.out
#SBATCH --error=/shared/shen/2026/ultimate/logs/%x_%j.err
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --time=04:00:00

set -euo pipefail

PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
SCRNA_ENV="${ULTIMATE_SCRNA_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-scrna}"
CONDA_SH="${CONDA_SH:-/share/home/nshen/miniconda3/etc/profile.d/conda.sh}"
OUT_DIR="${ULTIMATE_SCRNA_COMM_OUT:-$PROJECT_ROOT/validations/slurm_scrna_communication_unified}"
MATRIX_DIR="${ULTIMATE_SCRNA_COMM_MATRIX:-$PROJECT_ROOT/public_data/scrna_pbmc3k/filtered_gene_bc_matrices/hg19}"
CONFIG_PATH="$OUT_DIR/config/project.yaml"
SAMPLESHEET="$OUT_DIR/config/samples.tsv"

mkdir -p "$PROJECT_ROOT/logs" "$OUT_DIR/config"

cat > "$SAMPLESHEET" <<TSV
sample_id	condition	input_path
PBMC3K	public_validation	$MATRIX_DIR
TSV

cat > "$CONFIG_PATH" <<YAML
project:
  name: slurm_scrna_communication_unified
  organism: human
  output_dir: $OUT_DIR
  server_root: $PROJECT_ROOT
  run_mode: slurm_validation
  delivery_scope: not_customer_delivery
  allow_overwrite: true
samples:
  samplesheet: $SAMPLESHEET
design:
  condition: condition
modules:
  scrna:
    enabled: true
    preset: communication
    input_path: $MATRIX_DIR
    input_type: 10x_mtx
    samplesheet: $SAMPLESHEET
    analysis_level: validated_backend
    public_dataset: true
    dataset_label: 10x_pbmc3k_public_matrix_unified_run
    max_cells: ${ULTIMATE_SCRNA_COMM_MAX_CELLS:-350}
    backends:
      communication: liana,cellchat
      annotation: celltypist
report:
  title: scRNA communication preset unified validation
  style: soft_color
YAML

if [[ ! -d "$MATRIX_DIR" ]]; then
  echo "Missing PBMC3k matrix directory: $MATRIX_DIR" >&2
  exit 2
fi
if [[ ! -x "$SCRNA_ENV/bin/python" ]]; then
  echo "Missing scRNA environment: $SCRNA_ENV" >&2
  exit 2
fi

if [[ -f "$CONDA_SH" ]]; then
  # shellcheck disable=SC1090
  source "$CONDA_SH"
  conda activate "$SCRNA_ENV"
else
  export PATH="$SCRNA_ENV/bin:$PATH"
fi

cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT/src:${PYTHONPATH:-}"
python -m ultimate.cli run --config "$CONFIG_PATH"
