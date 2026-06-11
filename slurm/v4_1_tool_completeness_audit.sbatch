#!/usr/bin/env bash
#SBATCH --job-name=ult_v4_1_tools
#SBATCH --output=/shared/shen/2026/ultimate/logs/%x_%j.out
#SBATCH --error=/shared/shen/2026/ultimate/logs/%x_%j.err
#SBATCH --cpus-per-task=2
#SBATCH --mem=12G
#SBATCH --time=02:00:00

set -euo pipefail

PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
CORE_ENV="${ULTIMATE_CORE_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-core}"

mkdir -p "$PROJECT_ROOT/logs" "$PROJECT_ROOT/audits" "$PROJECT_ROOT/reports"
cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

"$CORE_ENV/bin/python" -m ultimate.cli audit-tools \
  --root "$PROJECT_ROOT" \
  --output-dir "$PROJECT_ROOT/audits/tools_v4_1_latest"

"$CORE_ENV/bin/python" -m ultimate.cli validation-index \
  --root "$PROJECT_ROOT" \
  --output-dir "$PROJECT_ROOT/reports/validation_index_v4_1"

"$CORE_ENV/bin/python" -m ultimate.cli audit-production \
  --root "$PROJECT_ROOT" \
  --output-dir "$PROJECT_ROOT/audits/production_v4_1_latest"

"$CORE_ENV/bin/python" -m ultimate.cli audit-backends \
  --root "$PROJECT_ROOT" \
  --output-dir "$PROJECT_ROOT/audits/backends_v4_1_latest"

"$CORE_ENV/bin/python" -m ultimate.cli tool-completeness \
  --root "$PROJECT_ROOT" \
  --output-dir "$PROJECT_ROOT/audits/tool_completeness_latest"

"$CORE_ENV/bin/python" -m ultimate.cli order-readiness \
  --root "$PROJECT_ROOT" \
  --output-dir "$PROJECT_ROOT/audits/order_readiness_latest"

if [[ -f "$PROJECT_ROOT/01_tools/storage_audit.py" ]]; then
  "$CORE_ENV/bin/python" "$PROJECT_ROOT/01_tools/storage_audit.py" \
    --root "$PROJECT_ROOT" \
    --output-dir "$PROJECT_ROOT/audits/storage_v4_1_latest" \
    --budget-gb 500
fi

cp "$PROJECT_ROOT/audits/tool_completeness_latest/v4_1_tool_completeness_report.md" \
  "$PROJECT_ROOT/reports/v4_1_tool_completeness_report.md"

