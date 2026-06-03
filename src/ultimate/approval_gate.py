from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PRODUCTION_APPROVAL_FIELDS = (
    "approved",
    "approved_by",
    "approved_at",
    "project_id",
    "input_path",
    "output_dir",
    "reason",
)


def load_production_approval(
    approval_path: Path | None,
    *,
    analysis_level: str | None,
    input_path: Path,
    output_dir: Path,
) -> dict[str, Any] | None:
    if analysis_level != "production_backend":
        return None
    if approval_path is None:
        raise ValueError("production_backend requires --production-approval with an approved JSON gate file")
    try:
        approval = json.loads(approval_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"production approval JSON is invalid: {exc}") from exc
    validate_production_approval(approval, input_path=input_path, output_dir=output_dir)
    approval["_approval_path"] = str(approval_path.expanduser().resolve())
    return approval


def validate_production_approval(approval: dict[str, Any], *, input_path: Path, output_dir: Path) -> None:
    missing = [field for field in PRODUCTION_APPROVAL_FIELDS if field not in approval or approval[field] in (None, "")]
    if missing:
        raise ValueError(f"production approval JSON missing required fields: {','.join(missing)}")
    if approval.get("approved") is not True:
        raise ValueError("production approval JSON must contain approved=true")
    expected_input = input_path.expanduser().resolve()
    expected_output = output_dir.expanduser().resolve()
    approved_input = Path(str(approval["input_path"])).expanduser().resolve()
    approved_output = Path(str(approval["output_dir"])).expanduser().resolve()
    if approved_input != expected_input:
        raise ValueError(f"production approval input_path mismatch: expected {expected_input}, got {approved_input}")
    if approved_output != expected_output:
        raise ValueError(f"production approval output_dir mismatch: expected {expected_output}, got {approved_output}")
