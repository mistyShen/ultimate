#!/usr/bin/env bash
#SBATCH --job-name=ult_tumor_backend
#SBATCH --output=/shared/shen/2026/ultimate/logs/%x_%j.out
#SBATCH --error=/shared/shen/2026/ultimate/logs/%x_%j.err
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --time=00:50:00

set -euo pipefail

PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
SCRNA_ENV="${ULTIMATE_SCRNA_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-scrna}"
CORE_ENV="${ULTIMATE_CORE_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-core}"
PYTHON_BIN="${SCRNA_ENV}/bin/python"
OUT_DIR="${ULTIMATE_TUMOR_SC_BACKEND_OUT:-$PROJECT_ROOT/validations/slurm_tumor_sc_backend_maynard}"
INPUT_H5AD="${ULTIMATE_TUMOR_SC_BACKEND_INPUT:-/shared/shen/2026/nsclc_virtual_sc/02_processed_scRNA/Maynard_raw.h5ad}"
MAX_CELLS="${ULTIMATE_TUMOR_SC_BACKEND_MAX_CELLS:-6000}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="${CORE_ENV}/bin/python"
fi
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python"
fi

write_skip_manifest() {
  mkdir -p "$OUT_DIR/reports"
  "$PYTHON_BIN" - "$OUT_DIR" "$1" "$2" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

out = Path(sys.argv[1])
status = sys.argv[2]
reason = sys.argv[3]
manifest = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "output_dir": str(out),
    "module": "tumor_sc",
    "status": status,
    "analysis_level": "smoke_backend",
    "is_demo": False,
    "is_stub": True,
    "delivery_allowed": False,
    "validation_evidence_allowed": False,
    "non_delivery_reason": f"validation_not_completed:{reason}",
    "backend_id": "tumor_sc.default.summary_handoff",
    "backend_status": "planned_fully_automatic",
    "backend_skip_reason": reason,
    "skip_reason": reason,
    "slurm_job_id": os.environ.get("SLURM_JOB_ID", ""),
    "slurm_job_name": os.environ.get("SLURM_JOB_NAME", ""),
    "slurm": {
        "job_id": os.environ.get("SLURM_JOB_ID", ""),
        "job_name": os.environ.get("SLURM_JOB_NAME", ""),
        "submit_dir": os.environ.get("SLURM_SUBMIT_DIR", ""),
    },
}
(out / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
(out / "reports" / "methods.md").write_text(
    "# tumor_sc backend validation skipped\n\n"
    "analysis_level: `smoke_backend`\n\n"
    "delivery_allowed: `false`\n\n"
    f"reason: {reason}\n",
    encoding="utf-8",
)
(out / "reports" / "report.html").write_text(
    f"<html><body><h1>tumor_sc backend validation skipped</h1><p>{reason}</p></body></html>",
    encoding="utf-8",
)
PY
}

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  write_skip_manifest "partial:dependency_required" "No Python runtime was found"
  exit 0
fi
if [[ ! -s "$INPUT_H5AD" ]]; then
  write_skip_manifest "partial:data_required" "Missing tumor_sc validation h5ad: $INPUT_H5AD"
  exit 0
fi

export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
mkdir -p "$PROJECT_ROOT/logs" "$OUT_DIR/config"

cat > "$OUT_DIR/config/project.yaml" <<YAML
project:
  name: slurm_tumor_sc_backend_maynard
  organism: human
  output_dir: $OUT_DIR
  server_root: $PROJECT_ROOT
  run_mode: interactive
  overwrite: true
samples:
  items:
    - sample_id: tumor_sc_maynard
      condition: internal_validation
      input_path: $INPUT_H5AD
design:
  condition_column: condition
  control: internal_validation
  case: internal_validation
modules:
  tumor_sc:
    enabled: true
    preset: tumor
    input_h5ad: $INPUT_H5AD
    max_cells: $MAX_CELLS
    analysis_level: validated_backend
    validation_dataset: Maynard NSCLC internal raw h5ad
    raw:
      enabled: false
      input_type: h5ad
report:
  title: tumor_sc unified backend validation
  style: soft_color
YAML

"$PYTHON_BIN" -m ultimate.cli preflight --config "$OUT_DIR/config/project.yaml" > "$OUT_DIR/preflight_stdout.json"
"$PYTHON_BIN" -m ultimate.cli run --config "$OUT_DIR/config/project.yaml" > "$OUT_DIR/run_stdout.json"
