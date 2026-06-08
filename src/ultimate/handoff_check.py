from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from ultimate.template_resources import find_template_dir


NFCORE_HANDOFFS = {
    "nfcore_rnaseq": {
        "workflow": "nf-core/rnaseq",
        "module": "rnaseq",
        "required_phrase": "Ultimate does not execute nf-core/rnaseq",
    },
    "nfcore_scrnaseq": {
        "workflow": "nf-core/scrnaseq",
        "module": "scrna",
        "required_phrase": "Ultimate does not execute nf-core/scrnaseq",
    },
}

REQUIRED_FILES = (
    "README.md",
    "samplesheet.csv",
    "params.yaml",
    "nextflow.config",
    "command_plan.sh",
    "expected_matrix_import.yaml",
)


def run_handoff_check(*, root: Path | None = None, output_dir: Path | None = None) -> dict[str, Any]:
    """Check raw FASTQ upstream handoff templates without executing nf-core."""

    resolved_root = Path(root).resolve() if root else Path.cwd().resolve()
    if output_dir is None:
        output_dir = resolved_root / "audits" / "handoff_latest"
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for handoff_name, spec in NFCORE_HANDOFFS.items():
        rows.extend(_check_handoff_template(handoff_name, spec))

    ready_count = sum(1 for row in rows if row["status"] == "ready")
    blocked = [row for row in rows if row["status"] != "ready"]
    table_path = output_dir / "handoff_check.tsv"
    _write_rows(table_path, rows)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "ready" if not blocked else "blocked",
        "root": str(resolved_root),
        "output_dir": str(output_dir),
        "scope": "nf-core raw upstream handoff QA only; Ultimate does not execute these upstream workflows.",
        "checked_handoffs": sorted(NFCORE_HANDOFFS),
        "ready_checks": ready_count,
        "blocked_checks": len(blocked),
        "blockers": [f"{row['handoff']}:{row['check']}:{row['message']}" for row in blocked],
        "handoff_check_table": str(table_path),
    }
    manifest_path = output_dir / "handoff_check_manifest.json"
    manifest["manifest_path"] = str(manifest_path)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def _check_handoff_template(handoff_name: str, spec: dict[str, str]) -> list[dict[str, str]]:
    handoff_dir = find_template_dir("handoffs", handoff_name, required=False)
    rows: list[dict[str, str]] = []
    if handoff_dir is None:
        return [_row(handoff_name, "template_dir", "blocked", "template directory not found")]

    for filename in REQUIRED_FILES:
        path = handoff_dir / filename
        rows.append(_row(handoff_name, f"file:{filename}", "ready" if path.exists() and path.stat().st_size > 0 else "blocked", str(path)))

    command_plan = handoff_dir / "command_plan.sh"
    if command_plan.exists():
        text = command_plan.read_text(encoding="utf-8")
        _phrase(rows, handoff_name, "command_plan_not_executed", spec["required_phrase"], text)
        _phrase(rows, handoff_name, "command_plan_nextflow", f"nextflow run {spec['workflow']}", text)
        _phrase(rows, handoff_name, "command_plan_strict_shell", "set -euo pipefail", text)

    nextflow_config = handoff_dir / "nextflow.config"
    if nextflow_config.exists():
        text = nextflow_config.read_text(encoding="utf-8")
        _phrase(rows, handoff_name, "nextflow_slurm_executor", "executor = 'slurm'", text)
        rows.append(_row(handoff_name, "nextflow_no_home_cache", "blocked" if "/share/home" in text else "ready", "no /share/home path hardcoded"))

    readme = handoff_dir / "README.md"
    if readme.exists():
        text = readme.read_text(encoding="utf-8")
        _phrase(rows, handoff_name, "readme_fastq_boundary", "FASTQ 不直接进入 Ultimate core", text)
        _phrase(rows, handoff_name, "readme_open_source_handoff", "open-source upstream handoff", text)
        _phrase(rows, handoff_name, "readme_not_called", "not called by Ultimate", text)

    import_path = handoff_dir / "expected_matrix_import.yaml"
    if import_path.exists():
        try:
            payload = yaml.safe_load(import_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            rows.append(_row(handoff_name, "expected_import_yaml", "blocked", f"yaml parse failed: {exc}"))
        else:
            rows.extend(_check_expected_import(handoff_name, spec, payload))
    return rows


def _check_expected_import(handoff_name: str, spec: dict[str, str], payload: dict[str, Any]) -> list[dict[str, str]]:
    rows = []
    rows.append(
        _row(
            handoff_name,
            "expected_import_not_executed",
            "ready" if payload.get("execution_status") == "not_executed_by_ultimate" else "blocked",
            str(payload.get("execution_status", "")),
        )
    )
    gate = payload.get("production_gate") if isinstance(payload.get("production_gate"), dict) else {}
    rows.append(
        _row(
            handoff_name,
            "production_requires_approval",
            "ready" if gate.get("production_backend_requires_approval") is True else "blocked",
            str(gate.get("production_backend_requires_approval", "")),
        )
    )
    rows.append(
        _row(
            handoff_name,
            "raw_fastq_direct_import_forbidden",
            "ready" if gate.get("raw_fastq_direct_import_allowed") is False else "blocked",
            str(gate.get("raw_fastq_direct_import_allowed", "")),
        )
    )
    modules = (((payload.get("ultimate_import_config") or {}).get("modules") or {}) if isinstance(payload.get("ultimate_import_config"), dict) else {})
    module_cfg = modules.get(spec["module"]) if isinstance(modules, dict) else None
    rows.append(_row(handoff_name, "expected_import_module_present", "ready" if isinstance(module_cfg, dict) else "blocked", spec["module"]))
    if isinstance(module_cfg, dict):
        rows.append(_row(handoff_name, "expected_import_delivery_guard", "ready" if module_cfg.get("delivery_allowed") is False else "blocked", str(module_cfg.get("delivery_allowed", ""))))
        rows.append(_row(handoff_name, "expected_import_non_delivery_reason", "ready" if module_cfg.get("non_delivery_reason") else "blocked", str(module_cfg.get("non_delivery_reason", ""))))
    return rows


def _phrase(rows: list[dict[str, str]], handoff_name: str, check: str, phrase: str, text: str) -> None:
    rows.append(_row(handoff_name, check, "ready" if phrase in text else "blocked", phrase))


def _row(handoff: str, check: str, status: str, message: str) -> dict[str, str]:
    return {"handoff": handoff, "check": check, "status": status, "message": message}


def _write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    columns = ("handoff", "check", "status", "message")
    with path.open("w", encoding="utf-8") as handle:
        handle.write("\t".join(columns) + "\n")
        for row in rows:
            handle.write("\t".join(str(row.get(column, "")).replace("\t", " ").replace("\n", " ") for column in columns) + "\n")
