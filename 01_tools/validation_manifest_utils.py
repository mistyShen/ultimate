#!/usr/bin/env python3
from __future__ import annotations

import os
from typing import Any


REAL_VALIDATION_KINDS = {"public", "internal"}
SYNTHETIC_VALIDATION_KINDS = {"synthetic", "demo"}


def add_validation_guard_fields(
    manifest: dict[str, Any],
    *,
    validation_kind: str,
    validation_scope: str | None = None,
) -> dict[str, Any]:
    """Add Ultimate delivery/evidence guard fields to standalone validation manifests.

    Standalone scripts under 01_tools are validation evidence producers, not
    customer-delivery entrypoints. They must never emit delivery_allowed=true.
    """

    kind = validation_kind.strip().lower()
    if kind not in REAL_VALIDATION_KINDS | SYNTHETIC_VALIDATION_KINDS | {"smoke"}:
        raise ValueError(f"Unsupported validation_kind: {validation_kind}")

    status = str(manifest.get("status", "")).lower()
    ready = status == "ready"
    is_demo = kind in SYNTHETIC_VALIDATION_KINDS
    is_stub = kind == "smoke" or not ready

    if not ready:
        analysis_level = "smoke_backend"
        validation_evidence_allowed = False
        non_delivery_reason = f"validation_status_not_ready:{status or 'missing'}"
    elif is_demo:
        analysis_level = "demo_result"
        validation_evidence_allowed = False
        non_delivery_reason = "generated_demo_data_not_customer_delivery"
    elif kind in REAL_VALIDATION_KINDS:
        analysis_level = "validated_backend"
        validation_evidence_allowed = True
        non_delivery_reason = "validation_evidence_only_not_customer_delivery"
    else:
        analysis_level = "smoke_backend"
        validation_evidence_allowed = False
        non_delivery_reason = "backend_smoke_check_not_customer_delivery"

    slurm = manifest.get("slurm") if isinstance(manifest.get("slurm"), dict) else {}
    slurm_job_id = str(manifest.get("slurm_job_id") or slurm.get("job_id") or os.environ.get("SLURM_JOB_ID", ""))
    slurm_job_name = str(manifest.get("slurm_job_name") or slurm.get("job_name") or os.environ.get("SLURM_JOB_NAME", ""))
    slurm_submit_dir = str(
        manifest.get("slurm_submit_dir") or slurm.get("submit_dir") or os.environ.get("SLURM_SUBMIT_DIR", "")
    )

    manifest.update(
        {
            "analysis_level": analysis_level,
            "is_demo": is_demo,
            "is_stub": is_stub,
            "delivery_allowed": False,
            "validation_evidence_allowed": validation_evidence_allowed,
            "non_delivery_reason": non_delivery_reason,
            "evidence_policy": (
                "standalone validation run; may support validated_backend evidence "
                "only when non-demo inputs and ready status are recorded; never customer delivery"
            ),
            "slurm_job_id": slurm_job_id,
            "slurm_job_name": slurm_job_name,
            "slurm_submit_dir": slurm_submit_dir,
            "slurm": {
                "job_id": slurm_job_id,
                "job_name": slurm_job_name,
                "submit_dir": slurm_submit_dir,
                "cpus_per_task": str(slurm.get("cpus_per_task") or os.environ.get("SLURM_CPUS_PER_TASK", "")),
                "job_nodelist": str(slurm.get("job_nodelist") or os.environ.get("SLURM_JOB_NODELIST", "")),
            },
        }
    )
    if validation_scope and not manifest.get("validation_scope"):
        manifest["validation_scope"] = validation_scope
    return manifest
