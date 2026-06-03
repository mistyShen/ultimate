from __future__ import annotations

from ultimate.modules.common import known_limitations

MODULE_NAME = "proteomics"


def limitations():
    return list(known_limitations(MODULE_NAME))
