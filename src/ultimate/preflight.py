from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ultimate.config import enabled_modules, load_samples, output_dir
from ultimate.constants import MODULE_SPECS
from ultimate.raw_qc import RAW_CONTRACTS


def run_preflight(config: dict[str, Any], *, write: bool = True) -> dict[str, Any]:
    out_dir = output_dir(config)
    samples = load_samples(config)
    module_reports = []
    for module_name in enabled_modules(config):
        module_reports.append(_check_module(config, samples, module_name))

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project": config.get("project", {}),
        "output_dir": str(out_dir),
        "organism": config.get("project", {}).get("organism"),
        "samples": {
            "n_rows": int(samples.shape[0]),
            "columns": list(samples.columns),
            "missing_required_columns": _missing_columns(samples, ("sample_id", "condition")),
        },
        "modules": module_reports,
        "tool_checks": _global_tool_checks(),
        "status": _overall_status(module_reports, samples),
    }
    if write:
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "preflight_manifest.json"
        path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        manifest["manifest_path"] = str(path)
    return manifest


def _check_module(config: dict[str, Any], samples: pd.DataFrame, module_name: str) -> dict[str, Any]:
    spec = MODULE_SPECS[module_name]
    module_cfg = (config.get("modules") or {}).get(module_name) or {}
    input_matrix = module_cfg.get("input_matrix")
    samplesheet = module_cfg.get("samplesheet") or (config.get("samples") or {}).get("samplesheet")
    checks = {
        "input_matrix": _path_check(input_matrix),
        "samplesheet": _path_check(samplesheet),
        "required_sample_columns": _missing_columns(samples, spec.required_columns),
        "optional_commands": {cmd: bool(shutil.which(cmd)) for cmd in spec.optional_commands},
        "optional_r_packages": _r_package_checks(spec.optional_r_packages),
    }
    raw_report = _raw_preflight(module_cfg, samples, module_name)
    checks["raw"] = raw_report
    warnings = []
    if checks["required_sample_columns"]:
        warnings.append("missing_required_sample_columns")
    if not checks["input_matrix"]["exists"]:
        warnings.append("input_matrix_missing_or_not_configured")
    missing_commands = [cmd for cmd, ok in checks["optional_commands"].items() if not ok]
    if missing_commands:
        warnings.append("optional_commands_missing:" + ",".join(missing_commands))
    if raw_report["raw_enabled"] and raw_report["missing_required_columns"]:
        warnings.append("raw_missing_required_columns:" + ",".join(raw_report["missing_required_columns"]))
    if raw_report["raw_enabled"] and raw_report["input_type"] not in raw_report["supported_input_types"]:
        warnings.append("raw_unsupported_input_type:" + raw_report["input_type"])
    return {
        "module": module_name,
        "title_cn": spec.title_cn,
        "input_kind": spec.input_kind,
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
    return {
        "raw_enabled": enabled,
        "input_type": input_type,
        "supported_input_types": list(contract.input_types),
        "samplesheet": _path_check(raw_samplesheet),
        "required_columns": list(contract.required_columns),
        "missing_required_columns": _missing_columns(raw_samples, contract.required_columns),
        "declared_output_matrix": _path_check(raw_cfg.get("output_matrix")),
        "declared_output_object": _path_check(raw_cfg.get("output_object")),
        "toolchain": list(raw_cfg.get("toolchain") or contract.open_replacements),
        "open_replacements": list(contract.open_replacements),
        "raw_tools_on_path": {tool: bool(shutil.which(tool)) for tool in contract.tools},
    }


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


def _r_package_checks(packages: tuple[str, ...]) -> dict[str, str]:
    if not shutil.which("Rscript"):
        return {pkg: "not_checked:Rscript_missing" for pkg in packages}
    script = "cat(paste(installed.packages()[, 'Package'], collapse='\\n'))"
    try:
        completed = subprocess.run(
            ["Rscript", "-e", script],
            check=False,
            text=True,
            capture_output=True,
            timeout=20,
        )
    except Exception as exc:
        return {pkg: f"not_checked:{type(exc).__name__}" for pkg in packages}
    installed = set(completed.stdout.splitlines())
    return {pkg: "available" if pkg in installed else "missing_optional" for pkg in packages}


def _overall_status(module_reports: list[dict[str, Any]], samples: pd.DataFrame) -> str:
    if samples.empty:
        return "blocked:no_samples"
    if any(report["checks"]["required_sample_columns"] for report in module_reports):
        return "blocked:sample_schema"
    if any("input_matrix_missing_or_not_configured" in report["warnings"] for report in module_reports):
        return "ready_with_warnings"
    return "ready"
