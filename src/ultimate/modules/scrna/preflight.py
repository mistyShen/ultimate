from __future__ import annotations

from typing import Any

import pandas as pd

from ultimate.modules.backend_entrypoints import preflight as _preflight

MODULE_NAME = "scrna"


def preflight(config: dict[str, Any] | None = None, samples: pd.DataFrame | None = None):
    return _preflight(MODULE_NAME, config=config, samples=samples)
