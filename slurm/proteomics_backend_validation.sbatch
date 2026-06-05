#!/usr/bin/env bash
#SBATCH --job-name=ult_proteomics_backend
#SBATCH --output=/shared/shen/2026/ultimate/logs/%x_%j.out
#SBATCH --error=/shared/shen/2026/ultimate/logs/%x_%j.err
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --time=02:00:00

set -euo pipefail

PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
CORE_ENV="${ULTIMATE_CORE_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-core}"
CONDA_SH="${CONDA_SH:-/share/home/nshen/miniconda3/etc/profile.d/conda.sh}"
OUT_DIR="${ULTIMATE_PROTEOMICS_OUT:-$PROJECT_ROOT/validations/slurm_proteomics_lfq_analyst_public}"
PUBLIC_DATA_DIR="${ULTIMATE_PROTEOMICS_PUBLIC_DATA:-$PROJECT_ROOT/public_data/proteomics_lfq_analyst}"

mkdir -p "$PROJECT_ROOT/logs" "$OUT_DIR/reports" "$PUBLIC_DATA_DIR"
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
    "module": "proteomics",
    "output_dir": str(out),
    "status": status,
    "analysis_level": "smoke_backend",
    "is_demo": False,
    "is_stub": True,
    "delivery_allowed": False,
    "validation_evidence_allowed": False,
    "non_delivery_reason": f"validation_not_completed:{reason}",
    "backend_id": "proteomics.default.abundance_python_mvp",
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
    "# Proteomics backend validation skipped\n\n"
    "analysis_level: `smoke_backend`\n\n"
    "delivery_allowed: `false`\n\n"
    "validation_evidence_allowed: `false`\n\n"
    f"reason: {reason}\n",
    encoding="utf-8",
)
(out / "reports" / "report.html").write_text(
    "<html><body><h1>Proteomics backend validation skipped</h1>"
    "<p>analysis_level: smoke_backend</p>"
    "<p>delivery_allowed: false</p>"
    f"<p>{reason}</p></body></html>",
    encoding="utf-8",
)
PY
}

if [[ ! -x "$CORE_ENV/bin/python" ]]; then
  write_skip_manifest "partial:dependency_required" "ultimate-core Python environment not found at $CORE_ENV"
  exit 0
fi

if ! "$CORE_ENV/bin/python" - <<'PY' >/dev/null 2>&1
import click
import jinja2
import yaml
import pandas
import numpy
import matplotlib
import seaborn
PY
then
  write_skip_manifest "partial:dependency_required" "ultimate-core lacks required Python packages for proteomics validation"
  exit 0
fi

cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT/src"
export ULTIMATE_ALLOW_OVERWRITE=1

if ! "$CORE_ENV/bin/python" "$PROJECT_ROOT/01_tools/validate_proteomics_public.py" \
  --output-dir "$OUT_DIR" \
  --public-data-dir "$PUBLIC_DATA_DIR"; then
  write_skip_manifest "partial:validation_failed" "proteomics validation command failed; inspect $PROJECT_ROOT/logs/ult_proteomics_backend_${SLURM_JOB_ID:-unknown}.err"
  exit 0
fi
