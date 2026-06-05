#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VALID_DELIVERY_SCOPES = {"internal_rehearsal", "customer_delivery"}
VALIDATION_NON_DELIVERY_SCOPES = {"not_recorded", "not_applicable", "validation_evidence_only"}
REHEARSAL_SCOPE = "internal_rehearsal"
STORAGE_BUDGET_GB = 500.0


def main() -> None:
    parser = argparse.ArgumentParser(description="Write an Ultimate v2 status report from local readiness artifacts.")
    parser.add_argument("--root", type=Path, required=True, help="Ultimate project root.")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory for v2_status_report.md.")
    parser.add_argument(
        "--storage-summary",
        type=Path,
        default=None,
        help="Optional storage summary JSON. Defaults to <root>/audits/storage_latest/storage_audit_summary.json.",
    )
    parser.add_argument("--pytest-status", required=True, help="Pytest status label, for example pass, fail, partial, not_run.")
    parser.add_argument("--pytest-note", required=True, help="Short pytest evidence note.")
    parser.add_argument(
        "--rehearsal-job",
        action="append",
        default=[],
        help="Repeatable job id, job directory, run directory, or run_manifest.json for production-style rehearsal checks.",
    )
    args = parser.parse_args()
    report_path = write_v2_status_report(
        root=args.root,
        output_dir=args.output_dir,
        storage_summary=args.storage_summary,
        pytest_status=args.pytest_status,
        pytest_note=args.pytest_note,
        rehearsal_jobs=args.rehearsal_job,
    )
    print(json.dumps({"v2_status_report": str(report_path)}, indent=2, ensure_ascii=False))


def write_v2_status_report(
    *,
    root: Path,
    output_dir: Path,
    storage_summary: Path | None,
    pytest_status: str,
    pytest_note: str,
    rehearsal_jobs: list[str],
) -> Path:
    root = root.resolve()
    if not root.exists() or not root.is_dir():
        raise SystemExit(f"root must be an existing directory: {root}")
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    inputs = {
        "validation_index": _read_tsv(root / "reports" / "validation_index" / "validation_index.tsv"),
        "validation_summary": _read_tsv(root / "reports" / "validation_index" / "validation_summary.tsv"),
        "production_audit": _read_json(root / "audits" / "production_latest" / "production_audit.json"),
        "module_maturity": _read_tsv(root / "audits" / "production_latest" / "module_maturity_table.tsv"),
        "storage_summary": _read_json(storage_summary or root / "audits" / "storage_latest" / "storage_audit_summary.json"),
    }
    status = _build_status(
        root=root,
        inputs=inputs,
        pytest_status=pytest_status,
        pytest_note=pytest_note,
        rehearsal_jobs=rehearsal_jobs,
    )
    report_path = output_dir / "v2_status_report.md"
    report_path.write_text(_render_report(status), encoding="utf-8")
    return report_path


def _build_status(
    *,
    root: Path,
    inputs: dict[str, Any],
    pytest_status: str,
    pytest_note: str,
    rehearsal_jobs: list[str],
) -> dict[str, Any]:
    validation_rows = inputs["validation_index"]["rows"]
    maturity_rows = inputs["module_maturity"]["rows"]
    production_audit = inputs["production_audit"]["data"] or {}
    storage_summary = inputs["storage_summary"]["data"] or {}
    job_summaries = [_job_summary(root, value) for value in rehearsal_jobs]
    if not job_summaries:
        job_summaries = [_job_summary(root, str(path)) for path in sorted((root / "jobs").glob("*/runs/*/run_manifest.json"))]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "inputs": {name: _input_state(payload) for name, payload in inputs.items()},
        "pytest": {"status": pytest_status, "note": pytest_note},
        "validated_modules": _validated_modules(maturity_rows, validation_rows),
        "partial_modules": _partial_modules(maturity_rows, validation_rows),
        "rehearsal_jobs": job_summaries,
        "rehearsal_ready": sum(1 for row in job_summaries if row["ready"]) >= 2,
        "delivery_scope": _delivery_scope_status(validation_rows, job_summaries),
        "storage": _storage_status(storage_summary),
        "production_audit_summary": _production_audit_summary(production_audit),
    }


def _validated_modules(maturity_rows: list[dict[str, str]], validation_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    by_module: dict[str, dict[str, str]] = {}
    for row in maturity_rows:
        module = str(row.get("module_name") or row.get("module") or "").strip()
        if not module:
            continue
        analysis_level = str(row.get("analysis_level", ""))
        public_validation = str(row.get("public_validation_status", ""))
        maturity = str(row.get("maturity_level", ""))
        if analysis_level == "validated_backend" or public_validation == "available" or "validated" in maturity:
            by_module[module] = {
                "module": module,
                "source": "module_maturity_table",
                "evidence": f"analysis_level={analysis_level or 'missing'}; public_validation_status={public_validation or 'missing'}",
            }
    for row in validation_rows:
        if row.get("analysis_level") != "validated_backend":
            continue
        if row.get("evidence_status") and row["evidence_status"] not in {"ready_real_evidence", "ready"}:
            continue
        for module in _split_modules(row.get("module") or row.get("module_names")):
            by_module.setdefault(
                module,
                {
                    "module": module,
                    "source": "validation_index",
                    "evidence": f"run={row.get('run_name', 'missing')}; order_readiness_status={row.get('order_readiness_status', 'missing')}",
                },
            )
    return [by_module[module] for module in sorted(by_module)]


def _partial_modules(maturity_rows: list[dict[str, str]], validation_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if maturity_rows:
        for row in maturity_rows:
            module = str(row.get("module_name") or row.get("module") or "").strip()
            if not module:
                continue
            analysis_level = str(row.get("analysis_level", ""))
            public_validation = str(row.get("public_validation_status", ""))
            if analysis_level == "validated_backend" or public_validation == "available":
                continue
            reason = (
                str(row.get("next_required_backend") or "").strip()
                or str(row.get("known_limitations") or "").strip()
                or f"public_validation_status={public_validation or 'missing'}"
            )
            rows.append({"module": module, "status": analysis_level or "partial", "reason": reason})
        return rows

    modules_with_validated = {module for row in validation_rows if row.get("analysis_level") == "validated_backend" for module in _split_modules(row.get("module"))}
    modules_with_gaps = []
    for row in validation_rows:
        modules = _split_modules(row.get("module"))
        if not modules:
            continue
        if row.get("analysis_level") == "validated_backend":
            continue
        reason = row.get("missing_or_gap") or row.get("next_action") or row.get("guard_status") or "not_validated_backend"
        for module in modules:
            if module not in modules_with_validated:
                modules_with_gaps.append({"module": module, "status": row.get("analysis_level") or "partial", "reason": reason})
    return modules_with_gaps


def _job_summary(root: Path, value: str) -> dict[str, Any]:
    requested = value
    manifest_path = _resolve_job_manifest(root, value)
    if manifest_path is None:
        return {"requested": requested, "manifest_path": "", "ready": False, "delivery_scope": "", "reason": "run_manifest_missing"}
    manifest = _read_json(manifest_path)["data"]
    if not isinstance(manifest, dict):
        return {"requested": requested, "manifest_path": str(manifest_path), "ready": False, "delivery_scope": "", "reason": "manifest_unreadable"}
    gate = manifest.get("delivery_gate") if isinstance(manifest.get("delivery_gate"), dict) else {}
    approval = manifest.get("production_approval") if isinstance(manifest.get("production_approval"), dict) else {}
    modules = manifest.get("modules") if isinstance(manifest.get("modules"), list) else []
    has_production_module = (
        manifest.get("analysis_level") == "production_backend"
        or manifest.get("delivery_allowed") is True
        or any(
            isinstance(module, dict)
            and (module.get("analysis_level") == "production_backend" or module.get("delivery_allowed") is True)
            for module in modules
        )
    )
    scope = str(approval.get("delivery_scope") or gate.get("delivery_scope") or manifest.get("delivery_scope") or "")
    checks = {
        "production_module": has_production_module,
        "approved": approval.get("approved") is True,
        "delivery_gate_ready": gate.get("status") == "ready" and gate.get("delivery_allowed") is True,
        "delivery_scope_internal_rehearsal": scope == REHEARSAL_SCOPE,
    }
    missing = [name for name, ok in checks.items() if not ok]
    return {
        "requested": requested,
        "manifest_path": str(manifest_path),
        "job_id": str(approval.get("project_id") or manifest_path.parents[2].name if "runs" in manifest_path.parts else manifest_path.parent.name),
        "ready": not missing,
        "delivery_scope": scope or "missing",
        "reason": "ready" if not missing else ",".join(missing),
    }


def _resolve_job_manifest(root: Path, value: str) -> Path | None:
    path = Path(value)
    candidates: list[Path] = []
    if path.is_absolute() or "/" in value:
        candidates.append(path)
    else:
        candidates.append(root / "jobs" / value)
    expanded: list[Path] = []
    for candidate in candidates:
        if candidate.name == "run_manifest.json":
            expanded.append(candidate)
        expanded.append(candidate / "run_manifest.json")
        expanded.extend(sorted((candidate / "runs").glob("*/run_manifest.json")))
        expanded.extend(sorted(candidate.glob("runs/*/run_manifest.json")))
    for candidate in expanded:
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()
    return None


def _delivery_scope_status(validation_rows: list[dict[str, str]], job_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    invalid_validation = []
    for row in validation_rows:
        scope = str(row.get("delivery_scope") or "").strip()
        if scope and scope not in {*VALIDATION_NON_DELIVERY_SCOPES, *VALID_DELIVERY_SCOPES}:
            invalid_validation.append(f"{row.get('run_name', 'unknown')}:{scope}")
    invalid_jobs = [
        f"{row.get('requested', 'unknown')}:{row.get('delivery_scope', 'missing')}"
        for row in job_summaries
        if row.get("delivery_scope") != REHEARSAL_SCOPE
    ]
    ready = not invalid_validation and not invalid_jobs
    notes = []
    if invalid_validation:
        notes.append("invalid_validation_scopes=" + ",".join(invalid_validation))
    if invalid_jobs:
        notes.append("rehearsal_scope_gaps=" + ",".join(invalid_jobs))
    if not notes:
        notes.append("validation scopes are empty/non-delivery or valid; rehearsal jobs use internal_rehearsal")
    return {"correct": ready, "note": "; ".join(notes)}


def _storage_status(summary: dict[str, Any]) -> dict[str, Any]:
    if not summary:
        return {"status": "missing", "used_gb": "", "budget_gb": STORAGE_BUDGET_GB, "note": "storage summary missing"}
    flattened = _flatten_dict(summary)
    budget = _first_float(flattened, ("budget_gb", "storage_budget_gb", "max_gb", "limit_gb")) or STORAGE_BUDGET_GB
    used = _first_float(
        flattened,
        (
            "ultimate_root_total_gb",
            "ultimate_total_gb",
            "project_total_gb",
            "total_used_gb",
            "used_gb",
            "total_gb",
            "root_gb",
            "usage_gb",
        ),
    )
    guard = str(flattened.get("guard_status") or flattened.get("status") or "").lower()
    if used is None:
        if guard in {"ok", "pass", "ready", "under_budget"}:
            return {"status": "partial_ok", "used_gb": "", "budget_gb": budget, "note": f"no used_gb field; guard_status={guard}"}
        return {"status": "partial", "used_gb": "", "budget_gb": budget, "note": "no total storage usage field found"}
    under = used <= budget
    return {
        "status": "under_budget" if under else "over_budget",
        "used_gb": round(used, 3),
        "budget_gb": round(budget, 3),
        "note": f"used_gb={used:.3f}; budget_gb={budget:.3f}",
    }


def _production_audit_summary(production_audit: dict[str, Any]) -> str:
    if not production_audit:
        return "missing"
    final = production_audit.get("final_acceptance_summary")
    validation = production_audit.get("validation_gap_summary")
    pieces = []
    if isinstance(final, dict):
        pieces.append("final_acceptance_summary=" + json.dumps(final, ensure_ascii=False, sort_keys=True))
    if isinstance(validation, dict):
        pieces.append("validation_gap_summary=" + json.dumps(validation, ensure_ascii=False, sort_keys=True))
    return "; ".join(pieces) if pieces else "present"


def _render_report(status: dict[str, Any]) -> str:
    lines = [
        "# Ultimate v2 Status Report",
        "",
        f"- generated_at: `{status['generated_at']}`",
        f"- root: `{status['root']}`",
        "",
        "## Input artifact status",
    ]
    for name, payload in status["inputs"].items():
        lines.append(f"- {name}: {payload}")
    lines.extend(
        [
            "",
            "## 1. Pytest status",
            f"- pytest_status: `{status['pytest']['status']}`",
            f"- pytest_note: {status['pytest']['note']}",
            "",
            "## 2. Modules at validated_backend",
        ]
    )
    lines.extend(_bullet_rows(status["validated_modules"], ("module", "source", "evidence"), empty="missing_or_none_reported"))
    lines.extend(["", "## 3. Partial or blocked modules and reasons"])
    lines.extend(_bullet_rows(status["partial_modules"], ("module", "status", "reason"), empty="missing_or_none_reported"))
    lines.extend(["", "## 4. Two production-style rehearsal jobs ready"])
    lines.append(f"- ready_for_two_rehearsals: `{str(status['rehearsal_ready']).lower()}`")
    lines.extend(_bullet_rows(status["rehearsal_jobs"], ("requested", "job_id", "ready", "delivery_scope", "reason"), empty="missing_or_none_reported"))
    lines.extend(
        [
            "",
            "## 5. delivery_scope correctness",
            f"- delivery_scope_correct: `{str(status['delivery_scope']['correct']).lower()}`",
            f"- note: {status['delivery_scope']['note']}",
            "",
            "## 6. Storage under 500G",
            f"- storage_status: `{status['storage']['status']}`",
            f"- used_gb: `{status['storage']['used_gb']}`",
            f"- budget_gb: `{status['storage']['budget_gb']}`",
            f"- note: {status['storage']['note']}",
            "",
            "## 7. Next minimal fixes",
        ]
    )
    lines.extend(_next_minimal_fixes(status))
    lines.extend(["", "## Production audit summary", f"- {status['production_audit_summary']}", ""])
    return "\n".join(lines)


def _next_minimal_fixes(status: dict[str, Any]) -> list[str]:
    fixes: list[str] = []
    if status["pytest"]["status"].lower() not in {"pass", "passed", "ok"}:
        fixes.append(f"- Resolve pytest status: {status['pytest']['status']} ({status['pytest']['note']})")
    if not status["rehearsal_ready"]:
        fixes.append("- Prepare or repair two internal_rehearsal production-style jobs with approval, delivery gate, and production_backend module evidence.")
    if not status["delivery_scope"]["correct"]:
        fixes.append("- Fix delivery_scope so rehearsal jobs use internal_rehearsal and validation rows do not carry invalid scopes.")
    if status["storage"]["status"] not in {"under_budget", "partial_ok"}:
        fixes.append("- Refresh or reduce storage usage until the Ultimate root is confirmed under the 500G budget.")
    for row in status["partial_modules"][:5]:
        fixes.append(f"- {row['module']}: {row['reason']}")
    if not fixes:
        fixes.append("- No minimal v2 fixes reported by this slice.")
    return fixes


def _bullet_rows(rows: list[dict[str, Any]], fields: tuple[str, ...], *, empty: str) -> list[str]:
    if not rows:
        return [f"- {empty}"]
    rendered = []
    for row in rows:
        parts = [f"{field}={row.get(field, '')}" for field in fields]
        rendered.append("- " + "; ".join(parts))
    return rendered


def _read_tsv(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "status": "missing", "rows": []}
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            return {"path": str(path), "status": "present", "rows": list(csv.DictReader(handle, delimiter="\t"))}
    except (OSError, csv.Error) as exc:
        return {"path": str(path), "status": f"unreadable:{type(exc).__name__}", "rows": []}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "status": "missing", "data": {}}
    try:
        return {"path": str(path), "status": "present", "data": json.loads(path.read_text(encoding="utf-8"))}
    except (OSError, json.JSONDecodeError) as exc:
        return {"path": str(path), "status": f"unreadable:{type(exc).__name__}", "data": {}}


def _input_state(payload: dict[str, Any]) -> str:
    if "rows" in payload:
        return f"{payload['status']} rows={len(payload['rows'])} path={payload['path']}"
    return f"{payload['status']} path={payload['path']}"


def _split_modules(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _flatten_dict(value: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    for key, item in value.items():
        name = f"{prefix}.{key}" if prefix else str(key)
        flattened[name] = item
        flattened[str(key)] = item
        if isinstance(item, dict):
            flattened.update(_flatten_dict(item, name))
    return flattened


def _first_float(values: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        if key not in values:
            continue
        try:
            return float(values[key])
        except (TypeError, ValueError):
            continue
    return None


if __name__ == "__main__":
    main()
