#!/usr/bin/env bash
#SBATCH --job-name=ult_cite_seq
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
INPUT_H5="${ULTIMATE_CITE_SEQ_INPUT:-$PROJECT_ROOT/public_data/cite_seq/pbmc_10k_protein_v3_filtered_feature_bc_matrix.h5}"
OUT_DIR="${ULTIMATE_CITE_SEQ_OUT:-$PROJECT_ROOT/validations/slurm_cite_seq_10x_pbmc}"

mkdir -p "$PROJECT_ROOT/logs" "$PROJECT_ROOT/validations"
source "$CONDA_SH"

write_skip_manifest() {
  local out_dir="$1"
  local status="$2"
  local reason="$3"
  mkdir -p "$out_dir/reports" "$out_dir/results/tables" "$out_dir/results/figures" "$out_dir/objects"
  "$CORE_ENV/bin/python" - "$out_dir" "$status" "$reason" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

out = Path(sys.argv[1])
status = sys.argv[2]
reason = sys.argv[3]
manifest = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "output_dir": str(out),
    "status": status,
    "analysis_level": "smoke_backend",
    "is_demo": False,
    "is_stub": True,
    "delivery_allowed": False,
    "validation_evidence_allowed": False,
    "non_delivery_reason": f"validation_not_completed:{reason}",
    "skip_reason": reason,
    "tables": [],
    "figures": [],
    "objects": {},
}
(out / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
(out / "reports" / "report.md").write_text(
    f"# CITE-seq 验证跳过\n\nanalysis_level：`smoke_backend`\n\n"
    f"delivery_allowed：`false`\n\nvalidation_evidence_allowed：`false`\n\n"
    f"状态：`{status}`\n\n原因：{reason}\n",
    encoding="utf-8",
)
(out / "reports" / "report.html").write_text(
    "<html><body><h1>CITE-seq 验证跳过</h1>"
    "<p>analysis_level: smoke_backend</p>"
    "<p>delivery_allowed: false</p>"
    "<p>validation_evidence_allowed: false</p>"
    f"<p>{reason}</p></body></html>",
    encoding="utf-8",
)
(out / "reports" / "methods.md").write_text(
    "# CITE-seq 验证方法\n\n验证未完成；没有生成可作为 evidence 的 ADT/RNA 分析产物。\n",
    encoding="utf-8",
)
PY
}

if [[ ! -s "$INPUT_H5" ]]; then
  write_skip_manifest "$OUT_DIR" "partial:data_required" "未找到公开 CITE-seq feature-barcode H5：$INPUT_H5。请先运行 download_public_singlecell_data.sbatch。"
  exit 0
fi

if [[ -x "$SCRNA_ENV/bin/python" ]]; then
  PYTHON_BIN="$SCRNA_ENV/bin/python"
elif [[ -x "$SCRNA_FALLBACK_ENV/bin/python" ]]; then
  PYTHON_BIN="$SCRNA_FALLBACK_ENV/bin/python"
else
  write_skip_manifest "$OUT_DIR" "partial:dependency_required" "未找到 ultimate-scrna 或 singlecell_workbench scRNA Python 环境。"
  exit 0
fi

"$PYTHON_BIN" "$PROJECT_ROOT/01_tools/validate_cite_seq_public.py" \
  --input-h5 "$INPUT_H5" \
  --output-dir "$OUT_DIR" \
  --max-cells-object "${ULTIMATE_CITE_SEQ_MAX_CELLS_OBJECT:-3000}"

PYTHONPATH="$PROJECT_ROOT/src" "$CORE_ENV/bin/python" -m ultimate.cli validation-index \
  --root "$PROJECT_ROOT" \
  --output-dir "$PROJECT_ROOT/reports/validation_index"

PYTHONPATH="$PROJECT_ROOT/src" "$CORE_ENV/bin/python" -m ultimate.cli audit-production \
  --root "$PROJECT_ROOT" \
  --output-dir "$PROJECT_ROOT/audits/production_readiness_latest"
