#!/usr/bin/env bash
#SBATCH --job-name=ult_tumor_sc
#SBATCH --output=/shared/shen/2026/ultimate/logs/%x_%j.out
#SBATCH --error=/shared/shen/2026/ultimate/logs/%x_%j.err
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=04:00:00

set -euo pipefail

PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
SCRNA_ENV="${ULTIMATE_SCRNA_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-scrna}"
SCRNA_FALLBACK_ENV="${ULTIMATE_SCRNA_FALLBACK_ENV:-/shared/shen/2026/singlecell_workbench/.conda/envs/scw-py311}"
CORE_ENV="${ULTIMATE_CORE_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-core}"
INPUT_H5AD="${ULTIMATE_TUMOR_SC_INPUT:-$PROJECT_ROOT/validations/slurm_scrna_nsclc_lambrechts/objects/nsclc_scrna_validated.h5ad}"
RAW_INPUT_H5AD="${ULTIMATE_TUMOR_SC_RAW_INPUT:-/shared/shen/2026/nsclc_virtual_sc/02_processed_scRNA/Lambrechts_all_harmonized.h5ad}"
OUT_DIR="${ULTIMATE_TUMOR_SC_OUT:-$PROJECT_ROOT/validations/slurm_tumor_sc_nsclc}"
RSCRIPT="${ULTIMATE_TUMOR_SC_RSCRIPT:-$PROJECT_ROOT/.conda/envs/ultimate-scrna-r/bin/Rscript}"
RUN_COPYKAT="${ULTIMATE_TUMOR_SC_RUN_COPYKAT:-1}"
RUN_INFERCNV="${ULTIMATE_TUMOR_SC_RUN_INFERCNV:-1}"
GENE_ORDER_REF="${ULTIMATE_TUMOR_SC_GENE_ORDER_REF:-/shared/shen/2026/nsclc_virtual_sc/02_processed_scRNA/Lambrechts_all_harmonized.h5ad}"

mkdir -p "$PROJECT_ROOT/logs" "$PROJECT_ROOT/validations" "$PROJECT_ROOT/audits" "$PROJECT_ROOT/reports/validation_index"

if [[ -x "$SCRNA_ENV/bin/python" ]]; then
  PYTHON_BIN="$SCRNA_ENV/bin/python"
elif [[ -x "$SCRNA_FALLBACK_ENV/bin/python" ]]; then
  PYTHON_BIN="$SCRNA_FALLBACK_ENV/bin/python"
else
  PYTHON_BIN=""
fi

if [[ -z "$PYTHON_BIN" ]]; then
  mkdir -p "$OUT_DIR/reports"
  "$CORE_ENV/bin/python" - "$OUT_DIR" <<'PY'
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
    "analysis_level": "smoke_backend",
    "is_demo": False,
    "is_stub": True,
    "delivery_allowed": False,
    "validation_evidence_allowed": False,
    "non_delivery_reason": "validation_status_not_ready:dependency_required",
}
(out / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
(out / "reports" / "report.md").write_text("# tumor_sc 验证跳过\n\n未找到可用 scRNA Python 环境。\n", encoding="utf-8")
PY
  exit 0
fi

if [[ ! -s "$INPUT_H5AD" ]]; then
  INPUT_H5AD="$RAW_INPUT_H5AD"
fi

COPYKAT_ARG=()
INFERCNV_ARG=()
GENE_ORDER_ARG=()
if [[ "$RUN_COPYKAT" == "1" || "$RUN_COPYKAT" == "true" ]]; then
  COPYKAT_ARG=(--run-copykat)
fi
if [[ "$RUN_INFERCNV" == "1" || "$RUN_INFERCNV" == "true" ]]; then
  INFERCNV_ARG=(--run-infercnv)
fi
if [[ -s "$GENE_ORDER_REF" ]]; then
  GENE_ORDER_ARG=(--gene-order-reference-h5ad "$GENE_ORDER_REF")
fi

"$PYTHON_BIN" "$PROJECT_ROOT/01_tools/validate_tumor_sc_nsclc.py" \
  --input-h5ad "$INPUT_H5AD" \
  --output-dir "$OUT_DIR" \
  --max-cells "${ULTIMATE_TUMOR_SC_MAX_CELLS:-6000}" \
  --rscript "$RSCRIPT" \
  "${COPYKAT_ARG[@]}" \
  "${INFERCNV_ARG[@]}" \
  "${GENE_ORDER_ARG[@]}"

PYTHONPATH="$PROJECT_ROOT/src" "$CORE_ENV/bin/python" -m ultimate.cli validation-index \
  --root "$PROJECT_ROOT" \
  --output-dir "$PROJECT_ROOT/reports/validation_index"

PYTHONPATH="$PROJECT_ROOT/src" "$CORE_ENV/bin/python" -m ultimate.cli audit-production \
  --root "$PROJECT_ROOT" \
  --output-dir "$PROJECT_ROOT/audits/production_readiness_latest"
