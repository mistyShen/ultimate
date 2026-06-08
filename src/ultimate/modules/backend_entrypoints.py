from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pandas as pd

from ultimate.backend_registry import backends_for_module, build_backend_plan
from ultimate.modules.common import (
    demo_manifest,
    handoff_plan,
    known_limitations,
    module_contract,
    preflight_contract,
    report_contract,
    validation_plan,
)

ENTRYPOINT_NAMES = {"preflight", "demo", "validate", "run"}


def contract(module_name: str) -> dict[str, Any]:
    return module_contract(module_name).to_dict()


def preflight(module_name: str, config: dict[str, Any] | None = None, samples: pd.DataFrame | None = None) -> dict[str, Any]:
    report = preflight_contract(module_name, config=config)
    report["backend_plan"] = build_backend_plan(module_name, config or {})
    report["backend_metadata"] = backend_metadata(module_name)
    if samples is not None:
        report["sample_count"] = int(samples.shape[0])
    return report


def demo(module_name: str, output_dir: Path | None = None) -> dict[str, Any]:
    manifest = demo_manifest(module_name)
    manifest["backend"] = backend_metadata(module_name)
    manifest["demo_note"] = "backend-aware module demo; not validation evidence or customer delivery"
    if output_dir is not None:
        manifest["demo_output_dir"] = str(output_dir)
    return manifest


def validate(module_name: str) -> dict[str, Any]:
    plan = validation_plan(module_name)
    plan["backend"] = backend_metadata(module_name)
    default = default_backend_metadata(module_name)
    plan["slurm_profile"] = default.get("slurm_profile", "")
    plan["evidence_policy"] = "validated_backend is platform evidence only; delivery_allowed remains false."
    return plan


def run(module_name: str, output_dir: Path, config: dict[str, Any] | None = None, samples: pd.DataFrame | None = None) -> dict[str, Any]:
    from ultimate.modules.runner import run_module

    output_dir = Path(output_dir)
    if config is None:
        config = {
            "project": {"name": f"{module_name}_direct_run", "output_dir": str(output_dir), "run_mode": "interactive", "is_demo": True},
            "samples": {"items": []},
            "modules": {module_name: {"enabled": True, "is_demo": True}},
        }
    if samples is None:
        samples = pd.DataFrame(columns=["sample_id", "condition", "input_path"])
    return run_module(module_name=module_name, config=config, output_dir=output_dir, samples=samples)


def report(module_name: str) -> dict[str, Any]:
    return report_contract(module_name)


def handoff(module_name: str) -> dict[str, Any]:
    return handoff_plan(module_name)


def limitations(module_name: str) -> list[str]:
    return list(known_limitations(module_name))


def backend_metadata(module_name: str) -> dict[str, Any]:
    specs = backends_for_module(module_name)
    return {
        "module": module_name,
        "default_backend": default_backend_metadata(module_name),
        "registered_backends": [
            {
                "backend_id": spec.backend_id,
                "backend_role": spec.backend_role,
                "backend_status": spec.backend_status,
                "preset": spec.preset,
                "tool": spec.tool,
                "slurm_profile": spec.slurm_profile,
                "production_allowed": spec.production_allowed,
                "requires_license": spec.requires_license,
                "skip_reason": spec.skip_reason,
            }
            for spec in specs
        ],
    }


def default_backend_metadata(module_name: str) -> dict[str, Any]:
    specs = backends_for_module(module_name)
    default = next((spec for spec in specs if spec.backend_role == "default_backend"), specs[0] if specs else None)
    if default is None:
        return {"module": module_name, "backend_status": "missing", "backend_id": ""}
    return {
        "module": module_name,
        "backend_id": default.backend_id,
        "backend_role": default.backend_role,
        "backend_status": default.backend_status,
        "preset": default.preset,
        "tool": default.tool,
        "slurm_profile": default.slurm_profile,
        "output_contract": list(default.output_contract),
        "validation_dataset": default.validation_dataset,
        "known_limitations": list(default.known_limitations),
        "production_allowed": default.production_allowed,
        "requires_license": default.requires_license,
        "skip_reason": default.skip_reason,
        "resource_profile": default.resource_profile,
    }


def install_backend_package_router(package_name: str, module_name: str) -> None:
    package = sys.modules[package_name]

    class _BackendPackage(types.ModuleType):
        def __getattribute__(self, name: str):
            if name == "preflight":
                return lambda config=None, samples=None: preflight(module_name, config=config, samples=samples)
            if name == "demo":
                return lambda output_dir=None: demo(module_name, output_dir=output_dir)
            if name == "validate":
                return lambda: validate(module_name)
            if name == "run":
                return lambda output_dir, config=None, samples=None: run(module_name, output_dir, config=config, samples=samples)
            return super().__getattribute__(name)

    package.__class__ = _BackendPackage
