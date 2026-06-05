from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ultimate.analysis_levels import ANALYSIS_LEVELS, classify_analysis_level


REQUIRED_MODULE_MANIFEST_FIELDS = (
    "module",
    "status",
    "analysis_level",
    "is_demo",
    "is_stub",
    "delivery_allowed",
    "validation_evidence_allowed",
    "non_delivery_reason",
    "artifacts",
    "limitations",
    "handoff",
)

STANDARD_ARTIFACT_ROOTS = (
    "results/tables",
    "results/figures",
    "objects",
    "reports",
    "logs",
)


def build_module_manifest(
    *,
    module_name: str,
    status: str,
    analysis_level: str | None = None,
    input_path: str | Path | None = None,
    is_demo: bool | None = None,
    is_stub: bool = False,
    public_dataset: bool = False,
    artifacts: dict[str, Any] | None = None,
    limitations: list[str] | tuple[str, ...] | None = None,
    handoff: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    decision = classify_analysis_level(
        requested_level=analysis_level,
        input_path=input_path,
        is_demo=is_demo,
        is_stub=is_stub,
        public_dataset=public_dataset,
    )
    manifest: dict[str, Any] = {
        "module": module_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        **decision.to_manifest_fields(),
        "artifacts": artifacts or {"tables": {}, "figures": {}, "objects": {}},
        "limitations": list(limitations or ()),
        "handoff": handoff or {},
    }
    if extra:
        manifest.update(extra)
    return manifest


def validate_module_manifest_fields(manifest: dict[str, Any]) -> tuple[bool, list[str]]:
    missing = [field for field in REQUIRED_MODULE_MANIFEST_FIELDS if field not in manifest]
    level = manifest.get("analysis_level")
    if level not in ANALYSIS_LEVELS:
        missing.append("analysis_level_allowed_value")
    if manifest.get("delivery_allowed") and level != "production_backend":
        missing.append("delivery_requires_production_backend")
    return not missing, missing


def build_delivery_gate(
    *,
    modules: list[dict[str, Any]],
    production_approval: dict[str, Any] | None,
    run_status: str,
) -> dict[str, Any]:
    approval = production_approval or {}
    levels = sorted({str(module.get("analysis_level", "not_recorded")) for module in modules})
    production_modules = [str(module.get("module")) for module in modules if module.get("analysis_level") == "production_backend"]
    deliverable_modules = [str(module.get("module")) for module in modules if module.get("delivery_allowed") is True]
    evidence_modules = [str(module.get("module")) for module in modules if module.get("validation_evidence_allowed") is True]
    demo_modules = [str(module.get("module")) for module in modules if module.get("is_demo") is True]
    stub_modules = [str(module.get("module")) for module in modules if module.get("is_stub") is True]
    blocked_modules = [
        {
            "module": str(module.get("module", "unknown")),
            "analysis_level": str(module.get("analysis_level", "not_recorded")),
            "delivery_allowed": bool(module.get("delivery_allowed", False)),
            "non_delivery_reason": str(module.get("non_delivery_reason") or ""),
        }
        for module in modules
        if module.get("delivery_allowed") is not True
    ]
    non_delivery_reasons = sorted({str(item["non_delivery_reason"]) for item in blocked_modules if item["non_delivery_reason"]})
    approval_required = bool(production_modules)
    delivery_scope = str(approval.get("delivery_scope") or "not_applicable")
    approval_status = "not_required"
    if approval_required:
        approval_status = "approved" if approval.get("approved") is True else "missing_or_invalid"

    blockers: list[str] = []
    if run_status != "ready":
        blockers.append(f"run_status={run_status}")
    if demo_modules:
        blockers.append("demo_modules=" + ",".join(demo_modules))
    if stub_modules:
        blockers.append("stub_modules=" + ",".join(stub_modules))
    if approval_required and approval_status != "approved":
        blockers.append("production_approval_not_approved")
    if not production_modules:
        blockers.append("no_production_backend_modules")
    if production_modules and sorted(production_modules) != sorted(deliverable_modules):
        blockers.append("production_modules_not_all_deliverable")

    delivery_allowed = not blockers and bool(production_modules)
    validation_evidence_allowed = bool(evidence_modules) and not demo_modules and not stub_modules
    return {
        "status": "ready" if delivery_allowed else "blocked",
        "run_status": run_status,
        "analysis_levels": levels,
        "delivery_allowed": delivery_allowed,
        "validation_evidence_allowed": validation_evidence_allowed,
        "approval_required": approval_required,
        "approval_status": approval_status,
        "delivery_scope": delivery_scope,
        "production_modules": production_modules,
        "deliverable_modules": deliverable_modules,
        "validation_evidence_modules": evidence_modules,
        "demo_modules": demo_modules,
        "stub_modules": stub_modules,
        "blocked_modules": blocked_modules,
        "non_delivery_reasons": non_delivery_reasons,
        "blockers": blockers,
        "non_delivery_reason": "" if delivery_allowed else ";".join(blockers or ["not_marked_for_delivery"]),
    }
