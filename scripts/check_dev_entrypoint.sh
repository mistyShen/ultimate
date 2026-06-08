#!/usr/bin/env bash
set -euo pipefail

MODE="local"
ROOT=""
PYTHON_BIN=""

usage() {
  cat <<'USAGE'
usage: scripts/check_dev_entrypoint.sh [--mode local|remote] [--root PATH] [--python PATH]

Checks the Ultimate development entrypoint without requiring PYTHONPATH.
Remote mode uses hpc-run and performs only lightweight checks on the shared root.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)
      MODE="${2:?--mode requires local or remote}"
      shift 2
      ;;
    --root)
      ROOT="${2:?--root requires a path}"
      shift 2
      ;;
    --python)
      PYTHON_BIN="${2:?--python requires a path}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "$MODE" != "local" && "$MODE" != "remote" ]]; then
  echo "--mode must be local or remote" >&2
  exit 2
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
default_local_root="$(cd "$script_dir/.." && pwd)"
if [[ -z "$ROOT" ]]; then
  if [[ "$MODE" == "remote" ]]; then
    ROOT="/shared/shen/2026/ultimate"
  else
    ROOT="$default_local_root"
  fi
fi

run_local_checks() {
  local root="$1"
  local python_bin="${2:-python}"
  local tmp_dir
  tmp_dir="$(mktemp -d)"
  trap "rm -rf '$tmp_dir'" EXIT

  cd "$root"
  echo "[ultimate-dev-entrypoint] root=$root"
  echo "[ultimate-dev-entrypoint] python=$python_bin"
  "$python_bin" - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit(f"Ultimate requires Python >=3.11 for default dev checks; got {sys.version.split()[0]}")
PY
  "$python_bin" -m pytest -q \
    tests/test_cli.py::test_cli_prepare_intake \
    tests/test_analysis_levels.py \
    tests/test_packaging_stability.py \
    tests/test_handoff_check.py
  "$python_bin" -m pip install -e .
  ultimate --help >/dev/null
  ultimate handoff-check --root "$root" --output-dir "$tmp_dir/handoff_check" >/dev/null
  ultimate prepare-intake --root "$tmp_dir/root" --output-dir "$tmp_dir/intake" --refresh-audit >/dev/null
  "$python_bin" - "$tmp_dir" <<'PY'
import json
import sys
from pathlib import Path

tmp = Path(sys.argv[1])
handoff = json.loads((tmp / "handoff_check" / "handoff_check_manifest.json").read_text(encoding="utf-8"))
if handoff.get("status") != "ready":
    raise SystemExit(f"handoff-check not ready: {handoff}")
intake = json.loads((tmp / "intake" / "intake_package_manifest.json").read_text(encoding="utf-8"))
template_status = intake.get("template_status") if isinstance(intake.get("template_status"), dict) else {}
if template_status.get("status") != "ready":
    raise SystemExit(f"prepare-intake template lookup not ready: {intake}")
print("dev_entrypoint_status=ready")
PY
}

run_remote_checks() {
  local root="$1"
  local python_bin="$2"
  local remote_python_setup
  if [[ -n "$python_bin" ]]; then
    remote_python_setup="PYTHON_BIN='$python_bin'"
  else
    remote_python_setup='
if [[ -x "$ROOT/.conda/envs/ultimate-core/bin/python" ]]; then
  PYTHON_BIN="$ROOT/.conda/envs/ultimate-core/bin/python"
else
  PYTHON_BIN="$(command -v python3)"
fi'
  fi

  hpc-run "set -euo pipefail
ROOT='$root'
$remote_python_setup
TMP_DIR=\"\$(mktemp -d)\"
trap 'rm -rf \"\$TMP_DIR\"' EXIT
cd \"\$ROOT\"
echo \"[ultimate-dev-entrypoint] root=\$ROOT\"
echo \"[ultimate-dev-entrypoint] python=\$PYTHON_BIN\"
\"\$PYTHON_BIN\" -m pytest -q \\
  tests/test_cli.py::test_cli_prepare_intake \\
  tests/test_analysis_levels.py \\
  tests/test_packaging_stability.py \\
  tests/test_handoff_check.py
\"\$PYTHON_BIN\" -m pip install -e .
\"\$ROOT/.conda/envs/ultimate-core/bin/ultimate\" --help >/dev/null
\"\$ROOT/.conda/envs/ultimate-core/bin/ultimate\" handoff-check --root \"\$ROOT\" --output-dir \"\$TMP_DIR/handoff_check\" >/dev/null
\"\$ROOT/.conda/envs/ultimate-core/bin/ultimate\" prepare-intake --root \"\$TMP_DIR/root\" --output-dir \"\$TMP_DIR/intake\" --refresh-audit >/dev/null
\"\$PYTHON_BIN\" - \"\$TMP_DIR\" <<'PY'
import json
import sys
from pathlib import Path

tmp = Path(sys.argv[1])
handoff = json.loads((tmp / 'handoff_check' / 'handoff_check_manifest.json').read_text(encoding='utf-8'))
if handoff.get('status') != 'ready':
    raise SystemExit(f'handoff-check not ready: {handoff}')
intake = json.loads((tmp / 'intake' / 'intake_package_manifest.json').read_text(encoding='utf-8'))
template_status = intake.get('template_status') if isinstance(intake.get('template_status'), dict) else {}
if template_status.get('status') != 'ready':
    raise SystemExit(f'prepare-intake template lookup not ready: {intake}')
print('dev_entrypoint_status=ready')
PY"
}

if [[ "$MODE" == "remote" ]]; then
  run_remote_checks "$ROOT" "$PYTHON_BIN"
else
  run_local_checks "$ROOT" "${PYTHON_BIN:-python}"
fi
