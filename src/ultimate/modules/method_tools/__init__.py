from __future__ import annotations

from ultimate.modules.backend_entrypoints import (
    backend_metadata as _backend_metadata,
    contract as _contract,
    demo as _demo,
    handoff as _handoff,
    install_backend_package_router,
    limitations as _limitations,
    preflight as _preflight,
    report as _report,
    run as _run,
    validate as _validate,
)

MODULE_NAME = "method_tools"


def contract():
    return _contract(MODULE_NAME)


def preflight(config=None, samples=None):
    return _preflight(MODULE_NAME, config=config, samples=samples)


def demo(output_dir=None):
    return _demo(MODULE_NAME, output_dir=output_dir)


def validate():
    return _validate(MODULE_NAME)


def run(output_dir, config=None, samples=None):
    return _run(MODULE_NAME, output_dir, config=config, samples=samples)


def report():
    return _report(MODULE_NAME)


def handoff():
    return _handoff(MODULE_NAME)


def limitations():
    return _limitations(MODULE_NAME)


def backend_metadata():
    return _backend_metadata(MODULE_NAME)


install_backend_package_router(__name__, MODULE_NAME)


__all__ = [
    "MODULE_NAME",
    "backend_metadata",
    "contract",
    "demo",
    "handoff",
    "limitations",
    "preflight",
    "report",
    "run",
    "validate",
]
