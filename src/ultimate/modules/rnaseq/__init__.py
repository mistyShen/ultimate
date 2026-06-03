from __future__ import annotations

from ultimate.modules.common import (
    demo_manifest,
    handoff_plan,
    known_limitations,
    module_contract,
    preflight_contract,
    report_contract,
    run_contract_smoke,
    validation_plan,
)

MODULE_NAME = "rnaseq"


def contract():
    return module_contract(MODULE_NAME).to_dict()


def preflight(config=None):
    return preflight_contract(MODULE_NAME, config=config)


def demo():
    return demo_manifest(MODULE_NAME)


def validate():
    return validation_plan(MODULE_NAME)


def run(output_dir):
    return run_contract_smoke(MODULE_NAME, output_dir)


def report():
    return report_contract(MODULE_NAME)


def handoff():
    return handoff_plan(MODULE_NAME)


def limitations():
    return list(known_limitations(MODULE_NAME))
