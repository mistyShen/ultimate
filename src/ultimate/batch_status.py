from __future__ import annotations

import csv
import fnmatch
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BATCH_STATUS_COLUMNS = (
    "job_id",
    "job_dir",
    "scaffold_status",
    "raw_upstream_status",
    "run_status",
    "customer_package_status",
    "delivery_check_status",
    "overall_status",
    "failure_stage",
    "next_action",
    "failure_recovery",
)


def build_batch_status(*, batch_dir: Path, output_dir: Path | None = None, job_glob: str | None = None) -> dict[str, Any]:
    batch_dir = batch_dir.expanduser().resolve()
    output_dir = (output_dir or batch_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = [_status_row(job) for job in _job_dirs(batch_dir, job_glob=job_glob)]
    if not rows and (batch_dir / "batch_manifest.json").exists():
        rows = [
            _manifest_row(row)
            for row in _batch_manifest_rows(batch_dir / "batch_manifest.json")
            if _matches_job_glob(Path(str(row.get("job_dir") or row.get("job_id") or "")), job_glob)
        ]
    table = output_dir / "batch_status.tsv"
    report = output_dir / "batch_status_report.md"
    _write_tsv(table, rows, BATCH_STATUS_COLUMNS)
    _write_report(report, rows=rows, batch_dir=batch_dir)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "batch_dir": str(batch_dir),
        "output_dir": str(output_dir),
        "job_glob": job_glob or "",
        "job_count": len(rows),
        "status_counts": {status: sum(1 for row in rows if row["overall_status"] == status) for status in sorted({row["overall_status"] for row in rows})},
        "delivery_allowed": False,
        "non_delivery_reason": "batch_status_report_only_not_delivery",
        "artifacts": {"batch_status_tsv": str(table), "batch_status_report": str(report)},
        "rows": rows,
    }
    manifest_path = output_dir / "batch_status_manifest.json"
    manifest["manifest_path"] = str(manifest_path)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def _job_dirs(batch_dir: Path, *, job_glob: str | None = None) -> list[Path]:
    if (batch_dir / "jobs").is_dir():
        return _filter_job_dirs(sorted(path for path in (batch_dir / "jobs").iterdir() if path.is_dir()), job_glob)
    if (batch_dir / "batch_manifest.json").exists():
        return _filter_job_dirs(
            [Path(str(row.get("job_dir"))) for row in _batch_manifest_rows(batch_dir / "batch_manifest.json") if row.get("job_dir")],
            job_glob,
        )
    return (
        _filter_job_dirs(sorted(path for path in batch_dir.iterdir() if path.is_dir() and (path / "job_manifest.json").exists()), job_glob)
        if batch_dir.is_dir()
        else []
    )


def _filter_job_dirs(paths: list[Path], job_glob: str | None) -> list[Path]:
    return [path for path in paths if _matches_job_glob(path, job_glob)]


def _matches_job_glob(path: Path, job_glob: str | None) -> bool:
    if not job_glob:
        return True
    name = path.name or str(path)
    return fnmatch.fnmatch(name, job_glob)


def _status_row(job_dir: Path) -> dict[str, str]:
    job_id = job_dir.name
    job_manifest = _read_json(job_dir / "job_manifest.json")
    job_id = str(job_manifest.get("job_id") or job_id)
    raw_status = _raw_upstream_status(job_dir)
    run_status = _run_status(job_dir)
    customer_status = _customer_package_status(job_dir)
    delivery_status = _delivery_check_status(job_dir)
    overall, stage, action = _overall(raw_status, run_status, customer_status, delivery_status)
    recovery = _ensure_failure_recovery(job_dir, job_id=job_id, overall=overall, stage=stage, action=action)
    return {
        "job_id": job_id,
        "job_dir": str(job_dir),
        "scaffold_status": "scaffolded" if job_manifest else "unknown",
        "raw_upstream_status": raw_status,
        "run_status": run_status,
        "customer_package_status": customer_status,
        "delivery_check_status": delivery_status,
        "overall_status": overall,
        "failure_stage": stage,
        "next_action": action,
        "failure_recovery": str(recovery),
    }


def _manifest_row(row: dict[str, Any]) -> dict[str, str]:
    job_dir = Path(str(row.get("job_dir") or ""))
    if job_dir.exists():
        return _status_row(job_dir)
    return {
        "job_id": str(row.get("job_id") or ""),
        "job_dir": str(job_dir),
        "scaffold_status": str(row.get("scaffold_status") or "not_scaffolded"),
        "raw_upstream_status": "not_checked",
        "run_status": "missing",
        "customer_package_status": "missing",
        "delivery_check_status": "missing",
        "overall_status": str(row.get("status") or "blocked"),
        "failure_stage": "prepare_batch",
        "next_action": str(row.get("next_action") or "fix_scaffold_blocker"),
        "failure_recovery": str(row.get("failure_recovery") or ""),
    }


def _batch_manifest_rows(path: Path) -> list[dict[str, Any]]:
    payload = _read_json(path)
    rows = payload.get("rows")
    return rows if isinstance(rows, list) else []


def _raw_upstream_status(job_dir: Path) -> str:
    manifests = sorted((job_dir / "raw_upstream").glob("*/raw_upstream_manifest.json")) if (job_dir / "raw_upstream").is_dir() else []
    if manifests:
        statuses = [_read_json(path).get("status", "unknown") for path in manifests]
        if "blocked" in statuses:
            return "blocked"
        if all(status == "ready" for status in statuses):
            return "ready"
        return "partial"
    evidence = job_dir / "raw_links" / "raw_upstream_evidence.tsv"
    if evidence.exists():
        rows = _read_tsv(evidence)
        statuses = {row.get("execution_status", "") for row in rows}
        if "blocked" in statuses:
            return "blocked"
        if "ready" in statuses:
            return "ready"
        return "handoff_or_not_executed"
    return "not_recorded"


def _run_status(job_dir: Path) -> str:
    pointer = job_dir / "deliverables" / "latest_run_pointer.json"
    if pointer.exists():
        payload = _read_json(pointer)
        run_dir = Path(str(payload.get("latest_run_dir") or ""))
        run_manifest = _read_json(run_dir / "run_manifest.json") if run_dir.exists() else {}
        return str(run_manifest.get("status") or "ready_pointer_without_manifest")
    latest = job_dir / "deliverables" / "latest_run_manifest.json"
    if latest.exists():
        return str(_read_json(latest).get("status") or "unknown")
    return "missing"


def _customer_package_status(job_dir: Path) -> str:
    package_dir = job_dir / "deliverables" / "customer"
    required = ("report.html", "methods.md", "delivery_index.tsv", "sanitization.tsv", "customer_package_manifest.tsv", "readme_for_customer.md")
    if not package_dir.exists():
        return "missing"
    missing = [name for name in required if not (package_dir / name).exists() or (package_dir / name).stat().st_size == 0]
    return "ready" if not missing else "partial"


def _delivery_check_status(job_dir: Path) -> str:
    path = job_dir / "deliverables" / "latest_delivery_check.json"
    if not path.exists():
        return "missing"
    return str(_read_json(path).get("status") or "unknown")


def _overall(raw_status: str, run_status: str, customer_status: str, delivery_status: str) -> tuple[str, str, str]:
    if delivery_status == "ready":
        return "ready_for_customer_delivery_rehearsal", "complete", "keep_evidence_current"
    if raw_status == "blocked":
        return "blocked", "raw_upstream", "fix_raw_upstream_then_rerun_slurm"
    if run_status in {"missing", "partial", "failed"}:
        return "blocked", "analysis_run", "rerun_or_recover_analysis_job"
    if customer_status in {"missing", "partial"}:
        return "blocked", "customer_package", "run_ultimate_customer_package"
    if delivery_status in {"missing", "blocked"}:
        return "blocked", "delivery_check", "run_or_fix_delivery_check"
    return "needs_review", "unknown", "inspect_job_artifacts"


def _ensure_failure_recovery(job_dir: Path, *, job_id: str, overall: str, stage: str, action: str) -> Path:
    path = job_dir / "failure_recovery.md"
    if path.exists() and path.stat().st_size > 0:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "# Failure recovery",
                "",
                f"- job_id: `{job_id}`",
                f"- status: `{overall}`",
                f"- failure_stage: `{stage}`",
                "- reusable_artifacts: `prepared job directory, run manifest if present, customer package if present`",
                f"- rerun_required: `{str(overall != 'ready_for_customer_delivery_rehearsal').lower()}`",
                f"- slurm_required: `{str(stage in {'raw_upstream', 'analysis_run'}).lower()}`",
                f"- minimal_fix_command: `{action}`",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _write_tsv(path: Path, rows: list[dict[str, Any]], fieldnames: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_report(path: Path, *, rows: list[dict[str, str]], batch_dir: Path) -> None:
    lines = [
        "# Ultimate batch status report",
        "",
        f"- batch_dir: `{batch_dir}`",
        f"- jobs_total: {len(rows)}",
        f"- ready_for_customer_delivery_rehearsal: {sum(1 for row in rows if row['overall_status'] == 'ready_for_customer_delivery_rehearsal')}",
        f"- blocked: {sum(1 for row in rows if row['overall_status'] == 'blocked')}",
        "",
        "| job_id | overall_status | raw_upstream | run | customer_package | delivery_check | next_action |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['job_id']} | {row['overall_status']} | {row['raw_upstream_status']} | {row['run_status']} | "
            f"{row['customer_package_status']} | {row['delivery_check_status']} | {row['next_action']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
