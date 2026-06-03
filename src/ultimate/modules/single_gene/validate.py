from __future__ import annotations

from ultimate.modules.common import validation_plan

MODULE_NAME = "single_gene"


def validate():
    return validation_plan(MODULE_NAME)
