from __future__ import annotations

from pathlib import Path
from typing import Any

from ultimate.constants import MODULE_ORDER
from ultimate.raw_qc import RAW_CONTRACTS


MATURITY_COLUMNS = (
    "module_name",
    "input_contract_status",
    "preflight_status",
    "demo_smoke_status",
    "public_validation_status",
    "formal_backend_status",
    "report_status",
    "analysis_level",
    "delivery_allowed",
    "known_limitations",
    "next_required_backend",
)


def build_module_maturity_rows(root: Path, capability_rows: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    capability_by_module = {str(row.get("module")): row for row in capability_rows or []}
    rows: list[dict[str, Any]] = []
    for module_name in MODULE_ORDER:
        capability = capability_by_module.get(module_name, {})
        validation = str(capability.get("validation") or "missing")
        production_status = str(capability.get("production_status") or "partial")
        rows.append(
            {
                "module_name": module_name,
                "input_contract_status": "ready" if module_name in RAW_CONTRACTS else "missing",
                "preflight_status": "ready",
                "demo_smoke_status": "ready" if production_status.startswith("ready") else "partial",
                "public_validation_status": validation,
                "formal_backend_status": str(capability.get("basic_backend") or "partial:backend_not_audited"),
                "report_status": str(capability.get("report_output") or "ready"),
                "analysis_level": _analysis_level_for_validation(validation, production_status),
                "delivery_allowed": "false",
                "known_limitations": _known_limitations(module_name, validation),
                "next_required_backend": str(capability.get("next_action") or "Add module-specific validation backend."),
            }
        )
    return rows


def _analysis_level_for_validation(validation: str, production_status: str) -> str:
    if validation == "available":
        return "validated_backend"
    return "smoke_backend"


def _known_limitations(module_name: str, validation: str) -> str:
    generic = "validated_backend 不等于客户正式交付；production_backend 需要 approval gate。"
    if validation != "available":
        return generic + " 当前模块仍需要公开或内部数据验证。"
    return generic
