from __future__ import annotations

from ultimate.modules.common import validation_plan

MODULE_NAME = "functional_state"


def validate():
    return validation_plan(MODULE_NAME)
