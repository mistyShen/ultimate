#!/usr/bin/env bash
#SBATCH --job-name=ult_spatial_backend
#SBATCH --output=/shared/shen/2026/ultimate/logs/%x_%j.out
#SBATCH --error=/shared/shen/2026/ultimate/logs/%x_%j.err
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --time=04:00:00

set -euo pipefail

PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
CORE_ENV="${ULTIMATE_CORE_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-core}"
SPATIAL_ENV="${ULTIMATE_SPATIAL_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-spatial-py}"
SCRNA_FALLBACK_ENV="${ULTIMATE_SCRNA_FALLBACK_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-scrna}"
CONDA_SH="${CONDA_SH:-/share/home/nshen/miniconda3/etc/profile.d/conda.sh}"
PUBLIC_DATA_DIR="${ULTIMATE_SPATIAL_PUBLIC_DATA:-$PROJECT_ROOT/public_data/spatial}"
OUT_DIR="${ULTIMATE_SPATIAL_OUT:-$PROJECT_ROOT/validations/slurm_spatial_squidpy_visium}"

mkdir -p "$PROJECT_ROOT/logs" "$OUT_DIR/config" "$OUT_DIR/reports" "$PUBLIC_DATA_DIR"
source "$CONDA_SH"

select_python() {
  for candidate in "$SPATIAL_ENV/bin/python" "$SCRNA_FALLBACK_ENV/bin/python" "$CORE_ENV/bin/python"; do
    if [[ -x "$candidate" ]] && "$candidate" - <<'PY' >/dev/null 2>&1
import click
import jinja2
import yaml
import scanpy
import anndata
import squidpy
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
    "module": "spatial",
    "output_dir": str(out),
    "status": status,
    "analysis_level": "smoke_backend",
    "is_demo": False,
    "is_stub": True,
    "delivery_allowed": False,
    "validation_evidence_allowed": False,
    "non_delivery_reason": f"validation_not_completed:{reason}",
    "backend_id": "spatial.visium.squidpy_mvp",
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
    "# Spatial unified backend validation skipped\n\n"
    "analysis_level: `smoke_backend`\n\n"
    "delivery_allowed: `false`\n\n"
    "validation_evidence_allowed: `false`\n\n"
    f"reason: {reason}\n",
    encoding="utf-8",
)
(out / "reports" / "report.html").write_text(
    "<html><body><h1>Spatial unified backend validation skipped</h1>"
    "<p>analysis_level: smoke_backend</p>"
    "<p>delivery_allowed: false</p>"
    f"<p>{reason}</p></body></html>",
    encoding="utf-8",
)
PY
}

if ! PYTHON_BIN="$(select_python)"; then
  write_skip_manifest "partial:dependency_required" "No Python environment with scanpy, anndata, squidpy, sklearn, click, jinja2, and yaml was found"
  exit 0
fi

export PYTHONPATH="$PROJECT_ROOT/src"

cat > "$OUT_DIR/config/project.yaml" <<YAML
project:
  name: slurm_spatial_squidpy_visium
  organism: human
  output_dir: $OUT_DIR
  server_root: $PROJECT_ROOT
  run_mode: interactive
  overwrite: true
samples:
  items:
    - sample_id: visium_hne
      condition: public_validation
      input_path: $PUBLIC_DATA_DIR
design:
  condition_column: condition
  control: public_validation
  case: public_validation
modules:
  spatial:
    enabled: true
    preset: standard
    analysis_level: validated_backend
    public_dataset: true
    validation_dataset: squidpy_visium_hne
    public_data_dir: $PUBLIC_DATA_DIR
    max_spots_object: ${ULTIMATE_SPATIAL_MAX_SPOTS_OBJECT:-3000}
    raw:
      enabled: false
      input_type: visium_h5ad
report:
  title: Squidpy Visium spatial unified backend validation
  style: soft_color
YAML

"$PYTHON_BIN" -m ultimate.cli preflight --config "$OUT_DIR/config/project.yaml" > "$OUT_DIR/preflight_stdout.json"
"$PYTHON_BIN" -m ultimate.cli run --config "$OUT_DIR/config/project.yaml" > "$OUT_DIR/run_stdout.json"
