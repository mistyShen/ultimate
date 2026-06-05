from __future__ import annotations

import importlib
from pathlib import Path

from ultimate.manifest_schema import REQUIRED_MODULE_MANIFEST_FIELDS, validate_module_manifest_fields


MODULE_NAME = Path(__file__).resolve().parents[1].name


def test_module_entrypoints_expose_required_contracts() -> None:
    package = importlib.import_module(f"ultimate.modules.{MODULE_NAME}")

    contract = package.contract()
    assert contract["module_name"] == MODULE_NAME
    assert contract["supported_input_types"]
    assert {"results/tables", "results/figures", "objects", "reports", "logs"}.issubset(
        set(contract["required_artifact_roots"])
    )

    preflight = package.preflight()
    assert preflight["module"] == MODULE_NAME
    assert preflight["status"] == "ready"

    manifest = package.demo()
    ok, missing = validate_module_manifest_fields(manifest)
    assert ok, f"{MODULE_NAME}: {missing}"
    for field in REQUIRED_MODULE_MANIFEST_FIELDS:
        assert field in manifest
    assert manifest["module"] == MODULE_NAME
    assert manifest["analysis_level"] == "demo_result"
    assert manifest["delivery_allowed"] is False
    assert manifest["validation_evidence_allowed"] is False

    assert package.report()["status"] == "ready"
    assert "template_only" in package.handoff()["handoff_statuses"]
    assert package.limitations()
