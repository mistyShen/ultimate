from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ultimate.analysis_levels import require_real_evidence
from ultimate.bulk import BULK_MODULES
from ultimate.constants import MODULE_ORDER, MODULE_SPECS, SUPPORTED_ORGANISMS
from ultimate.module_maturity import build_module_maturity_rows
from ultimate.module_standardization import build_module_standardization_rows
from ultimate.modules.common import tool_coverage_rows
from ultimate.plot_style import available_styles
from ultimate.raw_qc import RAW_CONTRACTS
from ultimate.tool_registry import TOOL_REGISTRY


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
    "perturb_seq",
    "hto_demux",
    "genotype_demux",
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
    "perturb_seq": ("slurm_perturb_seq_adamson_public", "Adamson public Perturb-seq h5ad validation"),
    "hto_demux": ("slurm_hto_demux_seurat_public", "Seurat public HTO count demultiplex matrix validation"),
    "genotype_demux": ("slurm_genotype_demux_vireo_public", "Vireo/cellSNP public genotype demultiplex matrix validation"),
    "tumor_sc": ("slurm_tumor_sc_maynard_raw_counts", "NSCLC tumor single-cell raw-count specialty validation"),
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
    "bcl-convert/bcl2fastq": "测序仪 BCL demux；只做用户提供路径检测和 Slurm wrapper，不作为默认依赖。",
    "Cell Ranger": "10x 原厂 raw FASTQ 计数；平台提供 Cell Ranger 输出读取和 STARsolo/alevin-fry 等开源路线。",
    "Cell Ranger ATAC/ARC/VDJ": "10x scATAC/Multiome/VDJ 原厂上游；只检测用户提供路径。",
    "Space Ranger": "10x Visium 原厂计数；平台提供 Space Ranger 输出读取和 squidpy/Seurat 开源分析。",
    "CIBERSORT": "授权免疫浸润脚本；平台默认提供开源 signature/ssGSEA 替代。",
}

REQUIRED_GUARD_FIELDS = (
    "analysis_level",
    "is_demo",
    "is_stub",
    "delivery_allowed",
    "validation_evidence_allowed",
    "non_delivery_reason",
)

VALID_ANALYSIS_LEVELS = {"demo_result", "smoke_backend", "validated_backend", "production_backend"}

VALIDATION_RUN_REQUIREMENTS = {
    "scrna_mvp_h5ad": {
        "label_cn": "scRNA MVP h5ad 真实公开数据验证",
        "run_dir": "validation_runs/scrna_mvp_validation/h5ad",
        "min_tables": 8,
        "min_figures": 3,
        "min_objects": 1,
        "min_reports": 2,
        "require_real_evidence": True,
    },
    "scrna_mvp_10x_mtx": {
        "label_cn": "scRNA MVP 10x matrix 真实公开数据验证",
        "run_dir": "validation_runs/scrna_mvp_validation/10x_mtx",
        "min_tables": 8,
        "min_figures": 3,
        "min_objects": 1,
        "min_reports": 2,
        "require_real_evidence": True,
    },
    "slurm_scrna": {
        "label_cn": "NSCLC scRNA Slurm 生产验证",
        "run_dir": "validations/slurm_scrna_nsclc_lambrechts",
        "min_tables": 5,
        "min_figures": 5,
        "min_objects": 1,
        "min_reports": 2,
    },
    "slurm_scatac": {
        "label_cn": "10x PBMC scATAC Slurm 验证",
        "run_dir": "validations/slurm_scatac_10x_pbmc",
        "min_tables": 3,
        "min_figures": 3,
        "min_objects": 1,
        "min_reports": 2,
    },
    "slurm_multiome": {
        "label_cn": "10x PBMC Multiome Slurm 验证",
        "run_dir": "validations/slurm_multiome_10x_pbmc",
        "min_tables": 3,
        "min_figures": 3,
        "min_objects": 1,
        "min_reports": 2,
    },
    "slurm_vdj": {
        "label_cn": "10x PBMC VDJ Slurm 验证",
        "run_dir": "validations/slurm_vdj_10x_pbmc",
        "min_tables": 3,
        "min_figures": 3,
        "min_objects": 1,
        "min_reports": 2,
    },
    "slurm_spatial": {
        "label_cn": "Visium/Squidpy 空间 Slurm 验证",
        "run_dir": "validations/slurm_spatial_squidpy_visium",
        "min_tables": 3,
        "min_figures": 3,
        "min_objects": 1,
        "min_reports": 2,
    },
    "slurm_scdna": {
        "label_cn": "0518 scDNA/genome Slurm 验证",
        "run_dir": "validations/slurm_scdna_0518",
        "min_tables": 5,
        "min_figures": 3,
        "min_objects": 1,
        "min_reports": 2,
    },
    "slurm_mtdna": {
        "label_cn": "0518 mtDNA Slurm 验证",
        "run_dir": "validations/slurm_mtdna_0518",
        "min_tables": 5,
        "min_figures": 3,
        "min_objects": 1,
        "min_reports": 2,
    },
    "slurm_method_tools": {
        "label_cn": "NSCLC 方法学工具 Slurm 验证",
        "run_dir": "validations/slurm_method_tools_nsclc",
        "min_tables": 3,
        "min_figures": 3,
        "min_objects": 1,
        "min_reports": 2,
    },
    "slurm_tumor_sc": {
        "label_cn": "NSCLC 肿瘤单细胞 raw-count 专项 Slurm 验证",
        "run_dir": "validations/slurm_tumor_sc_maynard_raw_counts",
        "min_tables": 8,
        "min_figures": 3,
        "min_objects": 1,
        "min_reports": 2,
    },
    "slurm_perturb_seq": {
        "label_cn": "Adamson Perturb-seq/CRISPR 筛选公开 h5ad 验证",
        "run_dir": "validations/slurm_perturb_seq_adamson_public",
        "min_tables": 6,
        "min_figures": 3,
        "min_objects": 1,
        "min_reports": 2,
    },
    "slurm_hto_demux": {
        "label_cn": "HTO/Cell Hashing Seurat 公开矩阵验证",
        "run_dir": "validations/slurm_hto_demux_seurat_public",
        "min_tables": 3,
        "min_figures": 3,
        "min_objects": 1,
        "min_reports": 2,
    },
    "slurm_genotype_demux": {
        "label_cn": "Genotype demultiplex vireo/cellSNP 公开矩阵验证",
        "run_dir": "validations/slurm_genotype_demux_vireo_public",
        "min_tables": 4,
        "min_figures": 3,
        "min_objects": 1,
        "min_reports": 2,
    },
    "bulk_all_demo": {
        "label_cn": "bulk/甲基化/蛋白/公共库/WGCNA/单基因 Slurm 验证",
        "run_dir": "validations/bulk_demo_python/project/runs/project",
        "min_tables": 30,
        "min_figures": 25,
        "min_objects": 7,
        "min_reports": 2,
        "min_modules": len(MODULE_ORDER),
        "min_raw_qc_manifests": len(MODULE_ORDER),
    },
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

    validation_rows = _validation_evidence_rows(root)
    validation_path = output_dir / "validation_evidence_matrix.tsv"
    pd.DataFrame(validation_rows).to_csv(validation_path, sep="\t", index=False)

    final_rows = _final_acceptance_rows(root, capability_rows, validation_rows)
    final_path = output_dir / "final_acceptance_checklist.tsv"
    pd.DataFrame(final_rows).to_csv(final_path, sep="\t", index=False)

    maturity_rows = build_module_maturity_rows(root, capability_rows)
    maturity_path = output_dir / "module_maturity_table.tsv"
    pd.DataFrame(maturity_rows).to_csv(maturity_path, sep="\t", index=False)

    standardization_rows = build_module_standardization_rows()
    standardization_path = output_dir / "module_standardization_matrix.tsv"
    pd.DataFrame(standardization_rows).to_csv(standardization_path, sep="\t", index=False)

    coverage_rows = [row for module in MODULE_ORDER for row in tool_coverage_rows(module)]
    coverage_path = output_dir / "tool_coverage_by_module.tsv"
    pd.DataFrame(coverage_rows).to_csv(coverage_path, sep="\t", index=False)

    next_steps_path = output_dir / "next_steps.md"
    next_steps_path.write_text(_next_steps_markdown(capability_rows, final_rows), encoding="utf-8")

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
        "validation_evidence_matrix": str(validation_path),
        "final_acceptance_checklist": str(final_path),
        "module_maturity_table": str(maturity_path),
        "module_standardization_matrix": str(standardization_path),
        "tool_coverage_by_module": str(coverage_path),
        "final_acceptance_summary": _final_summary(final_rows),
        "module_standardization_summary": _standardization_summary(standardization_rows),
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


def _standardization_summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"ready": 0, "partial": 0}
    for row in rows:
        status = str(row.get("overall_status") or "partial")
        summary[status if status in summary else "partial"] += 1
    return summary


def _validation_evidence(root: Path, module: str) -> dict[str, str]:
    if module in BULK_MODULES:
        return {"validation": "not_required", "validation_label": "", "evidence_manifest": "", "evidence_artifacts": ""}

    if module in VALIDATION_HINTS:
        validation_dir, validation_label = VALIDATION_HINTS[module]
        run_dir = root / "validations" / validation_dir
        manifest = run_dir / "run_manifest.json"
        if _ready_validation_manifest(manifest):
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
        if _ready_validation_manifest(manifest) and all(path.exists() and path.stat().st_size > 0 for path in artifact_paths):
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


def _ready_validation_manifest(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if str(manifest.get("status", "")).lower() != "ready":
        return False
    guard_status, _, _ = _manifest_guard_status(manifest)
    if guard_status != "ready":
        return False
    return bool(manifest.get("validation_evidence_allowed") is True)


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
    if module in {"perturb_seq", "hto_demux", "genotype_demux"}:
        return "Keep public matrix/object validation current and add formal model backends when needed."
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


def _validation_evidence_rows(root: Path) -> list[dict[str, Any]]:
    rows = []
    for key, requirement in VALIDATION_RUN_REQUIREMENTS.items():
        rows.append(_validation_evidence_row(root, key, requirement))
    return rows


def _validation_evidence_row(root: Path, key: str, requirement: dict[str, Any]) -> dict[str, Any]:
    run_dir = root / str(requirement["run_dir"])
    manifest_path = run_dir / "run_manifest.json"
    manifest = _read_json(manifest_path)
    manifest_status = str((manifest or {}).get("status", "missing" if not manifest_path.exists() else "invalid")).lower()
    table_count = _count_files(run_dir / "results" / "tables")
    figure_count = _count_files(run_dir / "results" / "figures")
    object_count = _count_files(run_dir / "objects")
    report_count = _count_files(run_dir / "reports")
    raw_qc_count = _count_named_files(run_dir / "raw_qc", "raw_qc_manifest.json")
    module_count = int(((manifest or {}).get("summary") or {}).get("module_count") or len((manifest or {}).get("modules", [])))
    ready_module_count = int(((manifest or {}).get("summary") or {}).get("ready_module_count") or 0)

    missing = []
    if manifest_status != "ready":
        missing.append(f"manifest_status={manifest_status}")
    if table_count < int(requirement.get("min_tables", 0)):
        missing.append(f"tables<{requirement.get('min_tables')}")
    if figure_count < int(requirement.get("min_figures", 0)):
        missing.append(f"figures<{requirement.get('min_figures')}")
    if object_count < int(requirement.get("min_objects", 0)):
        missing.append(f"objects<{requirement.get('min_objects')}")
    if report_count < int(requirement.get("min_reports", 0)):
        missing.append(f"reports<{requirement.get('min_reports')}")
    if module_count < int(requirement.get("min_modules", 0)):
        missing.append(f"modules<{requirement.get('min_modules')}")
    if raw_qc_count < int(requirement.get("min_raw_qc_manifests", 0)):
        missing.append(f"raw_qc_manifests<{requirement.get('min_raw_qc_manifests')}")
    guard_status, guard_missing, guard_invalid = _manifest_guard_status(manifest or {})
    if guard_status != "ready":
        missing.append(f"guard_status={guard_status}")
    real_evidence_note = ""
    if requirement.get("require_real_evidence"):
        real_ready, real_evidence_note = require_real_evidence(manifest or {})
        if not real_ready:
            missing.append(real_evidence_note)

    return {
        "validation_key": key,
        "label_cn": requirement["label_cn"],
        "run_dir": str(run_dir),
        "run_manifest": str(manifest_path) if manifest_path.exists() else "",
        "status": "ready" if not missing else "partial",
        "manifest_status": manifest_status,
        "table_count": table_count,
        "figure_count": figure_count,
        "object_count": object_count,
        "report_count": report_count,
        "raw_qc_manifest_count": raw_qc_count,
        "module_count": module_count,
        "ready_module_count": ready_module_count,
        "analysis_level": str((manifest or {}).get("analysis_level", "")),
        "delivery_allowed": str((manifest or {}).get("delivery_allowed", "")),
        "validation_evidence_allowed": str((manifest or {}).get("validation_evidence_allowed", "")),
        "guard_status": guard_status,
        "guard_missing_fields": ",".join(guard_missing),
        "guard_invalid_fields": ",".join(guard_invalid),
        "real_evidence_note": real_evidence_note,
        "missing_or_gap": ";".join(missing),
    }


def _manifest_guard_status(manifest: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    missing = [field for field in REQUIRED_GUARD_FIELDS if field not in manifest]
    invalid = _invalid_guard_fields(manifest)
    if missing:
        return "missing_guard_fields", missing, invalid
    if invalid:
        return "invalid_guard_fields", missing, invalid
    return "ready", missing, invalid


def _invalid_guard_fields(manifest: dict[str, Any]) -> list[str]:
    invalid: list[str] = []
    if manifest.get("analysis_level") not in VALID_ANALYSIS_LEVELS:
        invalid.append("analysis_level")
    for field in ("is_demo", "is_stub", "delivery_allowed", "validation_evidence_allowed"):
        if not isinstance(manifest.get(field), bool):
            invalid.append(field)
    if manifest.get("delivery_allowed") is True and manifest.get("analysis_level") != "production_backend":
        invalid.append("delivery_allowed_requires_production_backend")
    if manifest.get("validation_evidence_allowed") is True and manifest.get("analysis_level") not in {
        "validated_backend",
        "production_backend",
    }:
        invalid.append("validation_evidence_requires_validated_or_production")
    if manifest.get("delivery_allowed") is False and not manifest.get("non_delivery_reason"):
        invalid.append("non_delivery_reason")
    return invalid


def _final_acceptance_rows(root: Path, capability_rows: list[dict[str, Any]], validation_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest_tool_manifest = _latest_tool_manifest(root)
    tool_manifest = _read_json(latest_tool_manifest) if latest_tool_manifest else {}
    tool_matrix = _read_tool_matrix(tool_manifest)
    validation_status = {str(row["validation_key"]): str(row["status"]) for row in validation_rows}
    ready_capabilities = [row for row in capability_rows if str(row["production_status"]) == "ready_basic"]
    partial_capabilities = [row for row in capability_rows if str(row["production_status"]) != "ready_basic"]
    prepared_delivery_ready, prepared_delivery_note = _prepared_job_delivery_status(root)

    rows = [
        _requirement_row(
            "tool_registry_all_candidates_triaged",
            "所有候选工具都有留存/淘汰结论",
            bool(tool_manifest) and int(tool_manifest.get("tool_count", 0)) >= len(TOOL_REGISTRY) and _count_tsv_rows(Path(str(tool_manifest.get("registry_tsv", "")))) >= len(TOOL_REGISTRY),
            f"tool_count={tool_manifest.get('tool_count', 0)} expected>={len(TOOL_REGISTRY)} manifest={latest_tool_manifest or ''}",
        ),
        _requirement_row(
            "tool_install_plan_empty",
            "无剩余 needs_trial_install 项",
            bool(tool_manifest) and _count_tsv_rows(Path(str(tool_manifest.get("install_plan", "")))) == 0,
            f"install_plan_rows={_count_tsv_rows(Path(str(tool_manifest.get('install_plan', ''))))}",
        ),
        _requirement_row(
            "default_tools_smoke_checked",
            "默认保留工具完成 import/version/command smoke",
            _default_tools_ready(tool_matrix),
            _tool_status_note(tool_matrix, decision="keep_default"),
        ),
        _requirement_row(
            "optional_tools_have_reason",
            "可选/外部/授权/淘汰工具有原因和处置",
            _optional_tools_documented(tool_matrix),
            _tool_status_note(tool_matrix),
        ),
        _requirement_row(
            "storage_guard_ok",
            "环境和缓存存储压力在预算内",
            str(((tool_manifest.get("storage") or {}).get("guard_status") or "")).lower() == "ok",
            json.dumps(tool_manifest.get("storage") or {}, ensure_ascii=False),
        ),
        _requirement_row(
            "scrna_input_contracts_validated",
            "scRNA MVP h5ad/10x matrix 真实公开数据验证全跑通",
            all(validation_status.get(key) == "ready" for key in ("scrna_mvp_h5ad", "scrna_mvp_10x_mtx")),
            ",".join(f"{key}={validation_status.get(key, 'missing')}" for key in ("scrna_mvp_h5ad", "scrna_mvp_10x_mtx")),
        ),
        _requirement_row(
            "slurm_singlecell_modalities_validated",
            "单细胞核心模态完成 Slurm 验证",
            all(
                validation_status.get(key) == "ready"
                for key in (
                    "slurm_scrna",
                    "slurm_scatac",
                    "slurm_multiome",
                    "slurm_vdj",
                    "slurm_spatial",
                    "slurm_scdna",
                    "slurm_mtdna",
                    "slurm_method_tools",
                    "slurm_tumor_sc",
                    "slurm_perturb_seq",
                    "slurm_hto_demux",
                    "slurm_genotype_demux",
                )
            ),
            ",".join(f"{key}={validation_status.get(key, 'missing')}" for key in validation_status if key.startswith("slurm_")),
        ),
        _requirement_row(
            "bulk_and_tabular_modalities_validated",
            "bulk/表格类模块有 Slurm demo 验证",
            validation_status.get("bulk_all_demo") == "ready",
            f"bulk_all_demo={validation_status.get('bulk_all_demo', 'missing')}",
        ),
        _requirement_row(
            "validation_manifest_guard_fields_ready",
            "生产审计要求的验证 run_manifest 显式记录 analysis_level 和交付边界",
            all(str(row.get("guard_status")) == "ready" for row in validation_rows),
            ",".join(f"{row['validation_key']}={row.get('guard_status', 'missing')}" for row in validation_rows),
        ),
        _requirement_row(
            "raw_qc_contracts_all_modules",
            "所有模块具备 raw/半 raw 输入契约",
            set(RAW_CONTRACTS) == set(MODULE_ORDER),
            f"contracts={len(RAW_CONTRACTS)} modules={len(MODULE_ORDER)}",
        ),
        _requirement_row(
            "production_capability_matrix_ready",
            f"{len(MODULE_ORDER)} 个模块生产能力矩阵达到 basic 级",
            len(ready_capabilities) == len(MODULE_ORDER),
            f"ready_basic={len(ready_capabilities)} partial={len(partial_capabilities)}",
        ),
        _requirement_row(
            "style_template_ready",
            "统一美术风格模板和多配色可用",
            len(available_styles()) >= 3,
            f"style_count={len(available_styles())}",
        ),
        _requirement_row(
            "licensed_tools_declared",
            "授权工具只做路径检测并在报告声明",
            bool(OPTIONAL_LICENSED),
            ",".join(sorted(OPTIONAL_LICENSED)),
        ),
        _requirement_row(
            "slurm_adapter_files_present",
            "正式验证和上游适配 Slurm 脚本存在",
            _slurm_adapter_files_present(root),
            "required=singlecell_validation_suite,scrna_mvp_validation,bulk_validation_suite,ultimate_run,tool_trial_batch",
        ),
        _requirement_row(
            "prepared_job_delivery_mirror_ready",
            "prepared job 根目录有最新交付物和复现代码镜像",
            prepared_delivery_ready,
            prepared_delivery_note,
        ),
    ]
    return rows


def _requirement_row(requirement: str, label_cn: str, passed: bool, evidence: str) -> dict[str, Any]:
    return {
        "requirement": requirement,
        "label_cn": label_cn,
        "status": "pass" if passed else "partial",
        "evidence": evidence,
    }


def _latest_tool_manifest(root: Path) -> Path | None:
    manifests = sorted((root / "audits").glob("tools*/tool_audit_manifest.json"))
    manifests.extend(sorted((root / "audits").glob("tools_after*/tool_audit_manifest.json")))
    existing = [path for path in manifests if path.exists()]
    if not existing:
        return None
    return max(existing, key=lambda path: path.stat().st_mtime)


def _read_tool_matrix(tool_manifest: dict[str, Any]) -> pd.DataFrame:
    path_value = tool_manifest.get("tool_audit_matrix")
    if not path_value:
        return pd.DataFrame()
    path = Path(str(path_value))
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, sep="\t")
    except Exception:
        return pd.DataFrame()


def _default_tools_ready(tool_matrix: pd.DataFrame) -> bool:
    if tool_matrix.empty or "decision" not in tool_matrix.columns or "status" not in tool_matrix.columns:
        return False
    defaults = tool_matrix[tool_matrix["decision"] == "keep_default"]
    if defaults.empty:
        return False
    return bool(defaults["status"].isin({"installed", "adapter_ready"}).all())


def _optional_tools_documented(tool_matrix: pd.DataFrame) -> bool:
    if tool_matrix.empty:
        return False
    required = {"decision", "status", "reason_cn"}
    if not required.issubset(tool_matrix.columns):
        return False
    documented = tool_matrix["decision"].isin({"keep_optional", "adapter_only", "reference_only", "licensed_path_only", "rejected_cleaned"})
    rows = tool_matrix[documented]
    if rows.empty:
        return False
    return bool(rows["reason_cn"].fillna("").astype(str).str.len().gt(0).all())


def _tool_status_note(tool_matrix: pd.DataFrame, decision: str | None = None) -> str:
    if tool_matrix.empty or "status" not in tool_matrix.columns:
        return "tool_matrix_missing"
    rows = tool_matrix
    if decision and "decision" in tool_matrix.columns:
        rows = tool_matrix[tool_matrix["decision"] == decision]
    counts = rows["status"].value_counts().to_dict()
    return json.dumps(counts, ensure_ascii=False, sort_keys=True)


def _slurm_adapter_files_present(root: Path) -> bool:
    required = (
        root / "slurm" / "singlecell_validation_suite.sbatch",
        root / "slurm" / "scrna_mvp_validation.sbatch",
        root / "slurm" / "bulk_validation_suite.sbatch",
        root / "slurm" / "ultimate_run.sbatch",
        root / "slurm" / "tool_trial_batch.sbatch",
        root / "slurm" / "gapfill_specialty_validation.sbatch",
    )
    return all(path.exists() and path.stat().st_size > 0 for path in required)


def _prepared_job_delivery_status(root: Path) -> tuple[bool, str]:
    job_dirs = _prepared_job_dirs(root)
    if not job_dirs:
        return False, "checked_jobs=0 ready_jobs=0 missing=jobs/*/runs/*/run_manifest.json"
    ready_count = 0
    gaps: list[str] = []
    for job_dir in job_dirs:
        missing = _prepared_job_delivery_gaps(job_dir)
        if missing:
            gaps.append(f"{job_dir.name}:{','.join(missing)}")
        else:
            ready_count += 1
    note = f"checked_jobs={len(job_dirs)} ready_jobs={ready_count}"
    if gaps:
        note += f" missing={';'.join(gaps[:5])}"
        if len(gaps) > 5:
            note += f";additional_missing_jobs={len(gaps) - 5}"
    return ready_count > 0 and ready_count == len(job_dirs), note


def _prepared_job_dirs(root: Path) -> list[Path]:
    jobs_root = root / "jobs"
    if not jobs_root.exists():
        return []
    return sorted(
        path.parent
        for path in jobs_root.glob("*/job_manifest.json")
        if path.is_file() and path.stat().st_size > 0 and any((path.parent / "runs").glob("*/run_manifest.json"))
    )


def _prepared_job_delivery_gaps(job_dir: Path) -> list[str]:
    required = {
        "latest_run_pointer": job_dir / "deliverables" / "latest_run_pointer.json",
        "latest_run_manifest": job_dir / "deliverables" / "latest_run_manifest.json",
        "latest_report": job_dir / "deliverables" / "latest_report.html",
        "latest_methods": job_dir / "deliverables" / "latest_methods.md",
        "latest_delivery_index": job_dir / "deliverables" / "latest_delivery_index.tsv",
        "rerun_script": job_dir / "reproducible_code" / "rerun.sh",
        "software_versions": job_dir / "reproducible_code" / "software_versions.tsv",
        "latest_repro_manifest": job_dir / "reproducible_code" / "latest_repro_manifest.json",
    }
    missing = [name for name, path in required.items() if not _nonempty(path)]
    pointer = _read_json(required["latest_run_pointer"])
    latest_run_dir = Path(str(pointer.get("latest_run_dir") or ""))
    run_manifest = Path(str(pointer.get("run_manifest") or ""))
    mirrored_run_manifest = required["latest_run_manifest"]
    run_manifest_data = _read_json(run_manifest)
    mirrored_run_manifest_data = _read_json(mirrored_run_manifest)
    copied = pointer.get("copied_artifacts") if isinstance(pointer.get("copied_artifacts"), dict) else {}
    for copied_key in ("run_manifest", "report_html", "methods_md", "delivery_index"):
        if not _nonempty(Path(str(copied.get(copied_key) or ""))):
            missing.append(f"copied_artifacts.{copied_key}")
    if not _is_relative_to(latest_run_dir, job_dir / "runs") or not latest_run_dir.exists():
        missing.append("latest_run_dir")
    if not _nonempty(run_manifest):
        missing.append("run_manifest")
    elif run_manifest_data != mirrored_run_manifest_data:
        missing.append("latest_run_manifest_stale")
    latest_ready_run = _latest_ready_run_dir(job_dir)
    if latest_ready_run and latest_run_dir.resolve() != latest_ready_run.resolve():
        missing.append("latest_run_dir_not_latest_ready")
    module_guard_status, module_guard_note = _pipeline_module_guard_status(run_manifest_data)
    if module_guard_status != "ready":
        missing.append(f"module_guard:{module_guard_note}")
    run_repro_manifest = latest_run_dir / "reproducible_code" / "repro_manifest.json"
    if not _same_json_file(run_repro_manifest, required["latest_repro_manifest"]):
        missing.append("latest_repro_manifest_stale")
    if "large result objects remain referenced from the run directory" not in str(pointer.get("policy") or ""):
        missing.append("policy")
    return missing


def _nonempty(path: Path) -> bool:
    try:
        return path.exists() and path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _is_relative_to(path: Path, parent: Path) -> bool:
    if not str(path):
        return False
    try:
        path.resolve().relative_to(parent.resolve())
    except (OSError, ValueError):
        return False
    return True


def _latest_ready_run_dir(job_dir: Path) -> Path | None:
    manifests = []
    for manifest_path in (job_dir / "runs").glob("*/run_manifest.json"):
        manifest = _read_json(manifest_path)
        if str(manifest.get("status", "")).lower() == "ready":
            manifests.append(manifest_path)
    if not manifests:
        return None
    return max(manifests, key=lambda path: path.stat().st_mtime).parent


def _pipeline_module_guard_status(manifest: dict[str, Any]) -> tuple[str, str]:
    if str(manifest.get("status", "")).lower() != "ready":
        return "manifest_not_ready", f"status={manifest.get('status', '')}"
    modules = manifest.get("modules")
    if not isinstance(modules, list) or not modules:
        return "missing_modules", "modules=0"
    missing_or_invalid = []
    production_requested = False
    for module in modules:
        if not isinstance(module, dict):
            missing_or_invalid.append("module:not_object")
            continue
        module_name = str(module.get("module") or "unknown")
        guard_status, missing, invalid = _manifest_guard_status(module)
        if guard_status != "ready":
            missing_or_invalid.append(f"{module_name}:{guard_status}:{','.join(missing + invalid)}")
        if module.get("analysis_level") == "production_backend" or module.get("delivery_allowed") is True:
            production_requested = True
    if missing_or_invalid:
        return "module_guard_not_ready", ";".join(missing_or_invalid[:5])
    approval = manifest.get("production_approval") if isinstance(manifest.get("production_approval"), dict) else {}
    if production_requested and approval.get("approved") is not True:
        return "production_approval_missing", "production modules require approved production_approval"
    return "ready", f"modules={len(modules)}"


def _same_json_file(left: Path, right: Path) -> bool:
    if not _nonempty(left) or not _nonempty(right):
        return False
    return _read_json(left) == _read_json(right)


def _final_summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for row in rows:
        status = str(row["status"])
        summary[status] = summary.get(status, 0) + 1
    return summary


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _count_files(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for item in path.rglob("*") if item.is_file() and item.stat().st_size > 0)


def _count_named_files(path: Path, filename: str) -> int:
    if not path.exists():
        return 0
    return sum(1 for item in path.rglob(filename) if item.is_file() and item.stat().st_size > 0)


def _count_tsv_rows(path: Path) -> int:
    if not path.exists():
        return -1
    try:
        with path.open("r", encoding="utf-8") as handle:
            line_count = sum(1 for _ in handle)
    except OSError:
        return -1
    return max(0, line_count - 1)


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


def _next_steps_markdown(rows: list[dict[str, Any]], final_rows: list[dict[str, Any]]) -> str:
    partials = [row for row in rows if str(row["production_status"]).startswith("partial")]
    final_partials = [row for row in final_rows if str(row["status"]) != "pass"]
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
    final_gap_lines = [f"- `{row['requirement']}`：{row['evidence']}" for row in final_partials] or ["- 最终验收清单当前全部通过。"]
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
            "## 最终验收缺口",
            "",
            *final_gap_lines,
            "",
        ]
    )
