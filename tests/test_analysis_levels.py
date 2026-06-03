from __future__ import annotations

from pathlib import Path

import pytest

from ultimate.analysis_levels import classify_analysis_level, require_real_evidence


def test_demo_path_defaults_to_non_delivery_demo_result() -> None:
    decision = classify_analysis_level(input_path=Path("/shared/demo/input.h5ad"))
    assert decision.analysis_level == "demo_result"
    assert decision.delivery_allowed is False
    assert decision.validation_evidence_allowed is False


def test_public_dataset_defaults_to_validated_evidence_not_delivery() -> None:
    decision = classify_analysis_level(input_path=Path("/shared/public/pbmc3k"), public_dataset=True)
    assert decision.analysis_level == "validated_backend"
    assert decision.delivery_allowed is False
    assert decision.validation_evidence_allowed is True


def test_demo_cannot_be_marked_validated_backend() -> None:
    with pytest.raises(ValueError, match="cannot be labeled as validated_backend"):
        classify_analysis_level(requested_level="validated_backend", input_path=Path("/shared/demo/input.h5ad"))


def test_require_real_evidence_rejects_demo_ready_manifest() -> None:
    ready, reason = require_real_evidence({"status": "ready", "analysis_level": "demo_result", "is_demo": True})
    assert ready is False
    assert reason == "analysis_level=demo_result"
