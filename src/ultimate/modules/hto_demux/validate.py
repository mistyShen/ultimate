from __future__ import annotations

from ultimate.modules.common import validation_plan

MODULE_NAME = "hto_demux"


def validate():
    return validation_plan(MODULE_NAME)
