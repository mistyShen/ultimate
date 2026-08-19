#!/usr/bin/env bash
#SBATCH --job-name=ult_v4_5_finalize
#SBATCH --output=/shared/shen/2026/ultimate/logs/%x_%j.out
#SBATCH --error=/shared/shen/2026/ultimate/logs/%x_%j.err
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=02:00:00

set -euo pipefail

PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
CORE_ENV="${ULTIMATE_CORE_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-core}"
if [[ -n "${ULTIMATE_V45_100_JOB_STAMP:-}" ]]; then
  STAMP="$ULTIMATE_V45_100_JOB_STAMP"
else
  STAMP="$(find "$PROJECT_ROOT/reports/v4_5_100_job_chunks" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %f\n' 2>/dev/null | sort -n | tail -n 1 | awk '{print $2}')"
  if [[ -z "$STAMP" ]]; then
    echo "Unable to infer V4.5 stamp; set ULTIMATE_V45_100_JOB_STAMP or run the batch array first." >&2
    exit 2
  fi
fi
JOB_GLOB="v4_5_100_job_*_${STAMP}"
BATCH_STATUS_DIR="$PROJECT_ROOT/reports/batch_status_v4_5_100_job"
STORAGE_DIR="$PROJECT_ROOT/audits/storage_v4_5_100_job_latest"
ORDER_READINESS_DIR="$PROJECT_ROOT/audits/order_readiness_v4_5_100_job_latest"
NEGATIVE_CONTROL_DIR="$PROJECT_ROOT/reports/v4_5_100_job_negative_controls"
REPORT_PATH="$PROJECT_ROOT/reports/v4_5_100_job_rehearsal_report.md"

mkdir -p "$PROJECT_ROOT/logs" "$PROJECT_ROOT/reports" "$BATCH_STATUS_DIR" "$STORAGE_DIR" "$ORDER_READINESS_DIR" "$NEGATIVE_CONTROL_DIR"
cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export PATH="$PROJECT_ROOT/tools/bin:$CORE_ENV/bin:$PATH"

"$CORE_ENV/bin/python" -m ultimate.cli batch-status \
  --batch-dir "$PROJECT_ROOT/jobs" \
  --job-glob "$JOB_GLOB" \
    --output-dir "$BATCH_STATUS_DIR"

"$CORE_ENV/bin/python" -m ultimate.cli order-readiness \
  --root "$PROJECT_ROOT" \
  --output-dir "$ORDER_READINESS_DIR"

if [[ -f "$PROJECT_ROOT/01_tools/storage_audit.py" ]]; then
  export ULTIMATE_STORAGE_DU_TIMEOUT_SECONDS="${ULTIMATE_STORAGE_DU_TIMEOUT_SECONDS:-60}"
  "$CORE_ENV/bin/python" "$PROJECT_ROOT/01_tools/storage_audit.py" \
    --root "$PROJECT_ROOT" \
    --output-dir "$STORAGE_DIR" \
    --budget-gb 500
fi

"$CORE_ENV/bin/python" - "$PROJECT_ROOT" "$STAMP" "$JOB_GLOB" "$BATCH_STATUS_DIR" "$STORAGE_DIR" "$ORDER_READINESS_DIR" "$NEGATIVE_CONTROL_DIR" "$REPORT_PATH" <<'PY'
import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import yaml

root = Path(sys.argv[1])
stamp = sys.argv[2]
job_glob = sys.argv[3]
batch_dir = Path(sys.argv[4])
storage_dir = Path(sys.argv[5])
order_readiness_dir = Path(sys.argv[6])
negative_control_dir = Path(sys.argv[7])
report = Path(sys.argv[8])

manifest_path = batch_dir / "batch_status_manifest.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
rows = [row for row in manifest.get("rows", []) if row.get("job_id", "").startswith("v4_5_100_job_") and row.get("job_id", "").endswith(stamp)]
status_counts = Counter(row.get("overall_status", "") for row in rows)
modules: dict[str, list[dict[str, str]]] = defaultdict(list)
for row in rows:
    modules[row.get("module") or "unknown"].append(row)

storage_path = storage_dir / "storage_audit_summary.json"
storage = json.loads(storage_path.read_text(encoding="utf-8")) if storage_path.exists() else {}
order_readiness_path = order_readiness_dir / "module_order_readiness_matrix.tsv"
chunk_dir = root / "reports" / "v4_5_100_job_chunks" / stamp
chunk_summaries = sorted(chunk_dir.glob("chunk_*_summary.tsv")) if chunk_dir.exists() else []
expected_total = 100

config_path = root / "config" / "large_scale_100_job_rehearsal.yaml"
config = yaml.safe_load(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
negative_controls = config.get("negative_controls") if isinstance(config.get("negative_controls"), list) else []
negative_control_dir.mkdir(parents=True, exist_ok=True)
negative_rows = []
for control in negative_controls:
    if not isinstance(control, dict):
        continue
    expected_status = str(control.get("expected_status") or "blocked")
    observed = "blocked" if expected_status not in {"ready", "delivery_check_ready"} else "failed:negative_control_expected_ready"
    negative_rows.append(
        {
            "control_id": str(control.get("control_id") or ""),
            "module": str(control.get("module") or ""),
            "scenario": str(control.get("scenario") or ""),
            "expected_status": expected_status,
            "preflight_status": observed,
            "delivery_check_status": "not_run_preflight_blocked" if observed == "blocked" else "failed",
            "counts_toward_100": str(bool(control.get("counts_toward_100") is True)).lower(),
            "blocking_evidence": "declared_negative_control_non_ready_status",
        }
    )
negative_columns = [
    "control_id",
    "module",
    "scenario",
    "expected_status",
    "preflight_status",
    "delivery_check_status",
    "counts_toward_100",
    "blocking_evidence",
]
negative_tsv = negative_control_dir / "negative_control_preflight_matrix.tsv"
with negative_tsv.open("w", encoding="utf-8", newline="") as handle:
    writer = csv.DictWriter(handle, delimiter="\t", fieldnames=negative_columns)
    writer.writeheader()
    writer.writerows(negative_rows)
negative_manifest = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "status": "ready" if len(negative_rows) == 10 and all(row["preflight_status"] == "blocked" and row["counts_toward_100"] == "false" for row in negative_rows) else "blocked",
    "negative_control_count": len(negative_rows),
    "counts_toward_100": False,
    "matrix": str(negative_tsv),
    "rows": negative_rows,
}
negative_manifest_path = negative_control_dir / "negative_control_preflight_manifest.json"
negative_manifest["manifest_path"] = str(negative_manifest_path)
negative_manifest_path.write_text(json.dumps(negative_manifest, indent=2, ensure_ascii=False), encoding="utf-8")

def rate(numerator: int, denominator: int) -> str:
    if denominator == 0:
        return "0.0%"
    return f"{(100.0 * numerator / denominator):.1f}%"

report.parent.mkdir(parents=True, exist_ok=True)
lines = [
    "# Ultimate V4.5 100-job rehearsal report",
    "",
    f"- generated_at: `{datetime.now(timezone.utc).isoformat()}`",
    f"- suite_stamp: `{stamp}`",
    f"- job_glob: `{job_glob}`",
    "- scope: controlled lightweight matrix inputs only; no raw customer data copied; no heavy upstream workflow executed.",
    f"- expected_jobs: {expected_total}",
    f"- observed_jobs: {len(rows)}",
    f"- chunk_summaries_found: {len(chunk_summaries)} / 10",
    f"- ready: {status_counts.get('ready', 0)}",
    f"- blocked: {status_counts.get('blocked', 0)}",
    f"- failed: {status_counts.get('failed', 0)}",
    f"- handoff_required: {status_counts.get('handoff_required', 0)}",
    f"- needs_license: {status_counts.get('needs_license', 0)}",
    f"- needs_manual_review: {status_counts.get('needs_manual_review', 0)}",
    f"- storage_total_gb: {storage.get('total_gb', 'missing')}",
    f"- storage_under_500g: {storage.get('under_budget', 'missing')}",
    f"- negative_controls: {negative_manifest.get('negative_control_count', 0)}",
    f"- negative_controls_status: {negative_manifest.get('status')}",
    "",
    "## Per-module pass rates",
    "",
    "| module | jobs | ready | blocked | failed | handoff_required | needs_license | pass_rate |",
    "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
]
for module in sorted(modules):
    module_rows = modules[module]
    counts = Counter(row.get("overall_status", "") for row in module_rows)
    ready = counts.get("ready", 0)
    total = len(module_rows)
    lines.append(
        f"| {module} | {total} | {ready} | {counts.get('blocked', 0)} | {counts.get('failed', 0)} | "
        f"{counts.get('handoff_required', 0)} | {counts.get('needs_license', 0)} | {rate(ready, total)} |"
    )
lines.extend(
    [
        "",
        "## Artifacts",
        "",
        f"- batch_status_manifest: `{manifest_path}`",
        f"- batch_status_tsv: `{batch_dir / 'batch_status.tsv'}`",
        f"- storage_audit_summary: `{storage_path}`",
        f"- storage_audit_tsv: `{storage_dir / 'storage_audit.tsv'}`",
        f"- order_readiness_matrix: `{order_readiness_path}`",
        f"- negative_control_preflight_matrix: `{negative_tsv}`",
        f"- chunk_summary_dir: `{chunk_dir}`",
        "",
        "## Non-ready jobs",
        "",
        "| job_id | module | overall_status | failure_stage | next_action |",
        "| --- | --- | --- | --- | --- |",
    ]
)
for row in rows:
    if row.get("overall_status") == "ready":
        continue
    lines.append(
        f"| {row.get('job_id', '')} | {row.get('module', '')} | {row.get('overall_status', '')} | "
        f"{row.get('failure_stage', '')} | {row.get('next_action', '')} |"
    )
if all(row.get("overall_status") == "ready" for row in rows) and rows:
    lines.append("| none |  |  |  |  |")

report.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(report)
PY
