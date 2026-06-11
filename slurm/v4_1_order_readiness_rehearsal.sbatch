#!/usr/bin/env bash
#SBATCH --job-name=ult_v4_1_order
#SBATCH --output=/shared/shen/2026/ultimate/logs/%x_%j.out
#SBATCH --error=/shared/shen/2026/ultimate/logs/%x_%j.err
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=06:00:00

set -euo pipefail

PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
CORE_ENV="${ULTIMATE_CORE_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-core}"
STAMP="${ULTIMATE_V41_REHEARSAL_STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}"

mkdir -p "$PROJECT_ROOT/logs" "$PROJECT_ROOT/jobs" "$PROJECT_ROOT/reports"
cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

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
    "policy": "V4.1 production-style internal rehearsal; not customer_delivery.",
    "directories": {name: str(job_dir / name) for name in ("config", "samples", "runs", "logs", "deliverables", "reproducible_code", "raw_links")},
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

payload = {
    "approved": True,
    "approved_by": "ultimate_v4_1_order_rehearsal",
    "approved_at": datetime.now(timezone.utc).isoformat(),
    "project_id": sys.argv[2],
    "input_path": str(Path(sys.argv[3]).resolve()),
    "output_dir": str(Path(sys.argv[4]).resolve()),
    "delivery_scope": "internal_rehearsal",
    "reason": "V4.1 internal production-style rehearsal on controlled small data; not customer_delivery.",
}
Path(sys.argv[1]).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
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

write_vdj_job() {
  local job_id="v4_1_vdj_standard_internal_rehearsal_${STAMP}"
  local job_dir="$PROJECT_ROOT/jobs/$job_id"
  local run_dir="$job_dir/runs/$job_id"
  write_job_manifest "$job_dir" "$job_id"
  "$CORE_ENV/bin/python" - "$job_dir" <<'PY'
import pandas as pd
import sys
from pathlib import Path

job_dir = Path(sys.argv[1])
cells = [f"S{i}_CELL{j:03d}" for i in (1, 2) for j in range(1, 13)]
contigs = []
for idx, barcode in enumerate(cells):
    clone = f"clonotype{(idx % 4) + 1}"
    condition = "control" if barcode.startswith("S1") else "case"
    for chain in ("TRA", "TRB"):
        contigs.append({
            "barcode": barcode,
            "is_cell": True,
            "productive": True,
            "chain": chain,
            "v_gene": f"TR{chain[-1]}V{(idx % 5) + 1}",
            "j_gene": f"TR{chain[-1]}J{(idx % 3) + 1}",
            "cdr3": f"CASS{idx:02d}{chain}F",
            "raw_clonotype_id": clone,
            "reads": 100 + idx,
            "umis": 10 + idx % 5,
            "condition": condition,
        })
pd.DataFrame(contigs).to_csv(job_dir / "samples" / "filtered_contig_annotations.csv", index=False)
pd.DataFrame({
    "clonotype_id": [f"clonotype{i}" for i in range(1, 5)],
    "frequency": [8, 7, 5, 4],
    "cdr3s_aa": ["TRA:AAA;TRB:BBB", "TRA:CCC;TRB:DDD", "TRA:EEE;TRB:FFF", "TRA:GGG;TRB:HHH"],
}).to_csv(job_dir / "samples" / "clonotypes.csv", index=False)
pd.DataFrame({
    "sample_id": ["S1", "S2"],
    "condition": ["control", "case"],
    "input_path": [str(job_dir / "samples" / "filtered_contig_annotations.csv")] * 2,
}).to_csv(job_dir / "samples" / "samples.tsv", sep="\t", index=False)
(job_dir / "config" / "analysis_request.md").write_text("VDJ internal rehearsal. Clonotype identity is not antigen specificity.\\n", encoding="utf-8")
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
  vdj:
    enabled: true
    preset: standard
    raw:
      enabled: false
    contig_annotations: $job_dir/samples/filtered_contig_annotations.csv
    clonotypes: $job_dir/samples/clonotypes.csv
    analysis_level: production_backend
    is_demo: false
report:
  title: V4.1 VDJ internal rehearsal
  style: morandi_clinical
YAML
  write_approval "$job_dir/config/production_approval.json" "$job_id" "$job_dir/config/project.yaml" "$run_dir"
  run_ultimate_job "$job_id"
}

write_cite_job() {
  local job_id="v4_1_cite_seq_standard_internal_rehearsal_${STAMP}"
  local job_dir="$PROJECT_ROOT/jobs/$job_id"
  local run_dir="$job_dir/runs/$job_id"
  write_job_manifest "$job_dir" "$job_id"
  "$CORE_ENV/bin/python" - "$job_dir" <<'PY'
import numpy as np
import pandas as pd
import sys
from pathlib import Path

job_dir = Path(sys.argv[1])
rng = np.random.default_rng(4101)
cells = [f"CELL_{idx:03d}" for idx in range(1, 41)]
rna = pd.DataFrame(rng.poisson(5, size=(50, 40)), columns=cells)
rna.insert(0, "feature_id", [f"GENE_{idx:03d}" for idx in range(50)])
adt = pd.DataFrame(rng.poisson(8, size=(8, 40)), columns=cells)
adt.iloc[:3, 20:] += 8
adt.insert(0, "feature_id", [f"ADT_{idx:02d}" for idx in range(8)])
rna.to_csv(job_dir / "samples" / "rna_matrix.tsv", sep="\t", index=False)
adt.to_csv(job_dir / "samples" / "adt_matrix.tsv", sep="\t", index=False)
pd.DataFrame({"sample_id": ["cite_internal"], "condition": ["case"], "input_path": [str(job_dir / "samples" / "rna_matrix.tsv")]}).to_csv(job_dir / "samples" / "samples.tsv", sep="\t", index=False)
(job_dir / "config" / "analysis_request.md").write_text("CITE-seq internal rehearsal. ADT is antibody tag data, not whole proteome.\\n", encoding="utf-8")
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
modules:
  cite_seq:
    enabled: true
    preset: standard
    raw:
      enabled: false
    rna_matrix: $job_dir/samples/rna_matrix.tsv
    adt_matrix: $job_dir/samples/adt_matrix.tsv
    analysis_level: production_backend
    is_demo: false
report:
  title: V4.1 CITE-seq internal rehearsal
  style: morandi_clinical
YAML
  write_approval "$job_dir/config/production_approval.json" "$job_id" "$job_dir/config/project.yaml" "$run_dir"
  run_ultimate_job "$job_id"
}

write_matrix_job() {
  local module="$1"
  local job_id="v4_1_${module}_publication_internal_rehearsal_${STAMP}"
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
rng = np.random.default_rng(4100 + len(module))
samples = pd.DataFrame({
    "sample_id": ["CTRL_A", "CTRL_B", "CASE_A", "CASE_B"],
    "condition": ["control", "control", "case", "case"],
})
features = [f"{module.upper()}_{idx:04d}" for idx in range(1, 65)]
if module == "methylation":
    values = rng.beta(2, 5, size=(len(features), 4))
    values[:8, 2:] = np.clip(values[:8, 2:] + 0.2, 0.001, 0.999)
else:
    values = rng.lognormal(mean=4.0, sigma=0.35, size=(len(features), 4))
    values[:10, 2:] *= 1.7
matrix = pd.DataFrame(values, columns=samples["sample_id"])
matrix.insert(0, "feature_id", features)
matrix_path = job_dir / "samples" / f"{module}_matrix.tsv"
matrix.to_csv(matrix_path, sep="\t", index=False)
samples["input_path"] = str(matrix_path)
samples.to_csv(job_dir / "samples" / "samples.tsv", sep="\t", index=False)
(job_dir / "config" / "analysis_request.md").write_text(
    f"{module} V4.1 internal rehearsal. Statistical outputs require method-boundary review.\\n",
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
    preset: publication
    raw:
      enabled: false
    input_matrix: $job_dir/samples/${module}_matrix.tsv
    analysis_level: production_backend
    is_demo: false
report:
  title: V4.1 $module internal rehearsal
  style: morandi_clinical
YAML
  write_approval "$job_dir/config/production_approval.json" "$job_id" "$job_dir/config/project.yaml" "$run_dir"
  run_ultimate_job "$job_id"
}

write_peak_job() {
  local module="$1"
  local job_id="v4_1_${module}_publication_internal_rehearsal_${STAMP}"
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
rng = np.random.default_rng(4110 + len(module))
cells = [f"CELL_{idx:03d}" for idx in range(1, 49)]
peaks = [f"chr1:{1000 + idx * 200}-{1100 + idx * 200}" for idx in range(72)]
values = rng.poisson(2.0, size=(len(peaks), len(cells))).astype(float)
values[:10, 24:] += rng.poisson(3.0, size=(10, 24))
peak_matrix = pd.DataFrame(values, columns=cells)
peak_matrix.insert(0, "peak_id", peaks)
peak_matrix.to_csv(job_dir / "samples" / f"{module}_peak_matrix.tsv", sep="\t", index=False)
metadata = pd.DataFrame({"cell_id": cells, "condition": ["control"] * 24 + ["case"] * 24})
metadata.to_csv(job_dir / "samples" / "cell_metadata.tsv", sep="\t", index=False)
pd.DataFrame({"sample_id": [f"{module}_internal"], "condition": ["publication"], "input_path": [str(job_dir / "samples" / f"{module}_peak_matrix.tsv")]}).to_csv(job_dir / "samples" / "samples.tsv", sep="\t", index=False)
(job_dir / "config" / "analysis_request.md").write_text(f"{module} V4.1 internal rehearsal. Peak results are statistical accessibility evidence.\\n", encoding="utf-8")
PY
  if [[ "$module" == "multiome" ]]; then
    "$CORE_ENV/bin/python" - "$job_dir" <<'PY'
import numpy as np
import pandas as pd
import sys
from pathlib import Path
job_dir = Path(sys.argv[1])
rng = np.random.default_rng(4120)
cells = [f"CELL_{idx:03d}" for idx in range(1, 49)]
rna = pd.DataFrame(rng.poisson(4.0, size=(60, 48)), columns=cells)
rna.insert(0, "feature_id", [f"GENE_{idx:03d}" for idx in range(60)])
rna.to_csv(job_dir / "samples" / "multiome_rna.tsv", sep="\t", index=False)
PY
    extra_config="    rna_matrix: $job_dir/samples/multiome_rna.tsv
    atac_matrix: $job_dir/samples/${module}_peak_matrix.tsv"
  else
    extra_config="    peak_matrix: $job_dir/samples/${module}_peak_matrix.tsv
    cell_metadata: $job_dir/samples/cell_metadata.tsv"
  fi
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
    preset: publication
    raw:
      enabled: false
$extra_config
    analysis_level: production_backend
    is_demo: false
report:
  title: V4.1 $module internal rehearsal
  style: morandi_clinical
YAML
  write_approval "$job_dir/config/production_approval.json" "$job_id" "$job_dir/config/project.yaml" "$run_dir"
  run_ultimate_job "$job_id"
}

write_vdj_job
write_cite_job
write_matrix_job methylation
write_peak_job scatac
write_peak_job multiome
write_matrix_job functional_state

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

"$CORE_ENV/bin/python" - "$PROJECT_ROOT" "$STAMP" <<'PY'
import csv
import sys
from pathlib import Path
root = Path(sys.argv[1])
stamp = sys.argv[2]
index = root / "reports" / "validation_index_v4_1" / "validation_index.tsv"
rows = []
if index.exists():
    rows = list(csv.DictReader(index.open("r", encoding="utf-8"), delimiter="\t"))
v41 = [row for row in rows if row.get("run_name", "").startswith("v4_1_") and row.get("run_name", "").endswith(stamp)]
ready = [row for row in v41 if row.get("order_readiness_status") == "ready_for_delivery"]
blocked = [row for row in v41 if row.get("order_readiness_status") != "ready_for_delivery"]
report = root / "reports" / "v4_1_order_readiness_report.md"
report.write_text(
    "# Ultimate V4.1 Order Readiness Rehearsal Report\n\n"
    f"- Stamp: {stamp}\n"
    f"- V4.1 rehearsal rows: {len(v41)}\n"
    f"- Ready internal rehearsals: {len(ready)}\n"
    f"- Blocked or partial rows: {len(blocked)}\n\n"
    "## Ready\n\n"
    + "\n".join(f"- {row.get('run_name')} ({row.get('module')})" for row in ready)
    + "\n\n## Blocked / Partial\n\n"
    + ("\n".join(f"- {row.get('run_name')} ({row.get('module')}): {row.get('missing_or_gap') or row.get('next_action')}" for row in blocked) or "- None")
    + "\n",
    encoding="utf-8",
)
PY
