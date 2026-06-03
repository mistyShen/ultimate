from __future__ import annotations

from pathlib import Path

from ultimate.modules.common import run_contract_smoke

MODULE_NAME = "spatial"


def run(output_dir: Path):
    return run_contract_smoke(MODULE_NAME, output_dir)
