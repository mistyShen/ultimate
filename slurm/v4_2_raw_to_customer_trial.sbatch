#!/usr/bin/env bash
#SBATCH --job-name=ult_v4_2_trial
#SBATCH --output=/shared/shen/2026/ultimate/logs/%x_%j.out
#SBATCH --error=/shared/shen/2026/ultimate/logs/%x_%j.err
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --time=08:00:00

set -euo pipefail

PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
CORE_ENV="${ULTIMATE_CORE_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-core}"
SCRNA_ENV="${ULTIMATE_SCRNA_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-scrna}"
STAMP="${ULTIMATE_V42_TRIAL_STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}"
REPORT_PATH="${ULTIMATE_V42_REPORT_PATH:-$PROJECT_ROOT/reports/v4_2_customer_trial_report.md}"
DELIVERY_CHECK_FAILURES=0

mkdir -p "$PROJECT_ROOT/logs" "$PROJECT_ROOT/jobs" "$PROJECT_ROOT/reports"
cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

write_job_manifest() {
  local job_dir="$1"
  local job_id="$2"
  if [[ -e "$job_dir" ]]; then
    echo "Refusing to reuse existing V4.2 trial job directory: $job_dir" >&2
    exit 4
  fi
  mkdir -p "$job_dir"/{config,samples,runs,logs,deliverables,reproducible_code,raw_links,raw_upstream}
  "$CORE_ENV/bin/python" - "$job_dir" "$job_id" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

job_dir = Path(sys.argv[1])
job_id = sys.argv[2]
payload = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "job_id": job_id,
    "job_dir": str(job_dir),
    "run_mode": "production",
    "delivery_scope": "customer_delivery",
    "delivery_mode": "customer_delivery_rehearsal",
    "controlled_small_data": True,
    "raw_data_policy": "controlled inputs generated inside this job only; no customer raw data is used",
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
    "approved_by": "ultimate_v4_2_customer_trial",
    "approved_at": datetime.now(timezone.utc).isoformat(),
    "project_id": sys.argv[2],
    "input_path": str(Path(sys.argv[3]).resolve()),
    "output_dir": str(Path(sys.argv[4]).resolve()),
    "delivery_scope": "customer_delivery",
    "delivery_mode": "customer_delivery_rehearsal",
    "reason": "V4.2 customer_delivery rehearsal on controlled small data; no real customer raw data is used.",
}
Path(sys.argv[1]).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
PY
}

run_raw_evidence_allow_blocked() {
  local module="$1"
  local input_path="$2"
  local samplesheet="$3"
  local out_dir="$4"
  shift 4
  mkdir -p "$out_dir"
  set +e
  "$CORE_ENV/bin/python" -m ultimate.cli raw-upstream-evidence \
    --module "$module" \
    --input-path "$input_path" \
    --output-dir "$out_dir" \
    ${samplesheet:+--samplesheet "$samplesheet"} \
    "$@"
  local status=$?
  set -e
  return "$status"
}

raw_status() {
  local manifest="$1/raw_upstream_manifest.json"
  "$CORE_ENV/bin/python" - "$manifest" <<'PY'
import json
import sys
from pathlib import Path
p = Path(sys.argv[1])
print((json.loads(p.read_text()).get("status") if p.exists() else "missing"))
PY
}

run_ultimate_job() {
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

write_rnaseq_raw_trial() {
  local job_id="v4_2_rnaseq_raw_customer_trial_${STAMP}"
  local job_dir="$PROJECT_ROOT/jobs/$job_id"
  local run_dir="$job_dir/runs/$job_id"
  write_job_manifest "$job_dir" "$job_id"
  mkdir -p "$job_dir/samples/fastq"
  cat > "$job_dir/samples/fastq/S1.fastq" <<'FASTQ'
@S1_1
ACGTACGT
+
!!!!!!!!
@S1_2
TGCATGCA
+
!!!!!!!!
FASTQ
  cat > "$job_dir/samples/tiny_reference.fa" <<'FASTA'
>GENE_A
ACGTACGT
>GENE_B
TGCATGCA
FASTA
  cat > "$job_dir/samples/raw_fastq_samples.tsv" <<TSV
sample_id	condition	fastq_1
S1	case	$job_dir/samples/fastq/S1.fastq
TSV
  local raw_dir="$job_dir/raw_upstream/rnaseq"
  run_raw_evidence_allow_blocked rnaseq "$job_dir/samples/fastq" "$job_dir/samples/raw_fastq_samples.tsv" "$raw_dir" \
    --stage rnaseq_fastq_tiny_counts \
    --tiny-reference "$job_dir/samples/tiny_reference.fa" \
    --quant-tool salmon || true
  cp "$raw_dir/raw_upstream_evidence.tsv" "$job_dir/raw_links/raw_upstream_evidence.tsv"
  if [[ "$(raw_status "$raw_dir")" != "ready" ]]; then
    cp "$raw_dir/failure_recovery.md" "$job_dir/failure_recovery.md"
    return 0
  fi
  "$CORE_ENV/bin/python" - "$job_dir" "$raw_dir/raw_import_matrix.tsv" <<'PY'
import sys
from pathlib import Path

job_dir = Path(sys.argv[1])
matrix = Path(sys.argv[2])
(job_dir / "samples" / "samples.tsv").write_text(
    f"sample_id\tcondition\tinput_path\nS1\tcase\t{matrix}\n",
    encoding="utf-8",
)
(job_dir / "config" / "analysis_request.md").write_text(
    "V4.2 rnaseq FASTQ tiny-count customer_delivery rehearsal. This is controlled small-data evidence, not a full nf-core run.\n",
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
  delivery_scope: customer_delivery
  delivery_mode: customer_delivery_rehearsal
  is_demo: false
analysis_request: $job_dir/config/analysis_request.md
samples:
  samplesheet: $job_dir/samples/samples.tsv
design:
  condition_column: condition
modules:
  rnaseq:
    enabled: true
    preset: publication
    raw:
      enabled: false
      upstream_evidence: $job_dir/raw_links/raw_upstream_evidence.tsv
    input_matrix: $raw_dir/raw_import_matrix.tsv
    analysis_level: production_backend
    is_demo: false
report:
  title: V4.2 RNA-seq raw customer trial
  style: morandi_clinical
YAML
  write_approval "$job_dir/config/production_approval.json" "$job_id" "$job_dir/config/project.yaml" "$run_dir"
  run_ultimate_job "$job_id" "$CORE_ENV"
}

write_scrna_mtx_trial() {
  local job_id="v4_2_scrna_mtx_customer_trial_${STAMP}"
  local job_dir="$PROJECT_ROOT/jobs/$job_id"
  local run_dir="$job_dir/runs/$job_id"
  write_job_manifest "$job_dir" "$job_id"
  "$SCRNA_ENV/bin/python" - "$job_dir" <<'PY'
import json
import sys
from pathlib import Path
from ultimate.scrna_smoke import create_demo_inputs

job_dir = Path(sys.argv[1])
payload = create_demo_inputs(job_dir / "samples" / "scrna_controlled_10x", n_cells=96, n_genes=70, seed=4202)
controlled_mtx = job_dir / "samples" / "scrna_controlled_10x" / "controlled_10x_mtx"
Path(payload["tenx_mtx"]).rename(controlled_mtx)
payload["tenx_mtx"] = str(controlled_mtx)
(job_dir / "samples" / "scrna_controlled_inputs.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
(job_dir / "config" / "analysis_request.md").write_text(
    "V4.2 scRNA 10x MTX customer_delivery rehearsal. Cell Ranger/nf-core raw handoff is not executed.\n",
    encoding="utf-8",
)
PY
  local raw_dir="$job_dir/raw_upstream/scrna"
  run_raw_evidence_allow_blocked scrna "$job_dir/samples/scrna_controlled_10x/controlled_10x_mtx" "" "$raw_dir" || true
  cp "$raw_dir/raw_upstream_evidence.tsv" "$job_dir/raw_links/raw_upstream_evidence.tsv"
  cat > "$job_dir/config/project.yaml" <<YAML
project:
  name: $job_id
  job_id: $job_id
  organism: human
  output_dir: $run_dir
  server_root: $PROJECT_ROOT
  run_mode: production
  analysis_level: production_backend
  delivery_scope: customer_delivery
  delivery_mode: customer_delivery_rehearsal
  is_demo: false
analysis_request: $job_dir/config/analysis_request.md
samples:
  samplesheet: $job_dir/samples/scrna_controlled_10x/samples.tsv
design:
  condition_column: condition
  control: control
  case: case
modules:
  scrna:
    enabled: true
    preset: standard
    raw:
      enabled: false
      upstream_evidence: $job_dir/raw_links/raw_upstream_evidence.tsv
    tenx_mtx: $job_dir/samples/scrna_controlled_10x/controlled_10x_mtx
    samplesheet: $job_dir/samples/scrna_controlled_10x/samples.tsv
    max_cells: 96
    analysis_level: production_backend
    is_demo: false
report:
  title: V4.2 scRNA MTX customer trial
  style: morandi_clinical
YAML
  write_approval "$job_dir/config/production_approval.json" "$job_id" "$job_dir/config/project.yaml" "$run_dir"
  run_ultimate_job "$job_id" "$SCRNA_ENV"
}

write_rnaseq_raw_trial
write_scrna_mtx_trial

"$CORE_ENV/bin/python" -m ultimate.cli validation-index \
  --root "$PROJECT_ROOT" \
  --output-dir "$PROJECT_ROOT/reports/validation_index_v4_2"
"$CORE_ENV/bin/python" -m ultimate.cli audit-production \
  --root "$PROJECT_ROOT" \
  --output-dir "$PROJECT_ROOT/audits/production_v4_2_latest"
"$CORE_ENV/bin/python" -m ultimate.cli audit-backends \
  --root "$PROJECT_ROOT" \
  --output-dir "$PROJECT_ROOT/audits/backends_v4_2_latest"
"$CORE_ENV/bin/python" -m ultimate.cli tool-completeness \
  --root "$PROJECT_ROOT" \
  --output-dir "$PROJECT_ROOT/audits/tool_completeness_v4_2_latest"
"$CORE_ENV/bin/python" -m ultimate.cli order-readiness \
  --root "$PROJECT_ROOT" \
  --output-dir "$PROJECT_ROOT/audits/order_readiness_v4_2_latest"
if [[ -f "$PROJECT_ROOT/01_tools/storage_audit.py" ]]; then
  "$CORE_ENV/bin/python" "$PROJECT_ROOT/01_tools/storage_audit.py" \
    --root "$PROJECT_ROOT" \
    --output-dir "$PROJECT_ROOT/audits/storage_v4_2_latest" \
    --budget-gb 500
fi

"$CORE_ENV/bin/python" - "$PROJECT_ROOT" "$STAMP" "$REPORT_PATH" <<'PY'
import csv
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
stamp = sys.argv[2]
report_path = Path(sys.argv[3])
jobs = sorted((root / "jobs").glob(f"v4_2_*_{stamp}"))
rows = []
for job in jobs:
    delivery = job / "deliverables" / "latest_delivery_check.json"
    delivery_status = json.loads(delivery.read_text()).get("status") if delivery.exists() else "missing"
    raw_rows = []
    raw_path = job / "raw_links" / "raw_upstream_evidence.tsv"
    if raw_path.exists():
        with raw_path.open(encoding="utf-8", newline="") as handle:
            raw_rows = list(csv.DictReader(handle, delimiter="\t"))
    raw_status = ",".join(row.get("execution_status", "") for row in raw_rows) or "missing"
    rows.append({"job": job.name, "delivery_status": delivery_status, "raw_status": raw_status})
ready = [row for row in rows if row["delivery_status"] == "ready"]
raw_upstream_validated = [row for row in rows if "ready" in row["raw_status"]]
blocked = [row for row in rows if "blocked" in row["raw_status"] or (row["delivery_status"] not in {"ready"} and "ready" not in row["raw_status"])]
handoff_required = [row for row in rows if "handoff" in row["raw_status"] or "adapter" in row["raw_status"]]
license_required = [row for row in rows if "license" in row["raw_status"] or "licensed" in row["raw_status"]]
report_path.parent.mkdir(parents=True, exist_ok=True)
lines = [
    "# Ultimate V4.2 raw-to-customer trial report",
    "",
    f"- Suite stamp: `{stamp}`",
    "- Scope: controlled customer_delivery rehearsal; no real customer data.",
    f"- Jobs found: {len(rows)}",
    f"- ready: {len(ready)} customer package(s) passed delivery-check.",
    f"- blocked: {len(blocked)} job(s) require dependency/input fixes before rerun.",
    f"- handoff-required: {len(handoff_required)} job(s) require upstream handoff or adapter execution.",
    f"- license-required: {len(license_required)} job(s) require user-provided licensed tool paths.",
    f"- raw-upstream-validated: {len(raw_upstream_validated)} raw/semi-raw import evidence row(s) are ready.",
    "",
    "## Jobs",
]
for row in rows:
    lines.append(f"- `{row['job']}`: delivery=`{row['delivery_status']}`, raw=`{row['raw_status']}`")
report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(report_path)
PY

"$CORE_ENV/bin/python" -m ultimate.cli batch-status \
  --batch-dir "$PROJECT_ROOT/jobs" \
  --job-glob "v4_2_*_${STAMP}" \
  --output-dir "$PROJECT_ROOT/reports/batch_status_v4_2"

if [[ "$DELIVERY_CHECK_FAILURES" -ne 0 ]]; then
  echo "V4.2 customer trial completed with delivery-check blockers: $DELIVERY_CHECK_FAILURES" >&2
  exit 5
fi
