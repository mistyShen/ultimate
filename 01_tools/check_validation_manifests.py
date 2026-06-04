#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


REQUIRED_GUARD_FIELDS = (
    "analysis_level",
    "is_demo",
    "is_stub",
    "delivery_allowed",
    "validation_evidence_allowed",
    "non_delivery_reason",
)

VALID_ANALYSIS_LEVELS = {"demo_result", "smoke_backend", "validated_backend", "production_backend"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Check Ultimate validation run manifests for guard fields.")
    parser.add_argument("--validations-dir", type=Path, default=Path("/shared/shen/2026/ultimate/validations"))
    parser.add_argument("--output-tsv", type=Path, required=True)
    args = parser.parse_args()
    rows = check_validation_manifests(args.validations_dir)
    write_tsv(args.output_tsv, rows)
    summary = summarize_rows(rows)
    print(json.dumps({"summary": summary, "output_tsv": str(args.output_tsv)}, indent=2, ensure_ascii=False))


def check_validation_manifests(validations_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for manifest_path in sorted(validations_dir.glob("*/run_manifest.json")):
        rows.append(_check_manifest(manifest_path))
    return rows


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for row in rows:
        status = str(row["guard_status"])
        summary[status] = summary.get(status, 0) + 1
    return summary


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = (
        "run_name",
        "manifest_path",
        "manifest_status",
        "guard_status",
        "analysis_level",
        "is_demo",
        "is_stub",
        "delivery_allowed",
        "validation_evidence_allowed",
        "non_delivery_reason",
        "slurm_job_id",
        "missing_fields",
        "invalid_fields",
        "n_figures",
        "n_tables",
        "n_objects",
        "report_html_exists",
    )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _check_manifest(path: Path) -> dict[str, Any]:
    run_dir = path.parent
    row: dict[str, Any] = {
        "run_name": run_dir.name,
        "manifest_path": str(path),
        "manifest_status": "missing",
        "guard_status": "invalid",
        "analysis_level": "",
        "is_demo": "",
        "is_stub": "",
        "delivery_allowed": "",
        "validation_evidence_allowed": "",
        "non_delivery_reason": "",
        "slurm_job_id": "",
        "missing_fields": "",
        "invalid_fields": "",
        "n_figures": 0,
        "n_tables": 0,
        "n_objects": 0,
        "report_html_exists": False,
    }
    if not path.exists():
        row["missing_fields"] = ",".join(REQUIRED_GUARD_FIELDS)
        return row
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        row["manifest_status"] = f"invalid_json:{exc.__class__.__name__}"
        row["missing_fields"] = ",".join(REQUIRED_GUARD_FIELDS)
        return row

    row["manifest_status"] = str(manifest.get("status", ""))
    row["analysis_level"] = str(manifest.get("analysis_level", ""))
    row["is_demo"] = _stringify_bool(manifest.get("is_demo", ""))
    row["is_stub"] = _stringify_bool(manifest.get("is_stub", ""))
    row["delivery_allowed"] = _stringify_bool(manifest.get("delivery_allowed", ""))
    row["validation_evidence_allowed"] = _stringify_bool(manifest.get("validation_evidence_allowed", ""))
    row["non_delivery_reason"] = str(manifest.get("non_delivery_reason", ""))
    row["slurm_job_id"] = str(manifest.get("slurm_job_id") or ((manifest.get("slurm") or {}).get("job_id") or ""))
    row["n_figures"] = len(manifest.get("figures", []) or [])
    row["n_tables"] = len(manifest.get("tables", []) or [])
    row["n_objects"] = len(manifest.get("objects", {}) or {})
    row["report_html_exists"] = (run_dir / "reports" / "report.html").exists()

    missing = [field for field in REQUIRED_GUARD_FIELDS if field not in manifest]
    invalid = _invalid_fields(manifest)
    row["missing_fields"] = ",".join(missing)
    row["invalid_fields"] = ",".join(invalid)
    if missing:
        row["guard_status"] = "missing_guard_fields"
    elif invalid:
        row["guard_status"] = "invalid_guard_fields"
    else:
        row["guard_status"] = "ready"
    return row


def _invalid_fields(manifest: dict[str, Any]) -> list[str]:
    invalid: list[str] = []
    if manifest.get("analysis_level") not in VALID_ANALYSIS_LEVELS:
        invalid.append("analysis_level")
    for field in ("is_demo", "is_stub", "delivery_allowed", "validation_evidence_allowed"):
        if not isinstance(manifest.get(field), bool):
            invalid.append(field)
    if manifest.get("delivery_allowed") is True and manifest.get("analysis_level") != "production_backend":
        invalid.append("delivery_allowed_requires_production_backend")
    if manifest.get("validation_evidence_allowed") is True and manifest.get("analysis_level") not in {"validated_backend", "production_backend"}:
        invalid.append("validation_evidence_requires_validated_or_production")
    if manifest.get("delivery_allowed") is False and not manifest.get("non_delivery_reason"):
        invalid.append("non_delivery_reason")
    return invalid


def _stringify_bool(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else str(value)


if __name__ == "__main__":
    main()
