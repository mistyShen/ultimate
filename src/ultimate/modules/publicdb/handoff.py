from __future__ import annotations

from ultimate.modules.common import handoff_plan

MODULE_NAME = "publicdb"


def handoff():
    return handoff_plan(MODULE_NAME)
