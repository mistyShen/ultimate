from __future__ import annotations

from typing import Any

import pandas as pd

from ultimate.modules.common import preflight_contract
from ultimate.scepi_backend import inspect_scepi_input_contract

MODULE_NAME = "scepi"


def preflight(config: dict[str, Any] | None = None, samples: pd.DataFrame | None = None):
    report = preflight_contract(MODULE_NAME, config=config)
    if config is not None:
        report["scepi_matrix_backend"] = inspect_scepi_input_contract(config, samples=samples)
        report["status"] = report["scepi_matrix_backend"]["status"]
    return report
