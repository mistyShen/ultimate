from __future__ import annotations

import json
import os
import platform
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ultimate.approval_gate import load_production_approval
from ultimate.config import dump_yaml, enabled_modules, load_analysis_request, load_config, load_samples, output_dir
from ultimate.manifest_schema import build_delivery_gate
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
    run_id = str(config.get("_run_id") or _run_id(config))
    config["_run_id"] = run_id
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
    slurm_context = _slurm_context()
    module_manifests = []
    for module_name in enabled_modules(config):
        _write_module_log(
            out_dir,
            module_name,
            {
                "event": "module_started",
                "module": module_name,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "config": config.get("_config_path", "<config.yaml>"),
            },
        )
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
        _attach_slurm_to_backend(module_manifest, slurm_context)
        module_manifest["raw_qc"] = raw_manifest
        module_manifests.append(module_manifest)
        _write_module_log(
            out_dir,
            module_name,
            {
                "event": "module_completed",
                "module": module_name,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "status": module_manifest.get("status"),
                "analysis_level": module_manifest.get("analysis_level"),
                "delivery_allowed": module_manifest.get("delivery_allowed"),
                "validation_evidence_allowed": module_manifest.get("validation_evidence_allowed"),
                "manifest_path": module_manifest.get("manifest_path"),
                "skip_reasons": module_manifest.get("skip_reasons", []),
            },
        )
    run_summary = _summarize_run(module_manifests)
    approval_summary = _approval_summary(production_approval)
    delivery_gate = build_delivery_gate(
        modules=module_manifests,
        production_approval=approval_summary,
        run_status=run_summary["status"],
    )
    run_level_fields = _aggregate_run_level_fields(module_manifests, delivery_gate)
    manifest = {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": run_summary["status"],
        **run_level_fields,
        "project": config.get("project", {}),
        "analysis_request": analysis_request,
        "output_dir": str(out_dir),
        "config_snapshot": str(config_snapshot),
        "reproducible_command": f"ultimate run --config {config.get('_config_path', '<config.yaml>')}",
        "slurm_job_id": slurm_context.get("slurm_job_id", ""),
        "slurm_job_name": slurm_context.get("slurm_job_name", ""),
        "slurm": slurm_context,
        "python": {
            "version": sys.version.split()[0],
            "executable": sys.executable,
            "platform": platform.platform(),
        },
        "preflight": preflight,
        "figure_style": active_style,
        "style_review": style_review,
        "production_approval": approval_summary,
        "delivery_gate": delivery_gate,
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
        "logs": {
            "directory": str(out_dir / "logs"),
            "module_logs": {module.get("module"): str(out_dir / "logs" / f"{module.get('module')}.log") for module in module_manifests},
        },
    }
    manifest_path = out_dir / "run_manifest.json"
    manifest["run_manifest_path"] = str(manifest_path)
    manifest["logs"]["run_context"] = str(_write_run_context_log(out_dir, manifest))
    return finalize_run_outputs(out_dir, manifest_path, manifest)


def finalize_run_outputs(out_dir: Path, manifest_path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """Write manifest, reproducibility package, and reports with a stable order."""
    out_dir = out_dir.resolve()
    manifest_path = manifest_path.resolve()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    repro_manifest = export_reproducible_package(out_dir)
    manifest["reproducible_package"] = repro_manifest
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    report_manifest = build_report(out_dir)
    manifest["report"] = report_manifest
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    report_manifest = build_report(out_dir)
    manifest["report"] = report_manifest
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    repro_manifest = export_reproducible_package(out_dir)
    manifest["reproducible_package"] = repro_manifest
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    _mirror_final_run_manifest(out_dir, manifest_path)
    return manifest


def _mirror_final_run_manifest(out_dir: Path, manifest_path: Path) -> None:
    parts = out_dir.resolve().parts
    if "jobs" not in parts or "runs" not in parts:
        return
    try:
        jobs_index = parts.index("jobs")
        runs_index = parts.index("runs")
    except ValueError:
        return
    if runs_index <= jobs_index + 1:
        return
    job_dir = Path(*parts[: jobs_index + 2])
    target = job_dir / "deliverables" / "latest_run_manifest.json"
    if target.parent.exists():
        shutil.copy2(manifest_path, target)


def _write_module_log(run_dir: Path, module_name: str, payload: dict[str, Any]) -> Path:
    path = run_dir / "logs" / f"{module_name}.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def _write_run_context_log(run_dir: Path, manifest: dict[str, Any]) -> Path:
    path = run_dir / "logs" / "run_context.json"
    payload = {
        "run_id": manifest.get("run_id"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": manifest.get("status"),
        "delivery_gate": manifest.get("delivery_gate", {}),
        "analysis_level_summary": [
            {
                "module": module.get("module"),
                "status": module.get("status"),
                "analysis_level": module.get("analysis_level"),
                "delivery_allowed": module.get("delivery_allowed"),
                "validation_evidence_allowed": module.get("validation_evidence_allowed"),
            }
            for module in manifest.get("modules", [])
            if isinstance(module, dict)
        ],
        "slurm": manifest.get("slurm", {}),
        "reproducible_command": manifest.get("reproducible_command"),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _attach_slurm_to_backend(module_manifest: dict[str, Any], slurm_context: dict[str, str]) -> None:
    job_id = str(slurm_context.get("slurm_job_id") or "")
    if not job_id:
        return
    module_manifest["backend_slurm_job_id"] = job_id
    backend = module_manifest.get("backend")
    if isinstance(backend, dict):
        backend["backend_slurm_job_id"] = job_id
    plan = module_manifest.get("backend_plan")
    if isinstance(plan, dict):
        plan["backend_slurm_job_id"] = job_id


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
        "input_path": str(approval.get("input_path", "")),
        "output_dir": str(approval.get("output_dir", "")),
        "delivery_scope": str(approval.get("delivery_scope", "")),
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


def _aggregate_run_level_fields(module_manifests: list[dict[str, Any]], delivery_gate: dict[str, Any]) -> dict[str, Any]:
    levels = {str(module.get("analysis_level") or "") for module in module_manifests if isinstance(module, dict)}
    if "production_backend" in levels:
        analysis_level = "production_backend"
    elif "validated_backend" in levels:
        analysis_level = "validated_backend"
    elif levels and levels <= {"demo_result"}:
        analysis_level = "demo_result"
    else:
        analysis_level = "smoke_backend"
    is_demo = any(module.get("is_demo") is True for module in module_manifests if isinstance(module, dict))
    is_stub = any(module.get("is_stub") is True for module in module_manifests if isinstance(module, dict))
    delivery_allowed = bool(delivery_gate.get("delivery_allowed") is True)
    validation_evidence_allowed = bool(delivery_gate.get("validation_evidence_allowed") is True and not is_demo and not is_stub)
    reasons = [
        str(module.get("non_delivery_reason"))
        for module in module_manifests
        if isinstance(module, dict) and module.get("non_delivery_reason")
    ]
    gate_reason = str(delivery_gate.get("non_delivery_reason") or "")
    non_delivery_reason = "" if delivery_allowed else (gate_reason or ";".join(sorted(set(reasons))) or "not_marked_for_delivery")
    delivery_scope = str(delivery_gate.get("delivery_scope") or "not_applicable")
    return {
        "analysis_level": analysis_level,
        "is_demo": is_demo,
        "is_stub": is_stub,
        "delivery_allowed": delivery_allowed,
        "validation_evidence_allowed": validation_evidence_allowed,
        "non_delivery_reason": non_delivery_reason,
        "delivery_scope": delivery_scope,
    }
