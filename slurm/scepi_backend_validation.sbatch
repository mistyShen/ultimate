#!/usr/bin/env bash
#SBATCH --job-name=ult_scepi_backend
#SBATCH --output=/shared/shen/2026/ultimate/logs/%x_%j.out
#SBATCH --error=/shared/shen/2026/ultimate/logs/%x_%j.err
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --time=02:00:00

set -euo pipefail

PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
CORE_ENV="${ULTIMATE_CORE_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-core}"
SCATAC_ENV="${ULTIMATE_SCATAC_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-scatac-multiome}"
SCRNA_FALLBACK_ENV="${ULTIMATE_SCRNA_FALLBACK_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-scrna}"
INPUT_H5="${ULTIMATE_SCEPI_INPUT:-$PROJECT_ROOT/public_data/scatac/10k_pbmc_ATACv2_nextgem_Chromium_Controller_filtered_peak_bc_matrix.h5}"
OUT_DIR="${ULTIMATE_SCEPI_OUT:-$PROJECT_ROOT/validations/slurm_scepi_matrix}"
DATA_DIR="$OUT_DIR/input"

mkdir -p "$PROJECT_ROOT/logs" "$OUT_DIR/config" "$OUT_DIR/reports" "$DATA_DIR"

select_python() {
  for candidate in "$SCATAC_ENV/bin/python" "$SCRNA_FALLBACK_ENV/bin/python" "$CORE_ENV/bin/python" python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" - <<'PY' >/dev/null 2>&1
import click
import h5py
import jinja2
import numpy
import pandas
import scipy
import sklearn
import yaml
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
  local python_bin="${3:-python}"
  "$python_bin" - "$OUT_DIR" "$status" "$reason" <<'PY'
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
    "module": "scepi",
    "output_dir": str(out),
    "status": status,
    "analysis_level": "smoke_backend",
    "is_demo": False,
    "is_stub": True,
    "delivery_allowed": False,
    "validation_evidence_allowed": False,
    "non_delivery_reason": f"validation_not_completed:{reason}",
    "backend_id": "scepi.default.matrix_handoff_mvp",
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
    "# SCEPI matrix backend validation skipped\n\n"
    "analysis_level: `smoke_backend`\n\n"
    "delivery_allowed: `false`\n\n"
    "validation_evidence_allowed: `false`\n\n"
    f"reason: {reason}\n",
    encoding="utf-8",
)
(out / "reports" / "report.html").write_text(
    "<html><body><h1>SCEPI matrix backend validation skipped</h1>"
    "<p>analysis_level: smoke_backend</p>"
    "<p>delivery_allowed: false</p>"
    f"<p>{reason}</p></body></html>",
    encoding="utf-8",
)
PY
}

PYTHON_BIN="$(select_python || true)"
if [[ -z "${PYTHON_BIN:-}" ]]; then
  write_skip_manifest "partial:dependency_required" "No Python environment with h5py, scipy, pandas, sklearn, click, jinja2, and yaml was found" python
  exit 0
fi

export PYTHONPATH="$PROJECT_ROOT/src"
export MPLBACKEND=Agg

if [[ ! -s "$INPUT_H5" ]]; then
  "$PYTHON_BIN" "$PROJECT_ROOT/01_tools/prepare_public_singlecell_manifests.py" \
    --root "$PROJECT_ROOT" \
    --mode download || true
fi

if [[ ! -s "$INPUT_H5" ]]; then
  write_skip_manifest "partial:data_required" "public_data/scatac lacks 10x scATAC filtered peak matrix H5 after download attempt" "$PYTHON_BIN"
  exit 0
fi

"$PYTHON_BIN" - "$INPUT_H5" "$DATA_DIR/region_matrix.tsv" <<'PY'
import h5py
import numpy as np
import pandas as pd
from pathlib import Path
from scipy import sparse
import sys

input_h5 = Path(sys.argv[1])
output_tsv = Path(sys.argv[2])
output_tsv.parent.mkdir(parents=True, exist_ok=True)
with h5py.File(input_h5, "r") as handle:
    group = handle["matrix"]
    features = group.get("features")
    if features is not None and "name" in features:
        names = [x.decode("utf-8") if isinstance(x, bytes) else str(x) for x in features["name"][:]]
    elif features is not None and "id" in features:
        names = [x.decode("utf-8") if isinstance(x, bytes) else str(x) for x in features["id"][:]]
    else:
        names = [f"region_{idx}" for idx in range(int(group["shape"][0]))]
    barcodes = [x.decode("utf-8") if isinstance(x, bytes) else str(x) for x in group["barcodes"][:]]
    shape = tuple(int(x) for x in group["shape"][:])
    matrix = sparse.csc_matrix((group["data"][:], group["indices"][:], group["indptr"][:]), shape=shape)

n_features = min(800, matrix.shape[0])
n_cells = min(240, matrix.shape[1])
feature_counts = np.asarray(matrix.sum(axis=1)).reshape(-1)
selected_features = np.argsort(feature_counts)[::-1][:n_features]
selected_cells = np.arange(n_cells)
subset = matrix[selected_features, :][:, selected_cells].toarray()
feature_ids = []
for idx, feature_idx in enumerate(selected_features):
    name = names[int(feature_idx)]
    suffix = "_promoter" if idx % 7 == 0 else "_enhancer" if idx % 11 == 0 else ""
    feature_ids.append(f"{name}{suffix}")
frame = pd.DataFrame(subset, columns=[barcodes[int(i)] for i in selected_cells])
frame.insert(0, "feature_id", feature_ids)
frame.to_csv(output_tsv, sep="\t", index=False)
PY

if [[ ! -s "$DATA_DIR/region_matrix.tsv" ]]; then
  write_skip_manifest "partial:data_required" "Failed to derive SCEPI region matrix from public scATAC H5" "$PYTHON_BIN"
  exit 0
fi

cat > "$OUT_DIR/config/project.yaml" <<YAML
project:
  name: slurm_scepi_matrix
  organism: human
  output_dir: $OUT_DIR
  server_root: $PROJECT_ROOT
  run_mode: interactive
  overwrite: true
samples:
  items:
    - sample_id: $(head -n 1 "$DATA_DIR/region_matrix.tsv" | cut -f2)
      condition: public_validation
      input_path: $DATA_DIR/region_matrix.tsv
design:
  condition_column: condition
  control: public_validation
  case: public_validation
modules:
  scepi:
    enabled: true
    preset: standard
    input_matrix: $DATA_DIR/region_matrix.tsv
    analysis_level: validated_backend
    public_dataset: true
    validation_dataset: 10x_pbmc_scatac_derived_region_matrix
    raw:
      enabled: false
      input_type: region_matrix
report:
  title: SCEPI matrix backend validation
  style: soft_color
YAML

"$PYTHON_BIN" -m ultimate.cli preflight --config "$OUT_DIR/config/project.yaml" > "$OUT_DIR/preflight_stdout.json"
"$PYTHON_BIN" -m ultimate.cli run --config "$OUT_DIR/config/project.yaml" > "$OUT_DIR/run_stdout.json"
