from __future__ import annotations

import csv
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VALID_DELIVERY_SCOPES = {"internal_rehearsal", "customer_delivery"}
REQUIRED_CATEGORIES = ("figure", "table", "object", "report", "reproducible_code")
CUSTOMER_PACKAGE_FILES = (
    "report.html",
    "methods.md",
    "delivery_index.tsv",
    "sanitization.tsv",
    "customer_delivery_sanitization.tsv",
    "customer_package_manifest.tsv",
    "readme_for_customer.md",
)
CUSTOMER_FORBIDDEN_TOKENS = (
    "/shared",
    "/Users",
    "raw_links",
    "production_approval",
    "production approval",
    "SLURM_JOB_ID",
    "slurm_job_id",
    ".conda",
    "/jobs/",
)
CUSTOMER_FORBIDDEN_RAW_PATH_HINTS = (
    "raw data path",
    "raw_data_path",
    "raw input path",
    "raw_input_path",
    "raw fastq path",
    "raw_fastq_path",
    "raw bam path",
    "raw_bam_path",
    "raw data dir",
    "raw_data_dir",
    "raw_dir",
    "input_path",
    "source_raw_path",
)
CUSTOMER_TEXT_SUFFIXES = {
    ".csv",
    ".html",
    ".htm",
    ".json",
    ".log",
    ".md",
    ".tsv",
    ".txt",
    ".svg",
    ".yaml",
    ".yml",
}
CUSTOMER_WARNING_TOKENS = (
    "warning",
    "warn",
    "interpretation",
    "boundary",
    "not causal",
    "not direct",
    "not mechanism",
    "not proof",
    "警示",
    "解释边界",
    "不是",
    "不能",
    "不得",
)


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
    repro_manifest = resolved_run_dir / "reproducible_code" / "repro_manifest.json"
    repro_readme = resolved_run_dir / "reproducible_code" / "README.md"
    advanced_manifest = resolved_run_dir / "results" / "tables" / "advanced_backend_execution_manifest.json"
    figure_manifest = resolved_run_dir / "results" / "tables" / "figure_manifest.tsv"
    layout_qc = resolved_run_dir / "results" / "tables" / "layout_qc.tsv"

    for check_id, path, note in (
        ("report_html", report_html, "reports/report.html must exist and be non-empty"),
        ("methods_md", methods_md, "reports/methods.md must exist and be non-empty"),
        ("delivery_index", delivery_index, "delivery_index.tsv must exist and be non-empty"),
        ("software_versions", software_versions, "software_versions.tsv must exist and be non-empty"),
        ("input_checksums", input_checksums, "input_checksums.tsv must exist and be non-empty"),
        ("rerun_script", rerun_script, "rerun.sh must exist and be non-empty"),
        ("repro_manifest", repro_manifest, "repro_manifest.json must exist and be non-empty"),
        ("repro_readme", repro_readme, "reproducible README.md must exist and be non-empty"),
        ("advanced_backend_manifest", advanced_manifest, "advanced backend execution manifest must exist and be non-empty"),
        ("figure_manifest", figure_manifest, "figure_manifest.tsv must exist and be non-empty"),
        ("layout_qc", layout_qc, "layout_qc.tsv must exist and be non-empty"),
    ):
        _check(rows, check_id, _nonempty(path), path, note)

    if _nonempty(delivery_index):
        _check_delivery_index(rows, delivery_index)
    if _nonempty(advanced_manifest):
        _check_advanced_backend_manifest(rows, advanced_manifest, manifest)
    if _nonempty(repro_manifest):
        _check_repro_manifest(rows, repro_manifest)
    if _nonempty(figure_manifest):
        _check_figure_manifest(rows, figure_manifest)
    if _nonempty(layout_qc):
        _check_layout_qc(rows, layout_qc)
    if _nonempty(report_html) and _nonempty(methods_md):
        _check_report_warnings(rows, report_html, methods_md)
    if manifest and _delivery_scope(manifest) == "customer_delivery":
        _check_customer_delivery_package(rows, resolved_run_dir, job_dir)

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
    mode = str(approval.get("delivery_mode") or manifest.get("delivery_mode") or "")
    _check(rows, "production_approval_approved", approval.get("approved") is True, path, "production approval must be approved=true")
    _check(rows, "delivery_scope_valid", scope in VALID_DELIVERY_SCOPES, path, "delivery_scope must be internal_rehearsal or customer_delivery")
    if scope == "customer_delivery":
        _check(rows, "delivery_mode_customer_declared", bool(mode), path, "customer_delivery packages must declare delivery_mode")
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
    _check(rows, "advanced_backend_rows_present", bool(rows_payload), path, "production delivery must include backend execution rows")
    unresolved = [
        row
        for row in rows_payload
        if str(row.get("execution_status") or "") == "registered_active"
        and str(row.get("backend_registry_status") or "").startswith("fully_automatic")
    ]
    _check(rows, "advanced_backend_no_unresolved_active_rows", not unresolved, path, "fully automatic active backend rows must be executed or explicitly skipped")
    unexplained_skips = [
        row
        for row in rows_payload
        if str(row.get("execution_status") or "") in {"skipped", "partial", "blocked"}
        and not str(row.get("skip_reason") or "").strip()
    ]
    _check(rows, "advanced_backend_skips_explained", not unexplained_skips, path, "skipped/partial backend rows must include skip_reason")
    automatic_rows = [
        row
        for row in rows_payload
        if str(row.get("backend_registry_status") or "").startswith("fully_automatic")
        or str(row.get("execution_status") or "") in {"ready", "skipped"}
    ]
    missing_warnings = [
        row
        for row in automatic_rows
        if not str(row.get("interpretation_warning") or "").strip()
        and str(row.get("execution_status") or "") == "ready"
    ]
    _check(rows, "advanced_backend_warnings_present", not missing_warnings, path, "ready backend rows must include interpretation warnings")


def _check_figure_manifest(rows: list[dict[str, Any]], path: Path) -> None:
    indexed = _read_tsv(path)
    _check(rows, "figure_manifest_rows_present", bool(indexed), path, "figure manifest must include at least one figure")
    bad_paths = [row for row in indexed if not _nonempty(Path(str(row.get("path") or "")))]
    _check(rows, "figure_manifest_paths_nonempty", not bad_paths, path, "all figure manifest paths must exist and be non-empty")


def _check_layout_qc(rows: list[dict[str, Any]], path: Path) -> None:
    indexed = _read_tsv(path)
    _check(rows, "layout_qc_rows_present", bool(indexed), path, "layout QC must include at least one figure")
    failed = [row for row in indexed if str(row.get("layout_status") or "") == "layout_failed"]
    warnings = [row for row in indexed if str(row.get("layout_status") or "") == "layout_warning"]
    _check(rows, "layout_qc_no_failed", not failed, path, "layout QC must not contain layout_failed rows")
    _check(rows, "layout_qc_no_warnings", not warnings, path, "layout QC must not contain layout_warning rows for delivery")


def _check_repro_manifest(rows: list[dict[str, Any]], path: Path) -> None:
    payload = _read_json(path)
    _check(rows, "repro_manifest_valid", bool(payload), path, "repro manifest must be valid JSON")
    for key in ("rerun_script", "software_versions", "input_checksums", "delivery_index"):
        target = Path(str(payload.get(key) or ""))
        _check(rows, f"repro_manifest_{key}", _nonempty(target), path, f"repro manifest {key} must point to a non-empty file")


def _check_report_warnings(rows: list[dict[str, Any]], report_html: Path, methods_md: Path) -> None:
    text = (report_html.read_text(encoding="utf-8", errors="ignore") + "\n" + methods_md.read_text(encoding="utf-8", errors="ignore")).lower()
    _check(rows, "report_has_analysis_level", "analysis_level" in text, report_html, "report/methods must show analysis_level")
    _check(rows, "report_has_delivery_gate", "delivery_allowed" in text or "交付许可" in text, report_html, "report/methods must show delivery permission")
    warning_tokens = ("warn", "警示", "不得", "不能", "not direct", "not causal", "不是")
    _check(rows, "report_has_interpretation_warning", any(token in text for token in warning_tokens), report_html, "report/methods must include interpretation or delivery warnings")


def _delivery_scope(manifest: dict[str, Any]) -> str:
    approval = manifest.get("production_approval") if isinstance(manifest.get("production_approval"), dict) else {}
    gate = manifest.get("delivery_gate") if isinstance(manifest.get("delivery_gate"), dict) else {}
    return str(gate.get("delivery_scope") or approval.get("delivery_scope") or manifest.get("delivery_scope") or "")


def _check_customer_delivery_package(rows: list[dict[str, Any]], run_dir: Path, job_dir: Path | None) -> None:
    """Require a sanitized customer-facing package for true customer delivery.

    Internal run manifests and reproducibility packages intentionally retain
    paths and Slurm evidence. Customer delivery therefore needs a separate
    sanitized surface that can be checked without weakening internal provenance.
    """
    customer_dir = (job_dir / "deliverables" / "customer") if job_dir else (run_dir / "deliverables" / "customer")
    _check(rows, "customer_package_dir", customer_dir.exists(), customer_dir, "customer_delivery requires deliverables/customer")
    package_paths = [customer_dir / name for name in CUSTOMER_PACKAGE_FILES]
    for path in package_paths:
        _check(rows, f"customer_package_{path.name}", _nonempty(path), path, f"customer package must include non-empty {path.name}")

    for name in ("figures", "tables"):
        directory = customer_dir / name
        _check(rows, f"customer_package_{name}_dir", directory.is_dir(), directory, f"customer package must include {name}/")
        _check(rows, f"customer_package_{name}_nonempty", _has_nonempty_file(directory), directory, f"customer package {name}/ must contain at least one non-empty file")

    visible_paths = _customer_visible_text_files(customer_dir)
    leaks = _customer_visible_leaks(visible_paths)
    _check(rows, "customer_package_no_internal_path_leaks", not leaks, customer_dir, "customer-facing package must not expose server paths, raw_links, approval files, or Slurm internals")
    _check(
        rows,
        "customer_package_interpretation_warning",
        _customer_has_interpretation_warning(customer_dir),
        customer_dir,
        "customer-facing package must include an interpretation warning or boundary statement",
    )
    sanitization_path = customer_dir / "sanitization.tsv"
    legacy_sanitization_path = customer_dir / "customer_delivery_sanitization.tsv"
    if not sanitization_path.exists() and legacy_sanitization_path.exists():
        sanitization_path = legacy_sanitization_path
    if _nonempty(sanitization_path):
        scan_rows = _read_tsv(sanitization_path)
        _check(rows, "customer_sanitization_rows_present", bool(scan_rows), sanitization_path, "customer sanitization table must include checks")
        failed = [row for row in scan_rows if str(row.get("status") or "").lower() not in {"pass", "passed", "ready"}]
        _check(rows, "customer_sanitization_all_pass", not failed, sanitization_path, "customer sanitization checks must all pass")
        expected = {"internal_path_exposure", "raw_path_exposure", "sensitive_metadata", "interpretation_warning"}
        present = {str(row.get("check_id") or "") for row in scan_rows}
        _check(rows, "customer_sanitization_required_checks", expected.issubset(present), sanitization_path, "customer sanitization table must cover internal paths, raw paths, sensitive metadata, and warnings")
    package_manifest = customer_dir / "customer_package_manifest.tsv"
    if _nonempty(package_manifest):
        package_rows = _read_tsv(package_manifest)
        _check(rows, "customer_package_manifest_rows_present", bool(package_rows), package_manifest, "customer package manifest must list customer-visible files")
        bad_visibility = [
            row
            for row in package_rows
            if str(row.get("customer_visible") or "").lower() not in {"true", "yes", "1"}
            or str(row.get("sanitized") or "").lower() not in {"true", "yes", "1", "pass", "passed"}
        ]
        _check(rows, "customer_package_manifest_visible_sanitized", not bad_visibility, package_manifest, "customer package manifest rows must be customer-visible and sanitized")


def _has_nonempty_file(directory: Path) -> bool:
    return directory.is_dir() and any(path.is_file() and path.stat().st_size > 0 for path in directory.rglob("*"))


def _customer_visible_text_files(customer_dir: Path) -> list[Path]:
    if not customer_dir.is_dir():
        return []
    return sorted(
        path
        for path in customer_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in CUSTOMER_TEXT_SUFFIXES
    )


def _customer_visible_leaks(paths: list[Path]) -> list[str]:
    leaks: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="ignore")
        lower_text = text.lower()
        for token in CUSTOMER_FORBIDDEN_TOKENS:
            if token.lower() in lower_text:
                leaks.append(f"{path}:{token}")
        for token in CUSTOMER_FORBIDDEN_RAW_PATH_HINTS:
            if token in lower_text:
                leaks.append(f"{path}:{token}")
    return leaks


def _customer_has_interpretation_warning(customer_dir: Path) -> bool:
    paths = [customer_dir / "report.html", customer_dir / "methods.md", customer_dir / "readme_for_customer.md"]
    text = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in paths if path.exists()).lower()
    return any(token in text for token in CUSTOMER_WARNING_TOKENS)


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
