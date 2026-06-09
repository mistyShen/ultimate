#!/usr/bin/env bash
#SBATCH --job-name=ult_scatac_backend
#SBATCH --output=/shared/shen/2026/ultimate/logs/%x_%j.out
#SBATCH --error=/shared/shen/2026/ultimate/logs/%x_%j.err
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=04:00:00

set -euo pipefail

PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
CORE_ENV="${ULTIMATE_CORE_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-core}"
SCATAC_ENV="${ULTIMATE_SCATAC_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-scatac-multiome}"
SCRNA_FALLBACK_ENV="${ULTIMATE_SCRNA_FALLBACK_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-scrna}"
CONDA_SH="${CONDA_SH:-/share/home/nshen/miniconda3/etc/profile.d/conda.sh}"
INPUT_H5="${ULTIMATE_SCATAC_INPUT:-$PROJECT_ROOT/public_data/scatac/10k_pbmc_ATACv2_nextgem_Chromium_Controller_filtered_peak_bc_matrix.h5}"
OUT_DIR="${ULTIMATE_SCATAC_OUT:-$PROJECT_ROOT/validations/slurm_scatac_10x_pbmc}"

mkdir -p "$PROJECT_ROOT/logs" "$OUT_DIR/config" "$OUT_DIR/reports"
source "$CONDA_SH"

select_python() {
  for candidate in "$SCATAC_ENV/bin/python" "$SCRNA_FALLBACK_ENV/bin/python" "$CORE_ENV/bin/python"; do
    if [[ -x "$candidate" ]] && "$candidate" - <<'PY' >/dev/null 2>&1
import click
import jinja2
import yaml
import h5py
import scipy
import anndata
import sklearn
PY
    then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

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
    "analysis_level": "smoke_backend",
    "is_demo": False,
    "is_stub": True,
    "delivery_allowed": False,
    "validation_evidence_allowed": False,
    "non_delivery_reason": f"validation_not_completed:{reason}",
    "backend_id": "scatac.matrix.signac_or_snapatac2_mvp",
    "backend_status": "fully_automatic_validated_entrypoint",
    "backend_skip_reason": reason,
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
    "# scATAC unified backend validation skipped\n\n"
    "analysis_level: `smoke_backend`\n\n"
    "delivery_allowed: `false`\n\n"
    "validation_evidence_allowed: `false`\n\n"
    f"reason: {reason}\n",
    encoding="utf-8",
)
(out / "reports" / "report.html").write_text(
    "<html><body><h1>scATAC unified backend validation skipped</h1>"
    "<p>analysis_level: smoke_backend</p>"
    "<p>delivery_allowed: false</p>"
    f"<p>{reason}</p></body></html>",
    encoding="utf-8",
)
PY
}

if [[ ! -s "$INPUT_H5" ]]; then
  "$CORE_ENV/bin/python" "$PROJECT_ROOT/01_tools/prepare_public_singlecell_manifests.py" \
    --root "$PROJECT_ROOT" \
    --mode download || true
fi

if [[ ! -s "$INPUT_H5" ]]; then
  write_skip_manifest "partial:data_required" "public_data/scatac lacks 10x scATAC filtered peak matrix H5 after download attempt"
  exit 0
fi

if ! PYTHON_BIN="$(select_python)"; then
  write_skip_manifest "partial:dependency_required" "No Python environment with h5py, scipy, anndata, sklearn, click, jinja2, and yaml was found"
  exit 0
fi

export PYTHONPATH="$PROJECT_ROOT/src"
CELL_METADATA="$OUT_DIR/config/cell_metadata.tsv"
"$PYTHON_BIN" - "$INPUT_H5" "$CELL_METADATA" <<'PY'
import sys
from pathlib import Path

import h5py
import pandas as pd

input_h5 = Path(sys.argv[1])
out = Path(sys.argv[2])
out.parent.mkdir(parents=True, exist_ok=True)
with h5py.File(input_h5, "r") as handle:
    barcodes = [
        value.decode("utf-8") if isinstance(value, bytes) else str(value)
        for value in handle["matrix"]["barcodes"][:]
    ]
limit = min(len(barcodes), int(__import__("os").environ.get("ULTIMATE_SCATAC_VALIDATION_CELLS", "1200")))
barcodes = barcodes[:limit]
split = max(2, limit // 2)
labels = ["control" if idx < split else "treated" for idx in range(limit)]
if labels.count("treated") < 2 and limit >= 4:
    labels[-2:] = ["treated", "treated"]
pd.DataFrame(
    {
        "cell_id": barcodes,
        "condition": labels,
        "validation_note": "validation-only synthetic condition labels for DAR backend smoke; not biological annotation",
    }
).to_csv(out, sep="\t", index=False)
PY

cat > "$OUT_DIR/config/project.yaml" <<YAML
project:
  name: slurm_scatac_10x_pbmc
  organism: human
  output_dir: $OUT_DIR
  server_root: $PROJECT_ROOT
  run_mode: interactive
  overwrite: true
samples:
  items:
    - sample_id: pbmc_scatac
      condition: public_validation
      input_path: $INPUT_H5
design:
  condition_column: condition
  control: control
  case: treated
modules:
  scatac:
    enabled: true
    preset: publication
    input_h5: $INPUT_H5
    cell_metadata: $CELL_METADATA
    analysis_level: validated_backend
    public_dataset: true
    max_cells_object: ${ULTIMATE_SCATAC_MAX_CELLS_OBJECT:-3000}
    max_peaks_object: ${ULTIMATE_SCATAC_MAX_PEAKS_OBJECT:-2500}
    raw:
      enabled: false
      input_type: peak_matrix
report:
  title: 10x PBMC scATAC unified backend validation
  style: soft_color
YAML

"$PYTHON_BIN" -m ultimate.cli preflight --config "$OUT_DIR/config/project.yaml" > "$OUT_DIR/preflight_stdout.json"
"$PYTHON_BIN" -m ultimate.cli run --config "$OUT_DIR/config/project.yaml" > "$OUT_DIR/run_stdout.json"
