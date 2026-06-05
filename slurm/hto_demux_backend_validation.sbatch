#!/usr/bin/env bash
#SBATCH --job-name=ult_hto_demux
#SBATCH --output=/shared/shen/2026/ultimate/logs/%x_%j.out
#SBATCH --error=/shared/shen/2026/ultimate/logs/%x_%j.err
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:40:00

set -euo pipefail

PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
CORE_ENV="${ULTIMATE_CORE_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-core}"
PYTHON_BIN="${CORE_ENV}/bin/python"
OUT_DIR="${ULTIMATE_HTO_DEMUX_OUT:-$PROJECT_ROOT/validations/slurm_hto_demux_seurat_public}"
INPUT_TABLE="${ULTIMATE_HTO_DEMUX_PUBLIC_TABLE:-$PROJECT_ROOT/public_data/hto_demux/seurat_hto12/hto12_hto_mtx_5000.tsv}"

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
    "module": "hto_demux",
    "status": status,
    "analysis_level": "smoke_backend",
    "is_demo": False,
    "is_stub": True,
    "delivery_allowed": False,
    "validation_evidence_allowed": False,
    "non_delivery_reason": f"validation_not_completed:{reason}",
    "backend_id": "hto_demux.default.matrix_assignment_mvp",
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
    "# HTO demux validation skipped\n\n"
    "analysis_level: `smoke_backend`\n\n"
    "delivery_allowed: `false`\n\n"
    f"reason: {reason}\n",
    encoding="utf-8",
)
(out / "reports" / "report.html").write_text(
    f"<html><body><h1>HTO demux validation skipped</h1><p>{reason}</p></body></html>",
    encoding="utf-8",
)
PY
}

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python"
fi
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  write_skip_manifest "partial:dependency_required" "No Python runtime was found"
  exit 0
fi
if [[ ! -s "$INPUT_TABLE" ]]; then
  write_skip_manifest "partial:data_required" "Missing public HTO count table: $INPUT_TABLE"
  exit 0
fi

export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
mkdir -p "$OUT_DIR/config"

cat > "$OUT_DIR/config/project.yaml" <<YAML
project:
  name: slurm_hto_demux_seurat_public
  organism: human
  output_dir: $OUT_DIR
  server_root: $PROJECT_ROOT
  run_mode: interactive
  overwrite: true
samples:
  items:
    - sample_id: hto_public
      condition: public_validation
      input_path: $INPUT_TABLE
design:
  condition_column: condition
  control: public_validation
  case: public_validation
modules:
  hto_demux:
    enabled: true
    preset: standard
    input_table: $INPUT_TABLE
    analysis_level: validated_backend
    validation_dataset: Seurat 12-HTO hashing public fixture
    max_cells: ${ULTIMATE_HTO_DEMUX_MAX_CELLS:-5000}
    min_positive_count: ${ULTIMATE_HTO_MIN_POSITIVE_COUNT:-20}
    min_margin: ${ULTIMATE_HTO_MIN_MARGIN:-20}
    raw:
      enabled: false
      input_type: hto_count_matrix
report:
  title: HTO demux unified backend validation
  style: soft_color
YAML

"$PYTHON_BIN" -m ultimate.cli preflight --config "$OUT_DIR/config/project.yaml" > "$OUT_DIR/preflight_stdout.json"
"$PYTHON_BIN" -m ultimate.cli run --config "$OUT_DIR/config/project.yaml" > "$OUT_DIR/run_stdout.json"
