from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from ultimate.constants import MODULE_ORDER
from ultimate.manifest_schema import (
    REQUIRED_MODULE_MANIFEST_FIELDS,
    STANDARD_ARTIFACT_ROOTS,
    validate_module_manifest_fields,
)
from ultimate.modules.common import HANDOFF_STATUSES


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

STANDARDIZATION_COLUMNS = (
    "module_name",
    "module_dir_status",
    "required_files_status",
    "tests_status",
    "entrypoint_import_status",
    "contract_status",
    "preflight_status",
    "demo_manifest_status",
    "report_status",
    "handoff_status",
    "limitations_status",
    "artifact_contract_status",
    "overall_status",
    "missing_or_gap",
)


def build_module_standardization_rows(modules_root: Path | None = None) -> list[dict[str, str]]:
    """Audit the shared per-module shell required by AGENTS.md.

    This deliberately avoids running module backends. It checks that every module
    exposes the same CLI/reporting guardrails before any scientific result is
    considered delivery-grade.
    """

    modules_root = modules_root or Path(__file__).resolve().parent / "modules"
    rows: list[dict[str, str]] = []
    for module_name in MODULE_ORDER:
        rows.append(_module_standardization_row(modules_root, module_name))
    return rows


def _module_standardization_row(modules_root: Path, module_name: str) -> dict[str, str]:
    module_dir = modules_root / module_name
    gaps: list[str] = []

    module_dir_status = "ready" if module_dir.is_dir() else "missing"
    if module_dir_status != "ready":
        gaps.append("module_dir_missing")

    missing_files = [filename for filename in REQUIRED_MODULE_FILES if not (module_dir / filename).is_file()]
    required_files_status = "ready" if not missing_files else "missing"
    if missing_files:
        gaps.append("missing_files=" + ",".join(missing_files))

    test_files = sorted((module_dir / "tests").glob("test_*.py")) if (module_dir / "tests").is_dir() else []
    tests_status = (
        "ready"
        if (module_dir / "tests").is_dir() and (module_dir / "tests" / "__init__.py").is_file() and test_files
        else "missing"
    )
    if tests_status != "ready":
        gaps.append("tests_package_or_test_file_missing")

    package: Any | None = None
    entrypoint_import_status = "ready"
    try:
        package = importlib.import_module(f"ultimate.modules.{module_name}")
    except Exception as exc:  # pragma: no cover - exercised by failure state only
        entrypoint_import_status = "error"
        gaps.append(f"import_error={type(exc).__name__}:{exc}")

    contract_status = _status_from_call(package, "contract", gaps, module_name)
    preflight_status = _status_from_call(package, "preflight", gaps, module_name)
    report_status = _status_from_call(package, "report", gaps, module_name)
    handoff_status = _handoff_status(package, gaps, module_name)
    limitations_status = _limitations_status(package, gaps, module_name)
    demo_manifest_status = _demo_manifest_status(package, gaps, module_name)
    artifact_contract_status = _artifact_contract_status(package, gaps, module_name)

    statuses = (
        module_dir_status,
        required_files_status,
        tests_status,
        entrypoint_import_status,
        contract_status,
        preflight_status,
        demo_manifest_status,
        report_status,
        handoff_status,
        limitations_status,
        artifact_contract_status,
    )
    overall_status = "ready" if all(status == "ready" for status in statuses) else "partial"
    return {
        "module_name": module_name,
        "module_dir_status": module_dir_status,
        "required_files_status": required_files_status,
        "tests_status": tests_status,
        "entrypoint_import_status": entrypoint_import_status,
        "contract_status": contract_status,
        "preflight_status": preflight_status,
        "demo_manifest_status": demo_manifest_status,
        "report_status": report_status,
        "handoff_status": handoff_status,
        "limitations_status": limitations_status,
        "artifact_contract_status": artifact_contract_status,
        "overall_status": overall_status,
        "missing_or_gap": ";".join(gaps),
    }


def _status_from_call(package: Any | None, function_name: str, gaps: list[str], module_name: str) -> str:
    if package is None or not hasattr(package, function_name):
        gaps.append(f"{function_name}_entrypoint_missing")
        return "missing"
    try:
        payload = getattr(package, function_name)()
    except Exception as exc:  # pragma: no cover - exercised by failure state only
        gaps.append(f"{function_name}_error={type(exc).__name__}:{exc}")
        return "error"
    if not isinstance(payload, dict):
        gaps.append(f"{function_name}_not_dict")
        return "error"
    if function_name == "contract" and payload.get("module_name") != module_name:
        gaps.append("contract_module_name_mismatch")
        return "error"
    if function_name == "preflight" and payload.get("status") != "ready":
        gaps.append(f"preflight_status={payload.get('status')}")
        return "partial"
    if function_name == "report" and payload.get("status") != "ready":
        gaps.append(f"report_status={payload.get('status')}")
        return "partial"
    return "ready"


def _demo_manifest_status(package: Any | None, gaps: list[str], module_name: str) -> str:
    if package is None or not hasattr(package, "demo"):
        gaps.append("demo_entrypoint_missing")
        return "missing"
    try:
        manifest = package.demo()
    except Exception as exc:  # pragma: no cover - exercised by failure state only
        gaps.append(f"demo_error={type(exc).__name__}:{exc}")
        return "error"
    if not isinstance(manifest, dict):
        gaps.append("demo_not_dict")
        return "error"
    ok, missing = validate_module_manifest_fields(manifest)
    if not ok:
        gaps.append("demo_manifest_missing_fields=" + ",".join(missing))
        return "error"
    if manifest.get("module") != module_name:
        gaps.append("demo_module_name_mismatch")
        return "error"
    if manifest.get("analysis_level") != "demo_result":
        gaps.append(f"demo_analysis_level={manifest.get('analysis_level')}")
        return "partial"
    if manifest.get("delivery_allowed") is not False:
        gaps.append("demo_delivery_allowed_not_false")
        return "error"
    if manifest.get("validation_evidence_allowed") is not False:
        gaps.append("demo_validation_evidence_allowed_not_false")
        return "error"
    if manifest.get("is_demo") is not True or manifest.get("is_stub") is not True:
        gaps.append("demo_guard_flags_not_true")
        return "partial"
    for field in REQUIRED_MODULE_MANIFEST_FIELDS:
        if field not in manifest:
            gaps.append(f"demo_field_missing={field}")
            return "error"
    return "ready"


def _handoff_status(package: Any | None, gaps: list[str], module_name: str) -> str:
    if package is None or not hasattr(package, "handoff"):
        gaps.append("handoff_entrypoint_missing")
        return "missing"
    try:
        payload = package.handoff()
    except Exception as exc:  # pragma: no cover - exercised by failure state only
        gaps.append(f"handoff_error={type(exc).__name__}:{exc}")
        return "error"
    if not isinstance(payload, dict):
        gaps.append("handoff_not_dict")
        return "error"
    if payload.get("module") != module_name:
        gaps.append("handoff_module_name_mismatch")
        return "error"
    status = str(payload.get("handoff_status") or "")
    statuses = payload.get("handoff_statuses") or []
    if status not in HANDOFF_STATUSES:
        gaps.append(f"handoff_status={payload.get('handoff_status')}")
        return "partial"
    if not isinstance(statuses, list) or "template_only" not in statuses:
        gaps.append("handoff_statuses_missing_template_only")
        return "partial"
    return "ready"


def _limitations_status(package: Any | None, gaps: list[str], module_name: str) -> str:
    if package is None or not hasattr(package, "limitations"):
        gaps.append("limitations_entrypoint_missing")
        return "missing"
    try:
        limitations = package.limitations()
    except Exception as exc:  # pragma: no cover - exercised by failure state only
        gaps.append(f"limitations_error={type(exc).__name__}:{exc}")
        return "error"
    if not isinstance(limitations, list) or not limitations:
        gaps.append("limitations_empty")
        return "error"
    if not all(isinstance(item, str) and item.strip() for item in limitations):
        gaps.append("limitations_invalid")
        return "error"
    return "ready"


def _artifact_contract_status(package: Any | None, gaps: list[str], module_name: str) -> str:
    if package is None or not hasattr(package, "contract"):
        return "missing"
    try:
        contract = package.contract()
    except Exception as exc:  # pragma: no cover - exercised by failure state only
        gaps.append(f"artifact_contract_error={type(exc).__name__}:{exc}")
        return "error"
    roots = set(contract.get("required_artifact_roots") or ())
    missing = [root for root in STANDARD_ARTIFACT_ROOTS if root not in roots]
    if missing:
        gaps.append("artifact_roots_missing=" + ",".join(missing))
        return "error"
    return "ready"
