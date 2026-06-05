from __future__ import annotations

import csv
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from ultimate.constants import MODULE_ORDER, MODULE_SPECS, SUPPORTED_ORGANISMS


TRIAGE_STATUSES = {
    "ready_to_run",
    "needs_metadata",
    "needs_dependency",
    "needs_license",
    "needs_manual_review",
    "not_supported",
}

TRIAGE_PRESETS = {
    "basic",
    "standard",
    "tumor",
    "trajectory",
    "communication",
    "velocity",
    "publication",
    "handoff_required",
}

LICENSED_TOOL_TOKENS = {
    "bcl-convert",
    "bcl2fastq",
    "cellranger",
    "cell ranger",
    "cellranger-atac",
    "cellranger-arc",
    "spaceranger",
    "space ranger",
    "cibersort",
}


def run_triage(request_path: Path, output_dir: Path) -> dict[str, Any]:
    request_path = request_path.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    request = _load_request(request_path)
    modules = _requested_modules(request)
    presets = _requested_presets(request)
    missing_rows: list[dict[str, str]] = []
    risk_rows: list[dict[str, str]] = []

    unsupported = [module for module in modules if module not in MODULE_SPECS]
    if unsupported:
        for module in unsupported:
            missing_rows.append(_missing("module", module, "not_supported", "模块不在 Ultimate 支持列表中。"))

    organism = str((request.get("project") or {}).get("organism") or request.get("organism") or "human").lower()
    if organism not in SUPPORTED_ORGANISMS:
        missing_rows.append(_missing("organism", organism, "not_supported", f"仅支持 {','.join(sorted(SUPPORTED_ORGANISMS))}。"))

    samplesheet = _first_value(request, ("samplesheet", "sample_sheet", "samples"))
    if not samplesheet:
        missing_rows.append(_missing("metadata", "samplesheet", "needs_metadata", "缺少样本表路径或内联样本信息。"))
    elif isinstance(samplesheet, str) and not Path(samplesheet).expanduser().exists():
        missing_rows.append(_missing("metadata", "samplesheet", "needs_metadata", f"样本表不存在：{samplesheet}"))

    licensed_tools = _licensed_tools(request)
    for tool in licensed_tools:
        missing_rows.append(_missing("license", tool, "needs_license", "授权或商业工具只做路径检测，需用户提供可执行路径。"))

    missing_dependencies = _missing_dependencies(request)
    for command in missing_dependencies:
        missing_rows.append(_missing("dependency", command, "needs_dependency", "请求中指定的命令当前 PATH 不可用。"))

    invalid_presets = [preset for preset in presets if preset not in TRIAGE_PRESETS]
    for preset in invalid_presets:
        risk_rows.append(_risk("preset", preset, "unknown_preset", "未知 preset，需要人工确认。"))
    if "handoff_required" in presets:
        risk_rows.append(_risk("handoff", "handoff_required", "handoff_required", "请求需要 handoff/adapter，triage 不会自动开跑。"))
    if any(module in {"tumor_sc", "scdna", "mtdna"} for module in modules):
        risk_rows.append(_risk("interpretation", ",".join(modules), "specialty_caveat", "专项模块输出需要证据链和限制说明。"))

    status = _triage_status(missing_rows, risk_rows)
    suggested_project = _suggested_project_yaml(request, modules, presets, organism, samplesheet)
    samplesheet_path = _write_samplesheet_template(output_dir / "samplesheet_template.tsv", modules)
    suggested_project_path = output_dir / "suggested_project.yaml"
    suggested_project_path.write_text(yaml.safe_dump(suggested_project, allow_unicode=True, sort_keys=False), encoding="utf-8")
    slurm_command_path = output_dir / "slurm_command.txt"
    slurm_command_path.write_text(
        "hpc-sbatch /shared/shen/2026/ultimate/slurm/ultimate_run.sbatch "
        f"{suggested_project_path}\n",
        encoding="utf-8",
    )
    missing_path = _write_tsv(output_dir / "missing_requirements.tsv", missing_rows, ("category", "item", "status", "note"))
    risk_path = _write_tsv(output_dir / "risk_flags.tsv", risk_rows, ("category", "item", "risk", "note"))

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "request_path": str(request_path),
        "output_dir": str(output_dir),
        "status": status,
        "analysis_level": "smoke_backend",
        "is_demo": False,
        "is_stub": False,
        "delivery_allowed": False,
        "validation_evidence_allowed": False,
        "non_delivery_reason": "triage_only_not_analysis_run",
        "requested_modules": modules,
        "presets": presets,
        "unsupported_modules": unsupported,
        "licensed_tools": licensed_tools,
        "missing_dependencies": missing_dependencies,
        "missing_requirements": str(missing_path),
        "risk_flags": str(risk_path),
        "suggested_project_yaml": str(suggested_project_path),
        "samplesheet": str(samplesheet_path),
        "slurm_command": str(slurm_command_path),
        "note": "triage 只做技术判断，不开跑、不报价、不生成 production approval 或 run_manifest。",
    }
    manifest_path = output_dir / "triage_manifest.json"
    manifest["manifest_path"] = str(manifest_path)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    report_md = _write_report_md(output_dir / "triage_report.md", manifest, missing_rows, risk_rows)
    report_html = _write_report_html(output_dir / "triage_report.html", manifest, missing_rows, risk_rows)
    manifest["triage_report_md"] = str(report_md)
    manifest["triage_report_html"] = str(report_html)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def _load_request(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing analysis request: {path}")
    if path.suffix.lower() in {".yaml", ".yml"}:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    elif path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = {"notes": path.read_text(encoding="utf-8")}
    if not isinstance(data, dict):
        raise TypeError("analysis request must be a mapping")
    return data


def _requested_modules(request: dict[str, Any]) -> list[str]:
    candidates = (
        request.get("modules")
        or request.get("enabled_modules")
        or request.get("project_type")
        or (request.get("project") or {}).get("type")
        or []
    )
    if isinstance(candidates, str):
        modules = [candidates]
    else:
        modules = [str(item) for item in candidates]
    if not modules or modules == ["all"]:
        return ["rnaseq"]
    return modules


def _requested_presets(request: dict[str, Any]) -> list[str]:
    candidates = request.get("presets") or request.get("analysis_presets") or request.get("preset") or ["standard"]
    if isinstance(candidates, str):
        return [candidates]
    return [str(item) for item in candidates]


def _first_value(request: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if request.get(key):
            return request[key]
    samples = request.get("samples")
    if isinstance(samples, dict):
        return samples.get("samplesheet") or samples.get("items")
    return None


def _licensed_tools(request: dict[str, Any]) -> list[str]:
    tools = request.get("licensed_tools") or request.get("required_licensed_tools") or request.get("tools") or []
    if isinstance(tools, str):
        tools = [tools]
    found = []
    for tool in tools:
        token = str(tool).strip()
        if token and any(licensed in token.lower() for licensed in LICENSED_TOOL_TOKENS):
            found.append(token)
    return sorted(set(found))


def _missing_dependencies(request: dict[str, Any]) -> list[str]:
    commands = request.get("required_commands") or request.get("dependencies") or []
    if isinstance(commands, str):
        commands = [commands]
    missing = [str(command) for command in commands if str(command) and shutil.which(str(command)) is None]
    return sorted(set(missing))


def _triage_status(missing_rows: list[dict[str, str]], risk_rows: list[dict[str, str]]) -> str:
    statuses = {row["status"] for row in missing_rows}
    if "not_supported" in statuses:
        return "not_supported"
    if "needs_license" in statuses:
        return "needs_license"
    if "needs_dependency" in statuses:
        return "needs_dependency"
    if "needs_metadata" in statuses:
        return "needs_metadata"
    if any(row["risk"] in {"unknown_preset", "specialty_caveat"} for row in risk_rows):
        return "needs_manual_review"
    return "ready_to_run"


def _suggested_project_yaml(
    request: dict[str, Any],
    modules: list[str],
    presets: list[str],
    organism: str,
    samplesheet: Any,
) -> dict[str, Any]:
    job_id = str(request.get("job_id") or request.get("request_id") or "triage_suggested_job")
    enabled = {module: {"enabled": module in modules, "analysis_level": "smoke_backend"} for module in MODULE_ORDER}
    return {
        "project": {
            "name": job_id,
            "organism": organism,
            "output_dir": f"/shared/shen/2026/ultimate/jobs/{job_id}/runs/{job_id}",
            "server_root": "/shared/shen/2026/ultimate",
            "run_mode": "interactive",
        },
        "analysis_request": {
            "source": str(request.get("request_id") or job_id),
            "presets": presets,
            "triage_status": "triage_only",
        },
        "samples": {"samplesheet": str(samplesheet) if isinstance(samplesheet, str) else "samples/samples.tsv"},
        "design": {
            "condition_column": "condition",
            "control": "control",
            "case": "treated",
            "comparisons": ["treated_vs_control"],
        },
        "modules": enabled,
    }


def _write_samplesheet_template(path: Path, modules: list[str]) -> Path:
    columns = ["sample_id", "condition", "batch", "input_path"]
    if "rnaseq" in modules:
        columns.extend(["fastq_1", "fastq_2"])
    if "scrna" in modules:
        columns.extend(["input_type", "tenx_path"])
    row = {column: "" for column in dict.fromkeys(columns)}
    row["sample_id"] = "sample_001"
    row["condition"] = "control"
    row["batch"] = "batch1"
    _write_tsv(path, [row], tuple(row))
    return path


def _missing(category: str, item: str, status: str, note: str) -> dict[str, str]:
    return {"category": category, "item": item, "status": status, "note": note}


def _risk(category: str, item: str, risk: str, note: str) -> dict[str, str]:
    return {"category": category, "item": item, "risk": risk, "note": note}


def _write_tsv(path: Path, rows: list[dict[str, str]], fieldnames: tuple[str, ...]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _write_report_md(path: Path, manifest: dict[str, Any], missing_rows: list[dict[str, str]], risk_rows: list[dict[str, str]]) -> Path:
    lines = [
        "# Ultimate triage report",
        "",
        f"- status: `{manifest['status']}`",
        "- analysis_level: `smoke_backend`",
        "- delivery_allowed: `false`",
        "- non_delivery_reason: `triage_only_not_analysis_run`",
        f"- requested_modules: `{', '.join(manifest['requested_modules'])}`",
        f"- presets: `{', '.join(manifest['presets'])}`",
        "",
        "## Missing requirements",
        *(f"- {row['category']} / {row['item']}: {row['status']} - {row['note']}" for row in missing_rows),
        "",
        "## Risk flags",
        *(f"- {row['category']} / {row['item']}: {row['risk']} - {row['note']}" for row in risk_rows),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_report_html(path: Path, manifest: dict[str, Any], missing_rows: list[dict[str, str]], risk_rows: list[dict[str, str]]) -> Path:
    missing = "".join(f"<li>{row['category']} / {row['item']}: <code>{row['status']}</code> - {row['note']}</li>" for row in missing_rows)
    risks = "".join(f"<li>{row['category']} / {row['item']}: <code>{row['risk']}</code> - {row['note']}</li>" for row in risk_rows)
    html = f"""<!doctype html>
<html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><title>Ultimate triage report</title></head>
<body>
<h1>Ultimate triage report</h1>
<p>status: <code>{manifest['status']}</code></p>
<p>analysis_level: <code>smoke_backend</code>; delivery_allowed: <code>false</code></p>
<p>non_delivery_reason: <code>triage_only_not_analysis_run</code></p>
<h2>Missing requirements</h2><ul>{missing or '<li>none</li>'}</ul>
<h2>Risk flags</h2><ul>{risks or '<li>none</li>'}</ul>
</body></html>
"""
    path.write_text(html, encoding="utf-8")
    return path
