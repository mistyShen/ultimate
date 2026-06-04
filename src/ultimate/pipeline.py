from __future__ import annotations

import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ultimate.approval_gate import load_production_approval
from ultimate.config import dump_yaml, enabled_modules, load_analysis_request, load_config, load_samples, output_dir
from ultimate.modules import run_module
from ultimate.plot_style import generate_style_review, set_active_style_from_config
from ultimate.preflight import run_preflight
from ultimate.raw_qc import run_raw_qc
from ultimate.report import build_report
from ultimate.reproducibility import export_reproducible_package


def run_pipeline_from_config(config_path: Path, *, production_approval_path: Path | None = None) -> dict[str, Any]:
    loaded = load_config(config_path)
    loaded.raw["_config_path"] = str(loaded.path)
    return run_pipeline(loaded.raw, config_path=loaded.path, production_approval_path=production_approval_path)


def run_pipeline(config: dict[str, Any], *, config_path: Path | None = None, production_approval_path: Path | None = None) -> dict[str, Any]:
    out_dir = output_dir(config)
    production_approval = _load_pipeline_approval(config, config_path=config_path, output_dir=out_dir, approval_path=production_approval_path)
    for directory in ("results/figures", "results/tables", "objects", "reports", "logs", "raw_qc"):
        (out_dir / directory).mkdir(parents=True, exist_ok=True)
    active_style = set_active_style_from_config(config)
    config_snapshot = dump_yaml(config, out_dir / "config_snapshot.yaml")
    preflight = run_preflight(config, write=True)
    if str(preflight.get("status", "")).startswith("blocked"):
        raise RuntimeError(f"Preflight blocked run: {preflight['status']}")
    samples = load_samples(config)
    analysis_request = load_analysis_request(config)
    style_review = generate_style_review(out_dir / "reports" / "style_review")
    module_manifests = []
    for module_name in enabled_modules(config):
        raw_manifest = run_raw_qc(
            module_name=module_name,
            config=config,
            output_dir=out_dir,
            samples=samples,
        )
        _attach_raw_handoff(config, module_name, raw_manifest)
        module_manifest = run_module(
            module_name=module_name,
            config=config,
            output_dir=out_dir,
            samples=samples,
        )
        module_manifest["raw_qc"] = raw_manifest
        module_manifests.append(module_manifest)
    run_summary = _summarize_run(module_manifests)
    manifest = {
        "run_id": _run_id(config),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": run_summary["status"],
        "project": config.get("project", {}),
        "analysis_request": analysis_request,
        "output_dir": str(out_dir),
        "config_snapshot": str(config_snapshot),
        "reproducible_command": f"ultimate run --config {config.get('_config_path', '<config.yaml>')}",
        "slurm": _slurm_context(),
        "python": {
            "version": sys.version.split()[0],
            "executable": sys.executable,
            "platform": platform.platform(),
        },
        "preflight": preflight,
        "figure_style": active_style,
        "style_review": style_review,
        "production_approval": _approval_summary(production_approval),
        "modules": module_manifests,
        "module_status": run_summary["module_status"],
        "summary": run_summary,
        "artifacts_root": {
            "figures": str(out_dir / "results" / "figures"),
            "tables": str(out_dir / "results" / "tables"),
            "objects": str(out_dir / "objects"),
            "reports": str(out_dir / "reports"),
            "logs": str(out_dir / "logs"),
        },
    }
    manifest_path = out_dir / "run_manifest.json"
    manifest["run_manifest_path"] = str(manifest_path)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    report_manifest = build_report(out_dir)
    manifest["report"] = report_manifest
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    repro_manifest = export_reproducible_package(out_dir)
    manifest["reproducible_package"] = repro_manifest
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    report_manifest = build_report(out_dir)
    manifest["report"] = report_manifest
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    export_reproducible_package(out_dir)
    return manifest


def _load_pipeline_approval(
    config: dict[str, Any],
    *,
    config_path: Path | None,
    output_dir: Path,
    approval_path: Path | None,
) -> dict[str, Any] | None:
    if not _production_requested(config):
        return None
    configured = (config.get("project") or {}).get("production_approval")
    selected = approval_path or (Path(str(configured)) if configured else None)
    approval_input = config_path or Path(str(config.get("_config_path") or "config.yaml"))
    try:
        return load_production_approval(
            selected,
            analysis_level="production_backend",
            input_path=approval_input,
            output_dir=output_dir,
        )
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc


def _production_requested(config: dict[str, Any]) -> bool:
    project = config.get("project") or {}
    if str(project.get("analysis_level", "")).lower() == "production_backend":
        return True
    if str(project.get("run_mode", "")).lower() == "production":
        return True
    for module_cfg in (config.get("modules") or {}).values():
        if isinstance(module_cfg, dict) and str(module_cfg.get("analysis_level", "")).lower() == "production_backend":
            return True
    return False


def _approval_summary(approval: dict[str, Any] | None) -> dict[str, Any]:
    if not approval:
        return {}
    return {
        "approved": bool(approval.get("approved")),
        "approved_by": str(approval.get("approved_by", "")),
        "approved_at": str(approval.get("approved_at", "")),
        "project_id": str(approval.get("project_id", "")),
        "reason": str(approval.get("reason", "")),
        "approval_path": str(approval.get("_approval_path", "")),
    }


def _slurm_context() -> dict[str, str]:
    keys = ("SLURM_JOB_ID", "SLURM_JOB_NAME", "SLURM_SUBMIT_DIR", "SLURM_CPUS_PER_TASK", "SLURM_MEM_PER_NODE", "SLURM_JOB_NODELIST")
    return {key.lower(): os.environ.get(key, "") for key in keys}


def _attach_raw_handoff(config: dict[str, Any], module_name: str, raw_manifest: dict[str, Any]) -> None:
    module_cfg = (config.get("modules") or {}).setdefault(module_name, {})
    current = module_cfg.get("input_matrix")
    if current and Path(current).exists():
        return
    standard_matrix = ((raw_manifest.get("artifacts") or {}).get("objects") or {}).get("standard_matrix")
    if standard_matrix and Path(standard_matrix).exists():
        module_cfg["input_matrix"] = standard_matrix


def _run_id(config: dict[str, Any]) -> str:
    project = config.get("project") or {}
    name = str(project.get("name") or "ultimate_run").strip() or "ultimate_run"
    safe_name = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in name)
    return f"{safe_name}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"


def _summarize_run(module_manifests: list[dict[str, Any]]) -> dict[str, Any]:
    module_status = {str(module.get("module")): str(module.get("status", "unknown")) for module in module_manifests}
    module_skip_reasons = {
        str(module.get("module")): module.get("skip_reasons", [])
        for module in module_manifests
        if module.get("skip_reasons")
    }
    partial_modules = [
        module_name
        for module_name, status in module_status.items()
        if status.startswith("partial") or status.startswith("missing") or status.startswith("failed")
    ]
    status = "ready" if not partial_modules else "partial"
    return {
        "status": status,
        "module_count": len(module_manifests),
        "ready_module_count": len(module_manifests) - len(partial_modules),
        "partial_module_count": len(partial_modules),
        "partial_modules": partial_modules,
        "module_status": module_status,
        "module_skip_reasons": module_skip_reasons,
    }
