from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from ultimate.modules.backend_entrypoints import backend_metadata as _backend_metadata
from ultimate.modules.backend_entrypoints import run as _run

MODULE_NAME = "method_tools"


def run(output_dir: Path, config: dict[str, Any] | None = None, samples: pd.DataFrame | None = None):
    return _run(MODULE_NAME, output_dir, config=config, samples=samples)


def backend_metadata() -> dict[str, Any]:
    return _backend_metadata(MODULE_NAME)
