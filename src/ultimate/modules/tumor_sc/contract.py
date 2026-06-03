from __future__ import annotations

from ultimate.modules.common import module_contract

MODULE_NAME = "tumor_sc"


def contract():
    return module_contract(MODULE_NAME).to_dict()
