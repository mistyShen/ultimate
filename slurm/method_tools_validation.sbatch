#!/usr/bin/env bash
#SBATCH --job-name=ult_method_tools
#SBATCH --output=/shared/shen/2026/ultimate/logs/%x_%j.out
#SBATCH --error=/shared/shen/2026/ultimate/logs/%x_%j.err
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=02:00:00

set -euo pipefail

PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
SCRNA_ENV="${ULTIMATE_SCRNA_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-scrna}"
SCRNA_FALLBACK_ENV="${ULTIMATE_SCRNA_FALLBACK_ENV:-/shared/shen/2026/singlecell_workbench/.conda/envs/scw-py311}"
CONDA_SH="${CONDA_SH:-/share/home/nshen/miniconda3/etc/profile.d/conda.sh}"
INPUT_H5AD="${ULTIMATE_METHOD_TOOLS_INPUT:-/shared/shen/2026/nsclc_virtual_sc/02_processed_scRNA/Lambrechts_all_harmonized.h5ad}"
OUT_DIR="${ULTIMATE_METHOD_TOOLS_OUT:-$PROJECT_ROOT/validations/slurm_method_tools_nsclc}"

mkdir -p "$PROJECT_ROOT/logs" "$PROJECT_ROOT/validations"
source "$CONDA_SH"

if [[ -x "$SCRNA_ENV/bin/python" ]]; then
  PYTHON_BIN="$SCRNA_ENV/bin/python"
elif [[ -x "$SCRNA_FALLBACK_ENV/bin/python" ]]; then
  PYTHON_BIN="$SCRNA_FALLBACK_ENV/bin/python"
else
  PYTHON_BIN=""
fi

if [[ -z "$PYTHON_BIN" ]]; then
  mkdir -p "$OUT_DIR/reports"
  python - "$OUT_DIR" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

out = Path(sys.argv[1])
manifest = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "output_dir": str(out),
    "status": "partial:dependency_required",
    "skip_reason": "未找到 ultimate-scrna 或 singlecell_workbench scRNA Python 环境。",
}
(out / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
(out / "reports" / "report.md").write_text("# 方法学工具验证跳过\n\n未找到可用 scRNA Python 环境。\n", encoding="utf-8")
PY
  exit 0
fi

"$PYTHON_BIN" "$PROJECT_ROOT/01_tools/validate_method_tools_scrna.py" \
  --input-h5ad "$INPUT_H5AD" \
  --output-dir "$OUT_DIR" \
  --max-cells "${ULTIMATE_METHOD_TOOLS_MAX_CELLS:-3000}"
