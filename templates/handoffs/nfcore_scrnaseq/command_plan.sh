#!/usr/bin/env bash
set -euo pipefail

JOB_ID="${1:?usage: command_plan.sh <job_id>}"
ULTIMATE_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
JOB_ROOT="${ULTIMATE_ROOT}/jobs/${JOB_ID}"
CONFIG_DIR="${JOB_ROOT}/config"
RUN_DIR="${JOB_ROOT}/runs/nfcore_scrnaseq"
WORK_DIR="${JOB_ROOT}/work/nfcore_scrnaseq"

cat <<PLAN
# Reviewed command plan only. Ultimate does not execute nf-core/scrnaseq.
# Submit this through Slurm only after FASTQ paths, reference settings, protocol,
# container cache, and storage budget have been manually reviewed.

set -euo pipefail

export NXF_HOME="${ULTIMATE_ROOT}/.nextflow"
export NXF_WORK="${WORK_DIR}"
mkdir -p "${RUN_DIR}" "${WORK_DIR}" "${ULTIMATE_ROOT}/logs"

nextflow run nf-core/scrnaseq \\
  -profile apptainer,slurm \\
  -c "${CONFIG_DIR}/nfcore_scrnaseq_nextflow.config" \\
  -params-file "${CONFIG_DIR}/nfcore_scrnaseq_params.yaml" \\
  -work-dir "\${NXF_WORK}" \\
  -resume
PLAN
