from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from ultimate.scepi_backend import SCEPI_BACKEND_METADATA, run_scepi_backend

MODULE_NAME = "scepi"


def run(output_dir: Path, config: dict[str, Any] | None = None, samples: pd.DataFrame | None = None):
    """Run the SCEPI matrix-level backend.

    The package-level entrypoint is intentionally wired to the real backend so
    the module does not look like a contract smoke stub when inspected directly.
    Unified project runs still dispatch through `ultimate.modules.runner`.
    """

    if config is None:
        config = {
            "project": {"name": "scepi_direct_run", "output_dir": str(output_dir), "run_mode": "interactive"},
            "samples": {"items": []},
            "modules": {"scepi": {"enabled": True}},
        }
    if samples is None:
        samples = pd.DataFrame(columns=["sample_id", "condition", "input_path"])
    return run_scepi_backend(config=config, output_dir=output_dir, samples=samples)


def backend_metadata() -> dict[str, Any]:
    return dict(SCEPI_BACKEND_METADATA)
