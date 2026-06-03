from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


ANALYSIS_LEVELS = ("demo_result", "smoke_backend", "validated_backend", "production_backend")
EVIDENCE_LEVELS = {"validated_backend", "production_backend"}
DELIVERY_LEVELS = {"production_backend"}


@dataclass(frozen=True)
class AnalysisLevelDecision:
    analysis_level: str
    is_demo: bool
    is_stub: bool
    delivery_allowed: bool
    validation_evidence_allowed: bool
    non_delivery_reason: str

    def to_manifest_fields(self) -> dict[str, Any]:
        return asdict(self)


def classify_analysis_level(
    *,
    requested_level: str | None = None,
    input_path: Path | str | None = None,
    is_demo: bool | None = None,
    is_stub: bool = False,
    public_dataset: bool = False,
) -> AnalysisLevelDecision:
    """Classify run evidence without allowing demo/stub data to look production-ready."""

    inferred_demo = _looks_like_demo_path(input_path) if is_demo is None else bool(is_demo)
    if requested_level is not None and requested_level not in ANALYSIS_LEVELS:
        raise ValueError(f"Unsupported analysis_level: {requested_level}")

    if requested_level is None:
        if inferred_demo:
            level = "demo_result"
        elif public_dataset:
            level = "validated_backend"
        else:
            level = "smoke_backend"
    else:
        level = requested_level

    if (inferred_demo or is_stub) and level in EVIDENCE_LEVELS:
        marker = "demo" if inferred_demo else "stub"
        raise ValueError(f"{marker} inputs cannot be labeled as {level}")

    delivery_allowed = level in DELIVERY_LEVELS and not inferred_demo and not is_stub
    validation_evidence_allowed = level in EVIDENCE_LEVELS and not inferred_demo and not is_stub
    return AnalysisLevelDecision(
        analysis_level=level,
        is_demo=inferred_demo,
        is_stub=bool(is_stub),
        delivery_allowed=delivery_allowed,
        validation_evidence_allowed=validation_evidence_allowed,
        non_delivery_reason="" if delivery_allowed else _non_delivery_reason(level, inferred_demo, is_stub),
    )


def require_real_evidence(manifest: dict[str, Any]) -> tuple[bool, str]:
    """Return whether a manifest can count as real validation/production evidence."""

    status = str(manifest.get("status", "")).lower()
    level = str(manifest.get("analysis_level", ""))
    if status != "ready":
        return False, f"manifest_status={status or 'missing'}"
    if level not in EVIDENCE_LEVELS:
        return False, f"analysis_level={level or 'missing'}"
    if bool(manifest.get("is_demo")):
        return False, "is_demo=true"
    if bool(manifest.get("is_stub")):
        return False, "is_stub=true"
    return True, "ready_real_evidence"


def _non_delivery_reason(level: str, is_demo: bool, is_stub: bool) -> str:
    if is_demo:
        return "generated_demo_data_not_customer_delivery"
    if is_stub:
        return "stub_or_placeholder_result_not_customer_delivery"
    if level == "validated_backend":
        return "validation_evidence_only_not_customer_delivery"
    if level == "smoke_backend":
        return "backend_smoke_check_not_customer_delivery"
    if level == "demo_result":
        return "generated_demo_data_not_customer_delivery"
    return "not_marked_for_delivery"


def _looks_like_demo_path(input_path: Path | str | None) -> bool:
    if input_path is None:
        return False
    text = str(input_path).lower()
    demo_markers = ("demo", "synthetic", "tiny", "stub", "placeholder")
    return any(marker in text for marker in demo_markers)
