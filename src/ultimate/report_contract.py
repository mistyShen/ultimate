from __future__ import annotations

from typing import Any


REQUIRED_REPORT_FIELDS = (
    "analysis_level",
    "delivery_allowed",
    "non_delivery_reason",
    "limitations",
    "handoff",
)


def report_contract_status(module_manifest: dict[str, Any]) -> dict[str, Any]:
    missing = [field for field in REQUIRED_REPORT_FIELDS if field not in module_manifest]
    warnings: list[str] = []
    if module_manifest.get("is_stub"):
        warnings.append("stub_result_not_biological_conclusion")
    if module_manifest.get("analysis_level") in {"demo_result", "smoke_backend"}:
        warnings.append("non_delivery_analysis_level")
    return {
        "status": "ready" if not missing else "partial:missing_report_fields",
        "missing_fields": missing,
        "warnings": warnings,
    }
