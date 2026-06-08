#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


READY_ORDER_VALUES = {"yes", "ready", "ready_basic", "true"}
READY_EVIDENCE_VALUES = {"ready", "ready_real_evidence"}
READY_ORDER_READINESS_VALUES = {"ready_for_delivery", "ready_for_validation_evidence", "ready"}
VALID_REHEARSAL_SCOPES = {"internal_rehearsal", "customer_delivery"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Write an Ultimate V3.3 order-ready preset report.")
    parser.add_argument("--root", type=Path, required=True, help="Ultimate project root.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for v3_3_order_ready_report.md. Defaults to <root>/reports.",
    )
    parser.add_argument(
        "--validation-index",
        type=Path,
        default=None,
        help="Optional validation_index.tsv. Defaults to <root>/reports/validation_index/validation_index.tsv.",
    )
    parser.add_argument(
        "--production-audit",
        type=Path,
        default=None,
        help=(
            "Optional production_audit.json. Defaults to <root>/audits/production_latest/production_audit.json, "
            "then <root>/audits/local_production_check/production_audit.json."
        ),
    )
    args = parser.parse_args()
    report_path = write_v3_3_order_ready_report(
        root=args.root,
        output_dir=args.output_dir,
        validation_index=args.validation_index,
        production_audit=args.production_audit,
    )
    print(json.dumps({"v3_3_order_ready_report": str(report_path)}, indent=2, ensure_ascii=False))


def write_v3_3_order_ready_report(
    *,
    root: Path,
    output_dir: Path | None = None,
    validation_index: Path | None = None,
    production_audit: Path | None = None,
) -> Path:
    root = root.resolve()
    if not root.exists() or not root.is_dir():
        raise SystemExit(f"root must be an existing directory: {root}")
    output_dir = (output_dir or root / "reports").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    audit_path = _resolve_production_audit(root, production_audit)
    audit = _read_json(audit_path)
    validation_path = (validation_index or root / "reports" / "validation_index" / "validation_index.tsv").resolve()
    validation_rows = _read_tsv(validation_path)

    backend_rows = _read_tsv(_path_from_audit(audit, "backend_maturity_table"))
    backend_source = "backend_maturity_table"
    order_rows = _read_tsv(_path_from_audit(audit, "order_readiness_checklist"))
    capability_rows = _read_tsv(_path_from_audit(audit, "capability_matrix"))
    if not backend_rows:
        backend_rows = _fallback_standard_backend_rows(capability_rows=capability_rows, order_rows=order_rows)
        backend_source = "audit_standard_fallback" if backend_rows else "missing"
    rehearsal_rows = _collect_rehearsal_rows(root=root, validation_rows=validation_rows)

    status = _build_status(
        root=root,
        audit_path=audit_path,
        validation_path=validation_path,
        audit=audit,
        backend_rows=backend_rows,
        order_rows=order_rows,
        capability_rows=capability_rows,
        validation_rows=validation_rows,
        rehearsal_rows=rehearsal_rows,
        backend_source=backend_source,
    )
    report_path = output_dir / "v3_3_order_ready_report.md"
    report_path.write_text(_render_report(status), encoding="utf-8")
    return report_path


def _resolve_production_audit(root: Path, override: Path | None) -> Path:
    if override is not None:
        return override.resolve()
    candidates = (
        root / "audits" / "production_latest" / "production_audit.json",
        root / "audits" / "local_production_check" / "production_audit.json",
    )
    for path in candidates:
        if path.exists():
            return path.resolve()
    return candidates[0].resolve()


def _path_from_audit(audit: dict[str, Any], key: str) -> Path:
    value = audit.get(key)
    if not value:
        return Path("__missing__")
    return Path(str(value)).expanduser().resolve()


def _build_status(
    *,
    root: Path,
    audit_path: Path,
    validation_path: Path,
    audit: dict[str, Any],
    backend_rows: list[dict[str, str]],
    order_rows: list[dict[str, str]],
    capability_rows: list[dict[str, str]],
    validation_rows: list[dict[str, str]],
    rehearsal_rows: list[dict[str, str]],
    backend_source: str,
) -> dict[str, Any]:
    order_by_module = {row.get("module", ""): row for row in order_rows if row.get("module")}
    capability_by_module = {row.get("module", ""): row for row in capability_rows if row.get("module")}
    validation_by_module = _validation_evidence_by_module(validation_rows)
    rehearsal_by_module = _rehearsal_evidence_by_module(rehearsal_rows)
    preset_rows = _classify_presets(
        backend_rows=backend_rows,
        order_by_module=order_by_module,
        capability_by_module=capability_by_module,
        validation_by_module=validation_by_module,
        rehearsal_by_module=rehearsal_by_module,
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "audit_path": str(audit_path),
        "validation_path": str(validation_path),
        "input_counts": {
            "backend_rows": len(backend_rows),
            "order_readiness_rows": len(order_rows),
            "capability_rows": len(capability_rows),
            "validation_rows": len(validation_rows),
            "rehearsal_rows": len(rehearsal_rows),
        },
        "backend_source": backend_source,
        "audit_summary": audit.get("summary") if isinstance(audit.get("summary"), dict) else {},
        "preset_rows": preset_rows,
        "bucket_counts": _count_by(preset_rows, "status"),
        "rehearsal_summary": _rehearsal_summary(rehearsal_rows),
    }


def _classify_presets(
    *,
    backend_rows: list[dict[str, str]],
    order_by_module: dict[str, dict[str, str]],
    capability_by_module: dict[str, dict[str, str]],
    validation_by_module: dict[str, dict[str, Any]],
    rehearsal_by_module: dict[str, dict[str, Any]],
) -> list[dict[str, str]]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in backend_rows:
        module = str(row.get("module") or "").strip()
        preset = str(row.get("preset") or "standard").strip() or "standard"
        if not module:
            continue
        grouped.setdefault((module, preset), []).append(row)

    classified = []
    for (module, preset), rows in sorted(grouped.items()):
        statuses = sorted({str(row.get("backend_status") or "missing") for row in rows})
        backend_ids = ",".join(str(row.get("backend_id") or "") for row in rows if row.get("backend_id"))
        order_row = order_by_module.get(module, {})
        capability = capability_by_module.get(module, {})
        validation = validation_by_module.get(module, {"ready": False, "note": "validation_index_missing"})
        rehearsal = rehearsal_by_module.get(module, {"ready": False, "note": "no_ready_rehearsal"})
        production_status = str(capability.get("production_status") or "")
        basic_order = str(order_row.get("ready_for_basic_order") or "").lower()
        blockers = _preset_blockers(
            rows=rows,
            basic_order=basic_order,
            production_status=production_status,
            validation_ready=bool(validation["ready"]),
            rehearsal_ready=bool(rehearsal["ready"]),
        )
        classified.append(
            {
                "module": module,
                "preset": preset,
                "status": _bucket_from_blockers(blockers),
                "backend_ids": backend_ids,
                "backend_statuses": ",".join(statuses),
                "basic_order": basic_order or "missing",
                "production_status": production_status or "missing",
                "validation_evidence": str(validation["note"]),
                "rehearsal_evidence": str(rehearsal["note"]),
                "reason": "; ".join(blockers) if blockers else "order_ready",
            }
        )
    return classified


def _fallback_standard_backend_rows(
    *, capability_rows: list[dict[str, str]], order_rows: list[dict[str, str]]
) -> list[dict[str, str]]:
    modules = sorted(
        {
            str(row.get("module") or "").strip()
            for row in [*capability_rows, *order_rows]
            if str(row.get("module") or "").strip()
        }
    )
    capability_by_module = {row.get("module", ""): row for row in capability_rows if row.get("module")}
    rows = []
    for module in modules:
        capability = capability_by_module.get(module, {})
        production_status = str(capability.get("production_status") or "")
        rows.append(
            {
                "module": module,
                "backend_id": f"{module}.standard.audit_fallback",
                "preset": "standard",
                "tool": "production_audit",
                "backend_status": "missing_backend_maturity_table",
                "production_allowed": "false",
                "requires_license": "false",
                "skip_reason": "backend_maturity_table_missing",
                "next_required_evidence": production_status or "backend_maturity_table_missing",
            }
        )
    return rows


def _preset_blockers(
    *,
    rows: list[dict[str, str]],
    basic_order: str,
    production_status: str,
    validation_ready: bool,
    rehearsal_ready: bool,
) -> list[str]:
    blockers: list[str] = []
    statuses = [str(row.get("backend_status") or "") for row in rows]
    if any(_truthy(row.get("requires_license")) or status == "licensed_path_detection" for row, status in zip(rows, statuses)):
        blockers.append("needs_license")
    if any(status == "handoff_ready" for status in statuses):
        blockers.append("needs_handoff")
    if not any(status.startswith("fully_automatic") and _truthy(row.get("production_allowed")) for row, status in zip(rows, statuses)):
        blockers.append("no_production_allowed_automatic_backend")
    if basic_order not in READY_ORDER_VALUES and production_status not in READY_ORDER_VALUES:
        blockers.append(f"basic_order_not_ready:{basic_order or production_status or 'missing'}")
    if not validation_ready:
        blockers.append("validation_index_evidence_missing")
    if not rehearsal_ready:
        blockers.append("delivery_rehearsal_evidence_missing")
    if any(status.startswith("planned") or status in {"missing", "", "missing_backend_maturity_table"} for status in statuses):
        blockers.append("manual_review_backend_status")
    return blockers


def _bucket_from_blockers(blockers: list[str]) -> str:
    if not blockers:
        return "order_ready"
    if "needs_license" in blockers:
        return "needs_license"
    if "needs_handoff" in blockers:
        return "needs_handoff"
    return "needs_manual_review"


def _validation_evidence_by_module(rows: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    evidence: dict[str, dict[str, Any]] = {}
    for row in rows:
        ready = (
            row.get("guard_status") == "ready"
            and row.get("evidence_status") in READY_EVIDENCE_VALUES
            and row.get("order_readiness_status") in READY_ORDER_READINESS_VALUES
        )
        note = (
            f"run={row.get('run_name', 'unknown')}; "
            f"order_readiness_status={row.get('order_readiness_status', 'missing')}; "
            f"evidence_status={row.get('evidence_status', 'missing')}"
        )
        for module in _split_modules(row.get("module") or row.get("module_names")):
            current = evidence.get(module)
            if current is None or (ready and not current["ready"]):
                evidence[module] = {"ready": ready, "note": note}
    return evidence


def _collect_rehearsal_rows(*, root: Path, validation_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    rows = [_enrich_rehearsal_row(root, row) for row in validation_rows if row.get("run_kind") == "production_rehearsal"]
    seen = {row.get("manifest_path") for row in rows if row.get("manifest_path")}
    for manifest_path in sorted((root / "jobs").glob("*/runs/*/run_manifest.json")):
        resolved = str(manifest_path.resolve())
        if resolved in seen:
            continue
        row = _rehearsal_row_from_manifest(manifest_path)
        if row:
            rows.append(row)
    return rows


def _enrich_rehearsal_row(root: Path, row: dict[str, str]) -> dict[str, str]:
    enriched = dict(row)
    manifest_path = Path(str(enriched.get("manifest_path") or ""))
    if not manifest_path.is_absolute():
        manifest_path = root / manifest_path
    delivery_check = _delivery_check_for_manifest(manifest_path)
    enriched["delivery_check_status"] = str(delivery_check.get("status") or enriched.get("delivery_check_status") or "missing")
    enriched["delivery_check_allowed"] = str(
        delivery_check.get("delivery_allowed")
        if "delivery_allowed" in delivery_check
        else enriched.get("delivery_check_allowed") or "false"
    ).lower()
    return enriched


def _rehearsal_row_from_manifest(path: Path) -> dict[str, str] | None:
    manifest = _read_json(path)
    if not manifest:
        return None
    gate = manifest.get("delivery_gate") if isinstance(manifest.get("delivery_gate"), dict) else {}
    approval = manifest.get("production_approval") if isinstance(manifest.get("production_approval"), dict) else {}
    modules = manifest.get("modules") if isinstance(manifest.get("modules"), list) else []
    module_names = [
        str(module.get("module") or module.get("module_name") or "")
        for module in modules
        if isinstance(module, dict) and (module.get("module") or module.get("module_name"))
    ]
    if not module_names and manifest.get("module"):
        module_names = [str(manifest.get("module"))]
    scope = str(approval.get("delivery_scope") or gate.get("delivery_scope") or manifest.get("delivery_scope") or "")
    delivery_allowed = gate.get("delivery_allowed") is True or manifest.get("delivery_allowed") is True
    delivery_check = _delivery_check_for_manifest(path)
    return {
        "run_name": path.parent.name,
        "run_kind": "production_rehearsal",
        "module": ",".join(module_names),
        "delivery_scope": scope,
        "production_approval_status": "approved" if approval.get("approved") is True else "missing",
        "delivery_gate_status": str(gate.get("status") or ""),
        "delivery_gate_allowed": "true" if delivery_allowed else "false",
        "delivery_check_status": str(delivery_check.get("status") or "missing"),
        "delivery_check_allowed": str(delivery_check.get("delivery_allowed") is True).lower(),
        "manifest_path": str(path),
    }


def _delivery_check_for_manifest(manifest_path: Path) -> dict[str, Any]:
    if not manifest_path.exists():
        return {}
    candidates = [manifest_path.parent / "reports" / "delivery_check.json"]
    if manifest_path.parent.parent.name == "runs":
        job_dir = manifest_path.parent.parent.parent
        candidates.append(job_dir / "deliverables" / "latest_delivery_check.json")
    for candidate in candidates:
        payload = _read_json(candidate)
        if payload:
            return payload
    return {}


def _rehearsal_evidence_by_module(rows: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    evidence: dict[str, dict[str, Any]] = {}
    for row in rows:
        ready = (
            row.get("production_approval_status") in {"approved", "ready"}
            and row.get("delivery_gate_status") == "ready"
            and str(row.get("delivery_gate_allowed")).lower() == "true"
            and row.get("delivery_check_status") == "ready"
            and str(row.get("delivery_check_allowed")).lower() == "true"
            and row.get("delivery_scope") in VALID_REHEARSAL_SCOPES
        )
        note = (
            f"run={row.get('run_name', 'unknown')}; "
            f"scope={row.get('delivery_scope', 'missing')}; "
            f"delivery_gate_status={row.get('delivery_gate_status', 'missing')}; "
            f"delivery_check_status={row.get('delivery_check_status', 'missing')}"
        )
        for module in _split_modules(row.get("module") or row.get("module_names")):
            current = evidence.get(module)
            if current is None or (ready and not current["ready"]):
                evidence[module] = {"ready": ready, "note": note}
    return evidence


def _rehearsal_summary(rows: list[dict[str, str]]) -> dict[str, int]:
    ready = 0
    for row in rows:
        if (
            row.get("production_approval_status") in {"approved", "ready"}
            and row.get("delivery_gate_status") == "ready"
            and str(row.get("delivery_gate_allowed")).lower() == "true"
            and row.get("delivery_check_status") == "ready"
            and str(row.get("delivery_check_allowed")).lower() == "true"
            and row.get("delivery_scope") in VALID_REHEARSAL_SCOPES
        ):
            ready += 1
    return {"total": len(rows), "ready": ready}


def _render_report(status: dict[str, Any]) -> str:
    rows = status["preset_rows"]
    lines = [
        "# Ultimate V3.3 Order-Ready Report",
        "",
        f"- generated_at: `{status['generated_at']}`",
        f"- root: `{status['root']}`",
        f"- production_audit: `{status['audit_path']}`",
        f"- validation_index: `{status['validation_path']}`",
        f"- backend_source: `{status['backend_source']}`",
        f"- input_counts: `{json.dumps(status['input_counts'], ensure_ascii=False, sort_keys=True)}`",
        f"- audit_summary: `{json.dumps(status['audit_summary'], ensure_ascii=False, sort_keys=True)}`",
        f"- bucket_counts: `{json.dumps(status['bucket_counts'], ensure_ascii=False, sort_keys=True)}`",
        f"- rehearsal_summary: `{json.dumps(status['rehearsal_summary'], ensure_ascii=False, sort_keys=True)}`",
        "",
        "## Order-ready presets",
    ]
    lines.extend(_preset_lines(rows, "order_ready", "none"))
    lines.extend(["", "## Presets needing handoff"])
    lines.extend(_preset_lines(rows, "needs_handoff", "none"))
    lines.extend(["", "## Presets needing license"])
    lines.extend(_preset_lines(rows, "needs_license", "none"))
    lines.extend(["", "## Presets needing manual review"])
    lines.extend(_preset_lines(rows, "needs_manual_review", "none"))
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "- `order_ready` means the preset has an automatic production-allowed backend, basic order readiness, validation-index evidence, production rehearsal evidence, and a passing `delivery-check` in the artifacts read by this report.",
            "- `needs_handoff` means the preset depends on a handoff/adaptor path before it can be treated as directly order-ready.",
            "- `needs_license` means a licensed tool path or license-gated backend is involved and must be reviewed before order intake.",
            "- `needs_manual_review` means at least one required evidence source is missing, partial, planned, or otherwise not ready.",
            "",
        ]
    )
    return "\n".join(lines)


def _preset_lines(rows: list[dict[str, str]], bucket: str, empty: str) -> list[str]:
    selected = [row for row in rows if row["status"] == bucket]
    if not selected:
        return [f"- {empty}"]
    return [
        (
            f"- `{row['module']}` / `{row['preset']}`: {row['reason']} "
            f"(backends=`{row['backend_ids'] or 'missing'}`; backend_statuses=`{row['backend_statuses']}`; "
            f"validation=`{row['validation_evidence']}`; rehearsal=`{row['rehearsal_evidence']}`)"
        )
        for row in selected
    ]


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
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle, delimiter="\t"))
    except (OSError, csv.Error):
        return []


def _split_modules(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _count_by(rows: list[dict[str, str]], column: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = row.get(column) or "missing"
        counts[key] = counts.get(key, 0) + 1
    return counts


if __name__ == "__main__":
    main()
