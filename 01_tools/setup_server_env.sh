#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/envs/environment.core.yml"
ENV_PREFIX="${1:-$PROJECT_ROOT/.conda/envs/ultimate-core}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing environment file: $ENV_FILE" >&2
  exit 1
fi

if [[ ! -f /share/home/nshen/miniconda3/etc/profile.d/conda.sh ]]; then
  echo "Could not find conda activation script under /share/home/nshen/miniconda3" >&2
  exit 1
fi

source /share/home/nshen/miniconda3/etc/profile.d/conda.sh

if command -v mamba >/dev/null 2>&1; then
  CONDA_FRONTEND="mamba"
else
  CONDA_FRONTEND="conda"
fi

mkdir -p "$(dirname "$ENV_PREFIX")"
export CONDA_PKGS_DIRS="${CONDA_PKGS_DIRS:-$PROJECT_ROOT/.conda/pkgs}"
mkdir -p "$CONDA_PKGS_DIRS"

if [[ -d "$ENV_PREFIX" ]]; then
  "$CONDA_FRONTEND" env update -p "$ENV_PREFIX" -f "$ENV_FILE" --prune
else
  "$CONDA_FRONTEND" env create -p "$ENV_PREFIX" -f "$ENV_FILE"
fi

conda run -p "$ENV_PREFIX" python -m pip install -e "$PROJECT_ROOT"

echo "Environment ready: $ENV_PREFIX"
conda run -p "$ENV_PREFIX" python - <<'PY'
import importlib
mods = ["ultimate", "click", "yaml", "pandas", "numpy", "matplotlib", "seaborn", "jinja2"]
for mod in mods:
    module = importlib.import_module(mod)
    print(f"{mod}\t{getattr(module, '__version__', 'ok')}")
PY
