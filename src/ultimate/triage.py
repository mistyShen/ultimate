from __future__ import annotations

import csv
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from ultimate.constants import MODULE_ORDER, MODULE_SPECS, SUPPORTED_ORGANISMS
from ultimate.raw_qc import MATRIX_INPUT_KEYS, MATRIX_LIKE_INPUT_TYPES, PATH_COLUMNS


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
    request_base = request_path.parent
    modules = _requested_modules(request)
    presets = _requested_presets(request)
    missing_rows: list[dict[str, str]] = []
    risk_rows: list[dict[str, str]] = []
    samplesheet = _first_value(request, ("samplesheet", "sample_sheet", "samples"))
    resolved_samplesheet = _resolve_request_value(request_base, samplesheet)
    samplesheet_frame, samplesheet_issue = _read_samplesheet(resolved_samplesheet)
    if samplesheet_issue:
        risk_rows.append(_risk("metadata", "samplesheet", "samplesheet_read_warning", samplesheet_issue))
    input_assessment = _assess_inputs(request, _collect_input_rows(request), samplesheet_frame, modules, request_base)

    unsupported = [module for module in modules if module not in MODULE_SPECS]
    if unsupported:
        for module in unsupported:
            missing_rows.append(_missing("module", module, "not_supported", "模块不在 Ultimate 支持列表中。"))

    organism = str((request.get("project") or {}).get("organism") or request.get("organism") or "human").lower()
    if organism not in SUPPORTED_ORGANISMS:
        missing_rows.append(_missing("organism", organism, "not_supported", f"仅支持 {','.join(sorted(SUPPORTED_ORGANISMS))}。"))

    if not resolved_samplesheet:
        missing_rows.append(_missing("metadata", "samplesheet", "needs_metadata", "缺少样本表路径或内联样本信息。"))
    elif isinstance(resolved_samplesheet, str) and not Path(resolved_samplesheet).expanduser().exists():
        missing_rows.append(_missing("metadata", "samplesheet", "needs_metadata", f"样本表不存在：{resolved_samplesheet}"))
    if samplesheet_frame is not None:
        missing_sample_columns = _missing_sample_columns(samplesheet_frame, modules)
        for column in missing_sample_columns:
            missing_rows.append(_missing("metadata", f"samplesheet.{column}", "needs_metadata", f"样本表缺少必需列：{column}"))
    if input_assessment["raw_upstream_detected"] and not input_assessment["standard_input_detected"]:
        missing_rows.append(
            _missing(
                "upstream_handoff",
                ",".join(input_assessment["raw_input_types"]) or "raw_input",
                "needs_manual_review",
                "检测到 FASTQ/BCL/fragments 等上游输入；Ultimate core 需要先通过 nf-core/授权工具/开源上游生成标准矩阵或对象。",
            )
        )
        if "handoff_required" not in presets:
            presets.append("handoff_required")
    elif not input_assessment["standard_input_detected"] and not input_assessment["raw_upstream_detected"]:
        risk_rows.append(_risk("input", "data_path", "input_path_not_declared", "未在 request 或样本表中检测到明确数据路径；需要人工确认输入列。"))

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
    suggested_project = _suggested_project_yaml(request, modules, presets, organism, resolved_samplesheet, input_assessment)
    samplesheet_path = _write_samplesheet_template(output_dir / "samplesheet_template.tsv", modules)
    input_assessment_path = _write_tsv(
        output_dir / "input_assessment.tsv",
        input_assessment["rows"],
        ("source", "key", "path", "input_type", "input_role", "exists", "note"),
    )
    suggested_project_path = output_dir / "suggested_project.yaml"
    suggested_project_path.write_text(yaml.safe_dump(suggested_project, allow_unicode=True, sort_keys=False), encoding="utf-8")
    handoff_plan_path = _write_handoff_plan(output_dir / "handoff_plan.md", modules, input_assessment)
    slurm_command_path = output_dir / "slurm_command.txt"
    slurm_command_path.write_text(
        "\n".join(
            [
                "# Review suggested_project.yaml, then scaffold a job. This triage command plan does not start analysis.",
                f"ultimate prepare-job --config {suggested_project_path} --job-id {request.get('job_id') or request.get('request_id') or 'triage_suggested_job'} --root /shared/shen/2026/ultimate --run-mode production",
                f"hpc-sbatch /shared/shen/2026/ultimate/jobs/{request.get('job_id') or request.get('request_id') or 'triage_suggested_job'}/config/run_ultimate.sbatch",
                "",
            ]
        ),
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
        "input_assessment": str(input_assessment_path),
        "input_summary": {
            "standard_input_detected": input_assessment["standard_input_detected"],
            "raw_upstream_detected": input_assessment["raw_upstream_detected"],
            "standard_input_types": input_assessment["standard_input_types"],
            "raw_input_types": input_assessment["raw_input_types"],
            "handoff_required": input_assessment["handoff_required"],
        },
        "handoff_plan": str(handoff_plan_path),
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
        text = path.read_text(encoding="utf-8")
        hints = _parse_text_request_hints(text)
        data = {"notes": text, "parsed_text_hints": hints, **hints.get("fields", {})}
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
        hints = request.get("parsed_text_hints") if isinstance(request.get("parsed_text_hints"), dict) else {}
        hinted = hints.get("modules") if isinstance(hints, dict) else None
        if hinted:
            return [str(item) for item in hinted]
        return ["rnaseq"]
    return modules


def _requested_presets(request: dict[str, Any]) -> list[str]:
    candidates = request.get("presets") or request.get("analysis_presets") or request.get("preset")
    if not candidates:
        hints = request.get("parsed_text_hints") if isinstance(request.get("parsed_text_hints"), dict) else {}
        candidates = hints.get("presets") if isinstance(hints, dict) else None
    candidates = candidates or ["standard"]
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


def _resolve_request_value(base_dir: Path, value: Any) -> Any:
    if isinstance(value, str):
        path = Path(value).expanduser()
        return str(path if path.is_absolute() else (base_dir / path).resolve())
    return value


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
    if "needs_manual_review" in statuses:
        return "needs_manual_review"
    if any(row["risk"] in {"unknown_preset", "specialty_caveat"} for row in risk_rows):
        return "needs_manual_review"
    return "ready_to_run"


def _suggested_project_yaml(
    request: dict[str, Any],
    modules: list[str],
    presets: list[str],
    organism: str,
    samplesheet: Any,
    input_assessment: dict[str, Any],
) -> dict[str, Any]:
    job_id = str(request.get("job_id") or request.get("request_id") or "triage_suggested_job")
    standard_input = _primary_input(input_assessment, "standard_input")
    raw_input = _primary_input(input_assessment, "raw_upstream")
    enabled: dict[str, dict[str, Any]] = {}
    for module in MODULE_ORDER:
        module_cfg: dict[str, Any] = {
            "enabled": module in modules,
            "analysis_level": "smoke_backend",
            "delivery_allowed": False,
            "non_delivery_reason": "triage_only_not_analysis_run",
        }
        if module in modules and standard_input:
            module_cfg["input_matrix"] = standard_input["path"]
            module_cfg["raw"] = {"enabled": False, "input_type": standard_input["input_type"]}
        elif module in modules and raw_input:
            module_cfg["raw"] = {
                "enabled": True,
                "input_type": raw_input["input_type"],
                "input_path": raw_input["path"],
                "handoff_required": True,
                "handoff_status": "not_executed_by_triage",
            }
        enabled[module] = module_cfg
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
            "handoff_required": bool(input_assessment["handoff_required"]),
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


def _parse_text_request_hints(text: str) -> dict[str, Any]:
    lowered = text.lower()
    modules = []
    keyword_modules = {
        "scrna": ("scrna", "single cell", "单细胞", "h5ad", "10x"),
        "rnaseq": ("rnaseq", "rna-seq", "bulk", "转录组"),
        "scatac": ("scatac", "atac", "fragments"),
        "spatial": ("spatial", "visium", "空间"),
        "vdj": ("vdj", "tcr", "bcr", "airr"),
        "cite_seq": ("cite", "adt", "抗体标签"),
    }
    for module, tokens in keyword_modules.items():
        if any(token in lowered for token in tokens):
            modules.append(module)
    presets = []
    for preset in ("tumor", "communication", "trajectory", "velocity", "publication", "standard", "basic"):
        if preset in lowered:
            presets.append(preset)
    if "肿瘤" in lowered and "tumor" not in presets:
        presets.append("tumor")
    if "通讯" in lowered and "communication" not in presets:
        presets.append("communication")
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        normalized_key = key.strip().lower().replace(" ", "_")
        if normalized_key in {"samplesheet", "sample_sheet", "input_path", "matrix_path", "h5ad", "fastq_dir"} and value.strip():
            fields[normalized_key] = value.strip()
    return {"modules": modules, "presets": presets or ["standard"], "fields": fields}


def _collect_input_rows(request: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    def add(source: str, key: str, value: Any) -> None:
        if value in (None, ""):
            return
        if isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                add(source, f"{key}[{index}]", item)
            return
        if isinstance(value, dict):
            for nested_key, nested_value in value.items():
                add(source, f"{key}.{nested_key}", nested_value)
            return
        if isinstance(value, str):
            rows.append({"source": source, "key": key, "path": value})

    for key in (
        "input_path",
        "input_paths",
        "data_path",
        "data_paths",
        "raw_data",
        "matrix_path",
        "object_path",
        "h5ad",
        "h5mu",
        "tenx_h5",
        "tenx_mtx",
        "fastq_dir",
        "bcl_dir",
        "fragments",
        "peak_matrix",
    ):
        add("request", key, request.get(key))
    inputs = request.get("inputs")
    if isinstance(inputs, (dict, list)):
        add("inputs", "inputs", inputs)
    module_cfgs = request.get("module_inputs")
    if isinstance(module_cfgs, dict):
        for module_name, payload in module_cfgs.items():
            add(f"module:{module_name}", str(module_name), payload)
    return rows


def _read_samplesheet(samplesheet: Any) -> tuple[Any, str]:
    if not isinstance(samplesheet, str):
        return None, ""
    path = Path(samplesheet).expanduser()
    if not path.exists():
        return None, ""
    try:
        import pandas as pd

        return pd.read_csv(path, sep=None, engine="python"), ""
    except Exception as exc:
        return None, f"样本表读取失败：{type(exc).__name__}: {exc}"


def _assess_inputs(request: dict[str, Any], input_rows: list[dict[str, str]], samplesheet_frame: Any, modules: list[str], base_dir: Path) -> dict[str, Any]:
    rows: list[dict[str, str]] = []
    for row in input_rows:
        rows.append(_input_assessment_row(row["source"], row["key"], row["path"], base_dir))
    if samplesheet_frame is not None:
        for column in [col for col in getattr(samplesheet_frame, "columns", []) if col in PATH_COLUMNS or col in MATRIX_INPUT_KEYS]:
            for value in samplesheet_frame[column].dropna().astype(str).tolist():
                if value:
                    rows.append(_input_assessment_row("samplesheet", str(column), value, base_dir))

    standard_types = sorted({row["input_type"] for row in rows if row["input_role"] == "standard_input"})
    raw_types = sorted({row["input_type"] for row in rows if row["input_role"] == "raw_upstream"})
    return {
        "rows": rows,
        "standard_input_detected": bool(standard_types),
        "raw_upstream_detected": bool(raw_types),
        "standard_input_types": standard_types,
        "raw_input_types": raw_types,
        "handoff_required": bool(raw_types and not standard_types),
        "modules": modules,
    }


def _input_assessment_row(source: str, key: str, value: str, base_dir: Path) -> dict[str, str]:
    input_type, role, note = _classify_input(key, value)
    path = Path(value).expanduser()
    resolved = path if path.is_absolute() else (base_dir / path).resolve()
    return {
        "source": source,
        "key": key,
        "path": str(resolved),
        "input_type": input_type,
        "input_role": role,
        "exists": str(resolved.exists()).lower(),
        "note": note,
    }


def _classify_input(key: str, value: str) -> tuple[str, str, str]:
    lowered_key = key.lower()
    lowered = value.lower()
    suffixes = "".join(Path(lowered).suffixes)
    if any(token in lowered_key for token in ("fastq", "bcl")) or suffixes.endswith((".fastq.gz", ".fq.gz", ".fastq", ".fq")):
        return "fastq", "raw_upstream", "FASTQ/BCL 需要先通过 nf-core/授权或开源上游生成矩阵。"
    if "bcl" in lowered:
        return "bcl", "raw_upstream", "BCL 需要先 demultiplex，不直接进入 Ultimate core。"
    if "fragments" in lowered_key or "fragments.tsv" in lowered:
        return "fragments", "raw_upstream", "fragments 不是完整标准矩阵；正式分析前需提供 peak matrix/对象或专项后端证据。"
    if any(token in lowered_key for token in MATRIX_INPUT_KEYS) or lowered_key in {"h5ad", "h5mu", "tenx_h5", "tenx_mtx", "object_path"}:
        return _standard_input_type(lowered_key, lowered), "standard_input", "标准矩阵/对象输入，可进入模块 preflight。"
    if suffixes.endswith((".h5ad", ".h5mu", ".h5", ".mtx", ".rds", ".rdata", ".tsv", ".csv")):
        return _standard_input_type(lowered_key, lowered), "standard_input", "按扩展名识别为标准矩阵/对象或表格输入。"
    if any(token in lowered for token in ("matrix", "counts", "abundance", "beta")):
        return "matrix", "standard_input", "按路径文本识别为矩阵输入。"
    return "unknown", "unknown", "未识别为标准矩阵或 raw upstream，需要人工确认。"


def _standard_input_type(key: str, value: str) -> str:
    if "h5ad" in key or value.endswith(".h5ad"):
        return "h5ad"
    if "h5mu" in key or value.endswith(".h5mu"):
        return "h5mu"
    if "tenx" in key or value.endswith(".h5"):
        return "10x_h5"
    if "mtx" in key or value.endswith(".mtx"):
        return "10x_mtx"
    for input_type in MATRIX_LIKE_INPUT_TYPES:
        if input_type in key or input_type in value:
            return input_type
    return "matrix"


def _primary_input(input_assessment: dict[str, Any], role: str) -> dict[str, str] | None:
    for row in input_assessment["rows"]:
        if row["input_role"] == role:
            return row
    return None


def _missing_sample_columns(samplesheet_frame: Any, modules: list[str]) -> list[str]:
    columns = set(getattr(samplesheet_frame, "columns", []))
    missing: list[str] = []
    for module in modules:
        spec = MODULE_SPECS.get(module)
        if not spec:
            continue
        for column in spec.required_columns:
            if column not in columns and column not in missing:
                missing.append(column)
    return missing


def _write_handoff_plan(path: Path, modules: list[str], input_assessment: dict[str, Any]) -> Path:
    lines = [
        "# Ultimate upstream handoff plan",
        "",
        "本文件只描述上游准备路线；triage 不自动开跑、不报价、不生成 production evidence。",
        "",
        f"- standard_input_detected: `{str(input_assessment['standard_input_detected']).lower()}`",
        f"- raw_upstream_detected: `{str(input_assessment['raw_upstream_detected']).lower()}`",
        f"- handoff_required: `{str(input_assessment['handoff_required']).lower()}`",
        "",
        "## Recommended route",
        "",
    ]
    if input_assessment["handoff_required"]:
        if "rnaseq" in modules:
            lines.append("- bulk RNA-seq FASTQ: use `templates/handoffs/nfcore_rnaseq` to generate counts, then import the matrix into Ultimate.")
        if "scrna" in modules:
            lines.append("- scRNA FASTQ/BCL: use `templates/handoffs/nfcore_scrnaseq` or user-provided Cell Ranger/STARsolo/alevin-fry path, then import 10x matrix/h5ad.")
        if any(module in modules for module in ("scatac", "multiome")):
            lines.append("- scATAC/Multiome raw/fragments: provide peak matrix/ARC output or run an upstream adapter before formal analysis.")
        if not any(module in modules for module in ("rnaseq", "scrna", "scatac", "multiome")):
            lines.append("- Provide a module-specific standard matrix/object or validated upstream output before running Ultimate core.")
    else:
        lines.append("- Standard matrix/object input is present or no raw upstream input was declared; proceed to `prepare-job` and `preflight` after manual review.")
    lines.extend(
        [
            "",
            "## Boundaries",
            "",
            "- Do not move or overwrite raw data.",
            "- Do not mark this triage output as `production_backend`.",
            "- Licensed tools require user-provided executable paths.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


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
        f"- standard_input_detected: `{str(manifest['input_summary']['standard_input_detected']).lower()}`",
        f"- raw_upstream_detected: `{str(manifest['input_summary']['raw_upstream_detected']).lower()}`",
        f"- handoff_required: `{str(manifest['input_summary']['handoff_required']).lower()}`",
        f"- handoff_plan: `{manifest['handoff_plan']}`",
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
<p>standard_input_detected: <code>{str(manifest['input_summary']['standard_input_detected']).lower()}</code>; raw_upstream_detected: <code>{str(manifest['input_summary']['raw_upstream_detected']).lower()}</code>; handoff_required: <code>{str(manifest['input_summary']['handoff_required']).lower()}</code></p>
<p>handoff_plan: <code>{manifest['handoff_plan']}</code></p>
<h2>Missing requirements</h2><ul>{missing or '<li>none</li>'}</ul>
<h2>Risk flags</h2><ul>{risks or '<li>none</li>'}</ul>
</body></html>
"""
    path.write_text(html, encoding="utf-8")
    return path
