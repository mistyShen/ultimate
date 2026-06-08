from __future__ import annotations

import csv
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VALID_DELIVERY_SCOPES = {"internal_rehearsal", "customer_delivery"}
REQUIRED_CATEGORIES = ("figure", "table", "object", "report", "reproducible_code")


def run_delivery_check(run_dir: Path) -> dict[str, Any]:
    requested = run_dir.expanduser().resolve()
    resolved_run_dir, job_dir = _resolve_run_dir(requested)
    rows: list[dict[str, Any]] = []
    manifest_path = resolved_run_dir / "run_manifest.json"
    manifest = _read_json(manifest_path)

    _check(rows, "run_manifest", bool(manifest), manifest_path, "run_manifest.json must exist and be valid JSON")
    if manifest:
        _check(rows, "run_status_ready", manifest.get("status") == "ready", manifest_path, "run status must be ready")
        _check(rows, "analysis_level_production", manifest.get("analysis_level") == "production_backend", manifest_path, "delivery requires analysis_level=production_backend")
        _check(rows, "delivery_allowed_true", manifest.get("delivery_allowed") is True, manifest_path, "delivery_allowed must be true")
        _check(rows, "not_demo", manifest.get("is_demo") is False, manifest_path, "demo outputs cannot be delivered")
        _check(rows, "not_stub", manifest.get("is_stub") is False, manifest_path, "stub outputs cannot be delivered")
        _check(rows, "slurm_job_id", bool(str(manifest.get("slurm_job_id") or "")), manifest_path, "production delivery must record a Slurm job id")
        _check_production_approval(rows, manifest, manifest_path)
        _check_delivery_gate(rows, manifest, manifest_path)
        _check_module_guards(rows, manifest, manifest_path)

    report_html = resolved_run_dir / "reports" / "report.html"
    methods_md = resolved_run_dir / "reports" / "methods.md"
    delivery_index = resolved_run_dir / "delivery_index.tsv"
    software_versions = resolved_run_dir / "reproducible_code" / "software_versions.tsv"
    input_checksums = resolved_run_dir / "reproducible_code" / "input_checksums.tsv"
    rerun_script = resolved_run_dir / "reproducible_code" / "rerun.sh"
    advanced_manifest = resolved_run_dir / "results" / "tables" / "advanced_backend_execution_manifest.json"

    for check_id, path, note in (
        ("report_html", report_html, "reports/report.html must exist and be non-empty"),
        ("methods_md", methods_md, "reports/methods.md must exist and be non-empty"),
        ("delivery_index", delivery_index, "delivery_index.tsv must exist and be non-empty"),
        ("software_versions", software_versions, "software_versions.tsv must exist and be non-empty"),
        ("input_checksums", input_checksums, "input_checksums.tsv must exist and be non-empty"),
        ("rerun_script", rerun_script, "rerun.sh must exist and be non-empty"),
        ("advanced_backend_manifest", advanced_manifest, "advanced backend execution manifest must exist and be non-empty"),
    ):
        _check(rows, check_id, _nonempty(path), path, note)

    if _nonempty(delivery_index):
        _check_delivery_index(rows, delivery_index)
    if _nonempty(advanced_manifest):
        _check_advanced_backend_manifest(rows, advanced_manifest, manifest)
    if _nonempty(report_html) and _nonempty(methods_md):
        _check_report_warnings(rows, report_html, methods_md)

    status = "ready" if all(row["status"] == "pass" for row in rows) else "blocked"
    blockers = [row["check_id"] for row in rows if row["status"] != "pass"]
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requested_path": str(requested),
        "run_dir": str(resolved_run_dir),
        "job_dir": str(job_dir) if job_dir else "",
        "status": status,
        "delivery_allowed": status == "ready",
        "blockers": blockers,
        "summary": {
            "pass": sum(1 for row in rows if row["status"] == "pass"),
            "fail": sum(1 for row in rows if row["status"] != "pass"),
        },
        "checks": rows,
    }
    _write_outputs(resolved_run_dir, job_dir, payload)
    return payload


def _resolve_run_dir(path: Path) -> tuple[Path, Path | None]:
    if (path / "run_manifest.json").exists():
        return path, _prepared_job_dir(path)
    pointer = path / "deliverables" / "latest_run_pointer.json"
    if pointer.exists():
        payload = _read_json(pointer)
        latest = Path(str(payload.get("latest_run_dir") or ""))
        if latest.exists():
            return latest.resolve(), path
    manifest = path / "deliverables" / "latest_run_manifest.json"
    if manifest.exists():
        payload = _read_json(manifest)
        latest = Path(str(payload.get("output_dir") or ""))
        if latest.exists():
            return latest.resolve(), path
    return path, None


def _check_production_approval(rows: list[dict[str, Any]], manifest: dict[str, Any], path: Path) -> None:
    approval = manifest.get("production_approval") if isinstance(manifest.get("production_approval"), dict) else {}
    scope = str(approval.get("delivery_scope") or manifest.get("delivery_scope") or "")
    _check(rows, "production_approval_approved", approval.get("approved") is True, path, "production approval must be approved=true")
    _check(rows, "delivery_scope_valid", scope in VALID_DELIVERY_SCOPES, path, "delivery_scope must be internal_rehearsal or customer_delivery")
    for field in ("approved_by", "approved_at", "project_id", "input_path", "output_dir", "reason"):
        _check(rows, f"production_approval_{field}", bool(str(approval.get(field) or "")), path, f"production approval must include {field}")
    input_path = Path(str(approval.get("input_path") or ""))
    output_dir = Path(str(approval.get("output_dir") or ""))
    _check(rows, "production_approval_input_exists", bool(str(approval.get("input_path") or "")) and input_path.exists(), path, "production approval input_path must exist")
    _check(rows, "production_approval_output_matches_run", bool(str(output_dir)) and output_dir.resolve() == path.parent.resolve(), path, "production approval output_dir must match the checked run directory")


def _check_delivery_gate(rows: list[dict[str, Any]], manifest: dict[str, Any], path: Path) -> None:
    gate = manifest.get("delivery_gate") if isinstance(manifest.get("delivery_gate"), dict) else {}
    _check(rows, "delivery_gate_ready", gate.get("status") == "ready", path, "delivery gate status must be ready")
    _check(rows, "delivery_gate_allowed", gate.get("delivery_allowed") is True, path, "delivery gate must allow delivery")
    _check(rows, "delivery_gate_approval", gate.get("approval_status") == "approved", path, "delivery gate approval_status must be approved")
    _check(rows, "delivery_gate_no_blockers", not gate.get("blockers"), path, "delivery gate blockers must be empty")


def _check_module_guards(rows: list[dict[str, Any]], manifest: dict[str, Any], path: Path) -> None:
    modules = manifest.get("modules") if isinstance(manifest.get("modules"), list) else []
    _check(rows, "production_modules_present", bool(modules), path, "run manifest must contain module manifests")
    for module in modules:
        if not isinstance(module, dict):
            continue
        name = str(module.get("module") or "unknown")
        _check(rows, f"module_{name}_production", module.get("analysis_level") == "production_backend", path, f"module {name} must be production_backend")
        _check(rows, f"module_{name}_delivery_allowed", module.get("delivery_allowed") is True, path, f"module {name} must be delivery_allowed=true")
        _check(rows, f"module_{name}_not_demo", module.get("is_demo") is False, path, f"module {name} must not be demo")
        _check(rows, f"module_{name}_not_stub", module.get("is_stub") is False, path, f"module {name} must not be stub")


def _check_delivery_index(rows: list[dict[str, Any]], path: Path) -> None:
    indexed = _read_tsv(path)
    categories = {row.get("category", "") for row in indexed}
    for category in REQUIRED_CATEGORIES:
        _check(rows, f"delivery_index_has_{category}", category in categories, path, f"delivery index must include {category}")
    bad_rows = [row for row in indexed if not _nonempty(Path(str(row.get("path") or "")))]
    _check(rows, "delivery_index_paths_nonempty", not bad_rows, path, "all delivery index paths must exist and be non-empty")


def _check_advanced_backend_manifest(rows: list[dict[str, Any]], path: Path, manifest: dict[str, Any]) -> None:
    advanced = _read_json(path)
    _check(rows, "advanced_backend_manifest_ready", advanced.get("status") == "ready", path, "advanced backend manifest status must be ready")
    rows_payload = advanced.get("rows") if isinstance(advanced.get("rows"), list) else []
    module_names = {
        str(module.get("module") or "")
        for module in (manifest.get("modules") if isinstance(manifest.get("modules"), list) else [])
        if isinstance(module, dict)
    }
    if module_names & {"scrna", "scatac"}:
        _check(rows, "advanced_backend_rows_present", bool(rows_payload), path, "scrna/scatac delivery must include backend execution rows")
        unresolved = [
            row
            for row in rows_payload
            if str(row.get("execution_status") or "") == "registered_active"
            and str(row.get("backend_registry_status") or "").startswith("fully_automatic")
        ]
        _check(rows, "advanced_backend_no_unresolved_active_rows", not unresolved, path, "fully automatic active backend rows must be executed or explicitly skipped")


def _check_report_warnings(rows: list[dict[str, Any]], report_html: Path, methods_md: Path) -> None:
    text = (report_html.read_text(encoding="utf-8", errors="ignore") + "\n" + methods_md.read_text(encoding="utf-8", errors="ignore")).lower()
    _check(rows, "report_has_analysis_level", "analysis_level" in text, report_html, "report/methods must show analysis_level")
    _check(rows, "report_has_delivery_gate", "delivery_allowed" in text or "交付许可" in text, report_html, "report/methods must show delivery permission")
    warning_tokens = ("warn", "警示", "不得", "不能", "not direct", "not causal", "不是")
    _check(rows, "report_has_interpretation_warning", any(token in text for token in warning_tokens), report_html, "report/methods must include interpretation or delivery warnings")


def _write_outputs(run_dir: Path, job_dir: Path | None, payload: dict[str, Any]) -> None:
    reports = run_dir / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    json_path = reports / "delivery_check.json"
    tsv_path = reports / "delivery_check.tsv"
    payload["manifest_path"] = str(json_path)
    payload["table_path"] = str(tsv_path)
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_tsv(tsv_path, payload["checks"])
    if job_dir:
        deliverables = job_dir / "deliverables"
        deliverables.mkdir(parents=True, exist_ok=True)
        shutil.copy2(json_path, deliverables / "latest_delivery_check.json")
        shutil.copy2(tsv_path, deliverables / "latest_delivery_check.tsv")


def _check(rows: list[dict[str, Any]], check_id: str, ok: bool, path: Path, message: str) -> None:
    rows.append(
        {
            "check_id": check_id,
            "status": "pass" if ok else "fail",
            "path": str(path),
            "message": "" if ok else message,
        }
    )


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _read_tsv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = ("check_id", "status", "path", "message")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _nonempty(path: Path) -> bool:
    return path.exists() and path.is_file() and path.stat().st_size > 0


def _prepared_job_dir(run_dir: Path) -> Path | None:
    if run_dir.parent.name != "runs":
        return None
    job_dir = run_dir.parent.parent
    return job_dir if (job_dir / "job_manifest.json").exists() else None
