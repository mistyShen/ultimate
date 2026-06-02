#!/usr/bin/env bash
#SBATCH --job-name=ult_env_gmtdna
#SBATCH --output=/shared/shen/2026/ultimate/logs/%x_%j.out
#SBATCH --error=/shared/shen/2026/ultimate/logs/%x_%j.err
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=06:00:00

set -euo pipefail

PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
bash "$PROJECT_ROOT/slurm/setup_singlecell_envs.sbatch" genome_mtdna

