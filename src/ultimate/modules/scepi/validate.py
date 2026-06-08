from __future__ import annotations

from typing import Any

from ultimate.modules.common import validation_plan
from ultimate.scepi_backend import SCEPI_BACKEND_METADATA

MODULE_NAME = "scepi"


def validate() -> dict[str, Any]:
    plan = validation_plan(MODULE_NAME)
    plan["backend"] = dict(SCEPI_BACKEND_METADATA)
    plan["public_validation_entrypoint"] = "ultimate/01_tools/validate_scepi_public.py"
    plan["slurm_validation"] = "ultimate/slurm/scepi_backend_validation.sbatch"
    plan["evidence_policy"] = "validated_backend is platform evidence only; delivery_allowed remains false."
    return plan
