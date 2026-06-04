from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


INDEX_FIELDS = (
    "run_name",
    "status",
    "guard_status",
    "analysis_level",
    "is_demo",
    "is_stub",
    "delivery_allowed",
    "validation_evidence_allowed",
    "non_delivery_reason",
    "slurm_job_id",
    "input",
    "dataset",
    "n_cells",
    "n_genes",
    "n_spots",
    "n_peaks",
    "n_clonotypes",
    "n_clusters",
    "n_figures",
    "n_tables",
    "object_keys",
    "run_dir",
    "manifest_path",
    "report_html",
    "skip_reason",
    "guard_missing_fields",
    "guard_invalid_fields",
)

REQUIRED_GUARD_FIELDS = (
    "analysis_level",
    "is_demo",
    "is_stub",
    "delivery_allowed",
    "validation_evidence_allowed",
    "non_delivery_reason",
)

VALID_ANALYSIS_LEVELS = {"demo_result", "smoke_backend", "validated_backend", "production_backend"}


def build_validation_index(root: Path, output_dir: Path | None = None, validations_dir: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    validations_dir = (validations_dir or root / "validations").resolve()
    output_dir = (output_dir or root / "reports" / "validation_index").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = [_row_from_manifest(path) for path in _iter_validation_manifests(root=root, validations_dir=validations_dir)]
    rows = [row for row in rows if row is not None]

    tsv_path = output_dir / "validation_index.tsv"
    json_path = output_dir / "validation_index.json"
    md_path = output_dir / "report.md"
    html_path = output_dir / "report.html"
    _write_tsv(tsv_path, rows)
    json_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    summary = _summary(rows)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "validations_dir": str(validations_dir),
        "output_dir": str(output_dir),
        "validation_index_tsv": str(tsv_path),
        "validation_index_json": str(json_path),
        "report_md": str(md_path),
        "report_html": str(html_path),
        "summary": summary,
        "n_runs": len(rows),
    }
    (output_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_reports(md_path, html_path, rows, manifest)
    return manifest


def _iter_validation_manifests(*, root: Path, validations_dir: Path) -> list[Path]:
    paths = set(validations_dir.glob("*/run_manifest.json"))
    paths.update((root / "validation_runs").glob("*/*/run_manifest.json"))
    paths.update((root / "validations" / "bulk_demo_python" / "project" / "runs").glob("*/run_manifest.json"))
    return sorted(path for path in paths if path.exists())


def _row_from_manifest(path: Path) -> dict[str, str] | None:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    run_dir = path.parent
    reports = run_dir / "reports" / "report.html"
    input_value = (
        manifest.get("input_h5ad")
        or manifest.get("input_h5")
        or manifest.get("input_dir")
        or manifest.get("input_path")
        or manifest.get("source_root")
        or ""
    )
    row = {
        "run_name": run_dir.name,
        "status": str(manifest.get("status", "")),
        "guard_status": _guard_status(manifest)[0],
        "analysis_level": str(manifest.get("analysis_level", "")),
        "is_demo": _stringify_bool(manifest.get("is_demo", "")),
        "is_stub": _stringify_bool(manifest.get("is_stub", "")),
        "delivery_allowed": _stringify_bool(manifest.get("delivery_allowed", "")),
        "validation_evidence_allowed": _stringify_bool(manifest.get("validation_evidence_allowed", "")),
        "non_delivery_reason": str(manifest.get("non_delivery_reason", "")),
        "slurm_job_id": str(manifest.get("slurm_job_id") or ((manifest.get("slurm") or {}).get("job_id") or "")),
        "input": str(input_value),
        "dataset": str(manifest.get("dataset", manifest.get("dataset_label", ""))),
        "n_cells": _stringify(manifest.get("n_cells")),
        "n_genes": _stringify(manifest.get("n_genes")),
        "n_spots": _stringify(manifest.get("n_spots")),
        "n_peaks": _stringify(manifest.get("n_peaks")),
        "n_clonotypes": _stringify(manifest.get("n_clonotypes")),
        "n_clusters": _stringify(manifest.get("n_clusters")),
        "n_figures": str(len(manifest.get("figures", []))),
        "n_tables": str(len(manifest.get("tables", []))),
        "object_keys": ",".join(sorted((manifest.get("objects") or {}).keys())),
        "run_dir": str(run_dir),
        "manifest_path": str(path),
        "report_html": str(reports) if reports.exists() else "",
        "skip_reason": str(manifest.get("skip_reason", "")),
        "guard_missing_fields": ",".join(_guard_status(manifest)[1]),
        "guard_invalid_fields": ",".join(_guard_status(manifest)[2]),
    }
    return row


def _stringify(value: Any) -> str:
    return "" if value is None else str(value)


def _stringify_bool(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else str(value)


def _guard_status(manifest: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    missing = [field for field in REQUIRED_GUARD_FIELDS if field not in manifest]
    invalid = _invalid_guard_fields(manifest)
    if missing:
        return "missing_guard_fields", missing, invalid
    if invalid:
        return "invalid_guard_fields", missing, invalid
    return "ready", missing, invalid


def _invalid_guard_fields(manifest: dict[str, Any]) -> list[str]:
    invalid: list[str] = []
    if manifest.get("analysis_level") not in VALID_ANALYSIS_LEVELS:
        invalid.append("analysis_level")
    for field in ("is_demo", "is_stub", "delivery_allowed", "validation_evidence_allowed"):
        if not isinstance(manifest.get(field), bool):
            invalid.append(field)
    if manifest.get("delivery_allowed") is True and manifest.get("analysis_level") != "production_backend":
        invalid.append("delivery_allowed_requires_production_backend")
    if manifest.get("validation_evidence_allowed") is True and manifest.get("analysis_level") not in {
        "validated_backend",
        "production_backend",
    }:
        invalid.append("validation_evidence_requires_validated_or_production")
    if manifest.get("delivery_allowed") is False and not manifest.get("non_delivery_reason"):
        invalid.append("non_delivery_reason")
    return invalid


def _summary(rows: list[dict[str, str]]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for row in rows:
        status = row["status"] or "unknown"
        summary[status] = summary.get(status, 0) + 1
    return summary


def _write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=INDEX_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _write_reports(md_path: Path, html_path: Path, rows: list[dict[str, str]], manifest: dict[str, Any]) -> None:
    lines = [
        "# Ultimate 验证结果总索引",
        "",
        f"生成时间：{manifest['generated_at']}",
        f"验证目录：`{manifest['validations_dir']}`",
        "",
        "## 摘要",
        *[f"- {status}: {count}" for status, count in manifest["summary"].items()],
        "",
        "| Run | 状态 | 图 | 表 | 对象 | 规模 |",
        "|---|---|---:|---:|---|---|",
    ]
    for row in rows:
        scale = ", ".join(
            f"{label}={row[key]}"
            for label, key in (
                ("cells", "n_cells"),
                ("genes", "n_genes"),
                ("spots", "n_spots"),
                ("peaks", "n_peaks"),
                ("clonotypes", "n_clonotypes"),
                ("clusters", "n_clusters"),
            )
            if row[key]
        )
        lines.append(
            f"| {row['run_name']} | `{row['status']}` / `{row['guard_status']}` | {row['n_figures']} | {row['n_tables']} | {row['object_keys'] or '-'} | {scale or '-'} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    html_rows = "\n".join(
        "<tr>"
        f"<td>{row['run_name']}</td><td><code>{row['status']}</code></td><td><code>{row['guard_status']}</code></td>"
        f"<td>{row['analysis_level'] or '-'}</td><td>{row['delivery_allowed'] or '-'}</td>"
        f"<td>{row['n_figures']}</td><td>{row['n_tables']}</td><td>{row['object_keys'] or '-'}</td>"
        f"<td>{row['run_dir']}</td>"
        "</tr>"
        for row in rows
    )
    html_path.write_text(
        f"""<!doctype html>
<html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><title>Ultimate 验证结果总索引</title>
<style>body{{font-family:sans-serif;margin:32px}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ddd;padding:6px}}th{{background:#f6f8fa}}</style>
</head><body><h1>Ultimate 验证结果总索引</h1><p>生成时间：{manifest['generated_at']}</p>
<p>验证目录：<code>{manifest['validations_dir']}</code></p>
<table><thead><tr><th>Run</th><th>状态</th><th>Guard</th><th>analysis_level</th><th>delivery_allowed</th><th>图</th><th>表</th><th>对象</th><th>目录</th></tr></thead>
<tbody>{html_rows}</tbody></table></body></html>""",
        encoding="utf-8",
    )
