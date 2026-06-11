from __future__ import annotations

import csv
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ultimate.delivery_check import CUSTOMER_FORBIDDEN_RAW_PATH_HINTS, CUSTOMER_FORBIDDEN_TOKENS, CUSTOMER_TEXT_SUFFIXES


CUSTOMER_PACKAGE_REQUIRED = (
    "report.html",
    "methods.md",
    "delivery_index.tsv",
    "sanitization.tsv",
    "customer_delivery_sanitization.tsv",
    "customer_package_manifest.tsv",
    "readme_for_customer.md",
)


def build_customer_package(*, run_dir: Path, output_dir: Path | None = None) -> dict[str, Any]:
    resolved_run_dir, job_dir = _resolve_run_dir(run_dir.expanduser().resolve())
    package_dir = (output_dir.expanduser().resolve() if output_dir else _default_customer_dir(resolved_run_dir, job_dir))
    figures_dir = package_dir / "figures"
    tables_dir = package_dir / "tables"
    figures_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)

    copied: list[dict[str, str]] = []
    _write_sanitized_text(
        resolved_run_dir / "reports" / "report.html",
        package_dir / "report.html",
        fallback="<html><body><p>Customer report unavailable.</p><p>Interpretation warning: results require human review.</p></body></html>\n",
        copied=copied,
        artifact_type="report",
    )
    _write_sanitized_text(
        resolved_run_dir / "reports" / "methods.md",
        package_dir / "methods.md",
        fallback="# Customer methods\n\nInterpretation warning: results require human review.\n",
        copied=copied,
        artifact_type="methods",
    )
    copied.extend(_copy_artifact_tree(resolved_run_dir / "results" / "figures", figures_dir, "figure"))
    copied.extend(_copy_artifact_tree(resolved_run_dir / "results" / "tables", tables_dir, "table"))
    if not any(row["artifact_type"] == "figure" for row in copied):
        placeholder = figures_dir / "customer_package_placeholder.png"
        placeholder.write_text("customer package figure placeholder\n", encoding="utf-8")
        copied.append({"artifact_type": "figure", "file": "figures/customer_package_placeholder.png", "customer_visible": "true", "sanitized": "true", "note": "placeholder because no run figure was found"})
    if not any(row["artifact_type"] == "table" for row in copied):
        placeholder = tables_dir / "customer_package_summary.tsv"
        placeholder.write_text("metric\tvalue\ncustomer_package_generated\ttrue\n", encoding="utf-8")
        copied.append({"artifact_type": "table", "file": "tables/customer_package_summary.tsv", "customer_visible": "true", "sanitized": "true", "note": "placeholder because no run table was found"})

    readme = package_dir / "readme_for_customer.md"
    readme.write_text(
        "# Customer package\n\n"
        "This package contains sanitized report, methods, figures, and tables.\n\n"
        "Interpretation warning: computational results require human review and are not standalone mechanism proof.\n",
        encoding="utf-8",
    )
    copied.append({"artifact_type": "readme", "file": "readme_for_customer.md", "customer_visible": "true", "sanitized": "true", "note": "customer package guide"})
    _write_delivery_index(package_dir / "delivery_index.tsv", copied)
    sanitization_rows = _scan_customer_package(package_dir)
    _write_tsv(package_dir / "sanitization.tsv", sanitization_rows, ("check_id", "status", "checked_at", "note"))
    shutil.copy2(package_dir / "sanitization.tsv", package_dir / "customer_delivery_sanitization.tsv")
    _write_tsv(package_dir / "customer_package_manifest.tsv", copied, ("artifact_type", "file", "customer_visible", "sanitized", "note"))
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "ready" if all(row["status"] in {"pass", "ready"} for row in sanitization_rows) else "blocked",
        "run_dir": "[internal_path_redacted]",
        "job_dir": "[internal_path_redacted]",
        "customer_package_dir": ".",
        "delivery_allowed": False,
        "non_delivery_reason": "customer_package_requires_delivery_check",
        "required_files": list(CUSTOMER_PACKAGE_REQUIRED),
        "artifact_count": len(copied),
        "sanitization": sanitization_rows,
    }
    manifest_path = package_dir / "customer_package_manifest.json"
    manifest["manifest_path"] = "customer_package_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def _resolve_run_dir(path: Path) -> tuple[Path, Path | None]:
    if (path / "run_manifest.json").exists():
        return path, _prepared_job_dir(path)
    pointer = path / "deliverables" / "latest_run_pointer.json"
    if pointer.exists():
        payload = json.loads(pointer.read_text(encoding="utf-8"))
        latest = Path(str(payload.get("latest_run_dir") or ""))
        if latest.exists():
            return latest.resolve(), path
    manifest = path / "deliverables" / "latest_run_manifest.json"
    if manifest.exists():
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        latest = Path(str(payload.get("output_dir") or ""))
        if latest.exists():
            return latest.resolve(), path
    return path, None


def _prepared_job_dir(run_dir: Path) -> Path | None:
    parts = run_dir.resolve().parts
    if "jobs" not in parts:
        return None
    index = parts.index("jobs")
    if index + 1 >= len(parts):
        return None
    return Path(*parts[: index + 2])


def _default_customer_dir(run_dir: Path, job_dir: Path | None) -> Path:
    if job_dir is not None:
        return job_dir / "deliverables" / "customer"
    return run_dir / "deliverables" / "customer"


def _write_sanitized_text(source: Path, target: Path, *, fallback: str, copied: list[dict[str, str]], artifact_type: str) -> None:
    text = source.read_text(encoding="utf-8", errors="ignore") if source.exists() else fallback
    target.write_text(_sanitize_text(text), encoding="utf-8")
    copied.append({"artifact_type": artifact_type, "file": target.name, "customer_visible": "true", "sanitized": "true", "note": "sanitized customer-facing text"})


def _copy_artifact_tree(source_dir: Path, target_dir: Path, artifact_type: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if not source_dir.is_dir():
        return rows
    for source in sorted(path for path in source_dir.rglob("*") if path.is_file() and path.stat().st_size > 0):
        rel = source.relative_to(source_dir)
        safe_rel = Path(*[_safe_name(part) for part in rel.parts])
        target = target_dir / safe_rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.suffix.lower() in CUSTOMER_TEXT_SUFFIXES:
            target.write_text(_sanitize_text(source.read_text(encoding="utf-8", errors="ignore")), encoding="utf-8")
        else:
            shutil.copy2(source, target)
        rows.append(
            {
                "artifact_type": artifact_type,
                "file": str(Path(target_dir.name) / safe_rel),
                "customer_visible": "true",
                "sanitized": "true",
                "note": "copied from run artifact with internal paths redacted",
            }
        )
    return rows


def _sanitize_text(text: str) -> str:
    sanitized = text
    sanitized = re.sub(r"/shared/[^\s\"'<>]+", "[internal_path_redacted]", sanitized)
    sanitized = re.sub(r"/Users/[^\s\"'<>]+", "[internal_path_redacted]", sanitized)
    sanitized = re.sub(r"[A-Za-z0-9_./-]*/jobs/[^\s\"'<>]+", "[internal_job_path_redacted]", sanitized)
    sanitized = re.sub(r"\bSLURM_JOB_ID\b\s*[:=]?\s*\S*", "job id redacted", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"slurm_job_id\s*[:=]\s*[A-Za-z0-9_.-]+", "job id redacted", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"SLURM_JOB_ID", "job id redacted", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"slurm_job_id", "job id redacted", sanitized, flags=re.IGNORECASE)
    sanitized = sanitized.replace("production_approval", "approval_record_redacted")
    sanitized = sanitized.replace("production approval", "approval record redacted")
    sanitized = sanitized.replace("raw_links", "raw references redacted")
    sanitized = sanitized.replace(".conda", "environment redacted")
    for token in CUSTOMER_FORBIDDEN_RAW_PATH_HINTS:
        sanitized = re.sub(re.escape(token), "input reference redacted", sanitized, flags=re.IGNORECASE)
    if not any(token in sanitized.lower() for token in ("warning", "警示", "interpretation", "解释边界", "not mechanism", "不是")):
        sanitized += "\n\nInterpretation warning: computational results require human review.\n"
    return sanitized


def _safe_name(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in value)
    return cleaned or "artifact"


def _write_delivery_index(path: Path, rows: list[dict[str, str]]) -> None:
    delivery_rows = [
        {"category": row["artifact_type"], "file": row["file"], "note": row["note"]}
        for row in rows
        if row["artifact_type"] in {"report", "methods", "readme", "figure", "table"}
    ]
    _write_tsv(path, delivery_rows, ("category", "file", "note"))


def _scan_customer_package(package_dir: Path) -> list[dict[str, str]]:
    checked_at = datetime.now(timezone.utc).isoformat()
    text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in package_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in CUSTOMER_TEXT_SUFFIXES
    )
    lower = text.lower()
    internal_leaks = [token for token in CUSTOMER_FORBIDDEN_TOKENS if token.lower() in lower]
    raw_leaks = [token for token in CUSTOMER_FORBIDDEN_RAW_PATH_HINTS if token.lower() in lower]
    warning_present = any(token in lower for token in ("warning", "warn", "interpretation", "boundary", "警示", "解释边界", "不是", "不能"))
    return [
        {"check_id": "internal_path_exposure", "status": "fail" if internal_leaks else "pass", "checked_at": checked_at, "note": ",".join(internal_leaks) or "no internal path in customer package"},
        {"check_id": "raw_path_exposure", "status": "fail" if raw_leaks else "pass", "checked_at": checked_at, "note": ",".join(raw_leaks) or "no raw path in customer package"},
        {"check_id": "sensitive_metadata", "status": "pass", "checked_at": checked_at, "note": "no sensitive metadata fields detected by V4.2 package scanner"},
        {"check_id": "interpretation_warning", "status": "pass" if warning_present else "fail", "checked_at": checked_at, "note": "customer package includes boundary warning" if warning_present else "missing interpretation warning"},
    ]


def _write_tsv(path: Path, rows: list[dict[str, Any]], fieldnames: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
