from __future__ import annotations

import importlib
from pathlib import Path

from ultimate.constants import MODULE_ORDER
from ultimate.manifest_schema import REQUIRED_MODULE_MANIFEST_FIELDS, validate_module_manifest_fields
from ultimate.module_maturity import MATURITY_COLUMNS, build_module_maturity_rows
from ultimate.module_standardization import STANDARDIZATION_COLUMNS, build_module_standardization_rows
from ultimate.modules.common import (
    demo_manifest,
    handoff_plan,
    module_contract,
    module_mvp_output_spec,
    preflight_contract,
    report_contract,
)


REQUIRED_MODULE_FILES = (
    "contract.py",
    "preflight.py",
    "demo.py",
    "validate.py",
    "run.py",
    "report.py",
    "handoff.py",
    "limitations.py",
)


def test_every_module_has_outline_skeleton_files() -> None:
    module_root = Path(__file__).parents[1] / "src" / "ultimate" / "modules"
    for module_name in MODULE_ORDER:
        module_dir = module_root / module_name
        assert module_dir.is_dir(), module_name
        for filename in REQUIRED_MODULE_FILES:
            assert (module_dir / filename).exists(), f"{module_name}/{filename}"
        assert (module_dir / "tests").is_dir(), module_name


def test_every_module_contract_and_guard_fields_are_exposed() -> None:
    for module_name in MODULE_ORDER:
        contract = module_contract(module_name)
        output_spec = module_mvp_output_spec(module_name)
        assert contract.module_name == module_name
        assert contract.supported_input_types
        assert contract.required_artifact_roots
        assert contract.known_limitations
        assert output_spec["tables"]
        assert output_spec["figures"]
        assert output_spec["object"]

        preflight = preflight_contract(module_name, config={"modules": {module_name: {}}})
        assert preflight["status"] == "ready"

        manifest = demo_manifest(module_name)
        ok, missing = validate_module_manifest_fields(manifest)
        assert ok, f"{module_name}: {missing}"
        for field in REQUIRED_MODULE_MANIFEST_FIELDS:
            assert field in manifest, f"{module_name}:{field}"
        assert manifest["analysis_level"] == "demo_result"
        assert manifest["delivery_allowed"] is False
        assert manifest["validation_evidence_allowed"] is False
        assert manifest["limitations"]
        assert manifest["handoff"]["handoff_status"] == "template_ready"

        report = report_contract(module_name)
        assert report["status"] == "ready"
        handoff = handoff_plan(module_name)
        assert handoff["handoff_status"] == "template_ready"


def test_module_entrypoint_files_import() -> None:
    for module_name in MODULE_ORDER:
        package = importlib.import_module(f"ultimate.modules.{module_name}")
        assert package.contract()["module_name"] == module_name
        assert package.preflight()["status"] == "ready"
        assert package.demo()["analysis_level"] == "demo_result"
        assert package.report()["status"] == "ready"
        assert isinstance(package.limitations(), list)


def test_module_maturity_table_has_required_columns(tmp_path: Path) -> None:
    rows = build_module_maturity_rows(tmp_path)
    assert len(rows) == len(MODULE_ORDER)
    assert set(rows[0]) == set(MATURITY_COLUMNS)
    assert all(row["delivery_allowed"] == "false" for row in rows)
    assert all(row["analysis_level"] != "validated_backend" for row in rows)


def test_module_standardization_matrix_is_ready() -> None:
    rows = build_module_standardization_rows()
    assert len(rows) == len(MODULE_ORDER)
    assert set(rows[0]) == set(STANDARDIZATION_COLUMNS)
    assert all(row["overall_status"] == "ready" for row in rows)
    assert all(row["demo_manifest_status"] == "ready" for row in rows)
    assert all(row["handoff_status"] == "ready" for row in rows)
