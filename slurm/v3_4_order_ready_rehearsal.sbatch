#!/usr/bin/env bash
#SBATCH --job-name=ult_v3_4_order_ready
#SBATCH --output=/shared/shen/2026/ultimate/logs/%x_%j.out
#SBATCH --error=/shared/shen/2026/ultimate/logs/%x_%j.err
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --time=06:00:00

set -euo pipefail

PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
CORE_ENV="${ULTIMATE_CORE_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-core}"
CONDA_SH="${CONDA_SH:-}"
STAMP="${ULTIMATE_V34_REHEARSAL_STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}"

mkdir -p "$PROJECT_ROOT/logs" "$PROJECT_ROOT/jobs" "$PROJECT_ROOT/reports"
cd "$PROJECT_ROOT"

if [[ -z "$CONDA_SH" ]]; then
  for candidate in \
    "$PROJECT_ROOT/.conda/etc/profile.d/conda.sh" \
    "$PROJECT_ROOT/miniconda3/etc/profile.d/conda.sh" \
    "/shared/shen/2026/ultimate/.conda/etc/profile.d/conda.sh"
  do
    if [[ -f "$candidate" ]]; then
      CONDA_SH="$candidate"
      break
    fi
  done
fi
if [[ -n "$CONDA_SH" && -f "$CONDA_SH" ]]; then
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
    "policy": "V3.4 order-ready production-style rehearsal; not customer_delivery.",
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
    "approved_by": "ultimate_v3_4_order_ready_rehearsal",
    "approved_at": datetime.now(timezone.utc).isoformat(),
    "project_id": sys.argv[2],
    "input_path": str(Path(sys.argv[3]).resolve()),
    "output_dir": str(Path(sys.argv[4]).resolve()),
    "delivery_scope": "internal_rehearsal",
    "reason": "Internal production-style rehearsal for V3.4 order-ready expansion; not customer_delivery.",
}
approval_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
PY
}

run_ultimate_job() {
  local job_id="$1"
  local job_dir="$PROJECT_ROOT/jobs/$job_id"
  local config_path="$job_dir/config/project.yaml"
  local approval_path="$job_dir/config/production_approval.json"
  ULTIMATE_ENV="$CORE_ENV" bash "$PROJECT_ROOT/slurm/ultimate_run.sbatch" "$config_path" "$approval_path"
  "$CORE_ENV/bin/python" -m ultimate.cli delivery-check --run-dir "$job_dir"
}

write_cite_seq_job() {
  local job_id="v3_4_cite_seq_standard_rehearsal_${STAMP}"
  local job_dir="$PROJECT_ROOT/jobs/$job_id"
  local run_dir="$job_dir/runs/$job_id"
  write_job_manifest "$job_dir" "$job_id"
  "$CORE_ENV/bin/python" - "$job_dir" <<'PY'
import numpy as np
import pandas as pd
import sys
from pathlib import Path

job_dir = Path(sys.argv[1])
cells = [f"cell_{idx:03d}" for idx in range(1, 49)]
rng = np.random.default_rng(1701)
rna = pd.DataFrame(rng.poisson(4, size=(40, len(cells))), columns=cells)
rna.insert(0, "feature_id", [f"GENE_{idx:03d}" for idx in range(1, 41)])
adt = pd.DataFrame(rng.poisson(20, size=(8, len(cells))), columns=cells)
adt.insert(0, "feature_id", [f"ADT_{idx:02d}" for idx in range(1, 9)])
rna.to_csv(job_dir / "samples" / "cite_rna_counts.tsv", sep="\t", index=False)
adt.to_csv(job_dir / "samples" / "cite_adt_counts.tsv", sep="\t", index=False)
pd.DataFrame({"sample_id": ["cite_internal"], "condition": ["standard"], "input_path": [str(job_dir / "samples" / "cite_rna_counts.tsv")]}).to_csv(job_dir / "samples" / "samples.tsv", sep="\t", index=False)
(job_dir / "config" / "analysis_request.md").write_text(
    "CITE-seq standard internal rehearsal using RNA+ADT matrices. ADT is antibody-panel-limited, not full proteomics.\n",
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
  cite_seq:
    enabled: true
    preset: standard
    rna_matrix: $job_dir/samples/cite_rna_counts.tsv
    adt_matrix: $job_dir/samples/cite_adt_counts.tsv
    analysis_level: production_backend
    is_demo: false
report:
  title: V3.4 CITE-seq standard internal rehearsal
YAML
  write_approval "$job_dir/config/production_approval.json" "$job_id" "$job_dir/config/project.yaml" "$run_dir"
  run_ultimate_job "$job_id"
}

write_vdj_job() {
  local job_id="v3_4_vdj_standard_rehearsal_${STAMP}"
  local job_dir="$PROJECT_ROOT/jobs/$job_id"
  local run_dir="$job_dir/runs/$job_id"
  write_job_manifest "$job_dir" "$job_id"
  "$CORE_ENV/bin/python" - "$job_dir" <<'PY'
import pandas as pd
import sys
from pathlib import Path

job_dir = Path(sys.argv[1])
barcodes = [f"Tcell_{idx:03d}" for idx in range(1, 37)]
rows = []
for idx, barcode in enumerate(barcodes):
    clonotype = f"clonotype{1 + idx % 7}"
    rows.append({
        "barcode": barcode,
        "is_cell": True,
        "productive": True,
        "chain": "TRB",
        "v_gene": f"TRBV{1 + idx % 5}",
        "j_gene": f"TRBJ{1 + idx % 3}",
        "cdr3": f"CASSLGQ{idx % 10}YF",
        "cdr3_nt": f"TGTGCCAGCAGT{idx:03d}",
        "reads": 100 + idx,
        "umis": 10 + idx % 6,
        "raw_clonotype_id": clonotype,
    })
contigs = pd.DataFrame(rows)
clonotypes = (
    contigs.groupby("raw_clonotype_id")
    .agg(frequency=("barcode", "size"), cdr3s_aa=("cdr3", lambda x: ";".join(sorted(set(map(str, x))))))
    .reset_index()
    .rename(columns={"raw_clonotype_id": "clonotype_id"})
)
contigs.to_csv(job_dir / "samples" / "filtered_contig_annotations.csv", index=False)
clonotypes.to_csv(job_dir / "samples" / "clonotypes.csv", index=False)
pd.DataFrame({
    "sample_id": ["VDJ_A", "VDJ_B"],
    "condition": ["control", "case"],
    "input_path": [str(job_dir / "samples" / "filtered_contig_annotations.csv")] * 2,
}).to_csv(job_dir / "samples" / "samples.tsv", sep="\t", index=False)
(job_dir / "config" / "analysis_request.md").write_text(
    "VDJ standard internal rehearsal. Clonotype sharing is not antigen specificity.\n",
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
  vdj:
    enabled: true
    preset: standard
    contig_annotations: $job_dir/samples/filtered_contig_annotations.csv
    clonotypes: $job_dir/samples/clonotypes.csv
    analysis_level: production_backend
    is_demo: false
report:
  title: V3.4 VDJ standard internal rehearsal
YAML
  write_approval "$job_dir/config/production_approval.json" "$job_id" "$job_dir/config/project.yaml" "$run_dir"
  run_ultimate_job "$job_id"
}

write_spatial_job() {
  local job_id="v3_4_spatial_standard_rehearsal_${STAMP}"
  local job_dir="$PROJECT_ROOT/jobs/$job_id"
  local run_dir="$job_dir/runs/$job_id"
  write_job_manifest "$job_dir" "$job_id"
  "$CORE_ENV/bin/python" - "$job_dir" <<'PY'
import numpy as np
import pandas as pd
import sys
from pathlib import Path

job_dir = Path(sys.argv[1])
spots = [f"spot_{idx:03d}" for idx in range(1, 65)]
rng = np.random.default_rng(2024)
matrix = pd.DataFrame(rng.poisson(6, size=(45, len(spots))), columns=spots)
matrix.insert(0, "feature_id", [f"GENE_{idx:03d}" for idx in range(1, 46)])
coords = pd.DataFrame({
    "spot_id": spots,
    "x": [idx % 8 for idx in range(len(spots))],
    "y": [idx // 8 for idx in range(len(spots))],
    "in_tissue": 1,
})
matrix.to_csv(job_dir / "samples" / "spatial_counts.tsv", sep="\t", index=False)
coords.to_csv(job_dir / "samples" / "spatial_coordinates.tsv", sep="\t", index=False)
pd.DataFrame({"sample_id": ["spatial_internal"], "condition": ["standard"], "input_path": [str(job_dir / "samples" / "spatial_counts.tsv")]}).to_csv(job_dir / "samples" / "samples.tsv", sep="\t", index=False)
(job_dir / "config" / "analysis_request.md").write_text(
    "Spatial transcriptomics standard internal rehearsal. Visium-like spots are not single cells.\n",
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
  spatial:
    enabled: true
    preset: standard
    expression_matrix: $job_dir/samples/spatial_counts.tsv
    coordinates: $job_dir/samples/spatial_coordinates.tsv
    analysis_level: production_backend
    is_demo: false
report:
  title: V3.4 Spatial standard internal rehearsal
YAML
  write_approval "$job_dir/config/production_approval.json" "$job_id" "$job_dir/config/project.yaml" "$run_dir"
  run_ultimate_job "$job_id"
}

write_functional_state_job() {
  local job_id="v3_4_functional_state_standard_rehearsal_${STAMP}"
  local job_dir="$PROJECT_ROOT/jobs/$job_id"
  local run_dir="$job_dir/runs/$job_id"
  write_job_manifest "$job_dir" "$job_id"
  "$CORE_ENV/bin/python" - "$job_dir" <<'PY'
import numpy as np
import pandas as pd
import sys
from pathlib import Path

job_dir = Path(sys.argv[1])
samples = ["CTRL_A", "CTRL_B", "CASE_A", "CASE_B"]
rng = np.random.default_rng(99)
matrix = pd.DataFrame(rng.normal(5, 1, size=(70, len(samples))), columns=samples)
matrix.iloc[:10, 2:] += 1.5
matrix.insert(0, "feature_id", [f"GENE_{idx:03d}" for idx in range(1, 71)])
matrix.to_csv(job_dir / "samples" / "expression_matrix.tsv", sep="\t", index=False)
pd.DataFrame({
    "sample_id": samples,
    "condition": ["control", "control", "case", "case"],
    "input_path": [str(job_dir / "samples" / "expression_matrix.tsv")] * 4,
}).to_csv(job_dir / "samples" / "samples.tsv", sep="\t", index=False)
(job_dir / "samples" / "gene_sets.tsv").write_text(
    "geneset_id\tgene_id\nInflammation\tGENE_001\nInflammation\tGENE_002\nHypoxia\tGENE_003\nHypoxia\tGENE_004\n",
    encoding="utf-8",
)
(job_dir / "config" / "analysis_request.md").write_text(
    "Functional-state signature scoring internal rehearsal. Signature scores are not metabolic flux or clinical advice.\n",
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
  functional_state:
    enabled: true
    preset: standard
    input_matrix: $job_dir/samples/expression_matrix.tsv
    gene_sets: $job_dir/samples/gene_sets.tsv
    analysis_level: production_backend
    is_demo: false
report:
  title: V3.4 functional state standard internal rehearsal
YAML
  write_approval "$job_dir/config/production_approval.json" "$job_id" "$job_dir/config/project.yaml" "$run_dir"
  run_ultimate_job "$job_id"
}

write_cite_seq_job
write_vdj_job
write_spatial_job
write_functional_state_job

"$CORE_ENV/bin/python" -m ultimate.cli validation-index --root "$PROJECT_ROOT" --output-dir "$PROJECT_ROOT/reports/validation_index" >/dev/null
"$CORE_ENV/bin/python" -m ultimate.cli audit-production --root "$PROJECT_ROOT" --output-dir "$PROJECT_ROOT/audits/production_latest" >/dev/null
"$CORE_ENV/bin/python" -m ultimate.cli audit-backends --root "$PROJECT_ROOT" --output-dir "$PROJECT_ROOT/audits/backends_latest" >/dev/null
"$CORE_ENV/bin/python" "$PROJECT_ROOT/01_tools/write_v3_3_order_ready_report.py" --root "$PROJECT_ROOT" --output-dir "$PROJECT_ROOT/reports" >/dev/null

echo "V3.4 order-ready rehearsals completed for stamp ${STAMP}"
