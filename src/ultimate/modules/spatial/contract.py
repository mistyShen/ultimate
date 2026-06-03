from __future__ import annotations

from ultimate.modules.common import module_contract

MODULE_NAME = "spatial"


def contract():
    return module_contract(MODULE_NAME).to_dict()
