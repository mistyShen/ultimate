#!/usr/bin/env bash
#SBATCH --job-name=ult_ready_refresh
#SBATCH --output=/shared/shen/2026/ultimate/logs/%x_%j.out
#SBATCH --error=/shared/shen/2026/ultimate/logs/%x_%j.err
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=00:30:00

set -euo pipefail

PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
CORE_ENV="${ULTIMATE_CORE_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-core}"
PYTHON_BIN="${CORE_ENV}/bin/python"
VALIDATION_INDEX_OUT="${ULTIMATE_VALIDATION_INDEX_OUTPUT:-$PROJECT_ROOT/reports/validation_index}"
AUDIT_OUT="${ULTIMATE_PRODUCTION_AUDIT_OUTPUT:-$PROJECT_ROOT/audits/production_readiness_latest}"
GUARD_OUT="${ULTIMATE_VALIDATION_GUARD_OUTPUT:-$PROJECT_ROOT/audits/validation_guard_latest/validation_manifest_guard.tsv}"
METHODS_OUT="${ULTIMATE_VALIDATION_METHODS_OUTPUT:-$PROJECT_ROOT/audits/validation_guard_latest/validation_methods_backfill.tsv}"
MVP_OUT="${ULTIMATE_VALIDATION_MVP_OUTPUT:-$PROJECT_ROOT/audits/validation_guard_latest/validation_mvp_artifacts.tsv}"

mkdir -p "$PROJECT_ROOT/logs" "$VALIDATION_INDEX_OUT" "$AUDIT_OUT" "$(dirname "$GUARD_OUT")"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Missing ultimate-core Python: $PYTHON_BIN" >&2
  exit 2
fi

export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

"$PYTHON_BIN" "$PROJECT_ROOT/01_tools/ensure_validation_methods.py" \
  --root "$PROJECT_ROOT" \
  --validations-dir "$PROJECT_ROOT/validations" \
  --output-tsv "$METHODS_OUT"

"$PYTHON_BIN" "$PROJECT_ROOT/01_tools/ensure_validation_mvp_artifacts.py" \
  --root "$PROJECT_ROOT" \
  --validations-dir "$PROJECT_ROOT/validations" \
  --output-tsv "$MVP_OUT"

"$PYTHON_BIN" -m ultimate.cli validation-index \
  --root "$PROJECT_ROOT" \
  --output-dir "$VALIDATION_INDEX_OUT"

"$PYTHON_BIN" -m ultimate.cli audit-production \
  --root "$PROJECT_ROOT" \
  --output-dir "$AUDIT_OUT"

"$PYTHON_BIN" "$PROJECT_ROOT/01_tools/check_validation_manifests.py" \
  --root "$PROJECT_ROOT" \
  --validations-dir "$PROJECT_ROOT/validations" \
  --output-tsv "$GUARD_OUT"
