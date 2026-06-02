#!/usr/bin/env bash
#SBATCH --job-name=ult_mirror_test
#SBATCH --output=/shared/shen/2026/ultimate/logs/%x_%j.out
#SBATCH --error=/shared/shen/2026/ultimate/logs/%x_%j.err
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:20:00

set -euo pipefail

PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
CORE_ENV="${ULTIMATE_CORE_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-core}"
CONDA_SH="${CONDA_SH:-/share/home/nshen/miniconda3/etc/profile.d/conda.sh}"
CONDARC_PATH="${ULTIMATE_CONDARC:-$PROJECT_ROOT/config/condarc.mirrors.tuna.yml}"

mkdir -p "$PROJECT_ROOT/logs" "$PROJECT_ROOT/audits/mirror_test"
source "$CONDA_SH"
export CONDA_PKGS_DIRS="$PROJECT_ROOT/.conda/pkgs"
export CONDARC="$CONDARC_PATH"

echo "CONDARC=$CONDARC"
echo "CONDA_PKGS_DIRS=$CONDA_PKGS_DIRS"

python - <<'PY'
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

urls = [
    "https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge/linux-64/repodata.json.zst",
    "https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/bioconda/linux-64/repodata.json.zst",
    "https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main/linux-64/repodata.json.zst",
]
rows = []
for url in urls:
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=20) as response:
            rows.append({"url": url, "ok": True, "status": response.status})
    except Exception as exc:
        rows.append({"url": url, "ok": False, "error": f"{type(exc).__name__}: {exc}"})

out = Path("/shared/shen/2026/ultimate/audits/mirror_test/connectivity.json")
out.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "results": rows}, indent=2, ensure_ascii=False), encoding="utf-8")
print(out.read_text(encoding="utf-8"))
PY

if [[ -x "$CORE_ENV/bin/python" ]]; then
  conda activate "$CORE_ENV"
fi
mamba search -c conda-forge -c bioconda --override-channels samtools --json > "$PROJECT_ROOT/audits/mirror_test/mamba_search_samtools.json"

