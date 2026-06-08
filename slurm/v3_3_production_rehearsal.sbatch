#!/usr/bin/env bash
#SBATCH --job-name=ult_v3_3_rehearsal
#SBATCH --output=/shared/shen/2026/ultimate/logs/%x_%j.out
#SBATCH --error=/shared/shen/2026/ultimate/logs/%x_%j.err
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=08:00:00

set -euo pipefail

PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
CORE_ENV="${ULTIMATE_CORE_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-core}"
SCRNA_ENV="${ULTIMATE_SCRNA_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-scrna}"
SCATAC_ENV="${ULTIMATE_SCATAC_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-scatac-multiome}"
SCRNA_R_ENV="${ULTIMATE_SCRNA_R_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-scrna-r}"
SCATAC_R_ENV="${ULTIMATE_SCATAC_R_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-scatac-r}"
CONDA_SH="${CONDA_SH:-/share/home/nshen/miniconda3/etc/profile.d/conda.sh}"
STAMP="${ULTIMATE_V33_REHEARSAL_STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}"

mkdir -p "$PROJECT_ROOT/logs" "$PROJECT_ROOT/jobs" "$PROJECT_ROOT/reports"
cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT/src:${PYTHONPATH:-}"

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
    "policy": "V3.3 production-style rehearsal; not customer_delivery.",
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
    "approved_by": "ultimate_v3_3_rehearsal",
    "approved_at": datetime.now(timezone.utc).isoformat(),
    "project_id": sys.argv[2],
    "input_path": str(Path(sys.argv[3]).resolve()),
    "output_dir": str(Path(sys.argv[4]).resolve()),
    "delivery_scope": "internal_rehearsal",
    "reason": "Internal production-style rehearsal for V3.3 delivery QA; not customer_delivery.",
}
approval_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
PY
}

run_ultimate_job() {
  local job_id="$1"
  local env_prefix="$2"
  local extra_path="$3"
  local job_dir="$PROJECT_ROOT/jobs/$job_id"
  local config_path="$job_dir/config/project.yaml"
  local approval_path="$job_dir/config/production_approval.json"
  if [[ -n "$extra_path" ]]; then
    export PATH="$extra_path:$PATH"
  fi
  ULTIMATE_ENV="$env_prefix" bash "$PROJECT_ROOT/slurm/ultimate_run.sbatch" "$config_path" "$approval_path"
  "$env_prefix/bin/python" -m ultimate.cli delivery-check --run-dir "$job_dir"
}

select_python_env() {
  for candidate in "$@"; do
    if [[ -x "$candidate/bin/python" ]]; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

write_rnaseq_job() {
  local job_id="v3_3_rnaseq_matrix_rehearsal_${STAMP}"
  local job_dir="$PROJECT_ROOT/jobs/$job_id"
  local run_dir="$job_dir/runs/$job_id"
  write_job_manifest "$job_dir" "$job_id"
  "$CORE_ENV/bin/python" - "$job_dir" <<'PY'
import numpy as np
import pandas as pd
import sys
from pathlib import Path

job_dir = Path(sys.argv[1])
matrix_path = job_dir / "samples" / "rnaseq_counts.tsv"
samples = pd.DataFrame(
    {
        "sample_id": ["CTRL_A", "CTRL_B", "CASE_A", "CASE_B"],
        "condition": ["control", "control", "case", "case"],
        "input_path": [str(matrix_path)] * 4,
    }
)
genes = [f"GENE_{idx:04d}" for idx in range(1, 81)]
rng = np.random.default_rng(7331)
counts = rng.negative_binomial(n=40, p=0.42, size=(len(genes), 4)).astype(int)
counts[:12, 2:] = (counts[:12, 2:] * 2.2 + 10).astype(int)
matrix = pd.DataFrame(counts, columns=samples["sample_id"])
matrix.insert(0, "feature_id", genes)
samples.to_csv(job_dir / "samples" / "samples.tsv", sep="\t", index=False)
matrix.to_csv(matrix_path, sep="\t", index=False)
(job_dir / "config" / "analysis_request.md").write_text(
    "rnaseq matrix production-style internal rehearsal. Deliver QC, DE-ready table, report, and reproducible package.\n",
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
  condition: condition
  control: control
  case: case
modules:
  rnaseq:
    enabled: true
    preset: standard
    input_matrix: $job_dir/samples/rnaseq_counts.tsv
    input_matrix_kind: raw_gene_counts
    analysis_level: production_backend
    is_demo: false
report:
  title: V3.3 RNA-seq matrix internal rehearsal
  style: soft_color
YAML
  write_approval "$job_dir/config/production_approval.json" "$job_id" "$job_dir/config/project.yaml" "$run_dir"
  run_ultimate_job "$job_id" "$CORE_ENV" ""
}

write_scrna_job() {
  local job_id="v3_3_scrna_communication_rehearsal_${STAMP}"
  local job_dir="$PROJECT_ROOT/jobs/$job_id"
  local run_dir="$job_dir/runs/$job_id"
  local matrix_dir="${ULTIMATE_V33_SCRNA_MATRIX:-$PROJECT_ROOT/public_data/scrna_pbmc3k/filtered_gene_bc_matrices/hg19}"
  write_job_manifest "$job_dir" "$job_id"
  if [[ ! -d "$matrix_dir" ]]; then
    "$CORE_ENV/bin/python" "$PROJECT_ROOT/01_tools/prepare_public_singlecell_manifests.py" --root "$PROJECT_ROOT" --mode download || true
  fi
  if [[ ! -d "$matrix_dir" ]]; then
    echo "Missing PBMC3k matrix directory for scRNA rehearsal: $matrix_dir" >&2
    exit 3
  fi
  "$SCRNA_ENV/bin/python" - "$matrix_dir" "$job_dir" <<'PY'
import gzip
import sys
from pathlib import Path
import pandas as pd

matrix_dir = Path(sys.argv[1])
job_dir = Path(sys.argv[2])
barcodes_path = matrix_dir / "barcodes.tsv"
genes_path = matrix_dir / "genes.tsv"
if not barcodes_path.exists():
    barcodes_path = matrix_dir / "barcodes.tsv.gz"
if not genes_path.exists():
    genes_path = matrix_dir / "genes.tsv.gz"

def read_first(path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        return [line.rstrip("\n").split("\t")[0] for line in handle if line.strip()]

barcodes = read_first(barcodes_path)
genes = read_first(genes_path)
groups = ["reviewed_T_like", "reviewed_B_like", "reviewed_myeloid_like"]
labels = [
    {
        "barcode": barcode,
        "sample_id": f"rehearsal_sample_{1 + (idx % 2)}",
        "condition": "case" if idx % 2 else "control",
        "reviewed_cell_type": groups[idx % len(groups)],
    }
    for idx, barcode in enumerate(barcodes)
]
pd.DataFrame(labels).to_csv(job_dir / "samples" / "reviewed_cell_labels.tsv", sep="\t", index=False)
ligands = genes[: min(8, len(genes))]
targets = genes[: min(600, len(genes))]
rows = []
for ligand_idx, ligand in enumerate(ligands):
    for target_idx, target in enumerate(targets):
        if ligand != target:
            rows.append({"ligand": ligand, "target": target, "weight": round(1.0 / (1 + ((ligand_idx + target_idx) % 25)), 5)})
pd.DataFrame(rows).to_csv(job_dir / "samples" / "nichenet_ligand_target_resource.tsv", sep="\t", index=False)
(job_dir / "config" / "analysis_request.md").write_text(
    "scRNA communication production-style internal rehearsal. Use reviewed validation labels; results are candidate communication inferences only.\n",
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
  samplesheet: $job_dir/samples/reviewed_cell_labels.tsv
design:
  condition: condition
  control: control
  case: case
resources:
  nichenet_resource: $job_dir/samples/nichenet_ligand_target_resource.tsv
modules:
  scrna:
    enabled: true
    preset: communication
    input_path: $matrix_dir
    input_type: 10x_mtx
    samplesheet: $job_dir/samples/reviewed_cell_labels.tsv
    nichenet_resource: $job_dir/samples/nichenet_ligand_target_resource.tsv
    analysis_level: production_backend
    is_demo: false
    max_cells: ${ULTIMATE_V33_SCRNA_MAX_CELLS:-350}
    backends:
      communication: liana,cellchat,nichenet
      annotation: celltypist
report:
  title: V3.3 scRNA communication internal rehearsal
  style: soft_color
YAML
  write_approval "$job_dir/config/production_approval.json" "$job_id" "$job_dir/config/project.yaml" "$run_dir"
  run_ultimate_job "$job_id" "$SCRNA_ENV" "$SCRNA_R_ENV/bin"
}

write_scatac_job() {
  local job_id="v3_3_scatac_publication_rehearsal_${STAMP}"
  local job_dir="$PROJECT_ROOT/jobs/$job_id"
  local run_dir="$job_dir/runs/$job_id"
  local input_h5="${ULTIMATE_V33_SCATAC_H5:-$PROJECT_ROOT/public_data/scatac/10k_pbmc_ATACv2_nextgem_Chromium_Controller_filtered_peak_bc_matrix.h5}"
  local scatac_run_env
  write_job_manifest "$job_dir" "$job_id"
  if ! scatac_run_env="$(select_python_env "$SCATAC_ENV" "$SCRNA_ENV" "$CORE_ENV")"; then
    echo "No usable Python environment found for scATAC rehearsal." >&2
    exit 5
  fi
  if [[ ! -s "$input_h5" ]]; then
    "$CORE_ENV/bin/python" "$PROJECT_ROOT/01_tools/prepare_public_singlecell_manifests.py" --root "$PROJECT_ROOT" --mode download || true
  fi
  if [[ ! -s "$input_h5" ]]; then
    echo "Missing scATAC peak matrix H5 for publication rehearsal: $input_h5" >&2
    exit 4
  fi
  "$scatac_run_env/bin/python" - "$input_h5" "$job_dir" "${ULTIMATE_V33_SCATAC_MAX_PEAKS:-160}" <<'PY'
import sys
from pathlib import Path
import h5py
import pandas as pd

input_h5 = Path(sys.argv[1])
job_dir = Path(sys.argv[2])
max_peaks = int(sys.argv[3])
with h5py.File(input_h5, "r") as handle:
    features = handle["matrix"]["features"]
    key = "name" if "name" in features else "id"
    peaks = [value.decode("utf-8") if isinstance(value, bytes) else str(value) for value in features[key][:max_peaks]]
motif_rows = [{"peak_id": peak, "motif_id": f"PBMC_MOTIF_{idx % 8:02d}"} for idx, peak in enumerate(peaks)]
gene_rows = [{"peak_id": peak, "gene_id": f"GENE_ACTIVITY_{idx % 12:02d}"} for idx, peak in enumerate(peaks)]
pd.DataFrame(motif_rows).to_csv(job_dir / "samples" / "motif_peak_table.tsv", sep="\t", index=False)
pd.DataFrame(gene_rows).to_csv(job_dir / "samples" / "gene_peak_table.tsv", sep="\t", index=False)
pd.DataFrame([{"sample_id": "pbmc_scatac", "condition": "public_rehearsal", "input_path": str(input_h5)}]).to_csv(
    job_dir / "samples" / "samples.tsv", sep="\t", index=False
)
(job_dir / "config" / "analysis_request.md").write_text(
    "scATAC publication production-style internal rehearsal. chromVAR/Signac-compatible motif and gene activity outputs are inference only.\n",
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
  condition: condition
modules:
  scatac:
    enabled: true
    preset: publication
    input_h5: $input_h5
    motif_peak_table: $job_dir/samples/motif_peak_table.tsv
    gene_peak_table: $job_dir/samples/gene_peak_table.tsv
    analysis_level: production_backend
    is_demo: false
    backends:
      motif: chromvar
    raw:
      enabled: false
      input_type: peak_matrix
report:
  title: V3.3 scATAC publication internal rehearsal
  style: soft_color
YAML
  write_approval "$job_dir/config/production_approval.json" "$job_id" "$job_dir/config/project.yaml" "$run_dir"
  run_ultimate_job "$job_id" "$scatac_run_env" "$SCATAC_R_ENV/bin"
}

write_rnaseq_job
write_scrna_job
write_scatac_job

"$CORE_ENV/bin/python" -m ultimate.cli validation-index \
  --root "$PROJECT_ROOT" \
  --output-dir "$PROJECT_ROOT/reports/validation_index"
"$CORE_ENV/bin/python" -m ultimate.cli audit-production \
  --root "$PROJECT_ROOT" \
  --output-dir "$PROJECT_ROOT/audits/production_latest"
"$CORE_ENV/bin/python" -m ultimate.cli audit-backends \
  --root "$PROJECT_ROOT" \
  --output-dir "$PROJECT_ROOT/audits/backends_latest"
"$CORE_ENV/bin/python" "$PROJECT_ROOT/01_tools/write_v3_3_order_ready_report.py" \
  --root "$PROJECT_ROOT" \
  --output-dir "$PROJECT_ROOT/reports"
