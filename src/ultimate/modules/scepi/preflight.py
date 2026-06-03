from __future__ import annotations

from typing import Any

from ultimate.modules.common import preflight_contract

MODULE_NAME = "scepi"


def preflight(config: dict[str, Any] | None = None):
    return preflight_contract(MODULE_NAME, config=config)
