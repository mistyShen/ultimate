from __future__ import annotations

from pathlib import Path

import pytest

from ultimate.analysis_levels import classify_analysis_level, require_real_evidence
from ultimate.manifest_schema import build_delivery_gate


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


def test_explicit_demo_flag_cannot_be_marked_production_backend() -> None:
    with pytest.raises(ValueError, match="demo inputs cannot be labeled as production_backend"):
        classify_analysis_level(
            requested_level="production_backend",
            input_path=Path("/shared/customer_like/input.tsv"),
            is_demo=True,
        )


def test_require_real_evidence_rejects_demo_ready_manifest() -> None:
    ready, reason = require_real_evidence({"status": "ready", "analysis_level": "demo_result", "is_demo": True})
    assert ready is False
    assert reason == "analysis_level=demo_result"


def test_delivery_gate_blocks_mixed_production_and_demo_modules() -> None:
    gate = build_delivery_gate(
        modules=[
            {
                "module": "rnaseq",
                "analysis_level": "production_backend",
                "delivery_allowed": True,
                "validation_evidence_allowed": True,
                "is_demo": False,
                "is_stub": False,
                "non_delivery_reason": "",
            },
            {
                "module": "scrna",
                "analysis_level": "demo_result",
                "delivery_allowed": False,
                "validation_evidence_allowed": False,
                "is_demo": True,
                "is_stub": False,
                "non_delivery_reason": "generated_demo_data_not_customer_delivery",
            },
        ],
        production_approval={"approved": True},
        run_status="ready",
    )
    assert gate["status"] == "blocked"
    assert gate["delivery_allowed"] is False
    assert "demo_modules=scrna" in gate["blockers"]
    assert gate["blocked_modules"] == [
        {
            "module": "scrna",
            "analysis_level": "demo_result",
            "delivery_allowed": False,
            "non_delivery_reason": "generated_demo_data_not_customer_delivery",
        }
    ]
