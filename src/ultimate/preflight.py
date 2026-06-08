from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ultimate.config import enabled_modules, load_analysis_request, load_samples, output_dir
from ultimate.backend_registry import build_backend_plan
from ultimate.bulk import BULK_MODULES, bulk_requirement_checks
from ultimate.constants import MODULE_SPECS
from ultimate.raw_qc import PATH_COLUMNS, RAW_CONTRACTS
from ultimate.scepi_backend import inspect_scepi_input_contract


def run_preflight(config: dict[str, Any], *, write: bool = True) -> dict[str, Any]:
    out_dir = output_dir(config)
    samples = load_samples(config)
    strict = _strict_mode(config)
    output_check = _output_safety_check(config, out_dir)
    job_layout = _job_layout_check(config, out_dir, strict=strict)
    analysis_request = load_analysis_request(config)
    analysis_request_status = _analysis_request_status(analysis_request)
    module_reports = []
    for module_name in enabled_modules(config):
        module_reports.append(_check_module(config, samples, module_name, strict=strict))

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project": config.get("project", {}),
        "analysis_request": analysis_request,
        "analysis_request_status": analysis_request_status,
        "output_dir": str(out_dir),
        "organism": config.get("project", {}).get("organism"),
        "strict_mode": strict,
        "output_safety": output_check,
        "job_layout": job_layout,
        "licensed_tool_checks": _licensed_tool_checks(config),
        "samples": {
            "n_rows": int(samples.shape[0]),
            "columns": list(samples.columns),
            "missing_required_columns": _missing_columns(samples, ("sample_id", "condition")),
        },
        "modules": module_reports,
        "tool_checks": _global_tool_checks(),
    }
    manifest["status"] = _overall_status(module_reports, samples, output_check, job_layout, analysis_request_status, strict=strict)
    if write:
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "preflight_manifest.json"
        path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        manifest["manifest_path"] = str(path)
    return manifest


def _check_module(config: dict[str, Any], samples: pd.DataFrame, module_name: str, *, strict: bool = False) -> dict[str, Any]:
    spec = MODULE_SPECS[module_name]
    module_cfg = (config.get("modules") or {}).get(module_name) or {}
    input_matrix = module_cfg.get("input_matrix")
    samplesheet = module_cfg.get("samplesheet") or (config.get("samples") or {}).get("samplesheet")
    checks = {
        "input_matrix": _path_check(input_matrix),
        "samplesheet": _path_check(samplesheet),
        "required_sample_columns": _missing_columns(samples, spec.required_columns),
        "optional_commands": _command_checks(spec.optional_commands, config),
        "optional_r_packages": _r_package_checks(spec.optional_r_packages, config, module_name),
        "python_packages": bulk_requirement_checks(module_name) if module_name in BULK_MODULES else {},
    }
    backend_plan = build_backend_plan(module_name, config)
    raw_report = _raw_preflight(module_cfg, samples, module_name)
    checks["raw"] = raw_report
    checks["backend_plan"] = backend_plan
    if module_name == "scepi":
        checks["scepi_matrix_contract"] = inspect_scepi_input_contract(config, samples=samples)
    warnings = []
    if checks["required_sample_columns"]:
        warnings.append("missing_required_sample_columns")
    if not checks["input_matrix"]["exists"]:
        warnings.append("input_matrix_missing_or_not_configured")
    missing_commands = [cmd for cmd, ok in checks["optional_commands"].items() if not ok]
    missing_python = [pkg for pkg, ok in checks["python_packages"].items() if not ok]
    if missing_commands:
        warnings.append("optional_commands_missing:" + ",".join(missing_commands))
    if missing_python:
        warnings.append("python_packages_missing:" + ",".join(missing_python))
    if raw_report["raw_enabled"] and raw_report["missing_required_columns"]:
        warnings.append("raw_missing_required_columns:" + ",".join(raw_report["missing_required_columns"]))
    if raw_report["raw_enabled"] and raw_report["input_type"] not in raw_report["supported_input_types"]:
        warnings.append("raw_unsupported_input_type:" + raw_report["input_type"])
    if module_name == "scepi":
        scepi_status = str(checks["scepi_matrix_contract"].get("status", ""))
        if scepi_status.startswith("partial"):
            warnings.append("scepi_matrix_contract:" + scepi_status)
        if not checks["scepi_matrix_contract"].get("differential_preview_ready"):
            warnings.append("scepi_differential_preview_handoff_only")
    missing_raw_paths = raw_report.get("missing_input_paths") or []
    if strict and raw_report["raw_enabled"] and missing_raw_paths:
        warnings.append("raw_input_paths_missing:" + ",".join(missing_raw_paths[:5]))
    warnings.extend(backend_plan.get("interpretation_warnings") or [])
    return {
        "module": module_name,
        "title_cn": spec.title_cn,
        "input_kind": spec.input_kind,
        "backend_plan": backend_plan,
        "checks": checks,
        "warnings": warnings,
        "status": "ready_with_warnings" if warnings else "ready",
    }


def _raw_preflight(module_cfg: dict[str, Any], samples: pd.DataFrame, module_name: str) -> dict[str, Any]:
    contract = RAW_CONTRACTS[module_name]
    raw_cfg = module_cfg.get("raw") or {}
    enabled = bool(raw_cfg.get("enabled", True))
    input_type = str(raw_cfg.get("input_type") or contract.input_types[0])
    raw_samplesheet = raw_cfg.get("samplesheet")
    raw_samples = samples
    if raw_samplesheet and Path(raw_samplesheet).exists():
        raw_samples = pd.read_csv(raw_samplesheet, sep=None, engine="python")
    missing_paths = _missing_raw_input_paths(raw_samples)
    return {
        "raw_enabled": enabled,
        "input_type": input_type,
        "supported_input_types": list(contract.input_types),
        "samplesheet": _path_check(raw_samplesheet),
        "required_columns": list(contract.required_columns),
        "missing_required_columns": _missing_columns(raw_samples, contract.required_columns),
        "declared_output_matrix": _path_check(raw_cfg.get("output_matrix")),
        "declared_output_object": _path_check(raw_cfg.get("output_object")),
        "missing_input_paths": missing_paths,
        "existing_input_path_count": _existing_raw_input_count(raw_samples),
        "toolchain": list(raw_cfg.get("toolchain") or contract.open_replacements),
        "open_replacements": list(contract.open_replacements),
        "raw_tools_on_path": {tool: bool(shutil.which(tool)) for tool in contract.tools},
    }


def _missing_raw_input_paths(frame: pd.DataFrame) -> list[str]:
    if frame.empty:
        return []
    missing: list[str] = []
    for _, row in frame.iterrows():
        for column in PATH_COLUMNS:
            value = str(row.get(column, "") or "")
            if value and not Path(value).exists():
                missing.append(f"{column}:{value}")
    return missing


def _existing_raw_input_count(frame: pd.DataFrame) -> int:
    if frame.empty:
        return 0
    count = 0
    for _, row in frame.iterrows():
        for column in PATH_COLUMNS:
            value = str(row.get(column, "") or "")
            if value and Path(value).exists():
                count += 1
    return count


def _path_check(value: Any) -> dict[str, Any]:
    if value is None:
        return {"path": None, "exists": False, "kind": None}
    path = Path(value)
    return {
        "path": str(path),
        "exists": path.exists(),
        "kind": "dir" if path.is_dir() else "file" if path.is_file() else None,
    }


def _missing_columns(frame: pd.DataFrame, required: tuple[str, ...]) -> list[str]:
    if frame.empty:
        return list(required)
    return [column for column in required if column not in frame.columns]


def _global_tool_checks() -> dict[str, Any]:
    python_packages = ["click", "yaml", "pandas", "numpy", "matplotlib", "seaborn", "jinja2"]
    commands = ["snakemake", "Rscript", "conda", "mamba", "sbatch"]
    return {
        "commands": {cmd: bool(shutil.which(cmd)) for cmd in commands},
        "python_packages": {pkg: importlib.util.find_spec(pkg) is not None for pkg in python_packages},
    }


def _strict_mode(config: dict[str, Any]) -> bool:
    project = config.get("project") or {}
    return bool(
        project.get("strict_preflight")
        or str(project.get("run_mode", "")).lower() == "production"
        or os.environ.get("ULTIMATE_STRICT_PREFLIGHT")
    )


def _output_safety_check(config: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    project = config.get("project") or {}
    allow = bool(project.get("overwrite") or project.get("allow_overwrite") or os.environ.get("ULTIMATE_ALLOW_OVERWRITE"))
    existing_manifest = out_dir / "run_manifest.json"
    return {
        "output_dir": str(out_dir),
        "exists": out_dir.exists(),
        "existing_run_manifest": str(existing_manifest) if existing_manifest.exists() else "",
        "allow_overwrite": allow,
        "status": "blocked:existing_run_manifest" if existing_manifest.exists() and not allow else "ready",
    }


def _job_layout_check(config: dict[str, Any], out_dir: Path, *, strict: bool = False) -> dict[str, Any]:
    project = config.get("project") or {}
    server_root = Path(str(project.get("server_root", "/shared/shen/2026/ultimate"))).resolve()
    job_id = str(project.get("job_id", "") or "")
    expected_job_dir = (server_root / "jobs" / job_id).resolve() if job_id else None
    if not job_id:
        return {
            "job_id": "",
            "expected_job_dir": "",
            "output_dir": str(out_dir),
            "status": "blocked:missing_job_id" if strict else "not_required",
        }
    try:
        inside = expected_job_dir in [out_dir.resolve(), *out_dir.resolve().parents]
    except OSError:
        inside = False
    return {
        "job_id": job_id,
        "expected_job_dir": str(expected_job_dir),
        "output_dir": str(out_dir),
        "status": "ready" if inside else "blocked:output_not_under_job_dir",
    }


def _licensed_tool_checks(config: dict[str, Any]) -> dict[str, Any]:
    resources = config.get("resources") or {}
    licensed = resources.get("licensed_tools") if isinstance(resources.get("licensed_tools"), dict) else {}
    checks = {}
    for name, command in {
        "bcl_convert": "bcl-convert",
        "bcl2fastq": "bcl2fastq",
        "cellranger": "cellranger",
        "cellranger_vdj": "cellranger",
        "cellranger_atac": "cellranger-atac",
        "cellranger_arc": "cellranger-arc",
        "spaceranger": "spaceranger",
    }.items():
        configured = licensed.get(name) if isinstance(licensed, dict) else None
        checks[name] = {
            "configured_path": str(configured) if configured else "",
            "configured_exists": bool(configured and Path(str(configured)).exists()),
            "command_on_path": bool(shutil.which(command)),
            "policy": "user_provided_path_only",
        }
    cibersort = licensed.get("cibersort") if isinstance(licensed, dict) else None
    checks["cibersort"] = {
        "configured_path": str(cibersort) if cibersort else "",
        "configured_exists": bool(cibersort and Path(str(cibersort)).exists()),
        "command_on_path": False,
        "policy": "user_provided_script_or_signature_only",
    }
    return checks


def _command_checks(commands: tuple[str, ...], config: dict[str, Any]) -> dict[str, bool]:
    roots = _env_bin_roots(config)
    checks = {}
    for command in commands:
        configured = _configured_tool_path(command, config)
        checks[command] = bool(configured and configured.exists()) or bool(shutil.which(command)) or any((root / command).exists() for root in roots)
    return checks


def _configured_tool_path(command: str, config: dict[str, Any]) -> Path | None:
    resources = config.get("resources") or {}
    licensed = resources.get("licensed_tools") if isinstance(resources.get("licensed_tools"), dict) else {}
    aliases = {
        "bcl-convert": ("bcl_convert",),
        "bcl2fastq": ("bcl2fastq",),
        "cellranger": ("cellranger", "cellranger_vdj"),
        "cellranger-atac": ("cellranger_atac",),
        "cellranger-arc": ("cellranger_arc",),
        "spaceranger": ("spaceranger", "space_ranger"),
    }
    for key in aliases.get(command, (command.replace("-", "_"), command)):
        value = licensed.get(key) if isinstance(licensed, dict) else None
        if value:
            return Path(str(value))
    return None


def _r_package_checks(packages: tuple[str, ...], config: dict[str, Any] | None = None, module_name: str | None = None) -> dict[str, str]:
    candidates = []
    if shutil.which("Rscript"):
        candidates.append(Path(shutil.which("Rscript") or "Rscript"))
    if config is not None:
        for env_name in _candidate_env_names(module_name):
            rscript = Path((config.get("project") or {}).get("server_root", "/shared/shen/2026/ultimate")) / ".conda" / "envs" / env_name / "bin" / "Rscript"
            if rscript.exists():
                candidates.append(rscript)
    if not candidates:
        return {pkg: "not_checked:Rscript_missing" for pkg in packages}
    script = "cat(paste(installed.packages()[, 'Package'], collapse='\\n'))"
    installed = set()
    errors = []
    for rscript in candidates:
        try:
            completed = subprocess.run(
                [str(rscript), "-e", script],
                check=False,
                text=True,
                capture_output=True,
                timeout=45,
            )
        except Exception as exc:
            errors.append(f"{rscript}:{type(exc).__name__}")
            continue
        installed.update(completed.stdout.splitlines())
    if not installed and errors:
        return {pkg: "not_checked:" + ",".join(errors[:2]) for pkg in packages}
    return {pkg: "available" if pkg in installed else "missing_optional" for pkg in packages}


def _env_bin_roots(config: dict[str, Any]) -> list[Path]:
    root = Path((config.get("project") or {}).get("server_root", "/shared/shen/2026/ultimate"))
    envs = [
        "ultimate-core",
        "ultimate-rnaseq",
        "ultimate-methylation",
        "ultimate-proteomics",
        "ultimate-publicdb",
        "ultimate-wgcna",
        "ultimate-scrna",
        "ultimate-scrna-r",
        "ultimate-scatac-py",
        "ultimate-scatac-r",
        "ultimate-scatac-multiome",
        "ultimate-genome-mtdna",
        "ultimate-vdj",
        "ultimate-vdj-r",
        "ultimate-spatial",
        "ultimate-spatial-py",
        "ultimate-spatial-r",
        "ultimate-browser",
    ]
    return [root / ".conda" / "envs" / env / "bin" for env in envs]


def _candidate_env_names(module_name: str | None) -> list[str]:
    common = ["ultimate-core"]
    specific = {
        "rnaseq": ["ultimate-rnaseq"],
        "methylation": ["ultimate-methylation"],
        "proteomics": ["ultimate-proteomics"],
        "publicdb": ["ultimate-publicdb"],
        "wgcna": ["ultimate-wgcna"],
        "scrna": ["ultimate-scrna", "ultimate-scrna-r"],
        "scatac": ["ultimate-scatac-multiome", "ultimate-scatac-r"],
        "multiome": ["ultimate-scatac-multiome", "ultimate-scatac-r"],
        "vdj": ["ultimate-vdj", "ultimate-vdj-r"],
        "spatial": ["ultimate-spatial", "ultimate-spatial-r"],
        "perturb_seq": ["ultimate-scrna", "ultimate-scrna-r"],
        "hto_demux": ["ultimate-scrna", "ultimate-scrna-r"],
        "genotype_demux": ["ultimate-genome-mtdna"],
        "functional_state": ["ultimate-scrna", "ultimate-publicdb"],
        "tumor_sc": ["ultimate-scrna", "ultimate-publicdb"],
        "clinical_assoc": ["ultimate-publicdb"],
        "single_gene": ["ultimate-publicdb"],
        "method_tools": ["ultimate-scrna", "ultimate-scrna-r"],
        "scepi": ["ultimate-scatac-multiome", "ultimate-methylation"],
    }.get(module_name or "", [])
    return specific + common


def _analysis_request_status(analysis_request: dict[str, Any]) -> dict[str, Any]:
    if not analysis_request:
        return {
            "status": "missing",
            "reason": "analysis_request_not_configured",
        }
    if analysis_request.get("status") == "missing":
        return {
            "status": "missing",
            "reason": "analysis_request_path_missing",
            "source": str(analysis_request.get("source", "")),
        }
    return {
        "status": "ready",
        "reason": "analysis_request_loaded",
    }


def _overall_status(
    module_reports: list[dict[str, Any]],
    samples: pd.DataFrame,
    output_check: dict[str, Any],
    job_layout: dict[str, Any],
    analysis_request_status: dict[str, Any],
    *,
    strict: bool = False,
) -> str:
    if output_check["status"].startswith("blocked"):
        return output_check["status"]
    if strict and str(job_layout.get("status", "")).startswith("blocked"):
        return str(job_layout["status"])
    if strict and analysis_request_status.get("status") != "ready":
        return "blocked:missing_analysis_request"
    if samples.empty:
        return "blocked:no_samples"
    if any(report["checks"]["required_sample_columns"] for report in module_reports):
        return "blocked:sample_schema"
    if strict and any("raw_input_paths_missing:" in warning for report in module_reports for warning in report["warnings"]):
        return "blocked:raw_input_paths_missing"
    if any("input_matrix_missing_or_not_configured" in report["warnings"] for report in module_reports):
        return "ready_with_warnings"
    return "ready"
