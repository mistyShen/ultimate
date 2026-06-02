from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ultimate.bulk import BULK_MODULES
from ultimate.constants import MODULE_ORDER, MODULE_SPECS, SUPPORTED_ORGANISMS
from ultimate.plot_style import available_styles
from ultimate.raw_qc import RAW_CONTRACTS


SINGLE_CELL_MODULES = {
    "scrna",
    "scatac",
    "multiome",
    "vdj",
    "scdna",
    "mtdna",
    "scepi",
    "cite_seq",
    "spatial",
    "functional_state",
    "tumor_sc",
    "method_tools",
}

VALIDATION_HINTS = {
    "scrna": ("slurm_scrna_nsclc_lambrechts", "NSCLC scRNA production validation"),
    "scatac": ("slurm_scatac_10x_pbmc", "10x PBMC scATAC public validation"),
    "multiome": ("slurm_multiome_10x_pbmc", "10x PBMC Multiome public validation"),
    "vdj": ("slurm_vdj_10x_pbmc", "10x PBMC VDJ public validation"),
    "scdna": ("slurm_scdna_0518", "Existing 0518 scDNA/genome baseline validation"),
    "mtdna": ("slurm_mtdna_0518", "Existing 0518 mtDNA validation"),
    "cite_seq": ("cite_seq_10x_pbmc_cli", "10x PBMC CITE-seq public validation"),
    "spatial": ("slurm_spatial_squidpy_visium", "Squidpy Visium public validation"),
    "method_tools": ("slurm_method_tools_nsclc", "NSCLC scRNA method-tools baseline validation"),
}

DERIVED_VALIDATION_HINTS = {
    "functional_state": {
        "validation_dir": "slurm_scrna_nsclc_lambrechts",
        "validation_label": "NSCLC scRNA signature/function-state validation",
        "required_artifacts": (
            "results/tables/signature_scores_by_cell_type.tsv",
            "results/figures/signature_score_heatmap.png",
        ),
    },
    "tumor_sc": {
        "validation_dir": "slurm_scrna_nsclc_lambrechts",
        "validation_label": "NSCLC tumor single-cell CNV/signature validation",
        "required_artifacts": (
            "results/tables/tumor_cnv_proxy.tsv",
            "results/figures/tumor_cnv_proxy_by_chromosome.png",
            "results/tables/cell_type_proportions.tsv",
        ),
    },
    "scepi": {
        "validation_dir": "slurm_scatac_10x_pbmc",
        "validation_label": "10x PBMC single-cell epigenomic accessibility validation",
        "required_artifacts": (
            "results/tables/cell_qc_summary.tsv",
            "results/tables/top_peak_counts.tsv",
            "results/figures/top_accessible_peaks.png",
        ),
    },
}

OPTIONAL_LICENSED = {
    "Cell Ranger": "10x 原厂 raw FASTQ 计数；平台提供 Cell Ranger 输出读取和 STARsolo/alevin-fry 等开源路线。",
    "Space Ranger": "10x Visium 原厂计数；平台提供 Space Ranger 输出读取和 squidpy/Seurat 开源分析。",
    "CIBERSORT": "授权免疫浸润脚本；平台默认提供开源 signature/ssGSEA 替代。",
}


def run_production_audit(root: Path, output_dir: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    output_dir = (output_dir or root / "audits" / "production_readiness").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    capability_rows = [_capability_row(root, module) for module in MODULE_ORDER]
    capability_path = output_dir / "production_capability_matrix.tsv"
    pd.DataFrame(capability_rows).to_csv(capability_path, sep="\t", index=False)

    organism_rows = _organism_rows(root)
    organism_path = output_dir / "organism_support.tsv"
    pd.DataFrame(organism_rows).to_csv(organism_path, sep="\t", index=False)

    style_rows = _style_rows()
    style_path = output_dir / "style_options.tsv"
    pd.DataFrame(style_rows).to_csv(style_path, sep="\t", index=False)

    dependency_rows = _dependency_rows(root)
    dependency_path = output_dir / "dependency_report.tsv"
    pd.DataFrame(dependency_rows).to_csv(dependency_path, sep="\t", index=False)

    order_rows = _order_readiness_rows(capability_rows)
    order_path = output_dir / "order_readiness_checklist.tsv"
    pd.DataFrame(order_rows).to_csv(order_path, sep="\t", index=False)

    next_steps_path = output_dir / "next_steps.md"
    next_steps_path.write_text(_next_steps_markdown(capability_rows), encoding="utf-8")

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "output_dir": str(output_dir),
        "scope": {
            "organisms": sorted(SUPPORTED_ORGANISMS),
            "goal": "human/mouse raw-or-semiraw input to basic analysis, figures, report, and manifest for order-ready delivery",
        },
        "summary": _summary(capability_rows),
        "capability_matrix": str(capability_path),
        "organism_support": str(organism_path),
        "style_options": str(style_path),
        "dependency_report": str(dependency_path),
        "order_readiness_checklist": str(order_path),
        "next_steps": str(next_steps_path),
        "licensed_optional": OPTIONAL_LICENSED,
    }
    manifest_path = output_dir / "production_audit.json"
    manifest["manifest_path"] = str(manifest_path)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def _capability_row(root: Path, module: str) -> dict[str, Any]:
    spec = MODULE_SPECS[module]
    contract = RAW_CONTRACTS[module]
    evidence = _validation_evidence(root, module)
    validation_status = evidence["validation"]
    backend = _backend_label(module, validation_status)
    status = _production_status(module, validation_status)
    return {
        "module": module,
        "title_cn": spec.title_cn,
        "modality_group": "bulk" if module in BULK_MODULES else "single_cell",
        "organisms": ",".join(sorted(SUPPORTED_ORGANISMS)),
        "raw_input_types": ",".join(contract.input_types),
        "standard_output": contract.output_kind,
        "raw_contract": "ready",
        "basic_backend": backend,
        "figure_output": "ready",
        "report_output": "ready",
        "validation": validation_status,
        "validation_label": evidence["validation_label"],
        "evidence_manifest": evidence["evidence_manifest"],
        "evidence_artifacts": evidence["evidence_artifacts"],
        "workflow_stages": _workflow_stages(module, status),
        "style_selectable": "ready",
        "production_status": status,
        "next_action": _next_action(module, status, validation_status),
    }


def _validation_evidence(root: Path, module: str) -> dict[str, str]:
    if module in BULK_MODULES:
        return {"validation": "not_required", "validation_label": "", "evidence_manifest": "", "evidence_artifacts": ""}

    if module in VALIDATION_HINTS:
        validation_dir, validation_label = VALIDATION_HINTS[module]
        run_dir = root / "validations" / validation_dir
        manifest = run_dir / "run_manifest.json"
        if _ready_manifest(manifest):
            return {
                "validation": "available",
                "validation_label": validation_label,
                "evidence_manifest": str(manifest),
                "evidence_artifacts": "",
            }
        return {
            "validation": "partial:validation_manifest_not_ready" if manifest.exists() else "missing",
            "validation_label": validation_label,
            "evidence_manifest": str(manifest) if manifest.exists() else "",
            "evidence_artifacts": "",
        }

    if module in DERIVED_VALIDATION_HINTS:
        hint = DERIVED_VALIDATION_HINTS[module]
        run_dir = root / "validations" / str(hint["validation_dir"])
        manifest = run_dir / "run_manifest.json"
        artifacts = tuple(str(value) for value in hint["required_artifacts"])
        artifact_paths = [run_dir / artifact for artifact in artifacts]
        if _ready_manifest(manifest) and all(path.exists() and path.stat().st_size > 0 for path in artifact_paths):
            return {
                "validation": "available",
                "validation_label": str(hint["validation_label"]),
                "evidence_manifest": str(manifest),
                "evidence_artifacts": ",".join(str(path) for path in artifact_paths),
            }
        return {
            "validation": "partial:derived_artifacts_missing" if manifest.exists() else "missing",
            "validation_label": str(hint["validation_label"]),
            "evidence_manifest": str(manifest) if manifest.exists() else "",
            "evidence_artifacts": ",".join(str(path) for path in artifact_paths),
        }

    return {"validation": "missing", "validation_label": "", "evidence_manifest": "", "evidence_artifacts": ""}


def _ready_manifest(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return str(manifest.get("status", "")).lower() == "ready"


def _backend_label(module: str, validation_status: str) -> str:
    if module in BULK_MODULES:
        return "ready:python_bulk_backend_plus_optional_R"
    if validation_status == "available":
        return "ready:public_or_existing_data_validation"
    return "partial:standard_handoff_and_matrix_smoke_backend"


def _production_status(module: str, validation_status: str) -> str:
    if module in BULK_MODULES:
        return "ready_basic"
    if validation_status == "available":
        return "ready_basic"
    if validation_status.startswith("partial:"):
        return validation_status
    return "partial:needs_modality_validation"


def _next_action(module: str, status: str, validation_status: str) -> str:
    if status == "ready_basic":
        if module in BULK_MODULES:
            return "Add larger real-project smoke tests and optional advanced R backend parameters."
        return "Keep validation data current and add customer-facing parameter presets."
    if module in {"scdna", "scepi", "cite_seq"}:
        return "Download or collect public demo data for this modality and run raw-to-object validation."
    if module in {"functional_state", "tumor_sc", "method_tools"}:
        return "Promote matrix/object-level analysis from smoke backend to formal scanpy/Seurat workflow."
    return "Run public or existing production validation and record run_manifest.json."


def _workflow_stages(module: str, status: str) -> str:
    stages = ["raw_input_contract", "raw_qc_manifest", "standard_matrix_or_object", "basic_analysis", "figures", "chinese_report", "run_manifest"]
    if module in {"scdna"} and status != "ready_basic":
        stages.append("needs_real_modality_validation")
    return ",".join(stages)


def _organism_rows(root: Path) -> list[dict[str, Any]]:
    rows = []
    for organism in sorted(SUPPORTED_ORGANISMS):
        rows.append(
            {
                "organism": organism,
                "status": "supported",
                "default_reference": "GRCh38" if organism == "human" else "GRCm39",
                "resource_policy": "user-configurable paths under resources.<organism>; missing large references are reported by preflight",
                "server_root": str(root),
            }
        )
    return rows


def _style_rows() -> list[dict[str, Any]]:
    rows = []
    for key, style in available_styles().items():
        rows.append(
            {
                "style_key": key,
                "style_id": style["style_id"],
                "style_cn": style["style_cn"],
                "case_color": style["case"],
                "control_color": style["control"],
                "accent_color": style["accent"],
                "layout": "clinical_report",
            }
        )
    return rows


def _order_readiness_rows(capability_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in capability_rows:
        module = str(row["module"])
        contract = RAW_CONTRACTS[module]
        rows.append(
            {
                "module": module,
                "title_cn": row["title_cn"],
                "ready_for_basic_order": "yes" if row["production_status"] == "ready_basic" else "partial",
                "accepted_species": ",".join(sorted(SUPPORTED_ORGANISMS)),
                "accepted_raw_inputs": ",".join(contract.input_types),
                "quote_preflight_checks": ",".join(
                    [
                        "species",
                        "sample_sheet_columns",
                        "group_design",
                        "input_path_exists",
                        "reference_or_database_path",
                        "licensed_tool_path_if_requested",
                    ]
                ),
                "minimum_delivery_artifacts": ",".join(
                    [
                        "run_manifest.json",
                        "raw_qc_manifest.json",
                        "results/figures",
                        "results/tables",
                        "objects",
                        "reports/report.html",
                        "reports/methods.md",
                    ]
                ),
                "compute_policy": "slurm_for_raw_or_large_runs; cli_ok_for_preflight_style_and_small_matrix_smoke",
                "style_configuration": "report.style plus report.style_overrides; available styles are in style_options.tsv",
                "remaining_gap": "" if row["production_status"] == "ready_basic" else row["next_action"],
            }
        )
    return rows


def _dependency_rows(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    envs = {
        "core": ("ultimate-core",),
        "rnaseq": ("ultimate-rnaseq",),
        "methylation": ("ultimate-methylation",),
        "proteomics": ("ultimate-proteomics",),
        "publicdb": ("ultimate-publicdb",),
        "wgcna": ("ultimate-wgcna",),
        "scrna": ("ultimate-scrna", "ultimate-scrna-r"),
        "scatac": ("ultimate-scatac-py", "ultimate-scatac-r", "ultimate-scatac-multiome"),
        "vdj": ("ultimate-vdj", "ultimate-vdj-r"),
        "spatial": ("ultimate-spatial-py", "ultimate-spatial-r", "ultimate-spatial"),
        "genome_mtdna": ("ultimate-genome-mtdna",),
    }
    for name, candidates in envs.items():
        paths = [root / ".conda" / "envs" / candidate for candidate in candidates]
        available = [path for path in paths if path.exists()]
        rows.append(
            {
                "dependency_type": "env",
                "name": name,
                "status": "available" if available else "missing",
                "path": ",".join(str(path) for path in (available or paths)),
            }
        )
    for package in ("pandas", "numpy", "matplotlib", "seaborn", "jinja2", "yaml"):
        rows.append({"dependency_type": "python_package", "name": package, "status": "available" if importlib.util.find_spec(package) else "missing", "path": ""})
    for tool, note in OPTIONAL_LICENSED.items():
        rows.append({"dependency_type": "licensed_optional", "name": tool, "status": "user_provided_required", "path": note})
    return rows


def _summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for row in rows:
        key = str(row["production_status"])
        summary[key] = summary.get(key, 0) + 1
    return summary


def _next_steps_markdown(rows: list[dict[str, Any]]) -> str:
    partials = [row for row in rows if str(row["production_status"]).startswith("partial")]
    priority_lines = (
        [
            "1. 把仍为 partial 的模块补真实或公开验证数据，形成 Slurm smoke run。",
            "2. 把 scrna/scatac/multiome/spatial/vdj/cite_seq/method_tools/scdna/scepi 现有验证脚本接入统一 `ultimate run` 后端，而不是只作为独立 validation 脚本。",
            "3. 为 bulk RNA、甲基化、蛋白/代谢、公共数据库、WGCNA 增加真实公开数据 smoke，并固定验收产物。",
            "4. 继续完善接单模板：报价前 preflight、交付报告索引、风格选择单和客户数据回执。",
            "5. 保留 Cell Ranger、Space Ranger、CIBERSORT 为授权工具接口，不作为默认依赖。",
        ]
        if partials
        else [
            "1. 所有模块已经有 basic 级验证证据；下一步把独立 validation 脚本接入统一 `ultimate run` 后端。",
            "2. 为 bulk RNA、甲基化、蛋白/代谢、公共数据库、WGCNA 增加更大的真实公开数据 smoke，并固定验收产物。",
            "3. 把高级算法做成可选参数预设：inferCNV/CopyKAT、chromVAR、SCENIC、CellChat/NicheNet、RNA velocity、cellxgene/Shiny。",
            "4. 继续完善接单模板：报价前 preflight、交付报告索引、风格选择单和客户数据回执。",
            "5. 保留 Cell Ranger、Space Ranger、CIBERSORT 为授权工具接口，不作为默认依赖。",
        ]
    )
    remaining_lines = [f"- `{row['module']}`：{row['next_action']}" for row in partials] or ["- 暂无 partial 模块；当前缺口转为统一入口整合、真实项目压力测试和高级算法预设。"]
    return "\n".join(
        [
            "# Ultimate 生产级接单能力审计与下一步计划",
            "",
            "## 当前结论",
            "",
            f"- 已覆盖物种：{', '.join(sorted(SUPPORTED_ORGANISMS))}",
            "- 所有模块已有 raw/半 raw 输入契约、标准矩阵/对象交接、基础图表和中文报告入口。",
            "- bulk 模块已有 Python 基础后端，可从矩阵/表格输入生成 QC、差异、PCA、火山图、热图和模块专项表图。",
            "- 单细胞高级模态仍按 ready/partial 分级，缺真实验证数据的模块不得标为完全生产级。",
            "",
            "## 下一步优先级",
            "",
            *priority_lines,
            "",
            "## 仍需补齐的模块",
            "",
            *remaining_lines,
            "",
        ]
    )
