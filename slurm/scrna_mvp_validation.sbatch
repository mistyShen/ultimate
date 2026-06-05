#!/usr/bin/env bash
#SBATCH --job-name=ult_scrna_mvp
#SBATCH --output=/shared/shen/2026/ultimate/logs/%x_%j.out
#SBATCH --error=/shared/shen/2026/ultimate/logs/%x_%j.err
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=04:00:00

set -euo pipefail

PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
CORE_ENV="${ULTIMATE_CORE_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-core}"
SCRNA_ENV="${ULTIMATE_SCRNA_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-scrna}"
SCRNA_FALLBACK_ENV="${ULTIMATE_SCRNA_FALLBACK_ENV:-/shared/shen/2026/singlecell_workbench/.conda/envs/scw-py311}"
CONDA_SH="${CONDA_SH:-/share/home/nshen/miniconda3/etc/profile.d/conda.sh}"
OUT_ROOT="${ULTIMATE_SCRNA_MVP_OUT:-$PROJECT_ROOT/validation_runs/scrna_mvp_validation}"
PUBLIC_ROOT="${ULTIMATE_SCRNA_MVP_PUBLIC_ROOT:-$PROJECT_ROOT/public_data/scrna_pbmc3k}"
CELLTYPIST_FOLDER="${ULTIMATE_CELLTYPIST_FOLDER:-$PROJECT_ROOT/references/celltypist}"
CELLTYPIST_MODEL="${ULTIMATE_CELLTYPIST_MODEL:-$CELLTYPIST_FOLDER/data/models/Immune_All_Low.pkl}"

mkdir -p "$PROJECT_ROOT/logs" "$PROJECT_ROOT/public_data" "$OUT_ROOT" "$CELLTYPIST_FOLDER"
export CELLTYPIST_FOLDER
source "$CONDA_SH"

write_skip_manifest() {
  local out_dir="$1"
  local status="$2"
  local reason="$3"
  mkdir -p "$out_dir/reports" "$out_dir/results/tables" "$out_dir/results/figures" "$out_dir/objects"
  python - "$out_dir" "$status" "$reason" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

out = Path(sys.argv[1])
status = sys.argv[2]
reason = sys.argv[3]
manifest = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "status": status,
    "analysis_level": "smoke_backend",
    "is_demo": False,
    "is_stub": False,
    "delivery_allowed": False,
    "validation_evidence_allowed": False,
    "non_delivery_reason": f"validation_not_completed:{reason}",
    "output_dir": str(out),
    "skip_reason": reason,
}
(out / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
(out / "reports" / "report.md").write_text(f"# scRNA MVP 验证未完成\n\nanalysis_level：`smoke_backend`\n\n状态：`{status}`\n\n原因：{reason}\n", encoding="utf-8")
(out / "reports" / "report.html").write_text(f"<html><body><h1>scRNA MVP 验证未完成</h1><p>analysis_level: smoke_backend</p><p>{reason}</p></body></html>", encoding="utf-8")
PY
}

select_scrna_python() {
  if [[ -x "$SCRNA_ENV/bin/python" ]]; then
    echo "$SCRNA_ENV/bin/python"
  elif [[ -x "$SCRNA_FALLBACK_ENV/bin/python" ]]; then
    echo "$SCRNA_FALLBACK_ENV/bin/python"
  else
    echo ""
  fi
}

conda activate "$CORE_ENV"
python "$PROJECT_ROOT/01_tools/prepare_public_singlecell_manifests.py" \
  --root "$PROJECT_ROOT" \
  --mode download

MATRIX_DIR="$(
python - "$PUBLIC_ROOT/manifest.json" <<'PY'
import json
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
if not manifest_path.exists():
    print("")
    raise SystemExit(0)
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
result = manifest.get("download_result") or {}
matrix_dir = result.get("matrix_dir", "")
if manifest.get("validation_status") == "ready" and matrix_dir and Path(matrix_dir).exists():
    print(matrix_dir)
else:
    print("")
PY
)"

PYTHON_BIN="$(select_scrna_python)"
if [[ -z "$PYTHON_BIN" ]]; then
  write_skip_manifest "$OUT_ROOT/10x_mtx" "partial:dependency_required" "未找到 ultimate-scrna 或 singlecell_workbench scRNA Python 环境。"
  write_skip_manifest "$OUT_ROOT/h5ad" "partial:dependency_required" "未找到 ultimate-scrna 或 singlecell_workbench scRNA Python 环境。"
  exit 0
fi

if [[ -z "$MATRIX_DIR" ]]; then
  write_skip_manifest "$OUT_ROOT/10x_mtx" "partial:data_required" "公开 PBMC3k 10x matrix 未就绪；请检查 $PUBLIC_ROOT/manifest.json。"
  write_skip_manifest "$OUT_ROOT/h5ad" "partial:data_required" "公开 PBMC3k 10x matrix 未就绪，无法生成真实 h5ad 验证输入。"
  exit 0
fi

export PYTHONPATH="$PROJECT_ROOT/src:${PYTHONPATH:-}"
CELLTYPIST_ARGS=()
if [[ -s "$CELLTYPIST_MODEL" ]]; then
  CELLTYPIST_ARGS=(--celltypist-model "$CELLTYPIST_MODEL")
fi

"$PYTHON_BIN" -m ultimate.cli validate-scrna \
  --input-path "$MATRIX_DIR" \
  --input-type 10x_mtx \
  --output-dir "$OUT_ROOT/10x_mtx" \
  --max-cells "${ULTIMATE_SCRNA_MVP_MAX_CELLS:-1200}" \
  --analysis-level validated_backend \
  --public-dataset \
  --dataset-label "10x_pbmc3k_public_matrix" \
  "${CELLTYPIST_ARGS[@]}"

H5AD_INPUT="$OUT_ROOT/10x_mtx/objects/scrna_mvp.h5ad"
if [[ ! -s "$H5AD_INPUT" ]]; then
  write_skip_manifest "$OUT_ROOT/h5ad" "partial:object_required" "10x matrix 验证未生成 objects/scrna_mvp.h5ad。"
  exit 0
fi

"$PYTHON_BIN" -m ultimate.cli validate-scrna \
  --input-path "$H5AD_INPUT" \
  --input-type h5ad \
  --output-dir "$OUT_ROOT/h5ad" \
  --max-cells "${ULTIMATE_SCRNA_MVP_MAX_CELLS:-1200}" \
  --analysis-level validated_backend \
  --public-dataset \
  --dataset-label "10x_pbmc3k_public_h5ad_from_matrix" \
  "${CELLTYPIST_ARGS[@]}"

conda activate "$CORE_ENV"
ultimate audit-production \
  --root "$PROJECT_ROOT" \
  --output-dir "$PROJECT_ROOT/audits/scrna_mvp_validation_post"
