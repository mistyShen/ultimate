from __future__ import annotations

import json
import shutil
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ultimate.config import dump_yaml, load_config, resolve_path


JOB_SUBDIRS = ("raw_links", "config", "samples", "runs", "logs", "deliverables", "reproducible_code")


def prepare_job(
    *,
    config_path: Path,
    job_id: str,
    root: Path = Path("/shared/shen/2026/ultimate"),
    samplesheet: Path | None = None,
    analysis_request: Path | None = None,
    run_mode: str = "production",
) -> dict[str, Any]:
    if run_mode not in {"production", "interactive"}:
        raise ValueError("run_mode must be one of: production, interactive")
    clean_job_id = _clean_job_id(job_id)
    root = root.expanduser().resolve()
    job_dir = root / "jobs" / clean_job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    for name in JOB_SUBDIRS:
        (job_dir / name).mkdir(parents=True, exist_ok=True)
    _write_raw_links_readme(job_dir / "raw_links" / "README.md")

    loaded = load_config(config_path)
    config = loaded.raw
    selected_samplesheet = samplesheet or _configured_samplesheet(config, loaded.base_dir)
    selected_request = analysis_request or _configured_analysis_request(config, loaded.base_dir)
    copied_samplesheet = _copy_optional(selected_samplesheet, job_dir / "samples")
    copied_request = _copy_optional(selected_request, job_dir / "config")

    config.setdefault("project", {})
    config["project"]["job_id"] = clean_job_id
    config["project"]["server_root"] = str(root)
    config["project"]["run_mode"] = run_mode
    config["project"]["output_dir"] = f"../runs/{clean_job_id}"
    approval_path = job_dir / "config" / "production_approval.json"
    if run_mode == "production":
        config["project"]["production_approval"] = "../config/production_approval.json"
    if copied_samplesheet:
        config.setdefault("samples", {})
        config["samples"]["samplesheet"] = f"../samples/{copied_samplesheet.name}"
    if copied_request:
        config["analysis_request"] = f"../config/{copied_request.name}"

    job_config = dump_yaml(config, job_dir / "config" / "project.yaml")
    approval_template = _write_approval_template(approval_path, config_path=job_config, output_dir=job_dir / "runs" / clean_job_id)
    command_plan = _write_command_plan(job_dir / "config" / "command_plan.md", root=root, job_config=job_config, approval_path=approval_path, run_mode=run_mode)
    submit_script = _write_submit_script(job_dir / "config" / "submit.sh", root=root, job_config=job_config, approval_path=approval_path, run_mode=run_mode)

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "job_id": clean_job_id,
        "root": str(root),
        "job_dir": str(job_dir),
        "run_mode": run_mode,
        "source_config": str(config_path.expanduser().resolve()),
        "config_path": str(job_config),
        "samplesheet": str(copied_samplesheet) if copied_samplesheet else "",
        "analysis_request": str(copied_request) if copied_request else "",
        "approval_template": str(approval_template),
        "command_plan": str(command_plan),
        "submit_script": str(submit_script),
        "directories": {name: str(job_dir / name) for name in JOB_SUBDIRS},
        "safety": {
            "raw_data_policy": "read_only; do not copy or overwrite raw data; use raw_links for symlinks or manifests",
            "production_policy": "production_backend requires approval JSON with approved=true before running",
            "compute_policy": "formal raw or large jobs should be submitted through Slurm",
        },
    }
    manifest_path = job_dir / "job_manifest.json"
    manifest["manifest_path"] = str(manifest_path)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def _clean_job_id(job_id: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(job_id).strip())
    if not cleaned:
        raise ValueError("job_id cannot be empty")
    return cleaned


def _configured_samplesheet(config: dict[str, Any], base_dir: Path) -> Path | None:
    samples = config.get("samples")
    if isinstance(samples, dict) and samples.get("samplesheet"):
        return resolve_path(base_dir, samples["samplesheet"])
    return None


def _configured_analysis_request(config: dict[str, Any], base_dir: Path) -> Path | None:
    request = config.get("analysis_request") or (config.get("project") or {}).get("analysis_request")
    if isinstance(request, (str, Path)):
        return resolve_path(base_dir, request)
    return None


def _copy_optional(path: Path | None, target_dir: Path, *, preferred_name: str | None = None) -> Path | None:
    if not path or not path.exists():
        return None
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / (preferred_name or path.name)
    shutil.copy2(path, target)
    return target


def _write_raw_links_readme(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "# raw_links",
                "",
                "This directory is for symlinks or small manifests pointing to raw data.",
                "Do not copy, move, overwrite, or edit customer raw data here.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _write_approval_template(path: Path, *, config_path: Path, output_dir: Path) -> Path:
    payload = {
        "approved": False,
        "approved_by": "",
        "approved_at": "",
        "project_id": config_path.parents[1].name,
        "input_path": str(config_path.resolve()),
        "output_dir": str(output_dir.resolve()),
        "reason": "Set approved=true only after user has confirmed this is a production delivery run.",
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _write_command_plan(path: Path, *, root: Path, job_config: Path, approval_path: Path, run_mode: str) -> Path:
    approval_arg = f" {approval_path}" if run_mode == "production" else ""
    log_dir = job_config.parents[1] / "logs"
    lines = [
        "# Ultimate job command plan",
        "",
        "## Preflight",
        "",
        "```bash",
        f"ultimate preflight --config {job_config}",
        "```",
        "",
        "## Slurm run",
        "",
        "```bash",
        f"hpc-sbatch {root / 'slurm' / 'ultimate_run.sbatch'} {job_config}{approval_arg}",
        "```",
        "",
        f"运行日志会镜像到：`{log_dir}`。",
        "",
        "## Rebuild delivery/repro package",
        "",
        "```bash",
        f"ultimate export-repro --run-dir {job_config.parents[1] / 'runs' / job_config.parents[1].name}",
        "```",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _write_submit_script(path: Path, *, root: Path, job_config: Path, approval_path: Path, run_mode: str) -> Path:
    approval_arg = f' "{approval_path}"' if run_mode == "production" else ""
    content = f"""#!/usr/bin/env bash
set -euo pipefail

JOB_DIR="{job_config.parents[1]}"
LOG_DIR="$JOB_DIR/logs"
mkdir -p "$LOG_DIR"
SUBMIT_LOG="$LOG_DIR/slurm_submit_$(date -u +%Y%m%dT%H%M%SZ).log"
echo "hpc-sbatch {root / 'slurm' / 'ultimate_run.sbatch'} {job_config}{approval_arg}" | tee "$SUBMIT_LOG"
hpc-sbatch "{root / 'slurm' / 'ultimate_run.sbatch'}" "{job_config}"{approval_arg} | tee -a "$SUBMIT_LOG"
"""
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
    return path
