from __future__ import annotations

from pathlib import Path
from typing import Any

from ultimate.modules.common import demo_manifest
from ultimate.scepi_backend import SCEPI_BACKEND_METADATA

MODULE_NAME = "scepi"


def demo(output_dir: Path | None = None) -> dict[str, Any]:
    manifest = demo_manifest(MODULE_NAME)
    manifest["backend"] = dict(SCEPI_BACKEND_METADATA)
    manifest["demo_note"] = "SCEPI demo output is matrix-level smoke evidence only and is never customer-deliverable."
    if output_dir is not None:
        manifest["suggested_input_matrix"] = str(output_dir / "input" / "scepi_region_matrix.tsv")
    return manifest
