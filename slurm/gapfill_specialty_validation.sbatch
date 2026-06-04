#!/usr/bin/env bash
#SBATCH --job-name=ult_gapfill_validate
#SBATCH --output=/shared/shen/2026/ultimate/logs/%x_%j.out
#SBATCH --error=/shared/shen/2026/ultimate/logs/%x_%j.err
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=01:00:00

set -euo pipefail

PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
CORE_ENV="${ULTIMATE_CORE_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-core}"
PYTHON="${CORE_ENV}/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="python"
fi

mkdir -p "$PROJECT_ROOT/logs" "$PROJECT_ROOT/validations" "$PROJECT_ROOT/audits"
export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

"$PYTHON" "$PROJECT_ROOT/01_tools/validate_perturb_seq_demo.py" \
  --output-dir "$PROJECT_ROOT/validations/slurm_perturb_seq_demo"

PERTURB_PUBLIC_H5AD="${ULTIMATE_PERTURB_SEQ_PUBLIC_H5AD:-$PROJECT_ROOT/public_data/perturb_seq/adamson_2016_pilot/adamson_2016_pilot.h5ad}"
if [[ -s "$PERTURB_PUBLIC_H5AD" ]]; then
  PERTURB_PYTHON="${ULTIMATE_SCRNA_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-scrna}/bin/python"
  if [[ ! -x "$PERTURB_PYTHON" ]]; then
    PERTURB_PYTHON="$PYTHON"
  fi
  "$PERTURB_PYTHON" "$PROJECT_ROOT/01_tools/validate_perturb_seq_demo.py" \
    --input-h5ad "$PERTURB_PUBLIC_H5AD" \
    --source-url "https://exampledata.scverse.org/pertpy/adamson_2016_pilot.h5ad" \
    --output-dir "$PROJECT_ROOT/validations/slurm_perturb_seq_adamson_public"
fi

"$PYTHON" "$PROJECT_ROOT/01_tools/validate_hto_demux_demo.py" \
  --output-dir "$PROJECT_ROOT/validations/slurm_hto_demux_demo"

HTO_PUBLIC_TABLE="${ULTIMATE_HTO_DEMUX_PUBLIC_TABLE:-$PROJECT_ROOT/public_data/hto_demux/seurat_hto12/hto12_hto_mtx_5000.tsv}"
if [[ -s "$HTO_PUBLIC_TABLE" ]]; then
  "$PYTHON" "$PROJECT_ROOT/01_tools/validate_hto_demux_demo.py" \
    --input-table "$HTO_PUBLIC_TABLE" \
    --source-url "https://satijalab.org/seurat/articles/hashing_vignette.html" \
    --output-dir "$PROJECT_ROOT/validations/slurm_hto_demux_seurat_public"
fi

"$PYTHON" "$PROJECT_ROOT/01_tools/validate_genotype_demux_demo.py" \
  --output-dir "$PROJECT_ROOT/validations/slurm_genotype_demux_demo"

GENOTYPE_PUBLIC_INPUT="${ULTIMATE_GENOTYPE_DEMUX_PUBLIC_INPUT:-$PROJECT_ROOT/public_data/genotype_demux/vireo/data/cellSNP_mat}"
if [[ -s "$GENOTYPE_PUBLIC_INPUT/cellSNP.tag.AD.mtx" && -s "$GENOTYPE_PUBLIC_INPUT/cellSNP.tag.DP.mtx" ]]; then
  "$PYTHON" "$PROJECT_ROOT/01_tools/validate_genotype_demux_demo.py" \
    --input-dir "$GENOTYPE_PUBLIC_INPUT" \
    --source-url "https://github.com/single-cell-genetics/vireo/tree/master/data/cellSNP_mat" \
    --output-dir "$PROJECT_ROOT/validations/slurm_genotype_demux_vireo_public"
fi

"$PYTHON" -m ultimate.cli audit-production \
  --root "$PROJECT_ROOT" \
  --output-dir "$PROJECT_ROOT/audits/gapfill_specialty_post_validation"
