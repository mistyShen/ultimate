#!/usr/bin/env bash
#SBATCH --job-name=ult_vdj_backend
#SBATCH --output=/shared/shen/2026/ultimate/logs/%x_%j.out
#SBATCH --error=/shared/shen/2026/ultimate/logs/%x_%j.err
#SBATCH --cpus-per-task=2
#SBATCH --mem=12G
#SBATCH --time=01:00:00

set -euo pipefail

PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
CORE_ENV="${ULTIMATE_CORE_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-core}"
VDJ_ENV="${ULTIMATE_VDJ_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-vdj}"
CONDA_SH="${CONDA_SH:-/share/home/nshen/miniconda3/etc/profile.d/conda.sh}"
OUT_DIR="$PROJECT_ROOT/validations/slurm_vdj_10x_pbmc_unified"
INPUT_DIR="$PROJECT_ROOT/public_data/vdj"

mkdir -p "$PROJECT_ROOT/logs" "$OUT_DIR/config" "$OUT_DIR/reports"
source "$CONDA_SH"

select_python() {
  if [[ -x "$VDJ_ENV/bin/python" ]] && "$VDJ_ENV/bin/python" - <<'PY' >/dev/null 2>&1
import click
import jinja2
import yaml
PY
  then
    export LD_PRELOAD="${LD_PRELOAD:-$VDJ_ENV/lib/libgomp.so.1}"
    echo "$VDJ_ENV/bin/python"
  else
    echo "$CORE_ENV/bin/python"
  fi
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
    "module": "vdj",
    "output_dir": str(out),
    "status": status,
    "analysis_level": "smoke_backend",
    "is_demo": False,
    "is_stub": True,
    "delivery_allowed": False,
    "validation_evidence_allowed": False,
    "non_delivery_reason": f"validation_not_completed:{reason}",
    "backend_id": "vdj.default.scirpy_mvp",
    "backend_status": "fully_automatic_mvp",
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
    "# VDJ unified backend validation skipped\n\n"
    "analysis_level: `smoke_backend`\n\n"
    "delivery_allowed: `false`\n\n"
    "validation_evidence_allowed: `false`\n\n"
    f"reason: {reason}\n",
    encoding="utf-8",
)
(out / "reports" / "report.html").write_text(
    "<html><body><h1>VDJ unified backend validation skipped</h1>"
    "<p>analysis_level: smoke_backend</p>"
    "<p>delivery_allowed: false</p>"
    f"<p>{reason}</p></body></html>",
    encoding="utf-8",
)
PY
}

if [[ ! -s "$INPUT_DIR/filtered_contig_annotations.csv" || ! -s "$INPUT_DIR/clonotypes.csv" ]]; then
  "$CORE_ENV/bin/python" "$PROJECT_ROOT/01_tools/prepare_public_singlecell_manifests.py" \
    --root "$PROJECT_ROOT" \
    --mode download || true
fi

if [[ ! -s "$INPUT_DIR/filtered_contig_annotations.csv" || ! -s "$INPUT_DIR/clonotypes.csv" ]]; then
  write_skip_manifest "partial:data_required" "public_data/vdj lacks filtered_contig_annotations.csv or clonotypes.csv after download attempt"
  exit 0
fi

PYTHON_BIN="$(select_python)"
export PYTHONPATH="$PROJECT_ROOT/src"

cat > "$OUT_DIR/config/project.yaml" <<YAML
project:
  name: slurm_vdj_10x_pbmc_unified
  organism: human
  output_dir: $OUT_DIR
  server_root: $PROJECT_ROOT
  run_mode: interactive
  overwrite: true
samples:
  items:
    - sample_id: pbmc_vdj
      condition: public_validation
      input_path: $INPUT_DIR
design:
  condition_column: condition
  control: public_validation
  case: public_validation
modules:
  vdj:
    enabled: true
    preset: standard
    input_dir: $INPUT_DIR
    analysis_level: validated_backend
    public_dataset: true
    raw:
      enabled: false
      input_type: cellranger_vdj_out
report:
  title: 10x PBMC VDJ unified backend validation
  style: soft_color
YAML

"$PYTHON_BIN" -m ultimate.cli preflight --config "$OUT_DIR/config/project.yaml" > "$OUT_DIR/preflight_stdout.json"
"$PYTHON_BIN" -m ultimate.cli run --config "$OUT_DIR/config/project.yaml" > "$OUT_DIR/run_stdout.json"
