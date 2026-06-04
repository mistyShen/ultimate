#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path
from typing import Any

from validation_manifest_utils import add_validation_guard_fields


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
    parser.add_argument("--root", type=Path, default=Path("/shared/shen/2026/ultimate"))
    parser.add_argument("--validations-dir", type=Path, default=Path("/shared/shen/2026/ultimate/validations"))
    parser.add_argument("--output-tsv", type=Path, required=True)
    parser.add_argument("--normalize", action="store_true", help="Back up and add missing guard fields to validation manifests.")
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=None,
        help="Backup directory for old manifests. Defaults to <root>/audits/validation_guard_latest/backups.",
    )
    args = parser.parse_args()
    if args.normalize:
        rows = normalize_validation_manifests(
            root=args.root,
            validations_dir=args.validations_dir,
            backup_dir=args.backup_dir or args.root / "audits" / "validation_guard_latest" / "backups",
        )
    else:
        rows = check_validation_manifests(args.validations_dir, root=args.root)
    write_tsv(args.output_tsv, rows)
    summary = summarize_rows(rows)
    print(json.dumps({"summary": summary, "output_tsv": str(args.output_tsv)}, indent=2, ensure_ascii=False))


def check_validation_manifests(validations_dir: Path, *, root: Path | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for manifest_path in iter_validation_manifests(validations_dir=validations_dir, root=root):
        rows.append(_check_manifest(manifest_path))
    return rows


def normalize_validation_manifests(*, root: Path, validations_dir: Path, backup_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for manifest_path in iter_validation_manifests(validations_dir=validations_dir, root=root):
        rows.append(_normalize_manifest(manifest_path, root=root, backup_dir=backup_dir))
    return rows


def iter_validation_manifests(*, validations_dir: Path, root: Path | None = None) -> list[Path]:
    root = root.resolve() if root else None
    paths = set(validations_dir.resolve().glob("*/run_manifest.json"))
    if root:
        paths.update((root / "validation_runs").glob("*/*/run_manifest.json"))
        paths.update((root / "validations" / "bulk_demo_python" / "project" / "runs").glob("*/run_manifest.json"))
    return sorted(path for path in paths if path.exists())


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
        "normalization_action",
        "backup_path",
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
        "normalization_action": "",
        "backup_path": "",
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


def _normalize_manifest(path: Path, *, root: Path, backup_dir: Path) -> dict[str, Any]:
    before = _check_manifest(path)
    if before["guard_status"] == "ready":
        before["normalization_action"] = "unchanged"
        return before
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        before["normalization_action"] = "skipped:manifest_unreadable"
        return before

    validation_kind, validation_scope = _classify_validation_run(path, manifest)
    relative = _safe_relative_manifest_path(path, root)
    backup_path = backup_dir / relative
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backup_path)

    add_validation_guard_fields(manifest, validation_kind=validation_kind, validation_scope=validation_scope)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    after = _check_manifest(path)
    after["normalization_action"] = "normalized"
    after["backup_path"] = str(backup_path)
    return after


def _classify_validation_run(path: Path, manifest: dict[str, Any]) -> tuple[str, str]:
    text = f"{path} {manifest.get('dataset', '')} {manifest.get('dataset_label', '')}".lower()
    name = path.parent.name.lower()
    if "demo" in text or name in {"slurm_perturb_seq_demo", "slurm_hto_demux_demo", "slurm_genotype_demux_demo"}:
        return "synthetic", f"{path.parent.name} demo/synthetic validation"
    if any(token in text for token in ("nsclc", "0518", "method_tools")):
        return "internal", f"{path.parent.name} internal validation"
    if any(token in text for token in ("10x", "pbmc", "visium", "squidpy", "public", "geo")):
        return "public", f"{path.parent.name} public validation"
    return "smoke", f"{path.parent.name} validation smoke"


def _safe_relative_manifest_path(path: Path, root: Path) -> Path:
    try:
        return path.resolve().relative_to(root.resolve())
    except ValueError:
        return Path(path.parent.name) / path.name


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
