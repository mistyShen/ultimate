#!/usr/bin/env bash
#SBATCH --job-name=ult_v4_pilot
#SBATCH --output=/shared/shen/2026/ultimate/logs/%x_%j.out
#SBATCH --error=/shared/shen/2026/ultimate/logs/%x_%j.err
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --time=18:00:00

set -euo pipefail

PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
CORE_ENV="${ULTIMATE_CORE_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-core}"
STAMP="${ULTIMATE_V4_PILOT_STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}"
PILOT_REPORT="$PROJECT_ROOT/reports/v4_pilot_realistic_report.md"

mkdir -p "$PROJECT_ROOT/logs" "$PROJECT_ROOT/reports"
cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export PATH="$PROJECT_ROOT/tools/bin:$CORE_ENV/bin:$PATH"

# Pilot A: deep raw/standard input to customer package closure.
ULTIMATE_V42_TRIAL_STAMP="$STAMP" \
ULTIMATE_V42_REPORT_PATH="$PROJECT_ROOT/reports/v4_pilot_raw_to_customer_report.md" \
ULTIMATE_SKIP_STORAGE_AUDIT=1 \
bash "$PROJECT_ROOT/slurm/v4_2_raw_to_customer_trial.sbatch"

# Pilot B: module breadth coverage through existing lightweight rehearsal suites.
ULTIMATE_V38_REHEARSAL_STAMP="$STAMP" bash "$PROJECT_ROOT/slurm/v3_8_multiomics_publication_rehearsal.sbatch"
ULTIMATE_V41_REHEARSAL_STAMP="$STAMP" \
ULTIMATE_SKIP_STORAGE_AUDIT=1 \
bash "$PROJECT_ROOT/slurm/v4_1_order_readiness_rehearsal.sbatch"

# Normalize delivery artifacts across both layers. Older internal rehearsal
# suites may only write run-level deliverables; the realistic pilot requires a
# customer-package status for every stamped job, even when the package is a
# controlled rehearsal artifact rather than a true customer release.
while IFS= read -r job_dir; do
  [[ -n "$job_dir" ]] || continue
  "$CORE_ENV/bin/python" -m ultimate.cli customer-package --run-dir "$job_dir"
  "$CORE_ENV/bin/python" -m ultimate.cli delivery-check --run-dir "$job_dir"
done < <(find "$PROJECT_ROOT/jobs" -maxdepth 1 -type d -name "v*_*$STAMP" | sort)

"$CORE_ENV/bin/python" -m ultimate.cli validation-index \
  --root "$PROJECT_ROOT" \
  --output-dir "$PROJECT_ROOT/reports/validation_index_v4_pilot"
"$CORE_ENV/bin/python" -m ultimate.cli audit-production \
  --root "$PROJECT_ROOT" \
  --output-dir "$PROJECT_ROOT/audits/production_v4_pilot_latest"
"$CORE_ENV/bin/python" -m ultimate.cli audit-backends \
  --root "$PROJECT_ROOT" \
  --output-dir "$PROJECT_ROOT/audits/backends_v4_pilot_latest"
"$CORE_ENV/bin/python" -m ultimate.cli tool-completeness \
  --root "$PROJECT_ROOT" \
  --output-dir "$PROJECT_ROOT/audits/tool_completeness_v4_pilot_latest"
"$CORE_ENV/bin/python" -m ultimate.cli order-readiness \
  --root "$PROJECT_ROOT" \
  --output-dir "$PROJECT_ROOT/audits/order_readiness_v4_pilot_latest"
if [[ -f "$PROJECT_ROOT/01_tools/storage_audit.py" ]]; then
  export ULTIMATE_STORAGE_DU_TIMEOUT_SECONDS="${ULTIMATE_STORAGE_DU_TIMEOUT_SECONDS:-60}"
  "$CORE_ENV/bin/python" "$PROJECT_ROOT/01_tools/storage_audit.py" \
    --root "$PROJECT_ROOT" \
    --output-dir "$PROJECT_ROOT/audits/storage_v4_pilot_latest" \
    --budget-gb 500
fi

"$CORE_ENV/bin/python" -m ultimate.cli batch-status \
  --batch-dir "$PROJECT_ROOT/jobs" \
  --job-glob "v*_*$STAMP" \
  --output-dir "$PROJECT_ROOT/reports/batch_status_v4_pilot"

"$CORE_ENV/bin/python" - "$PROJECT_ROOT" "$STAMP" "$PILOT_REPORT" <<'PY'
import csv
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
stamp = sys.argv[2]
report = Path(sys.argv[3])
validation_path = root / "reports" / "validation_index_v4_pilot" / "validation_index.tsv"
rows = list(csv.DictReader(validation_path.open("r", encoding="utf-8"), delimiter="\t")) if validation_path.exists() else []
raw_report = root / "reports" / "v4_pilot_raw_to_customer_report.md"
batch_manifest = root / "reports" / "batch_status_v4_pilot" / "batch_status_manifest.json"
storage_path = root / "audits" / "storage_v4_pilot_latest" / "storage_audit_summary.json"
order_path = root / "audits" / "order_readiness_v4_pilot_latest" / "module_order_readiness_matrix.tsv"

pilot_rows = [r for r in rows if stamp in (r.get("run_name", "") + r.get("run_dir", ""))]
high_freq_modules = {"scrna", "rnaseq", "proteomics", "methylation", "scatac", "multiome", "spatial", "cite_seq", "vdj", "functional_state"}
covered = sorted({r.get("module") for r in pilot_rows if r.get("module") in high_freq_modules})
ready_rows = [r for r in pilot_rows if r.get("order_readiness_status") == "ready_for_delivery"]
blocked_rows = [r for r in pilot_rows if r.get("order_readiness_status") not in {"", "ready_for_delivery"}]

batch = json.loads(batch_manifest.read_text()) if batch_manifest.exists() else {"rows": []}
batch_rows = [r for r in batch.get("rows", []) if stamp in r.get("job_id", "")]
customer_package_ready = [r for r in batch_rows if r.get("customer_package_status") == "ready"]
delivery_ready = [r for r in batch_rows if r.get("delivery_check_status") == "ready"]
raw_ready = [r for r in batch_rows if r.get("raw_upstream_status") == "ready"]
raw_blocked = [r for r in batch_rows if r.get("raw_upstream_status") == "blocked"]
storage = json.loads(storage_path.read_text()) if storage_path.exists() else {}

license_required = []
handoff_required = []
if order_path.exists():
    order_rows = list(csv.DictReader(order_path.open("r", encoding="utf-8"), delimiter="\t"))
    license_required = [r for r in order_rows if "licensed" in r.get("backend_statuses", "") or "license" in r.get("next_action", "")]
    handoff_required = [r for r in order_rows if "handoff" in r.get("backend_statuses", "") or "handoff" in r.get("raw_upstream_status", "")]

report.parent.mkdir(parents=True, exist_ok=True)
lines = [
    "# Ultimate realistic pilot report",
    "",
    f"- Suite stamp: `{stamp}`",
    "- Scope: controlled public/internal data pilot; no real customer data.",
    f"- ready: {len(ready_rows)} validation/rehearsal row(s) are ready for delivery.",
    f"- blocked: {len(raw_blocked) + len(blocked_rows)} raw or module row(s) require fixes/review.",
    f"- handoff-required: {len(handoff_required)} module/backend row(s) mention handoff routes.",
    f"- license-required: {len(license_required)} module/backend row(s) mention licensed routes.",
    f"- raw-upstream-validated: {len(raw_ready)} pilot raw/semi-raw job(s) are ready.",
    f"- customer-package-ready: {len(customer_package_ready)} pilot customer package(s) passed package/status checks.",
    f"- delivery-check-ready: {len(delivery_ready)} pilot job(s) passed delivery-check.",
    f"- high-frequency modules covered: {len(covered)} / {len(high_freq_modules)} ({', '.join(covered)})",
    f"- storage: {storage.get('total_gb', 'missing')}G; under_500G={storage.get('under_budget', 'missing')}",
    "",
    "## Raw-to-customer summary",
]
if raw_report.exists():
    lines.extend(raw_report.read_text(encoding="utf-8").splitlines()[2:])
else:
    lines.append("- raw-to-customer report missing")
lines.extend(["", "## Batch rows"])
for row in batch_rows:
    lines.append(
        f"- `{row.get('job_id')}`: raw=`{row.get('raw_upstream_status')}`, run=`{row.get('run_status')}`, "
        f"package=`{row.get('customer_package_status')}`, delivery=`{row.get('delivery_check_status')}`, overall=`{row.get('overall_status')}`"
    )
lines.extend(["", "## Module coverage"])
for module in sorted(high_freq_modules):
    status = "covered" if module in covered else "not_seen_in_pilot_index"
    lines.append(f"- `{module}`: {status}")
report.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(report)
PY
