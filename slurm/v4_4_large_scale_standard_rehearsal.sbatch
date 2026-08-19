#!/usr/bin/env bash
#SBATCH --job-name=ult_v4_4_large
#SBATCH --output=/shared/shen/2026/ultimate/logs/%x_%j.out
#SBATCH --error=/shared/shen/2026/ultimate/logs/%x_%j.err
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --time=10:00:00

set -euo pipefail

PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
CORE_ENV="${ULTIMATE_CORE_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-core}"
SCRNA_ENV="${ULTIMATE_SCRNA_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-scrna}"
STAMP="${ULTIMATE_V44_REHEARSAL_STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}"
REPORT_PATH="$PROJECT_ROOT/reports/v4_4_large_scale_standard_report.md"
STORAGE_DIR="$PROJECT_ROOT/audits/storage_v4_4_large_scale_latest"
BATCH_STATUS_DIR="$PROJECT_ROOT/reports/batch_status_v4_4_large_scale"
DELIVERY_CHECK_FAILURES=0

mkdir -p "$PROJECT_ROOT/logs" "$PROJECT_ROOT/jobs" "$PROJECT_ROOT/reports"
cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export PATH="$PROJECT_ROOT/tools/bin:$CORE_ENV/bin:$SCRNA_ENV/bin:$PATH"

write_job_manifest() {
  local job_dir="$1"
  local job_id="$2"
  local module="$3"
  local preset="$4"
  local input_type="$5"
  if [[ -e "$job_dir" ]]; then
    echo "Refusing to reuse existing V4.4 rehearsal job directory: $job_dir" >&2
    exit 4
  fi
  mkdir -p "$job_dir"/{config,samples,runs,logs,deliverables,reproducible_code,raw_links}
  "$CORE_ENV/bin/python" - "$job_dir" "$job_id" "$module" "$preset" "$input_type" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

job_dir = Path(sys.argv[1])
payload = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "job_id": sys.argv[2],
    "job_dir": str(job_dir),
    "module": sys.argv[3],
    "preset": sys.argv[4],
    "input_type": sys.argv[5],
    "run_mode": "production",
    "delivery_scope": "internal_rehearsal",
    "delivery_mode": "large_scale_standard_rehearsal",
    "controlled_synthetic_data": True,
    "raw_data_policy": "Synthetic or controlled lightweight inputs only; no raw customer data is copied or overwritten.",
}
(job_dir / "job_manifest.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
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
    "approved_by": "ultimate_v4_4_large_scale_standard_rehearsal",
    "approved_at": datetime.now(timezone.utc).isoformat(),
    "project_id": sys.argv[2],
    "input_path": str(Path(sys.argv[3]).resolve()),
    "output_dir": str(Path(sys.argv[4]).resolve()),
    "delivery_scope": "internal_rehearsal",
    "delivery_mode": "large_scale_standard_rehearsal",
    "reason": "Controlled V4.4 large-scale standard order rehearsal; not customer_delivery.",
}
Path(sys.argv[1]).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
PY
}

run_job() {
  local job_id="$1"
  local env_prefix="$2"
  local job_dir="$PROJECT_ROOT/jobs/$job_id"
  local config_path="$job_dir/config/project.yaml"
  local approval_path="$job_dir/config/production_approval.json"
  ULTIMATE_ENV="$env_prefix" bash "$PROJECT_ROOT/slurm/ultimate_run.sbatch" "$config_path" "$approval_path"
  "$env_prefix/bin/python" -m ultimate.cli customer-package --run-dir "$job_dir"
  set +e
  "$env_prefix/bin/python" -m ultimate.cli delivery-check --run-dir "$job_dir"
  local status=$?
  set -e
  if [[ "$status" -ne 0 ]]; then
    DELIVERY_CHECK_FAILURES=$((DELIVERY_CHECK_FAILURES + 1))
    echo "delivery-check blocked for $job_dir" >&2
  fi
}

write_rnaseq_50_sample_job() {
  local job_id="v4_4_rnaseq_50sample_standard_rehearsal_${STAMP}"
  local job_dir="$PROJECT_ROOT/jobs/$job_id"
  local run_dir="$job_dir/runs/$job_id"
  write_job_manifest "$job_dir" "$job_id" rnaseq standard count_matrix
  "$CORE_ENV/bin/python" - "$job_dir" <<'PY'
import numpy as np
import pandas as pd
import sys
from pathlib import Path

job_dir = Path(sys.argv[1])
rng = np.random.default_rng(4401)
sample_ids = [f"S{i:03d}" for i in range(1, 51)]
conditions = ["control"] * 25 + ["case"] * 25
batches = [f"B{(i % 5) + 1}" for i in range(50)]
features = [f"GENE_{i:05d}" for i in range(1, 2001)]
counts = rng.negative_binomial(20, 0.35, size=(len(features), len(sample_ids))).astype(int)
counts[:120, 25:] += rng.poisson(25, size=(120, 25))
matrix = pd.DataFrame(counts, columns=sample_ids)
matrix.insert(0, "feature_id", features)
matrix_path = job_dir / "samples" / "rnaseq_50sample_counts.tsv"
matrix.to_csv(matrix_path, sep="\t", index=False)
samples = pd.DataFrame({"sample_id": sample_ids, "condition": conditions, "batch": batches, "input_path": str(matrix_path)})
samples.to_csv(job_dir / "samples" / "samples.tsv", sep="\t", index=False)
(job_dir / "config" / "analysis_request.md").write_text(
    "V4.4 RNA-seq 50-sample standard matrix rehearsal. Differential results are statistical evidence and require review. No FASTQ upstream is executed.\n",
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
  delivery_mode: large_scale_standard_rehearsal
  is_demo: false
analysis_request: $job_dir/config/analysis_request.md
samples:
  samplesheet: $job_dir/samples/samples.tsv
design:
  condition_column: condition
  batch_column: batch
  control: control
  case: case
modules:
  rnaseq:
    enabled: true
    preset: standard
    raw:
      enabled: false
    input_matrix: $job_dir/samples/rnaseq_50sample_counts.tsv
    analysis_level: production_backend
    is_demo: false
report:
  title: V4.4 RNA-seq 50-sample standard rehearsal
  style: morandi_clinical
  figure_options:
    legend_position: outside_right
    show_grid: true
YAML
  write_approval "$job_dir/config/production_approval.json" "$job_id" "$job_dir/config/project.yaml" "$run_dir"
  run_job "$job_id" "$CORE_ENV"
}

write_scrna_multisample_job() {
  local job_id="v4_4_scrna_multisample_standard_rehearsal_${STAMP}"
  local job_dir="$PROJECT_ROOT/jobs/$job_id"
  local run_dir="$job_dir/runs/$job_id"
  write_job_manifest "$job_dir" "$job_id" scrna standard 10x_mtx
  "$SCRNA_ENV/bin/python" - "$job_dir" <<'PY'
import json
import pandas as pd
import sys
from pathlib import Path
from ultimate.scrna_smoke import create_demo_inputs

job_dir = Path(sys.argv[1])
payload = create_demo_inputs(job_dir / "samples" / "scrna_large_scale_10x", n_cells=240, n_genes=120, seed=4402)
controlled_mtx = job_dir / "samples" / "scrna_large_scale_10x" / "controlled_10x_mtx"
Path(payload["tenx_mtx"]).rename(controlled_mtx)
payload["tenx_mtx"] = str(controlled_mtx)
samples = pd.read_csv(payload["samplesheet"], sep="\t")
sample_labels = ["S1", "S2", "S3", "S4"]
samples["sample_id"] = [sample_labels[idx % 4] for idx in range(len(samples))]
samples["condition"] = samples["sample_id"].map({"S1": "control", "S2": "control", "S3": "case", "S4": "case"})
samples["batch"] = samples["sample_id"].map({"S1": "B1", "S2": "B1", "S3": "B2", "S4": "B2"})
samples["input_path"] = str(controlled_mtx)
samples.to_csv(job_dir / "samples" / "samples.tsv", sep="\t", index=False)
(job_dir / "samples" / "scrna_large_scale_inputs.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
(job_dir / "config" / "analysis_request.md").write_text(
    "V4.4 scRNA multi-sample 10x matrix standard rehearsal. Cluster labels are not cell type labels; complex communication and velocity are excluded.\n",
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
  delivery_mode: large_scale_standard_rehearsal
  is_demo: false
analysis_request: $job_dir/config/analysis_request.md
samples:
  samplesheet: $job_dir/samples/samples.tsv
design:
  condition_column: condition
  batch_column: batch
  control: control
  case: case
modules:
  scrna:
    enabled: true
    preset: standard
    raw:
      enabled: false
    tenx_mtx: $job_dir/samples/scrna_large_scale_10x/controlled_10x_mtx
    samplesheet: $job_dir/samples/samples.tsv
    max_cells: 240
    analysis_level: production_backend
    is_demo: false
report:
  title: V4.4 scRNA multi-sample standard rehearsal
  style: morandi_clinical
YAML
  write_approval "$job_dir/config/production_approval.json" "$job_id" "$job_dir/config/project.yaml" "$run_dir"
  run_job "$job_id" "$SCRNA_ENV"
}

write_proteomics_50_sample_job() {
  local job_id="v4_4_proteomics_50sample_standard_rehearsal_${STAMP}"
  local job_dir="$PROJECT_ROOT/jobs/$job_id"
  local run_dir="$job_dir/runs/$job_id"
  write_job_manifest "$job_dir" "$job_id" proteomics standard abundance_table
  "$CORE_ENV/bin/python" - "$job_dir" <<'PY'
import numpy as np
import pandas as pd
import sys
from pathlib import Path

job_dir = Path(sys.argv[1])
rng = np.random.default_rng(4403)
sample_ids = [f"P{i:03d}" for i in range(1, 51)]
conditions = ["control"] * 25 + ["case"] * 25
batches = [f"MS{(i % 4) + 1}" for i in range(50)]
features = [f"PROT_{i:05d}" for i in range(1, 1201)]
values = rng.lognormal(mean=8.0, sigma=0.35, size=(len(features), len(sample_ids)))
values[:80, 25:] *= 1.55
mask = rng.random(values.shape) < 0.015
values[mask] = np.nan
matrix = pd.DataFrame(values, columns=sample_ids)
matrix.insert(0, "feature_id", features)
matrix_path = job_dir / "samples" / "proteomics_50sample_abundance.tsv"
matrix.to_csv(matrix_path, sep="\t", index=False)
samples = pd.DataFrame({"sample_id": sample_ids, "condition": conditions, "batch": batches, "input_path": str(matrix_path)})
samples.to_csv(job_dir / "samples" / "samples.tsv", sep="\t", index=False)
(job_dir / "config" / "analysis_request.md").write_text(
    "V4.4 proteomics 50-sample abundance table rehearsal. Abundance statistics are not PPI or mechanism proof.\n",
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
  delivery_mode: large_scale_standard_rehearsal
  is_demo: false
analysis_request: $job_dir/config/analysis_request.md
samples:
  samplesheet: $job_dir/samples/samples.tsv
design:
  condition_column: condition
  batch_column: batch
  control: control
  case: case
modules:
  proteomics:
    enabled: true
    preset: standard
    raw:
      enabled: false
    input_matrix: $job_dir/samples/proteomics_50sample_abundance.tsv
    abundance_table: $job_dir/samples/proteomics_50sample_abundance.tsv
    analysis_level: production_backend
    is_demo: false
report:
  title: V4.4 proteomics 50-sample standard rehearsal
  style: morandi_clinical
YAML
  write_approval "$job_dir/config/production_approval.json" "$job_id" "$job_dir/config/project.yaml" "$run_dir"
  run_job "$job_id" "$CORE_ENV"
}

write_rnaseq_50_sample_job
write_scrna_multisample_job
write_proteomics_50_sample_job

if [[ -f "$PROJECT_ROOT/01_tools/storage_audit.py" ]]; then
  export ULTIMATE_STORAGE_DU_TIMEOUT_SECONDS="${ULTIMATE_STORAGE_DU_TIMEOUT_SECONDS:-60}"
  "$CORE_ENV/bin/python" "$PROJECT_ROOT/01_tools/storage_audit.py" \
    --root "$PROJECT_ROOT" \
    --output-dir "$STORAGE_DIR" \
    --budget-gb 500
fi

"$CORE_ENV/bin/python" -m ultimate.cli batch-status \
  --batch-dir "$PROJECT_ROOT/jobs" \
  --job-glob "v4_4_*_${STAMP}" \
  --output-dir "$BATCH_STATUS_DIR"

"$CORE_ENV/bin/python" - "$PROJECT_ROOT" "$STAMP" "$REPORT_PATH" "$BATCH_STATUS_DIR" "$STORAGE_DIR" <<'PY'
import csv
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
stamp = sys.argv[2]
report = Path(sys.argv[3])
batch_dir = Path(sys.argv[4])
storage_dir = Path(sys.argv[5])
batch_manifest = json.loads((batch_dir / "batch_status_manifest.json").read_text())
rows = [row for row in batch_manifest.get("rows", []) if stamp in row.get("job_id", "")]
storage_path = storage_dir / "storage_audit_summary.json"
storage = json.loads(storage_path.read_text()) if storage_path.exists() else {}

ready = [row for row in rows if row.get("overall_status") == "ready"]
blocked = [row for row in rows if row.get("overall_status") in {"blocked", "failed"}]
manual = [
    "CellChat/NicheNet communication inference",
    "inferCNV/CopyKAT malignant inference",
    "RNA velocity",
    "complex spatial communication",
    "clinical survival/risk model",
    "full FASTQ/BCL upstream production",
]
slurm_covered = [row for row in rows if row.get("slurm_job_id")]
delivery_ready = [row for row in rows if row.get("delivery_check_status") == "ready"]
package_ready = [row for row in rows if row.get("customer_package_status") == "ready"]
if blocked:
    biggest = blocked[0].get("next_action", "inspect_job_artifacts")
else:
    biggest = "none"
can_trial = bool(rows) and len(ready) == len(rows) and storage.get("under_budget") is True

report.parent.mkdir(parents=True, exist_ok=True)
lines = [
    "# Ultimate V4.4 large-scale standard rehearsal report",
    "",
    f"- Suite stamp: `{stamp}`",
    "- Scope: controlled synthetic/lightweight data; no real customer data.",
    f"- batch job total: {len(rows)}",
    f"- ready count: {len(ready)}",
    f"- blocked/failed count: {len(blocked)}",
    f"- Slurm job id coverage: {len(slurm_covered)} / {len(rows)}",
    f"- delivery-check pass count: {len(delivery_ready)}",
    f"- customer-package pass count: {len(package_ready)}",
    f"- storage total: {storage.get('total_gb', 'missing')}G",
    f"- storage under 500G: {storage.get('under_budget', 'missing')}",
    f"- biggest blocker: {biggest}",
    f"- ready for real large-sample trial order: {str(can_trial).lower()}",
    "",
    "## Module sample scales",
    "",
    "| job_id | module | preset | input_type | sample_count | cell_count | feature_count | status |",
    "| --- | --- | --- | --- | --- | --- | --- | --- |",
]
for row in rows:
    lines.append(
        f"| {row.get('job_id', '')} | {row.get('module', '')} | {row.get('preset', '')} | "
        f"{row.get('input_type', '')} | {row.get('sample_count', '')} | {row.get('cell_count', '')} | "
        f"{row.get('feature_count', '')} | {row.get('overall_status', '')} |"
    )
lines.extend(["", "## Manual Review / Handoff Only", ""])
for item in manual:
    lines.append(f"- {item}: manual_review_required")
lines.extend(["", "## Artifacts", ""])
lines.append(f"- batch-status: `{batch_dir / 'batch_status.tsv'}`")
lines.append(f"- storage audit: `{storage_dir / 'storage_audit.tsv'}`")
lines.append(f"- cleanup plan: `{storage_dir / 'cleanup_plan.tsv'}`")
report.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(report)
PY

if [[ "$DELIVERY_CHECK_FAILURES" -ne 0 ]]; then
  echo "V4.4 large-scale rehearsal completed with delivery-check blockers: $DELIVERY_CHECK_FAILURES" >&2
  exit 5
fi
