#!/usr/bin/env bash
#SBATCH --job-name=ult_scrna_nichenet
#SBATCH --output=/shared/shen/2026/ultimate/logs/%x_%j.out
#SBATCH --error=/shared/shen/2026/ultimate/logs/%x_%j.err
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=02:00:00

set -euo pipefail

PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
CORE_ENV="${ULTIMATE_CORE_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-core}"
SCRNA_ENV="${ULTIMATE_SCRNA_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-scrna}"
SCRNA_R_ENV="${ULTIMATE_SCRNA_R_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-scrna-r}"
CONDA_SH="${CONDA_SH:-/share/home/nshen/miniconda3/etc/profile.d/conda.sh}"
PUBLIC_ROOT="${ULTIMATE_PUBLIC_SCRNA:-$PROJECT_ROOT/public_data/scrna_pbmc3k}"
OUT_DIR="${ULTIMATE_NICHENET_OUT:-$PROJECT_ROOT/validations/slurm_scrna_nichenet_pbmc}"

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
    "module": "scrna",
    "output_dir": str(out),
    "status": status,
    "backend_validation_target": "scrna.communication.nichenet_optional",
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
    "# scRNA NicheNet validation skipped\n\n"
    "analysis_level: `smoke_backend`\n\n"
    "delivery_allowed: `false`\n\n"
    "validation_evidence_allowed: `false`\n\n"
    f"reason: {reason}\n",
    encoding="utf-8",
)
(out / "reports" / "report.html").write_text(
    "<html><body><h1>scRNA NicheNet validation skipped</h1>"
    "<p>analysis_level: smoke_backend</p>"
    "<p>delivery_allowed: false</p>"
    f"<p>{reason}</p></body></html>",
    encoding="utf-8",
)
PY
}

select_scrna_python() {
  for candidate in "$SCRNA_ENV/bin/python" "$CORE_ENV/bin/python"; do
    if [[ -x "$candidate" ]] && "$candidate" - <<'PY' >/dev/null 2>&1
import scanpy
import anndata
import h5py
import scipy
PY
    then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

"$CORE_ENV/bin/python" "$PROJECT_ROOT/01_tools/prepare_public_singlecell_manifests.py" \
  --root "$PROJECT_ROOT" \
  --mode download || true

MATRIX_DIR="$("$CORE_ENV/bin/python" - "$PUBLIC_ROOT/manifest.json" <<'PY'
import json
import sys
from pathlib import Path
path = Path(sys.argv[1])
if not path.exists():
    print("")
    raise SystemExit(0)
manifest = json.loads(path.read_text(encoding="utf-8"))
matrix_dir = (manifest.get("download_result") or {}).get("matrix_dir", "")
print(matrix_dir if matrix_dir and Path(matrix_dir).exists() else "")
PY
)"

if [[ -z "$MATRIX_DIR" ]]; then
  write_skip_manifest "partial:data_required" "public PBMC3k matrix is not available"
  exit 0
fi

if ! PYTHON_BIN="$(select_scrna_python)"; then
  write_skip_manifest "partial:dependency_required" "No Python environment with scanpy/anndata/h5py/scipy was found"
  exit 0
fi

export PYTHONPATH="$PROJECT_ROOT/src:$PROJECT_ROOT/01_tools:${PYTHONPATH:-}"
if [[ -x "$SCRNA_R_ENV/bin/Rscript" ]]; then
  export PATH="$SCRNA_R_ENV/bin:$PATH"
fi

"$PYTHON_BIN" "$PROJECT_ROOT/01_tools/validate_scrna_nichenet.py" \
  --input-path "$MATRIX_DIR" \
  --input-type 10x_mtx \
  --output-dir "$OUT_DIR" \
  --max-cells "${ULTIMATE_NICHENET_MAX_CELLS:-1200}"
