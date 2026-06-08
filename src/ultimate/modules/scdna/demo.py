from __future__ import annotations

from pathlib import Path

from ultimate.modules.backend_entrypoints import demo as _demo

MODULE_NAME = "scdna"


def demo(output_dir: Path | None = None):
    return _demo(MODULE_NAME, output_dir=output_dir)
