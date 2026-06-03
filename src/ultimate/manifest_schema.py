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
