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
    "mtdna": ("slurm_mtdna_0518", "Existing 0518 mtDNA validation"),
    "spatial": ("slurm_spatial_squidpy_visium", "Squidpy Visium public validation"),
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
    validation_dir, validation_label = VALIDATION_HINTS.get(module, ("", ""))
    validation_manifest = root / "validations" / validation_dir / "run_manifest.json" if validation_dir else None
    validation_status = "available" if validation_manifest and validation_manifest.exists() else "not_required" if module in BULK_MODULES else "missing"
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
        "validation_label": validation_label,
        "production_status": status,
        "next_action": _next_action(module, status, validation_status),
    }


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
            "1. 把 scDNA、CITE-seq、单细胞表观组学补一套公开 tiny/真实验证数据，形成 Slurm smoke run。",
            "2. 把 scrna/scatac/multiome/spatial/vdj 现有验证脚本接入统一 `ultimate run` 后端，而不是只作为独立 validation 脚本。",
            "3. 为 bulk RNA、甲基化、蛋白/代谢、公共数据库、WGCNA 增加真实公开数据 smoke，并固定验收产物。",
            "4. 增加接单模板：客户数据清单、报价前 preflight、交付报告索引、风格选择单。",
            "5. 保留 Cell Ranger、Space Ranger、CIBERSORT 为授权工具接口，不作为默认依赖。",
            "",
            "## 仍需补齐的模块",
            "",
            *[f"- `{row['module']}`：{row['next_action']}" for row in partials],
            "",
        ]
    )
