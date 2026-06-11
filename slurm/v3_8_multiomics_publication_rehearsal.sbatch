#!/usr/bin/env bash
#SBATCH --job-name=ult_v3_8_rehearsal
#SBATCH --output=/shared/shen/2026/ultimate/logs/%x_%j.out
#SBATCH --error=/shared/shen/2026/ultimate/logs/%x_%j.err
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --time=08:00:00

set -euo pipefail

PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
CORE_ENV="${ULTIMATE_CORE_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-core}"
SCRNA_ENV="${ULTIMATE_SCRNA_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-scrna}"
CONDA_SH="${CONDA_SH:-}"
STAMP="${ULTIMATE_V38_REHEARSAL_STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}"

mkdir -p "$PROJECT_ROOT/logs" "$PROJECT_ROOT/jobs" "$PROJECT_ROOT/reports"
cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

if [[ -f "$CONDA_SH" ]]; then
  # shellcheck disable=SC1090
  source "$CONDA_SH"
fi

write_job_manifest() {
  local job_dir="$1"
  local job_id="$2"
  mkdir -p "$job_dir"/{config,samples,runs,logs,deliverables,reproducible_code,raw_links}
  "$CORE_ENV/bin/python" - "$job_dir" "$job_id" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

job_dir = Path(sys.argv[1])
job_id = sys.argv[2]
manifest = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "job_id": job_id,
    "job_dir": str(job_dir),
    "run_mode": "production",
    "delivery_scope": "internal_rehearsal",
    "policy": "V3.8 production-style rehearsal; not customer_delivery.",
    "directories": {
        name: str(job_dir / name)
        for name in ("config", "samples", "runs", "logs", "deliverables", "reproducible_code", "raw_links")
    },
}
(job_dir / "job_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
PY
}

write_approval() {
  local approval_path="$1"
  local project_id="$2"
  local config_path="$3"
  local output_dir="$4"
  "$CORE_ENV/bin/python" - "$approval_path" "$project_id" "$config_path" "$output_dir" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

approval_path = Path(sys.argv[1])
payload = {
    "approved": True,
    "approved_by": "ultimate_v3_8_rehearsal",
    "approved_at": datetime.now(timezone.utc).isoformat(),
    "project_id": sys.argv[2],
    "input_path": str(Path(sys.argv[3]).resolve()),
    "output_dir": str(Path(sys.argv[4]).resolve()),
    "delivery_scope": "internal_rehearsal",
    "reason": "Internal V3.8 production-style rehearsal; not customer_delivery.",
}
approval_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
PY
}

run_ultimate_job() {
  local job_id="$1"
  local env_prefix="$2"
  local job_dir="$PROJECT_ROOT/jobs/$job_id"
  local config_path="$job_dir/config/project.yaml"
  local approval_path="$job_dir/config/production_approval.json"
  ULTIMATE_ENV="$env_prefix" bash "$PROJECT_ROOT/slurm/ultimate_run.sbatch" "$config_path" "$approval_path"
  "$env_prefix/bin/python" -m ultimate.cli delivery-check --run-dir "$job_dir"
}

write_tabular_job() {
  local module="$1"
  local preset="$2"
  local job_id="v3_8_${module}_${preset}_rehearsal_${STAMP}"
  local job_dir="$PROJECT_ROOT/jobs/$job_id"
  local run_dir="$job_dir/runs/$job_id"
  write_job_manifest "$job_dir" "$job_id"
  "$CORE_ENV/bin/python" - "$job_dir" "$module" <<'PY'
import numpy as np
import pandas as pd
import sys
from pathlib import Path

job_dir = Path(sys.argv[1])
module = sys.argv[2]
rng = np.random.default_rng(3800 + len(module))
samples = pd.DataFrame({
    "sample_id": ["CTRL_A", "CTRL_B", "CASE_A", "CASE_B"],
    "condition": ["control", "control", "case", "case"],
})
features = [f"{module.upper()}_{idx:04d}" for idx in range(1, 81)]
if module == "methylation":
    values = rng.beta(2, 5, size=(len(features), 4))
    values[:10, 2:] = np.clip(values[:10, 2:] + 0.22, 0.001, 0.999)
else:
    values = rng.lognormal(mean=5.0, sigma=0.35, size=(len(features), 4))
    values[:12, 2:] *= 1.8
    if module == "rnaseq":
        values = np.rint(values).astype(int)
matrix = pd.DataFrame(values, columns=samples["sample_id"])
matrix.insert(0, "feature_id", features)
matrix_path = job_dir / "samples" / f"{module}_matrix.tsv"
matrix.to_csv(matrix_path, sep="\t", index=False)
samples["input_path"] = str(matrix_path)
samples.to_csv(job_dir / "samples" / "samples.tsv", sep="\t", index=False)
(job_dir / "config" / "analysis_request.md").write_text(
    f"{module} publication internal rehearsal. Results are computational/statistical evidence only and not customer delivery.\\n",
    encoding="utf-8",
)
PY
  cat > "$job_dir/config/project.yaml" <<YAML
project:
  name: $job_id
  job_id: $job_id
  organism: human
  output_dir: $run_dir
  server_root: $PROJECT_ROOT
  run_mode: production
  analysis_level: production_backend
  delivery_scope: internal_rehearsal
  is_demo: false
analysis_request: $job_dir/config/analysis_request.md
samples:
  samplesheet: $job_dir/samples/samples.tsv
design:
  condition_column: condition
  control: control
  case: case
modules:
  $module:
    enabled: true
    preset: $preset
    raw:
      enabled: false
    input_matrix: $job_dir/samples/${module}_matrix.tsv
    analysis_level: production_backend
    is_demo: false
report:
  title: V3.8 $module publication internal rehearsal
  style: morandi_clinical
  figure_options:
    legend_position: outside_right
    show_grid: true
YAML
  write_approval "$job_dir/config/production_approval.json" "$job_id" "$job_dir/config/project.yaml" "$run_dir"
  run_ultimate_job "$job_id" "$CORE_ENV"
}

write_scatac_job() {
  local job_id="v3_8_scatac_publication_rehearsal_${STAMP}"
  local job_dir="$PROJECT_ROOT/jobs/$job_id"
  local run_dir="$job_dir/runs/$job_id"
  write_job_manifest "$job_dir" "$job_id"
  "$CORE_ENV/bin/python" - "$job_dir" <<'PY'
import numpy as np
import pandas as pd
import sys
from pathlib import Path

job_dir = Path(sys.argv[1])
rng = np.random.default_rng(3810)
cells = [f"CELL_{idx:03d}" for idx in range(1, 49)]
peaks = [f"chr1:{1000 + idx * 200}-{1100 + idx * 200}" for idx in range(72)]
values = rng.poisson(2.0, size=(len(peaks), len(cells))).astype(float)
values[:12, 24:] += rng.poisson(3.0, size=(12, 24))
matrix = pd.DataFrame(values, columns=cells)
matrix.insert(0, "peak_id", peaks)
matrix.to_csv(job_dir / "samples" / "scatac_peak_matrix.tsv", sep="\t", index=False)
metadata = pd.DataFrame({"cell_id": cells, "condition": ["control"] * 24 + ["treated"] * 24})
metadata.to_csv(job_dir / "samples" / "cell_metadata.tsv", sep="\t", index=False)
pd.DataFrame({"sample_id": ["scatac_internal"], "condition": ["publication"], "input_path": [str(job_dir / "samples" / "scatac_peak_matrix.tsv")]}).to_csv(job_dir / "samples" / "samples.tsv", sep="\t", index=False)
(job_dir / "config" / "analysis_request.md").write_text("scATAC publication internal rehearsal. DAR is peak accessibility, not gene expression.\\n", encoding="utf-8")
PY
  cat > "$job_dir/config/project.yaml" <<YAML
project:
  name: $job_id
  job_id: $job_id
  organism: human
  output_dir: $run_dir
  server_root: $PROJECT_ROOT
  run_mode: production
  analysis_level: production_backend
  delivery_scope: internal_rehearsal
  is_demo: false
analysis_request: $job_dir/config/analysis_request.md
samples:
  samplesheet: $job_dir/samples/samples.tsv
design:
  condition_column: condition
  control: control
  case: treated
modules:
  scatac:
    enabled: true
    preset: publication
    raw:
      enabled: false
    peak_matrix: $job_dir/samples/scatac_peak_matrix.tsv
    cell_metadata: $job_dir/samples/cell_metadata.tsv
    analysis_level: production_backend
    is_demo: false
report:
  title: V3.8 scATAC publication internal rehearsal
  style: morandi_clinical
YAML
  write_approval "$job_dir/config/production_approval.json" "$job_id" "$job_dir/config/project.yaml" "$run_dir"
  run_ultimate_job "$job_id" "$CORE_ENV"
}

write_multiome_job() {
  local job_id="v3_8_multiome_publication_rehearsal_${STAMP}"
  local job_dir="$PROJECT_ROOT/jobs/$job_id"
  local run_dir="$job_dir/runs/$job_id"
  write_job_manifest "$job_dir" "$job_id"
  "$CORE_ENV/bin/python" - "$job_dir" <<'PY'
import numpy as np
import pandas as pd
import sys
from pathlib import Path

job_dir = Path(sys.argv[1])
rng = np.random.default_rng(3820)
cells = [f"CELL_{idx:03d}" for idx in range(1, 61)]
rna = rng.poisson(4.0, size=(60, len(cells))).astype(float)
atac = rng.poisson(2.0, size=(80, len(cells))).astype(float)
rna[:8, 30:] += 4
atac[:8, 30:] += 3
rna_frame = pd.DataFrame(rna, columns=cells)
rna_frame.insert(0, "feature_id", [f"GENE_{idx:03d}" for idx in range(60)])
atac_frame = pd.DataFrame(atac, columns=cells)
atac_frame.insert(0, "peak_id", [f"chr1:{1000 + idx * 180}-{1080 + idx * 180}" for idx in range(80)])
rna_frame.to_csv(job_dir / "samples" / "multiome_rna.tsv", sep="\t", index=False)
atac_frame.to_csv(job_dir / "samples" / "multiome_atac.tsv", sep="\t", index=False)
pd.DataFrame({"sample_id": ["multiome_internal"], "condition": ["publication"], "input_path": [str(job_dir / "samples" / "multiome_rna.tsv")]}).to_csv(job_dir / "samples" / "samples.tsv", sep="\t", index=False)
(job_dir / "config" / "analysis_request.md").write_text("Multiome publication internal rehearsal. Peak-gene links are statistical correlations.\\n", encoding="utf-8")
PY
  cat > "$job_dir/config/project.yaml" <<YAML
project:
  name: $job_id
  job_id: $job_id
  organism: human
  output_dir: $run_dir
  server_root: $PROJECT_ROOT
  run_mode: production
  analysis_level: production_backend
  delivery_scope: internal_rehearsal
  is_demo: false
analysis_request: $job_dir/config/analysis_request.md
samples:
  samplesheet: $job_dir/samples/samples.tsv
modules:
  multiome:
    enabled: true
    preset: publication
    raw:
      enabled: false
    rna_matrix: $job_dir/samples/multiome_rna.tsv
    atac_matrix: $job_dir/samples/multiome_atac.tsv
    analysis_level: production_backend
    is_demo: false
report:
  title: V3.8 Multiome publication internal rehearsal
  style: morandi_clinical
YAML
  write_approval "$job_dir/config/production_approval.json" "$job_id" "$job_dir/config/project.yaml" "$run_dir"
  run_ultimate_job "$job_id" "$CORE_ENV"
}

write_spatial_job() {
  local job_id="v3_8_spatial_publication_rehearsal_${STAMP}"
  local job_dir="$PROJECT_ROOT/jobs/$job_id"
  local run_dir="$job_dir/runs/$job_id"
  write_job_manifest "$job_dir" "$job_id"
  "$CORE_ENV/bin/python" - "$job_dir" <<'PY'
import numpy as np
import pandas as pd
import sys
from pathlib import Path

job_dir = Path(sys.argv[1])
rng = np.random.default_rng(3830)
spots = [f"SPOT_{idx:03d}" for idx in range(1, 121)]
genes = [f"GENE_{idx:03d}" for idx in range(50)]
coords = pd.DataFrame({"spot_id": spots, "x": np.tile(np.arange(12), 10)[:120], "y": np.repeat(np.arange(10), 12)[:120]})
values = rng.poisson(4.0, size=(len(genes), len(spots))).astype(float)
values[:6, coords["x"].to_numpy() > 6] += 4
matrix = pd.DataFrame(values, columns=spots)
matrix.insert(0, "feature_id", genes)
matrix.to_csv(job_dir / "samples" / "spatial_expression.tsv", sep="\t", index=False)
coords.to_csv(job_dir / "samples" / "spatial_coordinates.tsv", sep="\t", index=False)
pd.DataFrame({"sample_id": ["spatial_internal"], "condition": ["publication"], "input_path": [str(job_dir / "samples" / "spatial_expression.tsv")]}).to_csv(job_dir / "samples" / "samples.tsv", sep="\t", index=False)
(job_dir / "config" / "analysis_request.md").write_text("Spatial publication internal rehearsal. Visium-style spots are not single cells.\\n", encoding="utf-8")
PY
  cat > "$job_dir/config/project.yaml" <<YAML
project:
  name: $job_id
  job_id: $job_id
  organism: human
  output_dir: $run_dir
  server_root: $PROJECT_ROOT
  run_mode: production
  analysis_level: production_backend
  delivery_scope: internal_rehearsal
  is_demo: false
analysis_request: $job_dir/config/analysis_request.md
samples:
  samplesheet: $job_dir/samples/samples.tsv
modules:
  spatial:
    enabled: true
    preset: publication
    raw:
      enabled: false
    expression_matrix: $job_dir/samples/spatial_expression.tsv
    coordinates: $job_dir/samples/spatial_coordinates.tsv
    analysis_level: production_backend
    is_demo: false
report:
  title: V3.8 Spatial publication internal rehearsal
  style: morandi_clinical
YAML
  write_approval "$job_dir/config/production_approval.json" "$job_id" "$job_dir/config/project.yaml" "$run_dir"
  run_ultimate_job "$job_id" "$CORE_ENV"
}

write_scrna_job() {
  local job_id="v3_8_scrna_publication_rehearsal_${STAMP}"
  local job_dir="$PROJECT_ROOT/jobs/$job_id"
  local run_dir="$job_dir/runs/$job_id"
  local matrix_dir="${ULTIMATE_V38_SCRNA_MATRIX:-$PROJECT_ROOT/public_data/scrna_pbmc3k/filtered_gene_bc_matrices/hg19}"
  write_job_manifest "$job_dir" "$job_id"
  if [[ ! -d "$matrix_dir" ]]; then
    echo "Missing PBMC3k matrix directory for scRNA rehearsal: $matrix_dir" >&2
    exit 3
  fi
  "$CORE_ENV/bin/python" - "$matrix_dir" "$job_dir" <<'PY'
from pathlib import Path
import gzip
import pandas as pd
import sys

matrix_dir = Path(sys.argv[1])
job_dir = Path(sys.argv[2])
barcodes = matrix_dir / "barcodes.tsv"
if not barcodes.exists():
    barcodes = matrix_dir / "barcodes.tsv.gz"
opener = gzip.open if barcodes.suffix == ".gz" else open
with opener(barcodes, "rt", encoding="utf-8") as handle:
    cells = [line.strip().split("\t")[0] for line in handle if line.strip()]
labels = pd.DataFrame({
    "barcode": cells,
    "sample_id": [f"scrna_sample_{1 + idx % 2}" for idx in range(len(cells))],
    "condition": ["control" if idx % 2 == 0 else "case" for idx in range(len(cells))],
    "reviewed_cell_type": [f"reviewed_group_{1 + idx % 3}" for idx in range(len(cells))],
})
labels.to_csv(job_dir / "samples" / "scrna_samples.tsv", sep="\t", index=False)
(job_dir / "config" / "analysis_request.md").write_text("scRNA publication internal rehearsal. Cluster labels are not automatic cell types.\\n", encoding="utf-8")
PY
  cat > "$job_dir/config/project.yaml" <<YAML
project:
  name: $job_id
  job_id: $job_id
  organism: human
  output_dir: $run_dir
  server_root: $PROJECT_ROOT
  run_mode: production
  analysis_level: production_backend
  delivery_scope: internal_rehearsal
  is_demo: false
analysis_request: $job_dir/config/analysis_request.md
samples:
  samplesheet: $job_dir/samples/scrna_samples.tsv
design:
  condition_column: condition
  control: control
  case: case
modules:
  scrna:
    enabled: true
    preset: publication
    raw:
      enabled: false
    tenx_mtx: $matrix_dir
    samplesheet: $job_dir/samples/scrna_samples.tsv
    max_cells: 800
    analysis_level: production_backend
    is_demo: false
report:
  title: V3.8 scRNA publication internal rehearsal
  style: morandi_clinical
YAML
  write_approval "$job_dir/config/production_approval.json" "$job_id" "$job_dir/config/project.yaml" "$run_dir"
  run_ultimate_job "$job_id" "$SCRNA_ENV"
}

write_tabular_job rnaseq publication
write_scrna_job
write_tabular_job proteomics publication
write_tabular_job methylation publication
write_scatac_job
write_multiome_job
write_spatial_job

"$CORE_ENV/bin/python" -m ultimate.cli validation-index \
  --root "$PROJECT_ROOT" \
  --output-dir "$PROJECT_ROOT/reports/validation_index_v38"
"$CORE_ENV/bin/python" -m ultimate.cli audit-production \
  --root "$PROJECT_ROOT" \
  --output-dir "$PROJECT_ROOT/audits/production_v38_latest"
"$CORE_ENV/bin/python" -m ultimate.cli audit-backends \
  --root "$PROJECT_ROOT" \
  --output-dir "$PROJECT_ROOT/audits/backends_v38_latest"

"$CORE_ENV/bin/python" - "$PROJECT_ROOT" "$STAMP" <<'PY'
import csv
from pathlib import Path
import sys

root = Path(sys.argv[1])
stamp = sys.argv[2]
index = root / "reports" / "validation_index_v38" / "validation_index.tsv"
rows = []
if index.exists():
    rows = list(csv.DictReader(index.open(), delimiter="\t"))
v38 = [r for r in rows if r.get("run_name", "").startswith("v3_8_") and r.get("run_name", "").endswith(stamp)]
ready = [r for r in v38 if r.get("order_readiness_status") == "ready_for_delivery" and r.get("delivery_scope") == "internal_rehearsal"]
blocked = [r for r in v38 if r not in ready]
path = root / "reports" / "v3_8_order_ready_report.md"
path.parent.mkdir(parents=True, exist_ok=True)
lines = [
    "# Ultimate V3.8 order-ready report",
    "",
    f"- Suite stamp: `{stamp}`",
    f"- V3.8 rehearsal jobs found: {len(v38)}",
    f"- Ready internal rehearsals: {len(ready)}",
    f"- Blocked/needs review: {len(blocked)}",
    "",
    "## Ready modules",
]
for row in ready:
    lines.append(f"- `{row.get('module')}` / `{row.get('run_name')}` / Slurm `{row.get('slurm_job_id')}`")
lines.append("")
lines.append("## Blocked or needs review")
for row in blocked:
    lines.append(f"- `{row.get('module')}` / `{row.get('run_name')}`: {row.get('missing_or_gap') or row.get('next_action') or row.get('order_readiness_status')}")
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(path)
PY
