from __future__ import annotations

from ultimate.modules.common import known_limitations

MODULE_NAME = "tumor_sc"


def limitations():
    return list(known_limitations(MODULE_NAME))
