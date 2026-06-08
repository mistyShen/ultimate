from __future__ import annotations

import sys
import types

from ultimate.modules.common import handoff_plan, known_limitations, module_contract, report_contract
from ultimate.scepi_backend import SCEPI_BACKEND_METADATA, inspect_scepi_input_contract, run_scepi_backend

MODULE_NAME = "scepi"


def contract():
    return module_contract(MODULE_NAME).to_dict()


def preflight(config=None, samples=None):
    from ultimate.modules.scepi.preflight import preflight as _preflight

    return _preflight(config=config, samples=samples)


def demo(output_dir=None):
    from ultimate.modules.scepi.demo import demo as _demo

    return _demo(output_dir)


def validate():
    from ultimate.modules.scepi.validate import validate as _validate

    return _validate()


def run(output_dir, config=None, samples=None):
    from ultimate.modules.scepi.run import run as _run

    return _run(output_dir, config=config, samples=samples)


def report():
    return report_contract(MODULE_NAME)


def handoff():
    return handoff_plan(MODULE_NAME)


def limitations():
    return list(known_limitations(MODULE_NAME))


def backend_metadata():
    return dict(SCEPI_BACKEND_METADATA)


def input_contract(config=None, samples=None):
    return inspect_scepi_input_contract(config or {}, samples=samples)


class _ScepiPackage(types.ModuleType):
    """Keep package-level entrypoints callable after submodule imports.

    Python normally assigns `ultimate.modules.scepi.preflight` to the imported
    submodule object. The standardization audit expects the package attribute to
    stay callable, so this module type routes those public attributes back to the
    entrypoint functions above.
    """

    def __getattribute__(self, name):
        if name in {"preflight", "demo", "validate", "run"}:
            return globals()[f"_{name}_entrypoint"]
        return super().__getattribute__(name)


def _preflight_entrypoint(config=None, samples=None):
    from ultimate.modules.scepi.preflight import preflight as _preflight

    return _preflight(config=config, samples=samples)


def _demo_entrypoint(output_dir=None):
    from ultimate.modules.scepi.demo import demo as _demo

    return _demo(output_dir)


def _validate_entrypoint():
    from ultimate.modules.scepi.validate import validate as _validate

    return _validate()


def _run_entrypoint(output_dir, config=None, samples=None):
    from ultimate.modules.scepi.run import run as _run

    return _run(output_dir, config=config, samples=samples)


sys.modules[__name__].__class__ = _ScepiPackage


__all__ = [
    "MODULE_NAME",
    "backend_metadata",
    "contract",
    "demo",
    "handoff",
    "input_contract",
    "limitations",
    "preflight",
    "report",
    "run",
    "run_scepi_backend",
    "validate",
]
