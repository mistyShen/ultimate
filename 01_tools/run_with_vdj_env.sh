#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
VDJ_ENV="${ULTIMATE_VDJ_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-vdj}"
export LD_PRELOAD="${LD_PRELOAD:-$VDJ_ENV/lib/libgomp.so.1}"
exec "$VDJ_ENV/bin/python" "$@"

