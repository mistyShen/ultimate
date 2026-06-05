from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ultimate.analysis_levels import require_real_evidence
from ultimate.constants import MODULE_ORDER


INDEX_FIELDS = (
    "run_name",
    "run_kind",
    "module",
    "status",
    "guard_status",
    "evidence_status",
    "order_readiness_status",
    "analysis_level",
    "is_demo",
    "is_stub",
    "delivery_allowed",
    "validation_evidence_allowed",
    "non_delivery_reason",
    "slurm_job_id",
    "input",
    "dataset",
    "n_cells",
    "n_genes",
    "n_spots",
    "n_peaks",
    "n_clonotypes",
    "n_clusters",
    "n_figures",
    "n_tables",
    "object_keys",
    "module_names",
    "module_count",
    "ready_module_count",
    "has_report_html",
    "has_methods_md",
    "has_slurm_evidence",
    "production_approval_status",
    "delivery_gate_status",
    "delivery_gate_allowed",
    "delivery_gate_validation_evidence_allowed",
    "delivery_gate_validation_allowed",
    "delivery_gate_approval_status",
    "delivery_scope",
    "delivery_gate_blockers",
    "artifact_status",
    "raw_qc_manifest",
    "log_status",
    "run_dir",
    "manifest_path",
    "report_html",
    "methods_md",
    "skip_reason",
    "missing_or_gap",
    "next_action",
    "guard_missing_fields",
    "guard_invalid_fields",
)

SUMMARY_FIELDS = ("metric", "value")

REQUIRED_GUARD_FIELDS = (
    "analysis_level",
    "is_demo",
    "is_stub",
    "delivery_allowed",
    "validation_evidence_allowed",
    "non_delivery_reason",
)

VALID_ANALYSIS_LEVELS = {"demo_result", "smoke_backend", "validated_backend", "production_backend"}


def build_validation_index(root: Path, output_dir: Path | None = None, validations_dir: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    validations_dir = (validations_dir or root / "validations").resolve()
    output_dir = (output_dir or root / "reports" / "validation_index").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = [_row_from_manifest(path) for path in _iter_validation_manifests(root=root, validations_dir=validations_dir)]
    rows = [row for row in rows if row is not None]

    tsv_path = output_dir / "validation_index.tsv"
    json_path = output_dir / "validation_index.json"
    summary_path = output_dir / "validation_summary.tsv"
    md_path = output_dir / "report.md"
    html_path = output_dir / "report.html"
    _write_tsv(tsv_path, rows)
    json_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    summary = _summary(rows)
    _write_summary_tsv(summary_path, summary)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "validations_dir": str(validations_dir),
        "output_dir": str(output_dir),
        "validation_index_tsv": str(tsv_path),
        "validation_index_json": str(json_path),
        "validation_summary_tsv": str(summary_path),
        "report_md": str(md_path),
        "report_html": str(html_path),
        "summary": summary,
        "n_runs": len(rows),
    }
    (output_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_reports(md_path, html_path, rows, manifest)
    return manifest


def _iter_validation_manifests(*, root: Path, validations_dir: Path) -> list[Path]:
    paths = set(validations_dir.glob("*/run_manifest.json"))
    paths.update((root / "validation_runs").glob("*/*/run_manifest.json"))
    paths.update((root / "validations" / "bulk_demo_python" / "project" / "runs").glob("*/run_manifest.json"))
    paths.update((root / "jobs").glob("*/runs/*/run_manifest.json"))
    return sorted(path for path in paths if path.exists())


def _row_from_manifest(path: Path) -> dict[str, str] | None:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    run_dir = path.parent
    reports = run_dir / "reports" / "report.html"
    methods = run_dir / "reports" / "methods.md"
    raw_qc_manifest = _first_manifest(run_dir / "raw_qc", "raw_qc_manifest.json") or _first_manifest(run_dir, "module_qc_manifest.json")
    modules = manifest.get("modules") if isinstance(manifest.get("modules"), list) else []
    module_names = [
        str(module.get("module") or module.get("module_name") or "")
        for module in modules
        if isinstance(module, dict) and (module.get("module") or module.get("module_name"))
    ]
    module_label = _module_label(manifest, module_names, run_dir)
    ready_module_count = _ready_module_count(manifest, modules)
    slurm = manifest.get("slurm") if isinstance(manifest.get("slurm"), dict) else {}
    slurm_job_id = str(manifest.get("slurm_job_id") or slurm.get("slurm_job_id") or slurm.get("job_id") or "")
    guard_status, guard_missing, guard_invalid = _guard_status(manifest)
    evidence_status = _evidence_status(manifest, guard_status)
    approval_status = _production_approval_status(manifest)
    delivery_gate = _delivery_gate_fields(manifest)
    artifact_status, artifact_gaps = _artifact_status(manifest, run_dir)
    log_status = _log_status(run_dir)
    order_readiness, missing_or_gap, next_action = _order_readiness(
        manifest=manifest,
        guard_status=guard_status,
        evidence_status=evidence_status,
        approval_status=approval_status,
        artifact_status=artifact_status,
        artifact_gaps=artifact_gaps,
        has_report=reports.exists() and reports.stat().st_size > 0,
        has_methods=methods.exists() and methods.stat().st_size > 0,
        has_slurm=bool(slurm_job_id),
    )
    input_value = (
        manifest.get("input_h5ad")
        or manifest.get("input_h5")
        or manifest.get("input_dir")
        or manifest.get("input_path")
        or manifest.get("source_root")
        or ""
    )
    row = {
        "run_name": run_dir.name,
        "run_kind": _run_kind(path, manifest),
        "module": module_label,
        "status": str(manifest.get("status", "")),
        "guard_status": guard_status,
        "evidence_status": evidence_status,
        "order_readiness_status": order_readiness,
        "analysis_level": str(manifest.get("analysis_level", "")),
        "is_demo": _stringify_bool(manifest.get("is_demo", "")),
        "is_stub": _stringify_bool(manifest.get("is_stub", "")),
        "delivery_allowed": _stringify_bool(manifest.get("delivery_allowed", "")),
        "validation_evidence_allowed": _stringify_bool(manifest.get("validation_evidence_allowed", "")),
        "non_delivery_reason": str(manifest.get("non_delivery_reason", "")),
        "slurm_job_id": slurm_job_id,
        "input": str(input_value),
        "dataset": str(manifest.get("dataset", manifest.get("dataset_label", ""))),
        "n_cells": _stringify(manifest.get("n_cells")),
        "n_genes": _stringify(manifest.get("n_genes")),
        "n_spots": _stringify(manifest.get("n_spots")),
        "n_peaks": _stringify(manifest.get("n_peaks")),
        "n_clonotypes": _stringify(manifest.get("n_clonotypes")),
        "n_clusters": _stringify(manifest.get("n_clusters")),
        "n_figures": str(_artifact_count(manifest, "figures", run_dir / "results" / "figures")),
        "n_tables": str(_artifact_count(manifest, "tables", run_dir / "results" / "tables")),
        "object_keys": ",".join(sorted((manifest.get("objects") or {}).keys())),
        "module_names": ",".join(module_names),
        "module_count": _stringify(((manifest.get("summary") or {}).get("module_count") if isinstance(manifest.get("summary"), dict) else None) or len(modules)),
        "ready_module_count": _stringify(ready_module_count),
        "has_report_html": _stringify_bool(reports.exists() and reports.stat().st_size > 0),
        "has_methods_md": _stringify_bool(methods.exists() and methods.stat().st_size > 0),
        "has_slurm_evidence": _stringify_bool(bool(slurm_job_id)),
        "production_approval_status": approval_status,
        "delivery_scope": _delivery_scope(manifest),
        **delivery_gate,
        "artifact_status": artifact_status,
        "raw_qc_manifest": str(raw_qc_manifest) if raw_qc_manifest else "",
        "log_status": log_status,
        "run_dir": str(run_dir),
        "manifest_path": str(path),
        "report_html": str(reports) if reports.exists() else "",
        "methods_md": str(methods) if methods.exists() else "",
        "skip_reason": str(manifest.get("skip_reason", "")),
        "missing_or_gap": ";".join(missing_or_gap),
        "next_action": next_action,
        "guard_missing_fields": ",".join(guard_missing),
        "guard_invalid_fields": ",".join(guard_invalid),
    }
    return row


def _stringify(value: Any) -> str:
    return "" if value is None else str(value)


def _stringify_bool(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else str(value)


def _run_kind(path: Path, manifest: dict[str, Any]) -> str:
    parts = path.parts
    if "jobs" in parts and "runs" in parts:
        scope = _delivery_scope(manifest)
        if scope == "internal_rehearsal":
            return "production_rehearsal"
        if scope == "customer_delivery":
            return "customer_delivery"
        return "prepared_job"
    if "validation_runs" in parts:
        return "validation_runs"
    if "bulk_demo_python" in parts:
        return "bulk_demo_python"
    if "validations" in parts:
        return "validations"
    return "unknown"


def _module_label(manifest: dict[str, Any], module_names: list[str], run_dir: Path) -> str:
    direct = manifest.get("module") or manifest.get("module_name")
    if direct:
        return str(direct)
    if module_names:
        return ",".join(module_names)
    inferred = _infer_module_from_run_dir(run_dir)
    if inferred:
        return inferred
    return ""


def _infer_module_from_run_dir(run_dir: Path) -> str:
    run_name = run_dir.name
    parent_name = run_dir.parent.name
    if parent_name == "scrna_mvp_validation":
        return "scrna"
    if "bulk_demo_python" in run_dir.parts:
        return ",".join(MODULE_ORDER)
    aliases = {
        "rnaseq": "rnaseq",
        "bulk_rnaseq": "rnaseq",
        "scrna": "scrna",
        "scatac": "scatac",
        "multiome": "multiome",
        "vdj": "vdj",
        "spatial": "spatial",
        "cite_seq": "cite_seq",
        "scdna": "scdna",
        "mtdna": "mtdna",
        "method_tools": "method_tools",
        "tumor_sc": "tumor_sc",
        "perturb_seq": "perturb_seq",
        "hto_demux": "hto_demux",
        "genotype_demux": "genotype_demux",
    }
    normalized = run_name.removeprefix("slurm_")
    for token, module in aliases.items():
        if normalized == token or normalized.startswith(f"{token}_"):
            return module
    return ""


def _artifact_count(manifest: dict[str, Any], key: str, directory: Path) -> int:
    values = manifest.get(key)
    if isinstance(values, list):
        return sum(1 for value in values if _nonempty(_resolve_artifact_path(directory.parents[1], value)))
    if isinstance(values, dict):
        return sum(1 for value in values.values() if _nonempty(_resolve_artifact_path(directory.parents[1], value)))
    if directory.exists():
        return sum(1 for item in directory.rglob("*") if item.is_file() and item.stat().st_size > 0)
    return 0


def _first_manifest(root: Path, filename: str) -> Path | None:
    if not root.exists():
        return None
    matches = sorted(path for path in root.rglob(filename) if path.is_file() and path.stat().st_size > 0)
    return matches[0] if matches else None


def _artifact_status(manifest: dict[str, Any], run_dir: Path) -> tuple[str, list[str]]:
    gaps: list[str] = []
    for key in ("figures", "tables"):
        values = manifest.get(key)
        if not isinstance(values, list):
            continue
        for value in values:
            artifact_path = _resolve_artifact_path(run_dir, value)
            if not artifact_path.exists():
                gaps.append(f"missing_{key}:{value}")
            elif artifact_path.is_file() and artifact_path.stat().st_size == 0:
                gaps.append(f"empty_{key}:{value}")
    objects = manifest.get("objects")
    if isinstance(objects, dict):
        for name, value in objects.items():
            artifact_path = _resolve_artifact_path(run_dir, value)
            if not artifact_path.exists():
                gaps.append(f"missing_object:{name}")
            elif artifact_path.is_file() and artifact_path.stat().st_size == 0:
                gaps.append(f"empty_object:{name}")
    if gaps:
        return "missing_or_empty_artifacts", gaps
    if any(isinstance(manifest.get(key), expected) for key, expected in (("figures", list), ("tables", list), ("objects", dict))):
        return "ready", gaps
    return "not_checked", gaps


def _resolve_artifact_path(run_dir: Path, value: Any) -> Path:
    path = Path(str(value))
    if path.is_absolute():
        return path
    return run_dir / path


def _nonempty(path: Path) -> bool:
    try:
        return path.exists() and path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _log_status(run_dir: Path) -> str:
    logs_dir = run_dir / "logs"
    if not logs_dir.exists():
        return "missing"
    log_files = [path for path in logs_dir.rglob("*") if path.is_file() and path.stat().st_size > 0]
    if not log_files:
        return "missing"
    for path in log_files[:50]:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            continue
        if any(marker in text for marker in ("traceback", " error", "failed", "exception")):
            return "error_detected"
    return "present"


def _ready_module_count(manifest: dict[str, Any], modules: list[Any]) -> int:
    summary = manifest.get("summary")
    if isinstance(summary, dict) and summary.get("ready_module_count") is not None:
        try:
            return int(summary["ready_module_count"])
        except (TypeError, ValueError):
            return 0
    ready_count = 0
    for module in modules:
        if not isinstance(module, dict):
            continue
        status = str(module.get("status") or "")
        if status and not status.startswith(("partial", "missing", "failed")):
            ready_count += 1
    return ready_count


def _production_approval_status(manifest: dict[str, Any]) -> str:
    approval = manifest.get("production_approval")
    if manifest.get("analysis_level") == "production_backend" or manifest.get("delivery_allowed") is True:
        if not isinstance(approval, dict) or not approval:
            return "missing"
        required = ("approved_by", "approved_at", "project_id", "input_path", "output_dir", "delivery_scope", "reason")
        missing = [field for field in required if approval.get(field) in (None, "")]
        if approval.get("delivery_scope") not in {None, "", "internal_rehearsal", "customer_delivery"}:
            return "invalid_delivery_scope"
        if approval.get("approved") is True and not missing:
            return "approved"
        if approval.get("approved") is True and missing:
            return "invalid_missing_fields:" + ",".join(missing)
        return "invalid_or_unapproved"
    if not isinstance(approval, dict) or not approval:
        return "not_applicable"
    if approval.get("approved") is True:
        return "approved"
    return "present_not_approved"


def _delivery_scope(manifest: dict[str, Any]) -> str:
    gate = manifest.get("delivery_gate")
    if isinstance(gate, dict) and gate.get("delivery_scope"):
        return str(gate["delivery_scope"])
    approval = manifest.get("production_approval")
    if isinstance(approval, dict) and approval.get("delivery_scope"):
        return str(approval["delivery_scope"])
    if manifest.get("delivery_scope"):
        return str(manifest["delivery_scope"])
    return ""


def _delivery_gate_fields(manifest: dict[str, Any]) -> dict[str, str]:
    gate = manifest.get("delivery_gate")
    if not isinstance(gate, dict):
        return {
            "delivery_gate_status": "",
            "delivery_gate_allowed": "",
            "delivery_gate_validation_evidence_allowed": "",
            "delivery_gate_validation_allowed": "",
            "delivery_gate_approval_status": "",
            "delivery_gate_blockers": "",
        }
    blockers = gate.get("blockers")
    if isinstance(blockers, list):
        blocker_text = ";".join(str(item) for item in blockers)
    else:
        blocker_text = str(blockers or gate.get("non_delivery_reason") or "")
    return {
        "delivery_gate_status": str(gate.get("status", "")),
        "delivery_gate_allowed": _stringify_bool(gate.get("delivery_allowed", "")),
        "delivery_gate_validation_evidence_allowed": _stringify_bool(gate.get("validation_evidence_allowed", "")),
        "delivery_gate_validation_allowed": _stringify_bool(gate.get("validation_evidence_allowed", "")),
        "delivery_gate_approval_status": str(gate.get("approval_status", "")),
        "delivery_gate_blockers": blocker_text,
    }


def _evidence_status(manifest: dict[str, Any], guard_status: str) -> str:
    if guard_status != "ready":
        return "guard_not_ready"
    ready, note = require_real_evidence(manifest)
    if ready:
        return note
    if str(manifest.get("status", "")).lower() != "ready":
        return "manifest_not_ready"
    return "not_evidence"


def _order_readiness(
    *,
    manifest: dict[str, Any],
    guard_status: str,
    evidence_status: str,
    approval_status: str,
    artifact_status: str,
    artifact_gaps: list[str],
    has_report: bool,
    has_methods: bool,
    has_slurm: bool,
) -> tuple[str, list[str], str]:
    gaps: list[str] = []
    if str(manifest.get("status", "")).lower() != "ready":
        gaps.append(f"status={manifest.get('status', '') or 'missing'}")
    if guard_status != "ready":
        gaps.append(f"guard_status={guard_status}")
    if artifact_status == "missing_or_empty_artifacts":
        gaps.extend(artifact_gaps[:10])
    if artifact_status == "not_checked":
        gaps.append("artifact_status=not_checked")
    if not has_report:
        gaps.append("missing_report_html")
    if not has_methods:
        gaps.append("missing_methods_md")
    if manifest.get("delivery_allowed") is True:
        if approval_status != "approved":
            gaps.append(f"production_approval={approval_status}")
        if not gaps:
            return "ready_for_delivery", gaps, "ready"
        return "needs_manual_review", gaps, _next_action_from_gaps(gaps)
    if manifest.get("validation_evidence_allowed") is True and evidence_status == "ready_real_evidence":
        if not has_slurm:
            gaps.append("missing_slurm_job_id")
        if not gaps:
            return "ready_for_validation_evidence", gaps, "ready"
        return "needs_manual_review", gaps, _next_action_from_gaps(gaps)
    if evidence_status == "not_evidence":
        gaps.append(f"analysis_level={manifest.get('analysis_level', '') or 'missing'}")
    return "not_ready", gaps, _next_action_from_gaps(gaps)


def _next_action_from_gaps(gaps: list[str]) -> str:
    if not gaps:
        return "ready"
    joined = ";".join(gaps)
    if "guard_status" in joined:
        return "add_guard_fields"
    if "production_approval" in joined:
        return "add_production_approval"
    if "missing_report_html" in joined or "missing_methods_md" in joined:
        return "rebuild_report"
    if "missing_slurm_job_id" in joined:
        return "record_slurm_job_id"
    if "missing_" in joined or "empty_" in joined:
        return "check_missing_artifacts"
    if "analysis_level" in joined:
        return "run_public_or_internal_validation"
    return "manual_review"


def _guard_status(manifest: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    missing = [field for field in REQUIRED_GUARD_FIELDS if field not in manifest]
    invalid = _invalid_guard_fields(manifest)
    if missing:
        return "missing_guard_fields", missing, invalid
    if invalid:
        return "invalid_guard_fields", missing, invalid
    return "ready", missing, invalid


def _invalid_guard_fields(manifest: dict[str, Any]) -> list[str]:
    invalid: list[str] = []
    if manifest.get("analysis_level") not in VALID_ANALYSIS_LEVELS:
        invalid.append("analysis_level")
    for field in ("is_demo", "is_stub", "delivery_allowed", "validation_evidence_allowed"):
        if not isinstance(manifest.get(field), bool):
            invalid.append(field)
    if manifest.get("delivery_allowed") is True and manifest.get("analysis_level") != "production_backend":
        invalid.append("delivery_allowed_requires_production_backend")
    if manifest.get("validation_evidence_allowed") is True and manifest.get("analysis_level") not in {
        "validated_backend",
        "production_backend",
    }:
        invalid.append("validation_evidence_requires_validated_or_production")
    if manifest.get("delivery_allowed") is False and not manifest.get("non_delivery_reason"):
        invalid.append("non_delivery_reason")
    return invalid


def _summary(rows: list[dict[str, str]]) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    analysis_level_counts: dict[str, int] = {}
    guard_counts: dict[str, int] = {}
    run_kind_counts: dict[str, int] = {}
    delivery_counts: dict[str, int] = {}
    evidence_counts: dict[str, int] = {}
    approval_counts: dict[str, int] = {}
    delivery_gate_status_counts: dict[str, int] = {}
    delivery_gate_allowed_counts: dict[str, int] = {}
    evidence_status_counts: dict[str, int] = {}
    order_readiness_counts: dict[str, int] = {}
    artifact_status_counts: dict[str, int] = {}
    module_counts: dict[str, int] = {}
    for row in rows:
        status = row["status"] or "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1
        analysis_level = row["analysis_level"] or "missing"
        analysis_level_counts[analysis_level] = analysis_level_counts.get(analysis_level, 0) + 1
        guard = row["guard_status"] or "unknown"
        guard_counts[guard] = guard_counts.get(guard, 0) + 1
        kind = row["run_kind"] or "unknown"
        run_kind_counts[kind] = run_kind_counts.get(kind, 0) + 1
        delivery = row["delivery_allowed"] or "missing"
        delivery_counts[delivery] = delivery_counts.get(delivery, 0) + 1
        evidence = row["validation_evidence_allowed"] or "missing"
        evidence_counts[evidence] = evidence_counts.get(evidence, 0) + 1
        approval = row["production_approval_status"] or "unknown"
        approval_counts[approval] = approval_counts.get(approval, 0) + 1
        gate_status = row["delivery_gate_status"] or "not_recorded"
        delivery_gate_status_counts[gate_status] = delivery_gate_status_counts.get(gate_status, 0) + 1
        gate_delivery = row["delivery_gate_allowed"] or "not_recorded"
        delivery_gate_allowed_counts[gate_delivery] = delivery_gate_allowed_counts.get(gate_delivery, 0) + 1
        evidence_status = row["evidence_status"] or "unknown"
        evidence_status_counts[evidence_status] = evidence_status_counts.get(evidence_status, 0) + 1
        order_status = row["order_readiness_status"] or "unknown"
        order_readiness_counts[order_status] = order_readiness_counts.get(order_status, 0) + 1
        artifact_status = row["artifact_status"] or "unknown"
        artifact_status_counts[artifact_status] = artifact_status_counts.get(artifact_status, 0) + 1
        module_value = row["module"] or "unknown"
        for module in module_value.split(","):
            module = module.strip() or "unknown"
            module_counts[module] = module_counts.get(module, 0) + 1
    ready_validation_evidence = sum(
        1
        for row in rows
        if row["status"] == "ready" and row["guard_status"] == "ready" and row["validation_evidence_allowed"] == "true"
    )
    production_delivery_runs = sum(
        1
        for row in rows
        if row["analysis_level"] == "production_backend" and row["delivery_allowed"] == "true" and row["production_approval_status"] == "approved"
    )
    slurm_job_id_missing = sum(1 for row in rows if row["status"] == "ready" and not row["slurm_job_id"])
    report_missing = sum(1 for row in rows if row["has_report_html"] != "true")
    methods_missing = sum(1 for row in rows if row["has_methods_md"] != "true")
    guard_not_ready = sum(1 for row in rows if row["guard_status"] != "ready")
    return {
        "total_runs": len(rows),
        "ready_runs": status_counts.get("ready", 0),
        "partial_runs": sum(count for status, count in status_counts.items() if status.startswith("partial")),
        "guard_ready": guard_counts.get("ready", 0),
        "guard_not_ready": guard_not_ready,
        "ready_validation_evidence": ready_validation_evidence,
        "production_delivery_runs": production_delivery_runs,
        "delivery_allowed_true": delivery_counts.get("true", 0),
        "validation_evidence_allowed_true": evidence_counts.get("true", 0),
        "ready_for_validation_evidence": order_readiness_counts.get("ready_for_validation_evidence", 0),
        "ready_for_delivery": order_readiness_counts.get("ready_for_delivery", 0),
        "slurm_job_id_missing_for_ready_runs": slurm_job_id_missing,
        "report_html_missing": report_missing,
        "methods_md_missing": methods_missing,
        "status_counts": status_counts,
        "analysis_level_counts": analysis_level_counts,
        "guard_status_counts": guard_counts,
        "run_kind_counts": run_kind_counts,
        "delivery_allowed_counts": delivery_counts,
        "validation_evidence_allowed_counts": evidence_counts,
        "production_approval_counts": approval_counts,
        "delivery_gate_status_counts": delivery_gate_status_counts,
        "delivery_gate_allowed_counts": delivery_gate_allowed_counts,
        "evidence_status_counts": evidence_status_counts,
        "order_readiness_status_counts": order_readiness_counts,
        "artifact_status_counts": artifact_status_counts,
        "module_counts": module_counts,
    }


def _write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=INDEX_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _write_summary_tsv(path: Path, summary: dict[str, Any]) -> None:
    rows = []
    for key, value in summary.items():
        if isinstance(value, dict):
            for nested_key, nested_value in value.items():
                rows.append({"metric": f"{key}.{nested_key}", "value": str(nested_value)})
        else:
            rows.append({"metric": key, "value": str(value)})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _write_reports(md_path: Path, html_path: Path, rows: list[dict[str, str]], manifest: dict[str, Any]) -> None:
    lines = [
        "# Ultimate 验证结果总索引",
        "",
        f"生成时间：{manifest['generated_at']}",
        f"验证目录：`{manifest['validations_dir']}`",
        "",
        "## 摘要",
        f"- runs: {manifest['summary']['total_runs']}",
        f"- ready runs: {manifest['summary']['ready_runs']}",
        f"- guard ready: {manifest['summary']['guard_ready']}",
        f"- ready validation evidence: {manifest['summary']['ready_validation_evidence']}",
        f"- production delivery runs: {manifest['summary']['production_delivery_runs']}",
        f"- delivery gate ready: {manifest['summary']['delivery_gate_status_counts'].get('ready', 0)}",
        f"- delivery gate blocked: {manifest['summary']['delivery_gate_status_counts'].get('blocked', 0)}",
        f"- ready for validation evidence: {manifest['summary']['ready_for_validation_evidence']}",
        f"- ready for delivery: {manifest['summary']['ready_for_delivery']}",
        f"- ready runs missing Slurm job id: {manifest['summary']['slurm_job_id_missing_for_ready_runs']}",
        f"- report.html missing: {manifest['summary']['report_html_missing']}",
        f"- methods.md missing: {manifest['summary']['methods_md_missing']}",
        "",
        "## Analysis Level",
        *[f"- {level}: {count}" for level, count in manifest["summary"]["analysis_level_counts"].items()],
        "",
        "## Guard Status",
        *[f"- {status}: {count}" for status, count in manifest["summary"]["guard_status_counts"].items()],
        "",
        "| Run | 状态 | 图 | 表 | 对象 | 规模 |",
        "|---|---|---:|---:|---|---|",
    ]
    for row in rows:
        scale = ", ".join(
            f"{label}={row[key]}"
            for label, key in (
                ("cells", "n_cells"),
                ("genes", "n_genes"),
                ("spots", "n_spots"),
                ("peaks", "n_peaks"),
                ("clonotypes", "n_clonotypes"),
                ("clusters", "n_clusters"),
            )
            if row[key]
        )
        lines.append(
            f"| {row['run_name']} | `{row['status']}` / `{row['guard_status']}` / `{row['order_readiness_status']}` | {row['n_figures']} | {row['n_tables']} | {row['object_keys'] or '-'} | {scale or '-'} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    html_rows = "\n".join(
        "<tr>"
        f"<td>{row['run_name']}</td><td><code>{row['status']}</code></td><td><code>{row['guard_status']}</code></td>"
        f"<td>{row['analysis_level'] or '-'}</td><td>{row['order_readiness_status'] or '-'}</td><td>{row['delivery_allowed'] or '-'}</td>"
        f"<td>{row['delivery_gate_status'] or '-'}</td><td>{row['n_figures']}</td><td>{row['n_tables']}</td><td>{row['object_keys'] or '-'}</td>"
        f"<td>{row['run_dir']}</td>"
        "</tr>"
        for row in rows
    )
    html_path.write_text(
        f"""<!doctype html>
<html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><title>Ultimate 验证结果总索引</title>
<style>body{{font-family:sans-serif;margin:32px}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ddd;padding:6px}}th{{background:#f6f8fa}}</style>
</head><body><h1>Ultimate 验证结果总索引</h1><p>生成时间：{manifest['generated_at']}</p>
<p>验证目录：<code>{manifest['validations_dir']}</code></p>
<h2>摘要</h2><ul>
<li>runs: {manifest['summary']['total_runs']}</li>
<li>ready runs: {manifest['summary']['ready_runs']}</li>
<li>guard ready: {manifest['summary']['guard_ready']}</li>
<li>ready validation evidence: {manifest['summary']['ready_validation_evidence']}</li>
<li>production delivery runs: {manifest['summary']['production_delivery_runs']}</li>
<li>delivery gate ready: {manifest['summary']['delivery_gate_status_counts'].get('ready', 0)}</li>
<li>delivery gate blocked: {manifest['summary']['delivery_gate_status_counts'].get('blocked', 0)}</li>
<li>ready for validation evidence: {manifest['summary']['ready_for_validation_evidence']}</li>
<li>ready for delivery: {manifest['summary']['ready_for_delivery']}</li>
<li>ready runs missing Slurm job id: {manifest['summary']['slurm_job_id_missing_for_ready_runs']}</li>
</ul>
<table><thead><tr><th>Run</th><th>状态</th><th>Guard</th><th>analysis_level</th><th>order_readiness</th><th>delivery_allowed</th><th>delivery_gate</th><th>图</th><th>表</th><th>对象</th><th>目录</th></tr></thead>
<tbody>{html_rows}</tbody></table></body></html>""",
        encoding="utf-8",
    )
