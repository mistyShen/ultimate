#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


AUDIT_FIELDS = (
    "path",
    "category",
    "bytes",
    "size_gb",
    "resource_class",
    "reusable",
    "temporary",
    "duplicate",
    "do_not_delete",
    "cleanup_action",
    "reason",
)

CLEANUP_FIELDS = AUDIT_FIELDS


CATEGORY_RULES: tuple[tuple[str, str], ...] = (
    (".conda", "environments"),
    ("conda", "environments"),
    ("envs", "environments"),
    ("environments", "environments"),
    ("public_data", "public_data"),
    ("validation_runs", "validation_runs"),
    ("validations", "validation_runs"),
    ("jobs", "jobs"),
    ("job_runs", "jobs"),
    ("slurm_jobs", "jobs"),
    ("containers", "containers/cache"),
    ("container_cache", "containers/cache"),
    (".apptainer", "containers/cache"),
    ("apptainer", "containers/cache"),
    (".singularity", "containers/cache"),
    ("singularity", "containers/cache"),
    (".nextflow", "containers/cache"),
    ("nextflow", "containers/cache"),
    (".cache", "containers/cache"),
    ("cache", "containers/cache"),
    ("references", "references"),
    ("reference", "references"),
    ("refs", "references"),
    ("genomes", "references"),
    ("logs", "logs"),
    ("reports", "reports"),
    ("objects", "objects"),
    ("raw_links", "raw_links"),
    ("raw", "raw_links"),
    ("raw_data", "raw_links"),
)


RESOURCE_POLICY: dict[str, tuple[str, str, str]] = {
    "environments": (
        "environment",
        "review_prune_rebuildable_environment",
        "Conda/mamba environments are rebuildable when environment files and manifests are preserved.",
    ),
    "public_data": (
        "public_data",
        "retain_reuse_do_not_delete",
        "Public validation data should be reused and only pruned after provenance review.",
    ),
    "validation_runs": (
        "validation_output",
        "review_archive_old_validation_runs",
        "Validation outputs can become cleanup candidates after manifests and final reports are retained.",
    ),
    "jobs": (
        "job_output",
        "review_archive_old_job_outputs",
        "Job work directories can be large and should be reviewed against manifests before cleanup.",
    ),
    "containers/cache": (
        "cache",
        "review_prune_rebuildable_cache",
        "Container and workflow caches are often rebuildable but must be checked before removal.",
    ),
    "references": (
        "reference",
        "retain_reuse_do_not_delete",
        "Reference resources should be shared and retained unless a newer registered replacement exists.",
    ),
    "logs": (
        "log",
        "review_compress_or_archive_logs",
        "Logs are usually compressible or archivable after run status has been checked.",
    ),
    "reports": (
        "report",
        "retain_or_archive_delivery_reports",
        "Reports may be delivery evidence and should not be removed without review.",
    ),
    "objects": (
        "analysis_object",
        "review_archive_large_objects",
        "Large analysis objects can be archived when reports and manifests point to preserved copies.",
    ),
    "raw_links": (
        "raw_link",
        "retain_reuse_do_not_delete",
        "Raw-data links or raw-data entrypoints are protected and this audit never recommends deletion.",
    ),
    "other": (
        "other",
        "manual_review",
        "Unclassified top-level content needs manual ownership review before any cleanup.",
    ),
}


PROTECTED_ACTIONS = {"retain_reuse_do_not_delete", "retain_or_archive_delivery_reports"}
REQUIRED_CATEGORIES = (
    "environments",
    "public_data",
    "validation_runs",
    "jobs",
    "containers/cache",
    "references",
    "logs",
    "reports",
    "objects",
    "raw_links",
)
REUSABLE_CATEGORIES = {"environments", "public_data", "containers/cache", "references", "raw_links"}
TEMPORARY_CATEGORIES = {"validation_runs", "jobs", "logs", "objects"}
DO_NOT_DELETE_CATEGORIES = {"public_data", "references", "raw_links"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit Ultimate storage usage and write a cleanup review plan.")
    parser.add_argument("--root", type=Path, required=True, help="Ultimate project root to audit.")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory for audit artifacts.")
    parser.add_argument("--budget-gb", type=float, default=500.0, help="Storage budget in GB.")
    args = parser.parse_args()

    manifest = run_storage_audit(root=args.root, output_dir=args.output_dir, budget_gb=args.budget_gb)
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


def run_storage_audit(*, root: Path, output_dir: Path, budget_gb: float = 500.0) -> dict[str, Any]:
    root = root.resolve()
    output_dir = output_dir.resolve()
    rows = audit_storage(root=root, output_dir=output_dir)
    total_bytes = sum(int(row["bytes"]) for row in rows)
    budget_bytes = int(budget_gb * 1024**3)
    under_budget = total_bytes <= budget_bytes
    cleanup_rows = cleanup_candidates(rows, enabled=not under_budget)
    summary = summarize(root=root, budget_gb=budget_gb, rows=rows, cleanup_rows=cleanup_rows)

    output_dir.mkdir(parents=True, exist_ok=True)
    audit_tsv = output_dir / "storage_audit.tsv"
    summary_json = output_dir / "storage_audit_summary.json"
    cleanup_tsv = output_dir / "cleanup_plan.tsv"
    write_tsv(audit_tsv, rows, AUDIT_FIELDS)
    write_tsv(cleanup_tsv, cleanup_rows, CLEANUP_FIELDS)
    summary_json.write_text(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")

    return {
        "storage_audit": str(audit_tsv),
        "storage_audit_summary": str(summary_json),
        "cleanup_plan": str(cleanup_tsv),
        "summary": summary,
    }


def audit_storage(*, root: Path, output_dir: Path | None = None) -> list[dict[str, Any]]:
    if not root.exists():
        raise FileNotFoundError(f"root does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"root is not a directory: {root}")

    rows: list[dict[str, Any]] = []
    skip = output_dir.resolve() if output_dir else None
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        if skip and _same_or_contains(path.resolve(), skip):
            continue
        category = categorize(path.name)
        bytes_used = path_size(path)
        resource_class, cleanup_action, reason = RESOURCE_POLICY[category]
        rows.append(
            {
                "path": str(path),
                "category": category,
                "bytes": bytes_used,
                "size_gb": bytes_to_gb(bytes_used),
                "resource_class": resource_class,
                "reusable": str(category in REUSABLE_CATEGORIES).lower(),
                "temporary": str(category in TEMPORARY_CATEGORIES).lower(),
                "duplicate": "false",
                "do_not_delete": str(category in DO_NOT_DELETE_CATEGORIES).lower(),
                "cleanup_action": cleanup_action,
                "reason": reason,
            }
        )
    return rows


def categorize(name: str) -> str:
    lowered = name.lower()
    for exact, category in CATEGORY_RULES:
        if lowered == exact:
            return category
    return "other"


def path_size(path: Path) -> int:
    try:
        stat = path.lstat()
    except OSError:
        return 0
    if path.is_symlink() or path.is_file():
        return stat.st_size
    if not path.is_dir():
        return stat.st_size

    total = 0
    for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
        current = Path(dirpath)
        try:
            total += current.lstat().st_size
        except OSError:
            pass
        for dirname in list(dirnames):
            child = current / dirname
            if child.is_symlink():
                try:
                    total += child.lstat().st_size
                except OSError:
                    pass
                dirnames.remove(dirname)
        for filename in filenames:
            child = current / filename
            try:
                total += child.lstat().st_size
            except OSError:
                pass
    return total


def cleanup_candidates(rows: list[dict[str, Any]], *, enabled: bool) -> list[dict[str, Any]]:
    if not enabled:
        return []
    candidates = [row for row in rows if str(row["cleanup_action"]) not in PROTECTED_ACTIONS and int(row["bytes"]) > 0]
    return sorted(candidates, key=lambda row: int(row["bytes"]), reverse=True)


def summarize(*, root: Path, budget_gb: float, rows: list[dict[str, Any]], cleanup_rows: list[dict[str, Any]]) -> dict[str, Any]:
    total_bytes = sum(int(row["bytes"]) for row in rows)
    budget_bytes = int(budget_gb * 1024**3)
    category_totals: dict[str, dict[str, Any]] = {}
    for row in rows:
        category = str(row["category"])
        entry = category_totals.setdefault(category, {"bytes": 0, "size_gb": 0.0, "paths": 0})
        entry["bytes"] += int(row["bytes"])
        entry["paths"] += 1
    for category in REQUIRED_CATEGORIES:
        category_totals.setdefault(category, {"bytes": 0, "size_gb": 0.0, "paths": 0})
    for entry in category_totals.values():
        entry["size_gb"] = bytes_to_gb(int(entry["bytes"]))

    cleanup_bytes = sum(int(row["bytes"]) for row in cleanup_rows)
    return {
        "root": str(root),
        "budget_gb": budget_gb,
        "total_bytes": total_bytes,
        "total_gb": bytes_to_gb(total_bytes),
        "under_budget": total_bytes <= budget_bytes,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "category_totals": category_totals,
        "cleanup_candidate_total_bytes": cleanup_bytes,
        "cleanup_candidate_total_gb": bytes_to_gb(cleanup_bytes),
    }


def write_tsv(path: Path, rows: list[dict[str, Any]], fields: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def bytes_to_gb(value: int) -> float:
    return round(value / 1024**3, 6)


def _same_or_contains(path: Path, child: Path) -> bool:
    return path == child or path in child.parents


if __name__ == "__main__":
    main()
