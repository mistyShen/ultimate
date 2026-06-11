from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from ultimate.job import prepare_job


BATCH_NON_DELIVERY_REASON = "batch_scaffold_not_analysis_run"
ALLOWED_BATCH_STATUSES = ("ready_to_run", "needs_metadata", "needs_license", "raw_upstream_required", "blocked")
BATCH_ROW_COLUMNS = (
    "batch_id",
    "job_id",
    "status",
    "scaffold_status",
    "job_dir",
    "config_path",
    "source_config",
    "analysis_request",
    "analysis_request_status",
    "samplesheet",
    "samplesheet_status",
    "run_mode",
    "approval_status",
    "delivery_allowed",
    "non_delivery_reason",
    "next_action",
    "delivery_risk",
    "production_approval_allowed",
    "failure_recovery",
    "blockers",
)


def prepare_batch(
    *,
    batch_path: Path,
    root: Path | None = None,
    output_dir: Path | None = None,
    run_mode: str | None = None,
) -> dict[str, Any]:
    batch_path = batch_path.expanduser().resolve()
    batch = _load_batch(batch_path)
    base_dir = batch_path.parent
    batch_id = _clean_identifier(str(batch.get("batch_id") or batch_path.stem))
    batch_root = (root or _resolve_required_path(base_dir, batch.get("root"), field="root")).expanduser().resolve()
    batch_output_dir = (output_dir or batch_root / "batches" / batch_id).expanduser().resolve()
    batch_output_dir.mkdir(parents=True, exist_ok=True)

    jobs = _job_entries(batch)
    default_run_mode = run_mode or str(batch.get("run_mode") or "production")
    rows: list[dict[str, str]] = []
    job_manifests: list[dict[str, Any]] = []
    for index, job in enumerate(jobs, start=1):
        row, manifest = _prepare_batch_job(
            batch_id=batch_id,
            base_dir=base_dir,
            batch_root=batch_root,
            job=job,
            index=index,
            default_run_mode=default_run_mode,
        )
        rows.append(row)
        if manifest:
            job_manifests.append(manifest)

    summary_path = _write_summary_tsv(batch_output_dir / "batch_summary.tsv", rows)
    report_path = _write_report(batch_output_dir / "batch_report.md", batch_id=batch_id, rows=rows, root=batch_root)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "batch_id": batch_id,
        "batch_path": str(batch_path),
        "root": str(batch_root),
        "output_dir": str(batch_output_dir),
        "jobs_total": len(rows),
        "jobs_ready": sum(1 for row in rows if row["status"] == "ready_to_run"),
        "jobs_blocked": sum(1 for row in rows if row["status"] == "blocked"),
        "status_counts": {status: sum(1 for row in rows if row["status"] == status) for status in ALLOWED_BATCH_STATUSES},
        "delivery_allowed": False,
        "non_delivery_reason": BATCH_NON_DELIVERY_REASON,
        "analysis_level": "smoke_backend",
        "is_demo": False,
        "is_stub": False,
        "validation_evidence_allowed": False,
        "policy": {
            "scope": "batch scaffold only",
            "runs_analysis": False,
            "submits_slurm": False,
            "remote_commands": False,
            "raw_data_policy": "read_only_reference; raw data is not copied, moved, overwritten, or modified",
        },
        "artifacts": {
            "summary_tsv": str(summary_path),
            "report_md": str(report_path),
        },
        "rows": rows,
        "job_manifests": job_manifests,
    }
    manifest_path = batch_output_dir / "batch_manifest.json"
    manifest["manifest_path"] = str(manifest_path)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def _prepare_batch_job(
    *,
    batch_id: str,
    base_dir: Path,
    batch_root: Path,
    job: dict[str, Any],
    index: int,
    default_run_mode: str,
) -> tuple[dict[str, str], dict[str, Any] | None]:
    row = _base_row(batch_id=batch_id, job_id=str(job.get("job_id") or f"job_{index:03d}"), run_mode=str(job.get("run_mode") or default_run_mode))
    try:
        job_id = _required_text(job, "job_id")
        config_path = _resolve_required_path(base_dir, job.get("config") or job.get("config_path"), field="config")
        samplesheet = _resolve_optional_path(base_dir, job.get("samplesheet"))
        analysis_request = _resolve_optional_path(base_dir, job.get("request") or job.get("analysis_request"))
        job_run_mode = str(job.get("run_mode") or default_run_mode)
        if job_run_mode not in {"production", "interactive"}:
            raise ValueError("run_mode must be one of: production, interactive")
        if not config_path.exists():
            raise FileNotFoundError(f"config does not exist: {config_path}")

        manifest = prepare_job(
            config_path=config_path,
            job_id=job_id,
            root=batch_root,
            samplesheet=samplesheet,
            analysis_request=analysis_request,
            run_mode=job_run_mode,
        )
        _apply_explicit_approval(job, Path(manifest["approval_template"]))
        row.update(
            {
                "job_id": str(manifest["job_id"]),
                "status": _batch_status(job=job, manifest=manifest),
                "scaffold_status": "scaffolded",
                "job_dir": str(manifest["job_dir"]),
                "config_path": str(manifest["config_path"]),
                "source_config": str(config_path),
                "analysis_request": str(manifest.get("analysis_request") or ""),
                "analysis_request_status": str((manifest.get("analysis_request_status") or {}).get("status", "")),
                "samplesheet": str(manifest.get("samplesheet") or ""),
                "samplesheet_status": str((manifest.get("samplesheet_status") or {}).get("status", "")),
                "run_mode": str(manifest["run_mode"]),
                "approval_status": _approval_status(Path(manifest["approval_template"])),
            }
        )
        row.update(_status_fields(row["status"], blockers=""))
        recovery = _write_failure_recovery(Path(manifest["job_dir"]), row)
        row["failure_recovery"] = str(recovery)
        return row, manifest
    except Exception as exc:
        row.update(
            {
                "status": "blocked",
                "scaffold_status": "not_scaffolded",
                "blockers": f"{type(exc).__name__}: {exc}",
            }
        )
        row.update(_status_fields("blocked", blockers=row["blockers"]))
        return row, None


def _load_batch(batch_path: Path) -> dict[str, Any]:
    if not batch_path.exists():
        raise FileNotFoundError(f"batch file does not exist: {batch_path}")
    if batch_path.suffix.lower() == ".json":
        data = json.loads(batch_path.read_text(encoding="utf-8"))
    else:
        with batch_path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise TypeError(f"Batch file must be a mapping: {batch_path}")
    return data


def _job_entries(batch: dict[str, Any]) -> list[dict[str, Any]]:
    jobs = batch.get("jobs") or batch.get("entries")
    if not isinstance(jobs, list) or not jobs:
        raise ValueError("batch must contain a non-empty jobs or entries list")
    normalized: list[dict[str, Any]] = []
    for index, job in enumerate(jobs, start=1):
        if not isinstance(job, dict):
            raise TypeError(f"batch job entry {index} must be a mapping")
        merged = dict(job)
        if "config" not in merged and "config_path" not in merged and batch.get("config"):
            merged["config"] = batch["config"]
        normalized.append(merged)
    return normalized


def _base_row(*, batch_id: str, job_id: str, run_mode: str) -> dict[str, str]:
    row = {column: "" for column in BATCH_ROW_COLUMNS}
    row.update(
        {
            "batch_id": batch_id,
            "job_id": _clean_identifier(job_id),
            "status": "blocked",
            "scaffold_status": "not_scaffolded",
            "run_mode": run_mode,
            "delivery_allowed": "false",
            "non_delivery_reason": BATCH_NON_DELIVERY_REASON,
            "production_approval_allowed": "false",
        }
    )
    return row


def _batch_status(*, job: dict[str, Any], manifest: dict[str, Any]) -> str:
    explicit = str(job.get("status") or job.get("intake_status") or "").strip()
    if explicit in ALLOWED_BATCH_STATUSES:
        return explicit
    if job.get("requires_license") is True or job.get("licensed_tool") or job.get("license_path"):
        return "needs_license"
    samplesheet_status = str((manifest.get("samplesheet_status") or {}).get("status") or "")
    request_status = str((manifest.get("analysis_request_status") or {}).get("status") or "")
    if samplesheet_status in {"not_configured", "missing_or_not_copied"} or request_status in {"not_configured", "missing_or_not_copied"}:
        return "needs_metadata"
    if _manifest_has_raw_upstream(manifest):
        return "raw_upstream_required"
    return "ready_to_run"


def _manifest_has_raw_upstream(manifest: dict[str, Any]) -> bool:
    raw_manifest = Path(str(manifest.get("raw_input_manifest") or ""))
    if not raw_manifest.exists():
        return False
    with raw_manifest.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            path = str(row.get("path") or "").lower()
            key = str(row.get("key") or "").lower()
            if any(token in path for token in (".fastq", ".fq", ".bcl", "fragments.tsv")):
                return True
            if any(token in key for token in ("fastq", "bcl", "fragments")):
                return True
    return False


def _status_fields(status: str, *, blockers: str) -> dict[str, str]:
    if status == "ready_to_run":
        return {
            "next_action": "run_preflight_then_request_production_approval",
            "delivery_risk": "low_after_approval",
            "production_approval_allowed": "true",
        }
    if status == "needs_metadata":
        return {
            "next_action": "collect_samplesheet_analysis_request_and_design_metadata",
            "delivery_risk": "metadata_incomplete",
            "production_approval_allowed": "false",
        }
    if status == "needs_license":
        return {
            "next_action": "provide_or_validate_licensed_tool_path_before_running",
            "delivery_risk": "license_required",
            "production_approval_allowed": "false",
        }
    if status == "raw_upstream_required":
        return {
            "next_action": "run_raw_upstream_handoff_or_import_matrix_before_analysis",
            "delivery_risk": "raw_upstream_not_yet_materialized",
            "production_approval_allowed": "false",
        }
    return {
        "next_action": "fix_blocker_then_prepare_batch_again",
        "delivery_risk": blockers or "blocked",
        "production_approval_allowed": "false",
    }


def _write_failure_recovery(job_dir: Path, row: dict[str, str]) -> Path:
    path = job_dir / "failure_recovery.md"
    reusable = [
        "prepared job directory",
        "copied config and samplesheet snapshots" if row.get("samplesheet") else "config snapshot",
        "raw input path manifest",
    ]
    rerun_required = row["status"] in {"raw_upstream_required", "blocked"}
    lines = [
        "# Failure recovery",
        "",
        f"- job_id: `{row['job_id']}`",
        f"- status: `{row['status']}`",
        f"- failure_stage: `{_failure_stage(row['status'])}`",
        f"- reusable_artifacts: `{', '.join(reusable)}`",
        f"- rerun_required: `{str(rerun_required).lower()}`",
        f"- slurm_required: `{str(row['status'] in {'raw_upstream_required', 'ready_to_run'}).lower()}`",
        f"- next_action: `{row['next_action']}`",
        f"- minimal_fix_command: `{_minimal_fix_command(row)}`",
        "",
        "This scaffold did not run analysis and does not allow delivery.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _failure_stage(status: str) -> str:
    return {
        "ready_to_run": "not_failed_ready_for_preflight",
        "needs_metadata": "intake_metadata",
        "needs_license": "dependency_license",
        "raw_upstream_required": "raw_upstream",
        "blocked": "prepare_batch",
    }[status]


def _minimal_fix_command(row: dict[str, str]) -> str:
    if row["status"] == "ready_to_run":
        return f"ultimate preflight --config {row['config_path']}"
    if row["status"] == "raw_upstream_required":
        return f"review raw handoff and regenerate matrix import config for {row['job_id']}"
    if row["status"] == "needs_metadata":
        return f"update samplesheet/request then rerun ultimate prepare-batch for {row['job_id']}"
    if row["status"] == "needs_license":
        return f"set licensed tool path then rerun ultimate prepare-batch for {row['job_id']}"
    return f"fix blocker: {row['blockers']}"


def _required_text(job: dict[str, Any], field: str) -> str:
    value = job.get(field)
    if value in (None, ""):
        raise ValueError(f"missing required job field: {field}")
    return str(value)


def _resolve_required_path(base_dir: Path, value: Any, *, field: str) -> Path:
    path = _resolve_optional_path(base_dir, value)
    if path is None:
        raise ValueError(f"missing required batch field: {field}")
    return path


def _resolve_optional_path(base_dir: Path, value: Any) -> Path | None:
    if value in (None, ""):
        return None
    candidate = Path(str(value)).expanduser()
    return candidate if candidate.is_absolute() else (base_dir / candidate).resolve()


def _apply_explicit_approval(job: dict[str, Any], approval_path: Path) -> None:
    approval = job.get("approval") or job.get("production_approval")
    if not isinstance(approval, dict) or not approval:
        return
    payload = json.loads(approval_path.read_text(encoding="utf-8"))
    payload.update(approval)
    approval_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _approval_status(approval_path: Path) -> str:
    if not approval_path.exists():
        return "missing"
    payload = json.loads(approval_path.read_text(encoding="utf-8"))
    if payload.get("approved") is True and payload.get("delivery_scope") == "customer_delivery":
        return "customer_approved"
    if payload.get("approved") is True:
        return "approved_internal"
    return "template_pending_approval"


def _write_summary_tsv(path: Path, rows: list[dict[str, str]]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=BATCH_ROW_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _write_report(path: Path, *, batch_id: str, rows: list[dict[str, str]], root: Path) -> Path:
    ready = sum(1 for row in rows if row["status"] == "ready_to_run")
    blocked = sum(1 for row in rows if row["status"] == "blocked")
    lines = [
        "# Ultimate batch scaffold report",
        "",
        f"- batch_id: `{batch_id}`",
        f"- root: `{root}`",
        f"- jobs_total: {len(rows)}",
        f"- jobs_ready_to_run: {ready}",
        f"- jobs_blocked: {blocked}",
        "- delivery_allowed: false",
        f"- non_delivery_reason: `{BATCH_NON_DELIVERY_REASON}`",
        "- scope: scaffold only; no analysis, Slurm submission, or remote command is run.",
        "",
        "## Jobs",
        "",
        "| job_id | status | scaffold | approval | next_action | delivery_risk | production_approval_allowed | blockers |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        blockers = row["blockers"].replace("|", "\\|")
        lines.append(
            f"| {row['job_id']} | {row['status']} | {row['scaffold_status']} | {row['approval_status']} | "
            f"{row['next_action']} | {row['delivery_risk']} | {row['production_approval_allowed']} | {blockers} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _clean_identifier(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value).strip())
    if not cleaned:
        raise ValueError("identifier cannot be empty")
    return cleaned
