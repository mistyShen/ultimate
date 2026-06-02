#!/usr/bin/env bash
#SBATCH --job-name=ult_sc_envs
#SBATCH --output=/shared/shen/2026/ultimate/logs/%x_%j.out
#SBATCH --error=/shared/shen/2026/ultimate/logs/%x_%j.err
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=24:00:00

set -euo pipefail

PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
CONDA_SH="${CONDA_SH:-/share/home/nshen/miniconda3/etc/profile.d/conda.sh}"
MAMBA_EXE="${MAMBA_EXE:-mamba}"
CONDARC_PATH="${ULTIMATE_CONDARC:-$PROJECT_ROOT/config/condarc.mirrors.tuna.yml}"
ENV_KEYS=("$@")
if [[ ${#ENV_KEYS[@]} -eq 0 ]]; then
  ENV_KEYS=(genome_mtdna scrna vdj spatial scatac_multiome rnaseq methylation proteomics publicdb wgcna)
fi

mkdir -p "$PROJECT_ROOT/.conda/envs" "$PROJECT_ROOT/.conda/pkgs" "$PROJECT_ROOT/logs" "$PROJECT_ROOT/audits/env_setup"
source "$CONDA_SH"
export CONDA_PKGS_DIRS="$PROJECT_ROOT/.conda/pkgs"
if [[ -f "$CONDARC_PATH" ]]; then
  export CONDARC="$CONDARC_PATH"
fi

env_file_for_key() {
  case "$1" in
    genome_mtdna) echo "$PROJECT_ROOT/envs/environment.genome_mtdna.yml" ;;
    scrna) echo "$PROJECT_ROOT/envs/environment.scrna.full.yml" ;;
    vdj) echo "$PROJECT_ROOT/envs/environment.vdj.yml" ;;
    spatial) echo "$PROJECT_ROOT/envs/environment.spatial.yml" ;;
    scatac_multiome) echo "$PROJECT_ROOT/envs/environment.scatac_multiome.yml" ;;
    rnaseq) echo "$PROJECT_ROOT/envs/environment.rnaseq.yml" ;;
    methylation) echo "$PROJECT_ROOT/envs/environment.methylation.yml" ;;
    proteomics) echo "$PROJECT_ROOT/envs/environment.proteomics.yml" ;;
    publicdb) echo "$PROJECT_ROOT/envs/environment.publicdb.yml" ;;
    wgcna) echo "$PROJECT_ROOT/envs/environment.wgcna.yml" ;;
    *) return 1 ;;
  esac
}

env_name_for_key() {
  case "$1" in
    genome_mtdna) echo "ultimate-genome-mtdna" ;;
    scrna) echo "ultimate-scrna" ;;
    vdj) echo "ultimate-vdj" ;;
    spatial) echo "ultimate-spatial" ;;
    scatac_multiome) echo "ultimate-scatac-multiome" ;;
    rnaseq) echo "ultimate-rnaseq" ;;
    methylation) echo "ultimate-methylation" ;;
    proteomics) echo "ultimate-proteomics" ;;
    publicdb) echo "ultimate-publicdb" ;;
    wgcna) echo "ultimate-wgcna" ;;
    *) return 1 ;;
  esac
}

run_env_create() {
  local key="$1"
  local env_file
  local env_name
  env_file="$(env_file_for_key "$key")"
  env_name="$(env_name_for_key "$key")"
  local prefix="$PROJECT_ROOT/.conda/envs/$env_name"
  local log="$PROJECT_ROOT/audits/env_setup/${key}.log"
  {
    echo "[$(date -Is)] key=$key"
    echo "env_file=$env_file"
    echo "prefix=$prefix"
    if [[ ! -f "$env_file" ]]; then
      echo "missing_env_file"
      return 2
    fi
    if [[ -x "$prefix/bin/python" || -x "$prefix/bin/Rscript" ]]; then
      echo "env_exists_update"
      "$MAMBA_EXE" env update -p "$prefix" -f "$env_file" --prune -y
    else
      echo "env_create"
      "$MAMBA_EXE" env create -p "$prefix" -f "$env_file" -y
    fi
    echo "[$(date -Is)] done"
  } >"$log" 2>&1
}

status=0
for key in "${ENV_KEYS[@]}"; do
  if ! run_env_create "$key"; then
    status=1
  fi
done

if [[ -x "$PROJECT_ROOT/.conda/envs/ultimate-core/bin/ultimate" ]]; then
  conda activate "$PROJECT_ROOT/.conda/envs/ultimate-core"
  ultimate audit-singlecell \
    --root "$PROJECT_ROOT" \
    --output-dir "$PROJECT_ROOT/audits/singlecell_after_env_setup" || true
fi

exit "$status"
