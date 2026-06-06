#!/usr/bin/env bash
#SBATCH --job-name=ult_scrna_velocity
#SBATCH --output=/shared/shen/2026/ultimate/logs/%x_%j.out
#SBATCH --error=/shared/shen/2026/ultimate/logs/%x_%j.err
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=02:00:00

set -euo pipefail

PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
SCRNA_HEAVY_ENV="${ULTIMATE_SCRNA_HEAVY_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-scrna-heavy}"
PYTHON_BIN="${SCRNA_HEAVY_ENV}/bin/python"
OUT_DIR="${ULTIMATE_SCRNA_VELOCITY_OUT:-$PROJECT_ROOT/validations/slurm_scrna_velocity_pancreas}"
CACHE_DIR="${ULTIMATE_SCRNA_VELOCITY_CACHE:-$PROJECT_ROOT/public_data/scrna_velocity}"
INPUT_H5AD="${ULTIMATE_SCRNA_VELOCITY_INPUT:-$CACHE_DIR/pancreas.h5ad}"
MAX_CELLS="${ULTIMATE_SCRNA_VELOCITY_MAX_CELLS:-900}"
MAX_GENES="${ULTIMATE_SCRNA_VELOCITY_MAX_GENES:-1600}"

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
    "module": "scrna",
    "status": status,
    "analysis_level": "smoke_backend",
    "is_demo": False,
    "is_stub": True,
    "delivery_allowed": False,
    "validation_evidence_allowed": False,
    "non_delivery_reason": f"validation_not_completed:{reason}",
    "backend_id": "scrna.velocity.scvelo",
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
    "# scRNA velocity validation skipped\n\n"
    "analysis_level: `smoke_backend`\n\n"
    "delivery_allowed: `false`\n\n"
    f"reason: {reason}\n",
    encoding="utf-8",
)
(out / "reports" / "report.html").write_text(
    f"<html><body><h1>scRNA velocity validation skipped</h1><p>{reason}</p></body></html>",
    encoding="utf-8",
)
PY
}

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  write_skip_manifest "partial:dependency_required" "No Python runtime was found"
  exit 0
fi

mkdir -p "$PROJECT_ROOT/logs" "$CACHE_DIR" "$OUT_DIR/config"
export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export MPLBACKEND=Agg

if [[ ! -s "$INPUT_H5AD" ]]; then
  "$PYTHON_BIN" - "$INPUT_H5AD" <<'PY' || true
from pathlib import Path
import sys

path = Path(sys.argv[1])
path.parent.mkdir(parents=True, exist_ok=True)
try:
    import scvelo as scv

    adata = scv.datasets.pancreas(file_path=str(path))
    required = {"spliced", "unspliced"}
    if not required.issubset(set(adata.layers.keys())):
        raise RuntimeError(f"Downloaded pancreas dataset lacks required velocity layers: {sorted(adata.layers.keys())}")
    adata.write_h5ad(path)
    print(f"cached_velocity_dataset={path}")
except Exception as exc:
    print(f"velocity_dataset_download_failed:{type(exc).__name__}:{exc}")
    if path.exists() and path.stat().st_size == 0:
        path.unlink()
    raise
PY
fi

if [[ ! -s "$INPUT_H5AD" ]]; then
  write_skip_manifest "partial:data_required" "Missing public scVelo validation h5ad with spliced/unspliced layers: $INPUT_H5AD"
  exit 0
fi

cat > "$OUT_DIR/config/project.yaml" <<YAML
project:
  name: slurm_scrna_velocity_pancreas
  organism: mouse
  output_dir: $OUT_DIR
  server_root: $PROJECT_ROOT
  run_mode: interactive
  overwrite: true
samples:
  items:
    - sample_id: pancreas_velocity
      condition: public_validation
      input_path: $INPUT_H5AD
design:
  condition_column: condition
  control: public_validation
  case: public_validation
modules:
  scrna:
    enabled: true
    preset: trajectory
    analysis_level: validated_backend
    velocity:
      enabled: true
      backend: scvelo
      input_h5ad: $INPUT_H5AD
      input_type: h5ad
      public_dataset: true
      validation_dataset: scVelo pancreas endocrinogenesis day15
      max_cells: $MAX_CELLS
      max_genes: $MAX_GENES
      random_seed: 7
    raw:
      enabled: false
      input_type: h5ad
report:
  title: scVelo RNA velocity validation
  style: soft_color
YAML

"$PYTHON_BIN" -m ultimate.cli preflight --config "$OUT_DIR/config/project.yaml" > "$OUT_DIR/preflight_stdout.json"
"$PYTHON_BIN" -m ultimate.cli run --config "$OUT_DIR/config/project.yaml" > "$OUT_DIR/run_stdout.json"
