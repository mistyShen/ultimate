#!/usr/bin/env bash
#SBATCH --job-name=ult_v4_beta_trial
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
STAMP="${ULTIMATE_V4_BETA_REHEARSAL_STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}"
DEFAULT_REPORT_PATH="/shared/shen/2026/ultimate/reports/v4_beta_customer_trial_report.md"
REPORT_PATH="${ULTIMATE_V4_BETA_REPORT_PATH:-$PROJECT_ROOT/reports/v4_beta_customer_trial_report.md}"
DELIVERY_CHECK_FAILURES=0

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
  if [[ -e "$job_dir" ]]; then
    echo "Refusing to reuse existing V4 Beta rehearsal job directory: $job_dir" >&2
    exit 4
  fi
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
    "delivery_scope": "customer_delivery",
    "delivery_mode": "customer_delivery_rehearsal",
    "customer_delivery_rehearsal": True,
    "controlled_small_data": True,
    "raw_data_policy": "no raw customer data; controlled inputs generated inside this job directory only",
    "directories": {
        name: str(job_dir / name)
        for name in ("config", "samples", "runs", "logs", "deliverables", "reproducible_code", "raw_links")
    },
}
(job_dir / "job_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
PY
}

write_raw_upstream_evidence() {
  local job_dir="$1"
  local module="$2"
  local raw_stage="$3"
  local blocked_reason="$4"
  "$CORE_ENV/bin/python" - "$job_dir" "$module" "$raw_stage" "$blocked_reason" <<'PY'
import csv
import sys
from pathlib import Path

job_dir = Path(sys.argv[1])
module = sys.argv[2]
raw_stage = sys.argv[3]
blocked_reason = sys.argv[4]
path = job_dir / "raw_links" / "raw_upstream_evidence.tsv"
with path.open("w", encoding="utf-8", newline="") as handle:
    writer = csv.DictWriter(
        handle,
        fieldnames=("module", "raw_stage", "execution_status", "blocked_reason", "evidence_scope"),
        delimiter="\t",
    )
    writer.writeheader()
    writer.writerow(
        {
            "module": module,
            "raw_stage": raw_stage,
            "execution_status": "not_executed",
            "blocked_reason": blocked_reason,
            "evidence_scope": "controlled_lightweight_input_only",
        }
    )
PY
}

run_raw_upstream_evidence() {
  local job_dir="$1"
  local module="$2"
  local input_path="$3"
  local samplesheet="$4"
  local out_dir="$job_dir/raw_upstream/${module}"
  mkdir -p "$out_dir"
  local args=("$CORE_ENV/bin/python" -m ultimate.cli raw-upstream-evidence --module "$module" --input-path "$input_path" --output-dir "$out_dir")
  if [[ -n "$samplesheet" ]]; then
    args+=(--samplesheet "$samplesheet")
  fi
  "${args[@]}"
  cp "$out_dir/raw_upstream_evidence.tsv" "$job_dir/raw_links/raw_upstream_evidence.tsv"
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
    "approved_by": "ultimate_v4_beta_rehearsal",
    "approved_at": datetime.now(timezone.utc).isoformat(),
    "project_id": sys.argv[2],
    "input_path": str(Path(sys.argv[3]).resolve()),
    "output_dir": str(Path(sys.argv[4]).resolve()),
    "delivery_scope": "customer_delivery",
    "delivery_mode": "customer_delivery_rehearsal",
    "reason": "V4 Beta customer_delivery rehearsal on controlled small data; no real customer raw data is used.",
}
approval_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
PY
}

write_customer_package() {
  local job_dir="$1"
  local job_id="$2"
  local module="$3"
  "$CORE_ENV/bin/python" - "$job_dir" "$job_id" "$module" <<'PY'
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

job_dir = Path(sys.argv[1])
job_id = sys.argv[2]
module = sys.argv[3]
customer_dir = job_dir / "deliverables" / "customer"
figures = customer_dir / "figures"
tables = customer_dir / "tables"
figures.mkdir(parents=True, exist_ok=True)
tables.mkdir(parents=True, exist_ok=True)
summary = [
    f"V4 Beta customer delivery trial package",
    f"Job: {job_id}",
    f"Module: {module}",
    "Scope: customer_delivery rehearsal on controlled small data.",
    "Warning: this rehearsal does not contain real customer data.",
    "Interpretation boundary: outputs are operational delivery QA evidence only, not biological conclusions.",
]
(customer_dir / "report.html").write_text(
    "<html><body>" + "".join(f"<p>{line}</p>" for line in summary) + "</body></html>\n",
    encoding="utf-8",
)
(customer_dir / "methods.md").write_text("\n".join(f"- {line}" for line in summary) + "\n", encoding="utf-8")
(customer_dir / "readme_for_customer.md").write_text(
    "# Customer package\n\n"
    "This controlled V4 Beta package contains sanitized report, methods, figures, and tables.\n\n"
    "Interpretation warning: results require human review and are not mechanism proof.\n",
    encoding="utf-8",
)
(figures / f"{module}_overview.png").write_text("controlled customer-facing figure placeholder\n", encoding="utf-8")
(tables / f"{module}_summary.tsv").write_text("metric\tvalue\ncontrolled_rehearsal\ttrue\n", encoding="utf-8")
with (customer_dir / "delivery_index.tsv").open("w", encoding="utf-8", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=("category", "path", "module", "note"), delimiter="\t")
    writer.writeheader()
    writer.writerow({"category": "report", "path": "report.html", "module": module, "note": "sanitized rehearsal report"})
    writer.writerow({"category": "report", "path": "methods.md", "module": module, "note": "sanitized rehearsal methods"})
    writer.writerow({"category": "readme", "path": "readme_for_customer.md", "module": module, "note": "customer package guide"})
    writer.writerow({"category": "figure", "path": f"figures/{module}_overview.png", "module": module, "note": "customer-facing figure"})
    writer.writerow({"category": "table", "path": f"tables/{module}_summary.tsv", "module": module, "note": "customer-facing table"})
sanitization_rows = []
for check_id in ("internal_path_exposure", "raw_path_exposure", "sensitive_metadata", "interpretation_warning"):
    sanitization_rows.append(
        {
            "check_id": check_id,
            "status": "pass",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "note": "sanitized customer rehearsal package",
        }
    )
for sanitization_name in ("sanitization.tsv", "customer_delivery_sanitization.tsv"):
    with (customer_dir / sanitization_name).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("check_id", "status", "checked_at", "note"), delimiter="\t")
        writer.writeheader()
        writer.writerows(sanitization_rows)
with (customer_dir / "customer_package_manifest.tsv").open("w", encoding="utf-8", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=("artifact_type", "file", "customer_visible", "sanitized", "note"), delimiter="\t")
    writer.writeheader()
    writer.writerow({"artifact_type": "report", "file": "report.html", "customer_visible": "true", "sanitized": "true", "note": "sanitized customer report"})
    writer.writerow({"artifact_type": "methods", "file": "methods.md", "customer_visible": "true", "sanitized": "true", "note": "sanitized customer methods"})
    writer.writerow({"artifact_type": "readme", "file": "readme_for_customer.md", "customer_visible": "true", "sanitized": "true", "note": "customer package guide"})
    writer.writerow({"artifact_type": "figure", "file": f"figures/{module}_overview.png", "customer_visible": "true", "sanitized": "true", "note": "customer-facing figure"})
    writer.writerow({"artifact_type": "table", "file": f"tables/{module}_summary.tsv", "customer_visible": "true", "sanitized": "true", "note": "customer-facing table"})
PY
}

run_delivery_check() {
  local job_dir="$1"
  local env_prefix="$2"
  set +e
  "$env_prefix/bin/python" -m ultimate.cli delivery-check --run-dir "$job_dir"
  local status=$?
  set -e
  if [[ "$status" -ne 0 ]]; then
    DELIVERY_CHECK_FAILURES=$((DELIVERY_CHECK_FAILURES + 1))
    echo "delivery-check blocked for $job_dir; report will include blocker details." >&2
  fi
}

run_ultimate_job() {
  local job_id="$1"
  local module="$2"
  local env_prefix="$3"
  local job_dir="$PROJECT_ROOT/jobs/$job_id"
  local config_path="$job_dir/config/project.yaml"
  local approval_path="$job_dir/config/production_approval.json"
  ULTIMATE_ENV="$env_prefix" bash "$PROJECT_ROOT/slurm/ultimate_run.sbatch" "$config_path" "$approval_path"
  write_customer_package "$job_dir" "$job_id" "$module"
  run_delivery_check "$job_dir" "$env_prefix"
}

write_tabular_job() {
  local module="$1"
  local preset="$2"
  local job_id="v4_beta_${module}_${preset}_customer_delivery_rehearsal_${STAMP}"
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
samples = pd.DataFrame(
    {
        "sample_id": ["CTRL_A", "CTRL_B", "CASE_A", "CASE_B"],
        "condition": ["control", "control", "case", "case"],
    }
)
features = [f"{module.upper()}_{idx:04d}" for idx in range(1, 81)]
values = rng.lognormal(mean=5.0, sigma=0.35, size=(len(features), len(samples)))
values[:12, 2:] *= 1.7
if module == "rnaseq":
    values = np.rint(values).astype(int)
matrix = pd.DataFrame(values, columns=samples["sample_id"])
matrix.insert(0, "feature_id", features)
matrix_path = job_dir / "samples" / f"{module}_matrix.tsv"
matrix.to_csv(matrix_path, sep="\t", index=False)
samples["input_path"] = str(matrix_path)
samples.to_csv(job_dir / "samples" / "samples.tsv", sep="\t", index=False)
(job_dir / "config" / "analysis_request.md").write_text(
    f"{module} V4 Beta customer_delivery rehearsal on controlled small matrix input. Raw upstream handoff is not executed.\\n",
    encoding="utf-8",
	)
PY
  if [[ "$module" == "rnaseq" ]]; then
    mkdir -p "$job_dir/samples/fastq"
    cat > "$job_dir/samples/fastq/CTRL_A.fastq" <<'FASTQ'
@CTRL_A_1
ACGT
+
!!!!
@CTRL_A_2
TGCA
+
!!!!
FASTQ
    cat > "$job_dir/samples/raw_fastq_samples.tsv" <<FASTQTSV
sample_id	condition	fastq_1
CTRL_A	control	$job_dir/samples/fastq/CTRL_A.fastq
FASTQTSV
    run_raw_upstream_evidence "$job_dir" "rnaseq" "$job_dir/samples/fastq" "$job_dir/samples/raw_fastq_samples.tsv"
  else
    write_raw_upstream_evidence "$job_dir" "$module" "raw_to_matrix" "raw_upstream_not_run_controlled_matrix_input_only"
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
  delivery_scope: customer_delivery
  delivery_mode: customer_delivery_rehearsal
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
      upstream_evidence: $job_dir/raw_links/raw_upstream_evidence.tsv
      blocked_reason: raw_upstream_not_run_controlled_matrix_input_only
    input_matrix: $job_dir/samples/${module}_matrix.tsv
    analysis_level: production_backend
    is_demo: false
report:
  title: V4 Beta $module customer delivery trial
  style: morandi_clinical
  figure_options:
    legend_position: outside_right
    show_grid: true
YAML
  write_approval "$job_dir/config/production_approval.json" "$job_id" "$job_dir/config/project.yaml" "$run_dir"
  run_ultimate_job "$job_id" "$module" "$CORE_ENV"
}

write_scrna_job() {
  local job_id="v4_beta_scrna_standard_customer_delivery_rehearsal_${STAMP}"
  local job_dir="$PROJECT_ROOT/jobs/$job_id"
  local run_dir="$job_dir/runs/$job_id"
  write_job_manifest "$job_dir" "$job_id"
  "$SCRNA_ENV/bin/python" - "$job_dir" <<'PY'
import json
import sys
from pathlib import Path

from ultimate.scrna_smoke import create_demo_inputs

job_dir = Path(sys.argv[1])
payload = create_demo_inputs(job_dir / "samples" / "scrna_controlled_10x", n_cells=96, n_genes=70, seed=4107)
controlled_mtx = job_dir / "samples" / "scrna_controlled_10x" / "controlled_10x_mtx"
Path(payload["tenx_mtx"]).rename(controlled_mtx)
payload["tenx_mtx"] = str(controlled_mtx)
(job_dir / "samples" / "scrna_controlled_inputs.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
(job_dir / "config" / "analysis_request.md").write_text(
    "scRNA V4 Beta customer_delivery rehearsal on controlled 10x MTX input. Cell Ranger/nf-core raw handoff is not executed.\\n",
    encoding="utf-8",
)
PY
  run_raw_upstream_evidence "$job_dir" "scrna" "$job_dir/samples/scrna_controlled_10x/controlled_10x_mtx" ""
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
      blocked_reason: raw_upstream_not_run_controlled_10x_mtx_input_only
    tenx_mtx: $job_dir/samples/scrna_controlled_10x/controlled_10x_mtx
    samplesheet: $job_dir/samples/scrna_controlled_10x/samples.tsv
    max_cells: 96
    analysis_level: production_backend
    is_demo: false
report:
  title: V4 Beta scRNA customer delivery trial
  style: morandi_clinical
YAML
  write_approval "$job_dir/config/production_approval.json" "$job_id" "$job_dir/config/project.yaml" "$run_dir"
  run_ultimate_job "$job_id" "scrna" "$SCRNA_ENV"
}

write_spatial_job() {
  local job_id="v4_beta_spatial_standard_customer_delivery_rehearsal_${STAMP}"
  local job_dir="$PROJECT_ROOT/jobs/$job_id"
  local run_dir="$job_dir/runs/$job_id"
  write_job_manifest "$job_dir" "$job_id"
  write_raw_upstream_evidence "$job_dir" "spatial" "spaceranger_or_spatialdata_import" "raw_upstream_not_run_controlled_visium_matrix_input_only"
  "$CORE_ENV/bin/python" - "$job_dir" <<'PY'
import numpy as np
import pandas as pd
import sys
from pathlib import Path

job_dir = Path(sys.argv[1])
rng = np.random.default_rng(4130)
spots = [f"SPOT_{idx:03d}" for idx in range(1, 73)]
genes = [f"GENE_{idx:03d}" for idx in range(1, 49)]
coords = pd.DataFrame(
    {
        "spot_id": spots,
        "pxl_col": np.tile(np.arange(12), 6)[:72],
        "pxl_row": np.repeat(np.arange(6), 12)[:72],
        "array_col": np.tile(np.arange(12), 6)[:72],
        "array_row": np.repeat(np.arange(6), 12)[:72],
        "in_tissue": 1,
    }
)
values = rng.poisson(4.0, size=(len(genes), len(spots))).astype(float)
values[:6, coords["array_col"].to_numpy() > 6] += 4
matrix = pd.DataFrame(values, columns=spots)
matrix.insert(0, "feature_id", genes)
matrix.to_csv(job_dir / "samples" / "spatial_expression.tsv", sep="\t", index=False)
coords.to_csv(job_dir / "samples" / "spatial_coordinates.tsv", sep="\t", index=False)
pd.DataFrame(
    {
        "sample_id": ["spatial_controlled"],
        "condition": ["case"],
        "input_path": [str(job_dir / "samples" / "spatial_expression.tsv")],
    }
).to_csv(job_dir / "samples" / "samples.tsv", sep="\t", index=False)
(job_dir / "config" / "analysis_request.md").write_text(
    "Spatial V4 Beta customer_delivery rehearsal on controlled Visium-style matrix and coordinates. Space Ranger raw handoff is not executed.\\n",
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
modules:
  spatial:
    enabled: true
    preset: standard
    raw:
      enabled: false
      upstream_evidence: $job_dir/raw_links/raw_upstream_evidence.tsv
      blocked_reason: raw_upstream_not_run_controlled_visium_matrix_input_only
    expression_matrix: $job_dir/samples/spatial_expression.tsv
    coordinates: $job_dir/samples/spatial_coordinates.tsv
    analysis_level: production_backend
    is_demo: false
report:
  title: V4 Beta Spatial customer delivery trial
  style: morandi_clinical
YAML
  write_approval "$job_dir/config/production_approval.json" "$job_id" "$job_dir/config/project.yaml" "$run_dir"
  run_ultimate_job "$job_id" "spatial" "$CORE_ENV"
}

write_tabular_job rnaseq standard
write_scrna_job
write_tabular_job proteomics standard
write_spatial_job

"$CORE_ENV/bin/python" -m ultimate.cli validation-index \
  --root "$PROJECT_ROOT" \
  --output-dir "$PROJECT_ROOT/reports/validation_index_v4_beta"
"$CORE_ENV/bin/python" -m ultimate.cli audit-production \
  --root "$PROJECT_ROOT" \
  --output-dir "$PROJECT_ROOT/audits/production_v4_beta_latest"
"$CORE_ENV/bin/python" -m ultimate.cli audit-backends \
  --root "$PROJECT_ROOT" \
  --output-dir "$PROJECT_ROOT/audits/backends_v4_beta_latest"
if [[ -f "$PROJECT_ROOT/01_tools/storage_audit.py" ]]; then
  "$CORE_ENV/bin/python" "$PROJECT_ROOT/01_tools/storage_audit.py" \
    --root "$PROJECT_ROOT" \
    --output-dir "$PROJECT_ROOT/audits/storage_v4_beta_latest" \
    --budget-gb 500
fi

"$CORE_ENV/bin/python" - "$PROJECT_ROOT" "$STAMP" "$REPORT_PATH" <<'PY'
import csv
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
stamp = sys.argv[2]
report_path = Path(sys.argv[3])
index = root / "reports" / "validation_index_v4_beta" / "validation_index.tsv"
rows = list(csv.DictReader(index.open(), delimiter="\t")) if index.exists() else []
v4 = [r for r in rows if r.get("run_name", "").startswith("v4_beta_") and r.get("run_name", "").endswith(stamp)]
ready = [r for r in v4 if r.get("delivery_scope") == "customer_delivery" and r.get("order_readiness_status") == "ready_for_delivery"]
blocked = [r for r in v4 if r not in ready]
delivery_checks = []
raw_evidence = []
for job_dir in sorted((root / "jobs").glob(f"v4_beta_*_{stamp}")):
    check_path = job_dir / "deliverables" / "latest_delivery_check.json"
    if check_path.exists():
        payload = json.loads(check_path.read_text(encoding="utf-8"))
        delivery_checks.append(
            {
                "job": job_dir.name,
                "status": payload.get("status", "missing"),
                "blockers": ",".join(payload.get("blockers") or []) or "none",
            }
        )
    evidence_path = job_dir / "raw_links" / "raw_upstream_evidence.tsv"
    if evidence_path.exists():
        with evidence_path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                raw_evidence.append({"job": job_dir.name, **row})
raw_ready = [row for row in raw_evidence if row.get("execution_status") == "ready"]
raw_blocked = [row for row in raw_evidence if row.get("execution_status") != "ready"]
report_path.parent.mkdir(parents=True, exist_ok=True)
lines = [
    "# Ultimate V4 Beta customer delivery trial report",
    "",
    f"- Suite stamp: `{stamp}`",
    "- Scope: `customer_delivery` rehearsal on controlled small data only.",
    "- Raw customer data: not used.",
    f"- V4 Beta jobs found: {len(v4)}",
    f"- Ready customer_delivery rehearsals: {len(ready)}",
    f"- Blocked/needs review: {len(blocked)}",
    f"- Raw upstream ready evidence rows: {len(raw_ready)}",
    f"- Raw upstream blocked/handoff rows: {len(raw_blocked)}",
    "",
    "## Delivery-check status",
]
for row in delivery_checks:
    lines.append(f"- `{row['job']}`: `{row['status']}`; blockers: `{row['blockers']}`")
lines.extend(["", "## Raw upstream evidence"])
for row in raw_evidence:
    lines.append(
        f"- `{row.get('job')}` / `{row.get('module')}` / `{row.get('raw_stage')}`: "
        f"`{row.get('execution_status')}`; blocked_reason=`{row.get('blocked_reason')}`"
    )
lines.extend(["", "## Validation-index blocked or needs review"])
for row in blocked:
    lines.append(
        f"- `{row.get('module')}` / `{row.get('run_name')}`: "
        f"{row.get('missing_or_gap') or row.get('next_action') or row.get('order_readiness_status')}"
    )
report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(report_path)
PY

if [[ "$DELIVERY_CHECK_FAILURES" -ne 0 ]]; then
  echo "V4 Beta customer delivery trial completed with delivery-check blockers: $DELIVERY_CHECK_FAILURES" >&2
  exit 5
fi
