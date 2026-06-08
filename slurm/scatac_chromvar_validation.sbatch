#!/usr/bin/env bash
#SBATCH --job-name=ult_scatac_chromvar
#SBATCH --output=/shared/shen/2026/ultimate/logs/%x_%j.out
#SBATCH --error=/shared/shen/2026/ultimate/logs/%x_%j.err
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=03:00:00

set -euo pipefail

PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
CORE_ENV="${ULTIMATE_CORE_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-core}"
SCATAC_ENV="${ULTIMATE_SCATAC_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-scatac-multiome}"
SCRNA_FALLBACK_ENV="${ULTIMATE_SCRNA_FALLBACK_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-scrna}"
CONDA_SH="${CONDA_SH:-/share/home/nshen/miniconda3/etc/profile.d/conda.sh}"
INPUT_H5="${ULTIMATE_SCATAC_INPUT:-$PROJECT_ROOT/public_data/scatac/10k_pbmc_ATACv2_nextgem_Chromium_Controller_filtered_peak_bc_matrix.h5}"
OUT_DIR="${ULTIMATE_SCATAC_CHROMVAR_OUT:-$PROJECT_ROOT/validations/slurm_scatac_chromvar_signac}"

mkdir -p "$PROJECT_ROOT/logs" "$OUT_DIR/reports"
source "$CONDA_SH"

write_skip_manifest() {
  local status="$1"
  local reason="$2"
  "$CORE_ENV/bin/python" - "$OUT_DIR" "$status" "$reason" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

out = Path(sys.argv[1])
status = sys.argv[2]
reason = sys.argv[3]
out.mkdir(parents=True, exist_ok=True)
(out / "reports").mkdir(exist_ok=True)
manifest = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "module": "scatac",
    "output_dir": str(out),
    "status": status,
    "backend_validation_target": "scatac.motif.chromvar_signac",
    "analysis_level": "smoke_backend",
    "is_demo": False,
    "is_stub": True,
    "delivery_allowed": False,
    "validation_evidence_allowed": False,
    "non_delivery_reason": f"validation_not_completed:{reason}",
    "slurm_job_id": os.environ.get("SLURM_JOB_ID", ""),
    "slurm_job_name": os.environ.get("SLURM_JOB_NAME", ""),
    "slurm": {
        "job_id": os.environ.get("SLURM_JOB_ID", ""),
        "job_name": os.environ.get("SLURM_JOB_NAME", ""),
        "submit_dir": os.environ.get("SLURM_SUBMIT_DIR", ""),
    },
    "tables": [],
    "figures": [],
    "objects": {},
    "skip_reason": reason,
}
(out / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
(out / "reports" / "methods.md").write_text(
    "# scATAC chromVAR/Signac validation skipped\n\n"
    "analysis_level: `smoke_backend`\n\n"
    "delivery_allowed: `false`\n\n"
    "validation_evidence_allowed: `false`\n\n"
    f"reason: {reason}\n",
    encoding="utf-8",
)
(out / "reports" / "report.html").write_text(
    "<html><body><h1>scATAC chromVAR/Signac validation skipped</h1>"
    "<p>analysis_level: smoke_backend</p>"
    "<p>delivery_allowed: false</p>"
    f"<p>{reason}</p></body></html>",
    encoding="utf-8",
)
PY
}

select_python() {
  for candidate in "$SCATAC_ENV/bin/python" "$SCRNA_FALLBACK_ENV/bin/python" "$CORE_ENV/bin/python"; do
    if [[ -x "$candidate" ]] && "$candidate" - <<'PY' >/dev/null 2>&1
import h5py
import scipy
import anndata
import sklearn
import pandas
PY
    then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

if [[ ! -s "$INPUT_H5" ]]; then
  "$CORE_ENV/bin/python" "$PROJECT_ROOT/01_tools/prepare_public_singlecell_manifests.py" \
    --root "$PROJECT_ROOT" \
    --mode download || true
fi

if [[ ! -s "$INPUT_H5" ]]; then
  write_skip_manifest "partial:data_required" "public scATAC filtered peak matrix H5 is not available"
  exit 0
fi

if ! PYTHON_BIN="$(select_python)"; then
  write_skip_manifest "partial:dependency_required" "No Python environment with h5py/scipy/anndata/sklearn/pandas was found"
  exit 0
fi

export PYTHONPATH="$PROJECT_ROOT/src:$PROJECT_ROOT/01_tools:${PYTHONPATH:-}"
"$PYTHON_BIN" "$PROJECT_ROOT/01_tools/validate_scatac_chromvar.py" \
  --input-h5 "$INPUT_H5" \
  --output-dir "$OUT_DIR" \
  --max-peaks "${ULTIMATE_SCATAC_CHROMVAR_MAX_PEAKS:-160}"
