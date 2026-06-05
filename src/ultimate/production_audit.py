from __future__ import annotations

import importlib.util
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ultimate.analysis_levels import require_real_evidence
from ultimate.backend_registry import backend_maturity_rows, backend_registry_rows, modules_without_backend
from ultimate.bulk import BULK_MODULES
from ultimate.constants import MODULE_ORDER, MODULE_SPECS, SUPPORTED_ORGANISMS
from ultimate.module_maturity import build_module_maturity_rows
from ultimate.module_standardization import build_module_standardization_rows
from ultimate.modules.common import MODULE_MVP_FIGURES, MODULE_MVP_OBJECTS, MODULE_MVP_TABLES, module_mvp_table_schemas, tool_coverage_rows
from ultimate.plot_style import available_styles
from ultimate.raw_qc import RAW_CONTRACTS
from ultimate.tool_registry import TOOL_REGISTRY
from ultimate.tool_registry import DECISION_TO_V2_DISPOSITION


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
    "rnaseq": ("slurm_rnaseq_airway_public", "airway public bulk RNA-seq count-matrix validation"),
    "scrna": ("slurm_scrna_nsclc_lambrechts", "NSCLC scRNA production validation"),
    "scatac": ("slurm_scatac_10x_pbmc", "10x PBMC scATAC public validation"),
    "multiome": ("slurm_multiome_10x_pbmc", "10x PBMC Multiome public validation"),
    "vdj": ("slurm_vdj_10x_pbmc_unified", "10x PBMC VDJ unified backend public validation"),
    "scdna": ("slurm_scdna_0518", "Existing 0518 scDNA/genome baseline validation"),
    "mtdna": ("slurm_mtdna_0518", "Existing 0518 mtDNA validation"),
    "cite_seq": ("slurm_cite_seq_10x_pbmc_unified", "10x PBMC CITE-seq unified backend public validation"),
    "spatial": ("slurm_spatial_squidpy_visium", "Squidpy Visium public validation"),
    "perturb_seq": ("slurm_perturb_seq_adamson_public", "Adamson public Perturb-seq h5ad validation"),
    "hto_demux": ("slurm_hto_demux_seurat_public", "Seurat public HTO count demultiplex matrix validation"),
    "genotype_demux": ("slurm_genotype_demux_vireo_public", "Vireo/cellSNP public genotype demultiplex matrix validation"),
    "clinical_assoc": ("slurm_tabular_airway_public", "airway public clinical association table validation"),
    "methylation": ("slurm_methylation_arrmdata_public", "ARRmData public methylation beta-matrix validation"),
    "publicdb": ("slurm_tabular_airway_public", "airway public database-style cached table validation"),
    "wgcna": ("slurm_tabular_airway_public", "airway public WGCNA-ready matrix QC and handoff validation"),
    "single_gene": ("slurm_tabular_airway_public", "airway public single-gene report validation"),
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

V2_CORE_MODULES = ("rnaseq", "scrna", "vdj", "cite_seq", "functional_state")
V2_EXTENDED_PARTIAL_MODULES = ("scatac", "multiome", "spatial", "mtdna", "methylation")
V3_SPECIALTY_MODULES = (
    "scdna",
    "perturb_seq",
    "hto_demux",
    "genotype_demux",
    "tumor_sc",
    "method_tools",
    "publicdb",
    "clinical_assoc",
    "wgcna",
    "single_gene",
    "proteomics",
)

VALIDATION_RUN_REQUIREMENTS = {
    "slurm_rnaseq_public": {
        "label_cn": "airway bulk RNA-seq 公开 count matrix Slurm 验证",
        "run_dir": "validations/slurm_rnaseq_airway_public",
        "module": "rnaseq",
        "min_tables": 8,
        "min_figures": 4,
        "min_objects": 1,
        "min_reports": 2,
    },
    "slurm_tabular_public": {
        "label_cn": "airway 表格/公共库模块公开矩阵 Slurm 验证",
        "run_dir": "validations/slurm_tabular_airway_public",
        "module": "tabular_public",
        "min_tables": 20,
        "min_figures": 12,
        "min_objects": 4,
        "min_reports": 8,
    },
    "slurm_methylation_public": {
        "label_cn": "ARRmData 甲基化 beta matrix 公开 Slurm 验证",
        "run_dir": "validations/slurm_methylation_arrmdata_public",
        "module": "methylation",
        "min_tables": 8,
        "min_figures": 4,
        "min_objects": 1,
        "min_reports": 2,
    },
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
        "module": "scatac",
        "min_tables": 3,
        "min_figures": 3,
        "min_objects": 1,
        "min_reports": 2,
    },
    "slurm_multiome": {
        "label_cn": "10x PBMC Multiome Slurm 验证",
        "run_dir": "validations/slurm_multiome_10x_pbmc",
        "module": "multiome",
        "min_tables": 3,
        "min_figures": 3,
        "min_objects": 1,
        "min_reports": 2,
    },
    "slurm_vdj": {
        "label_cn": "10x PBMC VDJ unified backend Slurm 验证",
        "run_dir": "validations/slurm_vdj_10x_pbmc_unified",
        "module": "vdj",
        "min_tables": 3,
        "min_figures": 3,
        "min_objects": 1,
        "min_reports": 2,
    },
    "slurm_spatial": {
        "label_cn": "Visium/Squidpy 空间 Slurm 验证",
        "run_dir": "validations/slurm_spatial_squidpy_visium",
        "module": "spatial",
        "min_tables": 3,
        "min_figures": 3,
        "min_objects": 1,
        "min_reports": 2,
    },
    "slurm_cite_seq": {
        "label_cn": "10x PBMC CITE-seq/ADT unified backend Slurm 验证",
        "run_dir": "validations/slurm_cite_seq_10x_pbmc_unified",
        "module": "cite_seq",
        "min_tables": 3,
        "min_figures": 3,
        "min_objects": 1,
        "min_reports": 2,
    },
    "slurm_scdna": {
        "label_cn": "0518 scDNA/genome Slurm 验证",
        "run_dir": "validations/slurm_scdna_0518",
        "module": "scdna",
        "min_tables": 5,
        "min_figures": 3,
        "min_objects": 1,
        "min_reports": 2,
    },
    "slurm_mtdna": {
        "label_cn": "0518 mtDNA Slurm 验证",
        "run_dir": "validations/slurm_mtdna_0518",
        "module": "mtdna",
        "min_tables": 5,
        "min_figures": 3,
        "min_objects": 1,
        "min_reports": 2,
    },
    "slurm_method_tools": {
        "label_cn": "NSCLC 方法学工具 Slurm 验证",
        "run_dir": "validations/slurm_method_tools_nsclc",
        "module": "method_tools",
        "min_tables": 3,
        "min_figures": 3,
        "min_objects": 1,
        "min_reports": 2,
    },
    "slurm_tumor_sc": {
        "label_cn": "NSCLC 肿瘤单细胞 raw-count 专项 Slurm 验证",
        "run_dir": "validations/slurm_tumor_sc_maynard_raw_counts",
        "module": "tumor_sc",
        "min_tables": 8,
        "min_figures": 3,
        "min_objects": 1,
        "min_reports": 2,
    },
    "slurm_perturb_seq": {
        "label_cn": "Adamson Perturb-seq/CRISPR 筛选公开 h5ad 验证",
        "run_dir": "validations/slurm_perturb_seq_adamson_public",
        "module": "perturb_seq",
        "min_tables": 6,
        "min_figures": 3,
        "min_objects": 1,
        "min_reports": 2,
    },
    "slurm_hto_demux": {
        "label_cn": "HTO/Cell Hashing Seurat 公开矩阵验证",
        "run_dir": "validations/slurm_hto_demux_seurat_public",
        "module": "hto_demux",
        "min_tables": 3,
        "min_figures": 3,
        "min_objects": 1,
        "min_reports": 2,
    },
    "slurm_genotype_demux": {
        "label_cn": "Genotype demultiplex vireo/cellSNP 公开矩阵验证",
        "run_dir": "validations/slurm_genotype_demux_vireo_public",
        "module": "genotype_demux",
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
        "allow_smoke_backend": True,
    },
}

VALIDATION_RUN_COMMANDS = {
    "slurm_rnaseq_public": {
        "slurm_script": "slurm/bulk_validation_suite.sbatch",
        "recommended_entrypoint": "hpc-sbatch",
        "recommended_command": "hpc-sbatch {root}/slurm/bulk_validation_suite.sbatch",
        "prerequisite_command": "",
        "module_or_scope": "rnaseq",
        "compute_policy": "slurm_required_for_public_validation",
    },
    "slurm_tabular_public": {
        "slurm_script": "slurm/bulk_validation_suite.sbatch",
        "recommended_entrypoint": "hpc-sbatch",
        "recommended_command": "hpc-sbatch {root}/slurm/bulk_validation_suite.sbatch",
        "prerequisite_command": "",
        "module_or_scope": "clinical_assoc/publicdb/wgcna/single_gene",
        "compute_policy": "slurm_required_for_public_validation",
    },
    "slurm_methylation_public": {
        "slurm_script": "slurm/bulk_validation_suite.sbatch",
        "recommended_entrypoint": "hpc-sbatch",
        "recommended_command": "hpc-sbatch {root}/slurm/bulk_validation_suite.sbatch",
        "prerequisite_command": "",
        "module_or_scope": "methylation",
        "compute_policy": "slurm_required_for_public_validation",
    },
    "scrna_mvp_h5ad": {
        "slurm_script": "slurm/scrna_mvp_validation.sbatch",
        "recommended_entrypoint": "hpc-sbatch",
        "recommended_command": "hpc-sbatch {root}/slurm/scrna_mvp_validation.sbatch",
        "prerequisite_command": "hpc-sbatch {root}/slurm/download_public_singlecell_data.sbatch",
        "module_or_scope": "scrna",
        "compute_policy": "slurm_required_for_real_public_validation",
    },
    "scrna_mvp_10x_mtx": {
        "slurm_script": "slurm/scrna_mvp_validation.sbatch",
        "recommended_entrypoint": "hpc-sbatch",
        "recommended_command": "hpc-sbatch {root}/slurm/scrna_mvp_validation.sbatch",
        "prerequisite_command": "hpc-sbatch {root}/slurm/download_public_singlecell_data.sbatch",
        "module_or_scope": "scrna",
        "compute_policy": "slurm_required_for_real_public_validation",
    },
    "slurm_scrna": {
        "slurm_script": "slurm/singlecell_validation_suite.sbatch",
        "recommended_entrypoint": "hpc-sbatch",
        "recommended_command": "hpc-sbatch {root}/slurm/singlecell_validation_suite.sbatch",
        "prerequisite_command": "",
        "module_or_scope": "scrna",
        "compute_policy": "slurm_required_for_internal_validation",
    },
    "slurm_scatac": {
        "slurm_script": "slurm/singlecell_validation_suite.sbatch",
        "recommended_entrypoint": "hpc-sbatch",
        "recommended_command": "hpc-sbatch {root}/slurm/singlecell_validation_suite.sbatch",
        "prerequisite_command": "hpc-sbatch {root}/slurm/download_public_singlecell_data.sbatch",
        "module_or_scope": "scatac,scepi",
        "compute_policy": "slurm_required_for_public_validation",
    },
    "slurm_multiome": {
        "slurm_script": "slurm/singlecell_validation_suite.sbatch",
        "recommended_entrypoint": "hpc-sbatch",
        "recommended_command": "hpc-sbatch {root}/slurm/singlecell_validation_suite.sbatch",
        "prerequisite_command": "hpc-sbatch {root}/slurm/download_public_singlecell_data.sbatch",
        "module_or_scope": "multiome",
        "compute_policy": "slurm_required_for_public_validation",
    },
    "slurm_vdj": {
        "slurm_script": "slurm/vdj_backend_validation.sbatch",
        "recommended_entrypoint": "hpc-sbatch",
        "recommended_command": "hpc-sbatch {root}/slurm/vdj_backend_validation.sbatch",
        "prerequisite_command": "hpc-sbatch {root}/slurm/download_public_singlecell_data.sbatch",
        "module_or_scope": "vdj",
        "compute_policy": "slurm_required_for_public_validation",
    },
    "slurm_spatial": {
        "slurm_script": "slurm/singlecell_validation_suite.sbatch",
        "recommended_entrypoint": "hpc-sbatch",
        "recommended_command": "hpc-sbatch {root}/slurm/singlecell_validation_suite.sbatch",
        "prerequisite_command": "hpc-sbatch {root}/slurm/download_public_singlecell_data.sbatch",
        "module_or_scope": "spatial",
        "compute_policy": "slurm_required_for_public_validation",
    },
    "slurm_cite_seq": {
        "slurm_script": "slurm/cite_seq_backend_validation.sbatch",
        "recommended_entrypoint": "hpc-sbatch",
        "recommended_command": "hpc-sbatch {root}/slurm/cite_seq_backend_validation.sbatch",
        "prerequisite_command": "hpc-sbatch {root}/slurm/download_public_singlecell_data.sbatch",
        "module_or_scope": "cite_seq",
        "compute_policy": "slurm_required_for_public_validation",
    },
    "slurm_scdna": {
        "slurm_script": "slurm/scdna_validation.sbatch",
        "recommended_entrypoint": "hpc-sbatch",
        "recommended_command": "hpc-sbatch {root}/slurm/scdna_validation.sbatch",
        "prerequisite_command": "",
        "module_or_scope": "scdna",
        "compute_policy": "slurm_required_for_internal_validation",
    },
    "slurm_mtdna": {
        "slurm_script": "slurm/singlecell_validation_suite.sbatch",
        "recommended_entrypoint": "hpc-sbatch",
        "recommended_command": "hpc-sbatch {root}/slurm/singlecell_validation_suite.sbatch",
        "prerequisite_command": "",
        "module_or_scope": "mtdna",
        "compute_policy": "slurm_required_for_internal_validation",
    },
    "slurm_method_tools": {
        "slurm_script": "slurm/method_tools_validation.sbatch",
        "recommended_entrypoint": "hpc-sbatch",
        "recommended_command": "hpc-sbatch {root}/slurm/method_tools_validation.sbatch",
        "prerequisite_command": "",
        "module_or_scope": "method_tools",
        "compute_policy": "slurm_required_for_internal_validation",
    },
    "slurm_tumor_sc": {
        "slurm_script": "slurm/tumor_sc_maynard_raw_counts.sbatch",
        "recommended_entrypoint": "hpc-sbatch",
        "recommended_command": "hpc-sbatch {root}/slurm/tumor_sc_maynard_raw_counts.sbatch",
        "prerequisite_command": "",
        "module_or_scope": "tumor_sc",
        "compute_policy": "slurm_required_for_internal_validation",
    },
    "slurm_perturb_seq": {
        "slurm_script": "slurm/gapfill_specialty_validation.sbatch",
        "recommended_entrypoint": "hpc-sbatch",
        "recommended_command": "hpc-sbatch {root}/slurm/gapfill_specialty_validation.sbatch",
        "prerequisite_command": "hpc-sbatch {root}/slurm/download_public_singlecell_data.sbatch",
        "module_or_scope": "perturb_seq",
        "compute_policy": "slurm_required_for_public_validation",
    },
    "slurm_hto_demux": {
        "slurm_script": "slurm/gapfill_specialty_validation.sbatch",
        "recommended_entrypoint": "hpc-sbatch",
        "recommended_command": "hpc-sbatch {root}/slurm/gapfill_specialty_validation.sbatch",
        "prerequisite_command": "hpc-sbatch {root}/slurm/download_public_singlecell_data.sbatch",
        "module_or_scope": "hto_demux",
        "compute_policy": "slurm_required_for_public_validation",
    },
    "slurm_genotype_demux": {
        "slurm_script": "slurm/gapfill_specialty_validation.sbatch",
        "recommended_entrypoint": "hpc-sbatch",
        "recommended_command": "hpc-sbatch {root}/slurm/gapfill_specialty_validation.sbatch",
        "prerequisite_command": "hpc-sbatch {root}/slurm/download_public_singlecell_data.sbatch",
        "module_or_scope": "genotype_demux",
        "compute_policy": "slurm_required_for_public_validation",
    },
    "bulk_all_demo": {
        "slurm_script": "slurm/bulk_validation_suite.sbatch",
        "recommended_entrypoint": "hpc-sbatch",
        "recommended_command": "hpc-sbatch {root}/slurm/bulk_validation_suite.sbatch",
        "prerequisite_command": "",
        "module_or_scope": "rnaseq,methylation,clinical_assoc,publicdb,wgcna,single_gene,functional_state",
        "compute_policy": "slurm_required_for_bulk_suite_validation",
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

    validation_gap_rows = _validation_gap_plan_rows(root, validation_rows)
    validation_gap_path = output_dir / "validation_gap_plan.tsv"
    validation_gap_json_path = output_dir / "validation_gap_plan.json"
    pd.DataFrame(validation_gap_rows).to_csv(validation_gap_path, sep="\t", index=False)
    validation_gap_json_path.write_text(json.dumps(validation_gap_rows, indent=2, ensure_ascii=False), encoding="utf-8")

    backend_rows = backend_maturity_rows(root)
    backend_maturity_path = output_dir / "backend_maturity_table.tsv"
    pd.DataFrame(backend_rows).to_csv(backend_maturity_path, sep="\t", index=False)

    backend_registry_snapshot_rows = backend_registry_rows()
    backend_registry_path = output_dir / "backend_registry.tsv"
    backend_registry_json_path = output_dir / "backend_registry.json"
    pd.DataFrame(backend_registry_snapshot_rows).to_csv(backend_registry_path, sep="\t", index=False)
    backend_registry_json_path.write_text(json.dumps(backend_registry_snapshot_rows, indent=2, ensure_ascii=False), encoding="utf-8")

    final_rows = _final_acceptance_rows(root, capability_rows, validation_rows, backend_rows)
    final_path = output_dir / "final_acceptance_checklist.tsv"
    pd.DataFrame(final_rows).to_csv(final_path, sep="\t", index=False)
    production_audit_tsv_path = output_dir / "production_audit.tsv"
    pd.DataFrame(final_rows).to_csv(production_audit_tsv_path, sep="\t", index=False)

    maturity_rows = build_module_maturity_rows(root, capability_rows)
    maturity_path = output_dir / "module_maturity_table.tsv"
    pd.DataFrame(maturity_rows).to_csv(maturity_path, sep="\t", index=False)

    standardization_rows = build_module_standardization_rows()
    standardization_path = output_dir / "module_standardization_matrix.tsv"
    pd.DataFrame(standardization_rows).to_csv(standardization_path, sep="\t", index=False)

    coverage_rows = [row for module in MODULE_ORDER for row in tool_coverage_rows(module)]
    coverage_path = output_dir / "tool_coverage_by_module.tsv"
    pd.DataFrame(coverage_rows).to_csv(coverage_path, sep="\t", index=False)

    registry_rows = _tool_registry_snapshot_rows()
    registry_path = output_dir / "tool_registry_snapshot.tsv"
    registry_json_path = output_dir / "tool_registry_snapshot.json"
    pd.DataFrame(registry_rows).to_csv(registry_path, sep="\t", index=False)
    registry_json_path.write_text(json.dumps(registry_rows, indent=2, ensure_ascii=False), encoding="utf-8")

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
        "validation_gap_plan": str(validation_gap_path),
        "validation_gap_plan_json": str(validation_gap_json_path),
        "validation_gap_summary": _validation_gap_summary(validation_gap_rows),
        "production_audit_tsv": str(production_audit_tsv_path),
        "final_acceptance_checklist": str(final_path),
        "backend_maturity_table": str(backend_maturity_path),
        "backend_registry": str(backend_registry_path),
        "backend_registry_json": str(backend_registry_json_path),
        "backend_registry_summary": _backend_registry_summary(backend_rows),
        "module_maturity_table": str(maturity_path),
        "module_standardization_matrix": str(standardization_path),
        "tool_coverage_by_module": str(coverage_path),
        "tool_registry_snapshot": str(registry_path),
        "tool_registry_snapshot_json": str(registry_json_path),
        "tool_registry_summary": _tool_registry_summary(registry_rows),
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

    if module in BULK_MODULES:
        return {"validation": "not_required", "validation_label": "", "evidence_manifest": "", "evidence_artifacts": ""}

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
    real_ready, _ = require_real_evidence(manifest)
    return real_ready


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
                        "reports/<module>/report.html",
                        "reports/<module>/methods.md",
                        "reports/<module>/run_manifest.json",
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


def _validation_gap_plan_rows(root: Path, validation_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_validation_gap_plan_row(root, row) for row in validation_rows]


def _validation_gap_plan_row(root: Path, row: dict[str, Any]) -> dict[str, Any]:
    key = str(row["validation_key"])
    requirement = VALIDATION_RUN_REQUIREMENTS[key]
    command_info = VALIDATION_RUN_COMMANDS.get(key, {})
    run_dir = root / str(requirement["run_dir"])
    slurm_script = str(command_info.get("slurm_script", ""))
    slurm_script_path = root / slurm_script if slurm_script else None
    expected_report_html = run_dir / "reports" / "report.html"
    expected_methods_md = run_dir / "reports" / "methods.md"
    missing_or_gap = str(row.get("missing_or_gap", ""))
    status = str(row.get("status", "partial"))
    recommended_command = _format_audit_command(str(command_info.get("recommended_command", "")), root)
    prerequisite_command = _format_audit_command(str(command_info.get("prerequisite_command", "")), root)
    next_action = _validation_next_action(status, missing_or_gap, recommended_command, prerequisite_command)

    return {
        "validation_key": key,
        "label_cn": row["label_cn"],
        "module_or_scope": command_info.get("module_or_scope", _scope_from_validation_key(key)),
        "run_dir": str(run_dir),
        "status": status,
        "missing_or_gap": missing_or_gap,
        "recommended_entrypoint": command_info.get("recommended_entrypoint", "hpc-sbatch"),
        "recommended_command": recommended_command,
        "prerequisite_command": prerequisite_command,
        "slurm_script": str(slurm_script_path) if slurm_script_path else "",
        "slurm_script_status": "present" if slurm_script_path and slurm_script_path.is_file() else "missing",
        "expected_manifest": str(run_dir / "run_manifest.json"),
        "expected_report_html": str(expected_report_html),
        "expected_methods_md": str(expected_methods_md),
        "expected_min_tables": int(requirement.get("min_tables", 0)),
        "expected_min_figures": int(requirement.get("min_figures", 0)),
        "expected_min_objects": int(requirement.get("min_objects", 0)),
        "expected_min_reports": int(requirement.get("min_reports", 0)),
        "expected_min_modules": int(requirement.get("min_modules", 0)),
        "expected_min_raw_qc_manifests": int(requirement.get("min_raw_qc_manifests", 0)),
        "compute_policy": command_info.get("compute_policy", "slurm_required_for_validation"),
        "next_action_cn": next_action,
    }


def _format_audit_command(command: str, root: Path) -> str:
    return command.format(root=str(root)) if command else ""


def _scope_from_validation_key(key: str) -> str:
    if key.startswith("scrna"):
        return "scrna"
    if key.startswith("slurm_"):
        return key.removeprefix("slurm_")
    if key.startswith("bulk"):
        return "bulk_tabular"
    return "unknown"


def _validation_next_action(status: str, missing_or_gap: str, recommended_command: str, prerequisite_command: str) -> str:
    if status == "ready":
        return "已完成；后续只需定期刷新 validation-index 和 audit-production。"
    if "manifest_status=missing" in missing_or_gap:
        prefix = f"先运行前置数据准备：{prerequisite_command}；再" if prerequisite_command else "运行"
        return f"{prefix}验证命令：{recommended_command}"
    if "partial:data_required" in missing_or_gap or "data_required" in missing_or_gap:
        if prerequisite_command:
            return f"先补公开/内部验证数据：{prerequisite_command}；数据就绪后运行：{recommended_command}"
        return f"补齐输入数据后运行验证命令：{recommended_command}"
    if "dependency_required" in missing_or_gap:
        return f"先安装或激活对应环境；环境就绪后运行：{recommended_command}"
    if "guard_status=" in missing_or_gap or "artifact_status=" in missing_or_gap:
        return f"修复验证脚本/manifest 产物声明后重新运行：{recommended_command}"
    if "report.html_missing" in missing_or_gap or "methods.md_missing" in missing_or_gap:
        return f"补齐报告产物生成逻辑后重新运行：{recommended_command}"
    return f"按缺口字段修复后运行验证命令：{recommended_command}"


def _validation_gap_summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    total = len(rows)
    ready = sum(1 for row in rows if row.get("status") == "ready")
    script_missing = sum(1 for row in rows if row.get("slurm_script_status") != "present")
    return {
        "total": total,
        "ready": ready,
        "partial": total - ready,
        "slurm_script_missing": script_missing,
    }


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
    if not (run_dir / "reports" / "report.html").is_file() or (run_dir / "reports" / "report.html").stat().st_size <= 0:
        missing.append("report.html_missing")
    if not (run_dir / "reports" / "methods.md").is_file() or (run_dir / "reports" / "methods.md").stat().st_size <= 0:
        missing.append("methods.md_missing")
    guard_status, guard_missing, guard_invalid = _manifest_guard_status(manifest or {})
    if guard_status != "ready":
        missing.append(f"guard_status={guard_status}")
    artifact_status, artifact_gaps = _manifest_artifact_status(manifest or {}, run_dir)
    if artifact_status != "ready":
        missing.append(f"artifact_status={artifact_status}")
        missing.extend(artifact_gaps[:10])
    mvp_status, mvp_gaps = _module_mvp_artifact_status(manifest or {}, run_dir, str(requirement.get("module", "")))
    if mvp_status not in {"ready", "not_required"}:
        missing.append(f"mvp_artifact_status={mvp_status}")
        missing.extend(mvp_gaps[:10])
    real_evidence_note = ""
    if requirement.get("allow_smoke_backend"):
        real_ready, real_evidence_note = _require_smoke_or_real_run(manifest or {})
    else:
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
        "artifact_status": artifact_status,
        "artifact_gaps": ",".join(artifact_gaps),
        "mvp_artifact_status": mvp_status,
        "mvp_artifact_gaps": ",".join(mvp_gaps),
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


def _manifest_artifact_status(manifest: dict[str, Any], run_dir: Path) -> tuple[str, list[str]]:
    gaps: list[str] = []
    declared_any = False
    for key in ("figures", "tables"):
        values = manifest.get(key)
        if not isinstance(values, list):
            continue
        declared_any = True
        if not values:
            gaps.append(f"{key}_empty")
        for value in values:
            artifact_path = _resolve_manifest_artifact(run_dir, value)
            if not _nonempty(artifact_path):
                gaps.append(f"missing_{key}:{value}")
    objects = manifest.get("objects")
    if isinstance(objects, dict):
        declared_any = True
        if not objects:
            gaps.append("objects_empty")
        for key, value in objects.items():
            artifact_path = _resolve_manifest_artifact(run_dir, value)
            if not _nonempty(artifact_path):
                gaps.append(f"missing_object:{key}")
    for module in manifest.get("modules", []) or []:
        if not isinstance(module, dict):
            continue
        artifacts = module.get("artifacts")
        if not isinstance(artifacts, dict):
            continue
        for artifact_kind in ("figures", "tables", "objects", "reports"):
            values = artifacts.get(artifact_kind)
            if not isinstance(values, dict):
                continue
            declared_any = True
            if not values:
                gaps.append(f"module_{artifact_kind}_empty:{module.get('module', 'unknown')}")
            for artifact_name, artifact_value in values.items():
                artifact_path = _resolve_manifest_artifact(run_dir, artifact_value)
                if not _nonempty(artifact_path):
                    gaps.append(f"missing_module_{artifact_kind}:{module.get('module', 'unknown')}:{artifact_name}")
    if gaps:
        return "missing_or_empty_artifacts", gaps
    if not declared_any:
        return "not_declared", ["manifest_artifacts_not_declared"]
    return "ready", gaps


def _module_mvp_artifact_status(manifest: dict[str, Any], run_dir: Path, module_name: str) -> tuple[str, list[str]]:
    if not module_name:
        return "not_required", []
    expected_tables = MODULE_MVP_TABLES.get(module_name, ())
    expected_figures = MODULE_MVP_FIGURES.get(module_name, ())
    expected_object = MODULE_MVP_OBJECTS.get(module_name, f"{module_name}_mvp_object.rds")
    if not expected_tables and not expected_figures and not expected_object:
        return "not_required", []

    module_manifest = _find_module_manifest(manifest, module_name)
    artifact_paths = _collect_declared_artifact_paths(manifest, run_dir, module_manifest)
    gaps: list[str] = []
    table_schemas = module_mvp_table_schemas(module_name)
    for filename in expected_tables:
        matches = _artifact_filename_matches(filename, artifact_paths, run_dir / "results" / "tables")
        if not matches:
            gaps.append(f"missing_mvp_table:{filename}")
            continue
        missing_columns = _missing_table_schema_columns(matches[0], table_schemas.get(filename, []))
        if missing_columns:
            gaps.append(f"mvp_table_schema_missing:{filename}:{','.join(missing_columns)}")
    for filename in expected_figures:
        if not _artifact_filename_present(filename, artifact_paths, run_dir / "results" / "figures"):
            gaps.append(f"missing_mvp_figure:{filename}")
    if expected_object and not _artifact_filename_present(expected_object, artifact_paths, run_dir / "objects"):
        gaps.append(f"missing_mvp_object:{expected_object}")
    if gaps:
        return "missing_mvp_artifacts", gaps
    return "ready", []


def _find_module_manifest(manifest: dict[str, Any], module_name: str) -> dict[str, Any]:
    for module in manifest.get("modules", []) or []:
        if isinstance(module, dict) and module.get("module") == module_name:
            return module
    return {}


def _collect_declared_artifact_paths(manifest: dict[str, Any], run_dir: Path, module_manifest: dict[str, Any]) -> list[Path]:
    paths: list[Path] = []
    for key in ("figures", "tables"):
        values = manifest.get(key)
        if isinstance(values, list):
            paths.extend(_resolve_manifest_artifact(run_dir, value) for value in values)
    objects = manifest.get("objects")
    if isinstance(objects, dict):
        paths.extend(_resolve_manifest_artifact(run_dir, value) for value in objects.values())
    artifacts = module_manifest.get("artifacts") if isinstance(module_manifest, dict) else {}
    if isinstance(artifacts, dict):
        for artifact_kind in ("figures", "tables", "objects", "reports"):
            values = artifacts.get(artifact_kind)
            if isinstance(values, dict):
                paths.extend(_resolve_manifest_artifact(run_dir, value) for value in values.values())
    return paths


def _artifact_filename_present(filename: str, artifact_paths: list[Path], fallback_dir: Path) -> bool:
    return bool(_artifact_filename_matches(filename, artifact_paths, fallback_dir))


def _artifact_filename_matches(filename: str, artifact_paths: list[Path], fallback_dir: Path) -> list[Path]:
    matches = [path for path in artifact_paths if path.name == filename and _nonempty(path)]
    matches.extend(path for path in (fallback_dir.rglob(filename) if fallback_dir.exists() else []) if _nonempty(path))
    seen: set[str] = set()
    unique: list[Path] = []
    for path in matches:
        key = str(path)
        if key not in seen:
            unique.append(path)
            seen.add(key)
    return unique


def _missing_table_schema_columns(path: Path, expected_columns: list[str]) -> list[str]:
    if not expected_columns:
        return []
    try:
        with path.open("r", encoding="utf-8") as handle:
            header = handle.readline().rstrip("\n").split("\t")
    except OSError:
        return expected_columns
    header_set = set(header)
    return [column for column in expected_columns if column not in header_set]


def _require_smoke_or_real_run(manifest: dict[str, Any]) -> tuple[bool, str]:
    status = str(manifest.get("status", "")).lower()
    level = str(manifest.get("analysis_level", ""))
    if status != "ready":
        return False, f"manifest_status={status or 'missing'}"
    if level not in VALID_ANALYSIS_LEVELS:
        return False, f"analysis_level={level or 'missing'}"
    if manifest.get("delivery_allowed") is True and level != "production_backend":
        return False, "delivery_allowed_requires_production_backend"
    if level in {"demo_result", "smoke_backend"} and manifest.get("validation_evidence_allowed") is True:
        return False, "smoke_or_demo_cannot_be_validation_evidence"
    return True, "ready_smoke_or_real_run"


def _resolve_manifest_artifact(run_dir: Path, value: Any) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else run_dir / path


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


def _final_acceptance_rows(
    root: Path,
    capability_rows: list[dict[str, Any]],
    validation_rows: list[dict[str, Any]],
    backend_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    latest_tool_manifest = _latest_tool_manifest(root)
    tool_manifest = _read_json(latest_tool_manifest) if latest_tool_manifest else {}
    tool_matrix = _read_tool_matrix(tool_manifest)
    registry_rows = _tool_registry_snapshot_rows()
    registry_ready, registry_note = _tool_registry_triage_status(registry_rows)
    validation_status = {str(row["validation_key"]): str(row["status"]) for row in validation_rows}
    capability_by_module = {str(row.get("module")): row for row in capability_rows}
    backend_rows = backend_rows if backend_rows is not None else backend_maturity_rows(root)
    ready_capabilities = [row for row in capability_rows if str(row["production_status"]) == "ready_basic"]
    partial_capabilities = [row for row in capability_rows if str(row["production_status"]) != "ready_basic"]
    prepared_delivery_ready, prepared_delivery_note = _prepared_job_delivery_status(root)
    validation_index_ready, validation_index_note = _validation_index_status(root)

    rows = [
        _requirement_row(
            "tool_registry_all_candidates_triaged",
            "所有候选工具都有留存/淘汰结论",
            registry_ready,
            registry_note,
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
            "v2_core_modules_validated",
            "v2 core 模块具备真实 validated_backend 证据",
            _module_group_ready(capability_by_module, V2_CORE_MODULES),
            _module_group_note(capability_by_module, V2_CORE_MODULES),
        ),
        _requirement_row(
            "v2_extended_modules_partial_or_ready",
            "v2 extended 模块至少 partial/validated，不阻断 core 交付秩序",
            _module_group_not_missing(capability_by_module, V2_EXTENDED_PARTIAL_MODULES),
            _module_group_note(capability_by_module, V2_EXTENDED_PARTIAL_MODULES),
        ),
        _requirement_row(
            "v3_specialty_modules_tracked_not_blocking_v2",
            "v3 specialty 模块记录 blocked/partial/ready 原因，但不阻断 v2 core",
            _module_group_tracked(capability_by_module, V3_SPECIALTY_MODULES),
            _module_group_note(capability_by_module, V3_SPECIALTY_MODULES),
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
            "validation_index_summary_ready",
            "validation-index 汇总所有验证 run 并输出交付边界统计",
            validation_index_ready,
            validation_index_note,
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
            "required=singlecell_validation_suite,scrna_mvp_validation,cite_seq_validation,bulk_validation_suite,ultimate_run,tool_trial_batch,gapfill_specialty_validation,readiness_refresh",
        ),
        _requirement_row(
            "prepared_job_delivery_mirror_ready",
            "prepared job 根目录有最新交付物和复现代码镜像",
            prepared_delivery_ready,
            prepared_delivery_note,
        ),
        _requirement_row(
            "v3_backend_registry_ready",
            "V3 backend registry 覆盖全部模块并记录 backend 级成熟度",
            not modules_without_backend() and bool(backend_rows),
            _backend_registry_acceptance_evidence(backend_rows),
        ),
        _requirement_row(
            "v3_fully_automatic_backends_gated",
            "fully automatic backend 必须经过 evidence/approval gate，不把 planned/optional 写成正式后端",
            _backend_gate_ready(backend_rows),
            _backend_gate_evidence(backend_rows),
        ),
    ]
    return rows


def _module_group_ready(capability_by_module: dict[str, dict[str, Any]], modules: tuple[str, ...]) -> bool:
    return all(str(capability_by_module.get(module, {}).get("validation") or "") == "available" for module in modules)


def _module_group_not_missing(capability_by_module: dict[str, dict[str, Any]], modules: tuple[str, ...]) -> bool:
    return all(str(capability_by_module.get(module, {}).get("validation") or "missing") != "missing" for module in modules)


def _module_group_tracked(capability_by_module: dict[str, dict[str, Any]], modules: tuple[str, ...]) -> bool:
    return all(module in capability_by_module for module in modules)


def _module_group_note(capability_by_module: dict[str, dict[str, Any]], modules: tuple[str, ...]) -> str:
    notes = []
    for module in modules:
        row = capability_by_module.get(module, {})
        validation = str(row.get("validation") or "missing")
        production = str(row.get("production_status") or "missing")
        next_action = str(row.get("next_action") or "not_recorded")
        notes.append(f"{module}:validation={validation},production={production},blocked_reason={next_action}")
    return ";".join(notes)


def _backend_registry_summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for row in rows:
        status = str(row.get("backend_status") or "unknown")
        summary[status] = summary.get(status, 0) + 1
    return summary


def _backend_registry_acceptance_evidence(rows: list[dict[str, Any]]) -> str:
    missing = modules_without_backend()
    summary = _backend_registry_summary(rows)
    return f"backend_rows={len(rows)};missing_modules={','.join(missing) or 'none'};summary={json.dumps(summary, ensure_ascii=False, sort_keys=True)}"


def _backend_gate_ready(rows: list[dict[str, Any]]) -> bool:
    if not rows:
        return False
    for row in rows:
        status = str(row.get("backend_status") or "")
        production_allowed = str(row.get("production_allowed") or "").lower() == "true"
        if status.startswith("planned") and production_allowed:
            # Planned backends may allow production in the future, but their
            # current skip reason must make the gate explicit.
            if not str(row.get("skip_reason") or ""):
                return False
        if status in {"handoff_ready", "licensed_path_detection"} and production_allowed:
            if not str(row.get("next_required_evidence") or ""):
                return False
    return True


def _backend_gate_evidence(rows: list[dict[str, Any]]) -> str:
    summary = _backend_registry_summary(rows)
    planned_missing_skip = [
        str(row.get("backend_id"))
        for row in rows
        if str(row.get("backend_status") or "").startswith("planned") and not str(row.get("skip_reason") or "")
    ]
    return f"summary={json.dumps(summary, ensure_ascii=False, sort_keys=True)};planned_missing_skip_reason={','.join(planned_missing_skip) or 'none'}"


def _requirement_row(requirement: str, label_cn: str, passed: bool, evidence: str) -> dict[str, Any]:
    return {
        "requirement": requirement,
        "label_cn": label_cn,
        "status": "pass" if passed else "partial",
        "evidence": evidence,
    }


def _tool_registry_snapshot_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for tool in TOOL_REGISTRY:
        row = asdict(tool)
        row["v2_disposition"] = DECISION_TO_V2_DISPOSITION.get(tool.decision, tool.decision)
        row["triage_ready"] = bool(tool.decision and tool.reason_cn and tool.decision in {
            "keep_default",
            "keep_optional",
            "adapter_only",
            "reference_only",
            "licensed_path_only",
            "rejected_cleaned",
        })
        rows.append(row)
    return rows


def _tool_registry_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    decision_counts: dict[str, int] = {}
    disposition_counts: dict[str, int] = {}
    module_counts: dict[str, int] = {}
    for row in rows:
        decision = str(row.get("decision") or "missing")
        disposition = str(row.get("v2_disposition") or DECISION_TO_V2_DISPOSITION.get(decision, decision))
        module = str(row.get("module") or "missing")
        decision_counts[decision] = decision_counts.get(decision, 0) + 1
        disposition_counts[disposition] = disposition_counts.get(disposition, 0) + 1
        module_counts[module] = module_counts.get(module, 0) + 1
    return {
        "tool_count": len(rows),
        "triage_ready_count": sum(1 for row in rows if row.get("triage_ready") is True),
        "decision_counts": decision_counts,
        "v2_disposition_counts": disposition_counts,
        "module_counts": module_counts,
    }


def _tool_registry_triage_status(rows: list[dict[str, Any]]) -> tuple[bool, str]:
    missing = [
        str(row.get("name") or "unknown")
        for row in rows
        if row.get("triage_ready") is not True
    ]
    decisions = sorted({str(row.get("decision") or "") for row in rows})
    dispositions = sorted({str(row.get("v2_disposition") or DECISION_TO_V2_DISPOSITION.get(str(row.get("decision") or ""), "")) for row in rows})
    ready = len(rows) >= len(TOOL_REGISTRY) and not missing
    note = (
        f"registry_tool_count={len(rows)} expected={len(TOOL_REGISTRY)} "
        f"v2_dispositions={','.join(disposition for disposition in dispositions if disposition)} "
        f"legacy_decisions={','.join(decisions)}"
    )
    if missing:
        note += " missing_triage=" + ",".join(missing[:10])
    return ready, note


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
        root / "slurm" / "cite_seq_backend_validation.sbatch",
        root / "slurm" / "cite_seq_validation.sbatch",
        root / "slurm" / "bulk_validation_suite.sbatch",
        root / "slurm" / "ultimate_run.sbatch",
        root / "slurm" / "tool_trial_batch.sbatch",
        root / "slurm" / "gapfill_specialty_validation.sbatch",
        root / "slurm" / "readiness_refresh.sbatch",
    )
    return all(path.exists() and path.stat().st_size > 0 for path in required)


def _prepared_job_delivery_status(root: Path) -> tuple[bool, str]:
    job_dirs = _prepared_job_dirs(root)
    if not job_dirs:
        return False, "checked_jobs=0 ready_jobs=0 scoped_ready_jobs=0 missing=jobs/*/runs/*/run_manifest.json"
    ready_count = 0
    scoped_ready_count = 0
    gaps: list[str] = []
    legacy_or_unscoped: list[str] = []
    for job_dir in job_dirs:
        missing = _prepared_job_delivery_gaps(job_dir)
        if missing:
            gaps.append(f"{job_dir.name}:{','.join(missing)}")
        else:
            ready_count += 1
            scope_status, scope_note = _prepared_job_delivery_scope_status(job_dir)
            if scope_status:
                scoped_ready_count += 1
            else:
                legacy_or_unscoped.append(f"{job_dir.name}:{scope_note}")
    note = f"checked_jobs={len(job_dirs)} ready_jobs={ready_count} scoped_ready_jobs={scoped_ready_count}"
    if gaps:
        note += f" missing={';'.join(gaps[:5])}"
        if len(gaps) > 5:
            note += f";additional_missing_jobs={len(gaps) - 5}"
    if legacy_or_unscoped:
        note += f" legacy_or_unscoped={';'.join(legacy_or_unscoped[:5])}"
        if len(legacy_or_unscoped) > 5:
            note += f";additional_legacy_or_unscoped_jobs={len(legacy_or_unscoped) - 5}"
    return scoped_ready_count >= 2, note


def _prepared_job_delivery_scope_status(job_dir: Path) -> tuple[bool, str]:
    latest_run_dir = _latest_ready_run_dir(job_dir)
    if latest_run_dir is None:
        return False, "latest_ready_run_missing"
    manifest = _read_json(latest_run_dir / "run_manifest.json")
    gate = manifest.get("delivery_gate") if isinstance(manifest.get("delivery_gate"), dict) else {}
    approval = manifest.get("production_approval") if isinstance(manifest.get("production_approval"), dict) else {}
    modules = manifest.get("modules") if isinstance(manifest.get("modules"), list) else []
    has_production_module = any(
        isinstance(module, dict)
        and (module.get("analysis_level") == "production_backend" or module.get("delivery_allowed") is True)
        for module in modules
    )
    scope = str(approval.get("delivery_scope") or gate.get("delivery_scope") or "")
    if not has_production_module:
        return False, "production_module_missing"
    if scope not in {"internal_rehearsal", "customer_delivery"}:
        return False, "delivery_scope_missing"
    if approval.get("approved") is not True:
        return False, "production_approval_not_approved"
    if gate.get("status") != "ready" or gate.get("delivery_allowed") is not True:
        return False, f"delivery_gate_not_ready:{gate.get('status', '')}"
    return True, f"delivery_scope={scope}"


def _validation_index_status(root: Path) -> tuple[bool, str]:
    manifest_path = root / "reports" / "validation_index" / "run_manifest.json"
    manifest = _read_json(manifest_path)
    if not manifest:
        return False, f"manifest_missing={manifest_path}"
    summary = manifest.get("summary") if isinstance(manifest.get("summary"), dict) else {}
    required_summary_keys = (
        "total_runs",
        "ready_runs",
        "guard_ready",
        "ready_validation_evidence",
        "ready_for_validation_evidence",
        "ready_for_delivery",
        "analysis_level_counts",
        "guard_status_counts",
        "order_readiness_status_counts",
        "delivery_gate_status_counts",
        "module_counts",
    )
    missing_keys = [key for key in required_summary_keys if key not in summary]
    paths = {
        "validation_index_tsv": Path(str(manifest.get("validation_index_tsv") or "")),
        "validation_index_json": Path(str(manifest.get("validation_index_json") or "")),
        "validation_summary_tsv": Path(str(manifest.get("validation_summary_tsv") or "")),
        "report_html": Path(str(manifest.get("report_html") or "")),
        "report_md": Path(str(manifest.get("report_md") or "")),
    }
    missing_paths = [name for name, path in paths.items() if not _nonempty(path)]
    header = _tsv_header(paths["validation_index_tsv"])
    required_columns = {
        "module",
        "evidence_status",
        "order_readiness_status",
        "production_approval_status",
        "delivery_gate_status",
        "delivery_gate_allowed",
        "delivery_scope",
        "artifact_status",
        "missing_or_gap",
        "next_action",
    }
    missing_columns = sorted(required_columns - set(header))
    stale_rows = _validation_index_stale_rows(paths["validation_index_tsv"])
    n_runs = int(manifest.get("n_runs") or 0)
    ready_evidence = int(summary.get("ready_validation_evidence") or 0)
    gaps = []
    if n_runs <= 0:
        gaps.append("n_runs=0")
    if ready_evidence <= 0:
        gaps.append("ready_validation_evidence=0")
    if missing_keys:
        gaps.append(f"missing_summary_keys={','.join(missing_keys)}")
    if missing_paths:
        gaps.append(f"missing_paths={','.join(missing_paths)}")
    if missing_columns:
        gaps.append(f"missing_columns={','.join(missing_columns)}")
    if stale_rows:
        gaps.append(f"stale_rows={','.join(stale_rows[:5])}")
    note = f"manifest={manifest_path} n_runs={n_runs} ready_validation_evidence={ready_evidence}"
    if gaps:
        note += " " + ";".join(gaps)
    return not gaps, note


def _validation_index_stale_rows(index_path: Path) -> list[str]:
    if not _nonempty(index_path):
        return ["validation_index_missing"]
    try:
        frame = pd.read_csv(index_path, sep="\t").fillna("")
    except Exception as exc:
        return [f"validation_index_unreadable:{type(exc).__name__}"]
    required = {"run_name", "manifest_path", "status", "analysis_level", "evidence_status", "order_readiness_status"}
    if not required.issubset(frame.columns):
        return []
    stale: list[str] = []
    for _, row in frame.iterrows():
        run_name = str(row.get("run_name") or row.get("manifest_path") or "unknown")
        manifest_path = Path(str(row.get("manifest_path") or ""))
        manifest = _read_json(manifest_path)
        if not manifest:
            stale.append(f"{run_name}:manifest_missing_or_invalid")
            continue
        current_status = str(manifest.get("status", "")).lower()
        current_level = str(manifest.get("analysis_level", ""))
        if str(row.get("status", "")).lower() != current_status:
            stale.append(f"{run_name}:status_changed")
            continue
        if str(row.get("analysis_level", "")) != current_level:
            stale.append(f"{run_name}:analysis_level_changed")
            continue
        if str(row.get("evidence_status", "")) == "ready_real_evidence":
            ready, reason = require_real_evidence(manifest)
            if not ready:
                stale.append(f"{run_name}:evidence_changed:{reason}")
                continue
        if str(row.get("order_readiness_status", "")) in {"ready_for_delivery", "ready_for_validation_evidence"}:
            guard_status, _, _ = _manifest_guard_status(manifest)
            if guard_status != "ready":
                stale.append(f"{run_name}:guard_changed:{guard_status}")
                continue
    return stale


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
        "input_checksums": job_dir / "reproducible_code" / "input_checksums.tsv",
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
    missing.extend(_module_report_mirror_gaps(latest_run_dir, run_manifest_data, copied))
    if not _is_relative_to(latest_run_dir, job_dir / "runs") or not latest_run_dir.exists():
        missing.append("latest_run_dir")
    if not _nonempty(run_manifest):
        missing.append("run_manifest")
    elif run_manifest_data != mirrored_run_manifest_data:
        missing.append("latest_run_manifest_stale")
    missing.extend(_delivery_index_gaps(required["latest_delivery_index"], run_manifest_data))
    latest_ready_run = _latest_ready_run_dir(job_dir)
    if latest_ready_run and latest_run_dir.resolve() != latest_ready_run.resolve():
        missing.append("latest_run_dir_not_latest_ready")
    module_guard_status, module_guard_note = _pipeline_module_guard_status(run_manifest_data)
    if module_guard_status != "ready":
        missing.append(f"module_guard:{module_guard_note}")
    missing.extend(_delivery_gate_gaps(run_manifest_data))
    slurm_id = str(
        run_manifest_data.get("slurm_job_id")
        or ((run_manifest_data.get("slurm") or {}).get("slurm_job_id") if isinstance(run_manifest_data.get("slurm"), dict) else "")
        or ((run_manifest_data.get("slurm") or {}).get("job_id") if isinstance(run_manifest_data.get("slurm"), dict) else "")
        or ""
    )
    if not slurm_id:
        missing.append("slurm_job_id")
    for field in ("analysis_level", "is_demo", "is_stub", "delivery_allowed", "validation_evidence_allowed", "non_delivery_reason"):
        if field not in run_manifest_data:
            missing.append(f"run_guard:{field}")
    run_repro_manifest = latest_run_dir / "reproducible_code" / "repro_manifest.json"
    if not _same_json_file(run_repro_manifest, required["latest_repro_manifest"]):
        missing.append("latest_repro_manifest_stale")
    if "large result objects remain referenced from the run directory" not in str(pointer.get("policy") or ""):
        missing.append("policy")
    return missing


def _delivery_gate_gaps(manifest: dict[str, Any]) -> list[str]:
    gate = manifest.get("delivery_gate")
    if gate is None:
        return []
    if not isinstance(gate, dict):
        return ["delivery_gate:not_object"]
    required = {"status", "delivery_allowed", "validation_evidence_allowed", "approval_status", "blocked_modules"}
    missing = sorted(required - set(gate))
    gaps = [f"delivery_gate:missing:{','.join(missing)}"] if missing else []
    modules = manifest.get("modules") if isinstance(manifest.get("modules"), list) else []
    production_modules = [
        str(module.get("module") or "unknown")
        for module in modules
        if isinstance(module, dict) and (module.get("analysis_level") == "production_backend" or module.get("delivery_allowed") is True)
    ]
    if production_modules and gate.get("delivery_allowed") is not True:
        gaps.append("delivery_gate:production_not_deliverable")
    if gate.get("delivery_allowed") is True:
        if gate.get("status") != "ready":
            gaps.append("delivery_gate:status_not_ready")
        if gate.get("approval_status") != "approved":
            gaps.append("delivery_gate:approval_not_approved")
        if gate.get("blocked_modules"):
            gaps.append("delivery_gate:blocked_modules_present")
    return gaps


def _module_report_mirror_gaps(latest_run_dir: Path, run_manifest: dict[str, Any], copied: dict[str, Any]) -> list[str]:
    gaps: list[str] = []
    modules = run_manifest.get("modules")
    if not isinstance(modules, list):
        return gaps
    copied_reports = copied.get("module_reports") if isinstance(copied.get("module_reports"), dict) else {}
    for module in modules:
        if not isinstance(module, dict):
            continue
        module_name = str(module.get("module") or "unknown")
        artifacts = module.get("artifacts") if isinstance(module.get("artifacts"), dict) else {}
        reports = artifacts.get("reports") if isinstance(artifacts.get("reports"), dict) else {}
        if not reports:
            continue
        copied_module = copied_reports.get(module_name) if isinstance(copied_reports.get(module_name), dict) else {}
        for key, source_value in reports.items():
            source = Path(str(source_value))
            if not source.is_absolute():
                source = latest_run_dir / source
            mirror = Path(str(copied_module.get(str(key)) or ""))
            if not _nonempty(mirror):
                gaps.append(f"module_report_mirror_missing:{module_name}:{key}")
            elif _nonempty(source) and not _same_file_bytes(source, mirror):
                gaps.append(f"module_report_mirror_stale:{module_name}:{key}")
    return gaps


def _delivery_index_gaps(index_path: Path, run_manifest: dict[str, Any]) -> list[str]:
    if not _nonempty(index_path):
        return ["delivery_index_missing"]
    try:
        frame = pd.read_csv(index_path, sep="\t")
    except Exception as exc:
        return [f"delivery_index_unreadable:{type(exc).__name__}"]
    required_columns = {"category", "path", "size_bytes"}
    missing_columns = sorted(required_columns - set(frame.columns))
    if missing_columns:
        return [f"delivery_index_missing_columns:{','.join(missing_columns)}"]
    gaps: list[str] = []
    categories = set(frame["category"].fillna("").astype(str))
    required_categories = {"figure", "table", "object", "report", "reproducible_code"}
    if _declares_module_reports(run_manifest):
        required_categories.add("module_report")
    missing_categories = sorted(required_categories - categories)
    if missing_categories:
        gaps.append(f"delivery_index_missing_categories:{','.join(missing_categories)}")
    indexed_paths = {str(Path(value).expanduser().resolve()) for value in frame["path"].fillna("").astype(str) if value}
    missing_index_paths = []
    for value in frame["path"].fillna("").astype(str):
        if not value:
            continue
        path = Path(value).expanduser()
        if not _nonempty(path):
            missing_index_paths.append(str(path))
    if missing_index_paths:
        gaps.append(f"delivery_index_paths_missing:{','.join(missing_index_paths[:3])}")

    declared_paths = _declared_module_artifact_paths(run_manifest)
    missing_declared = [str(path) for path in declared_paths if not _nonempty(path)]
    if missing_declared:
        gaps.append(f"declared_artifacts_missing:{','.join(missing_declared[:3])}")
    unindexed_declared = [
        str(path)
        for path in declared_paths
        if _nonempty(path) and str(path.expanduser().resolve()) not in indexed_paths
    ]
    if unindexed_declared:
        gaps.append(f"declared_artifacts_not_indexed:{','.join(unindexed_declared[:3])}")
    return gaps


def _declares_module_reports(run_manifest: dict[str, Any]) -> bool:
    modules = run_manifest.get("modules")
    if not isinstance(modules, list):
        return False
    for module in modules:
        if not isinstance(module, dict):
            continue
        artifacts = module.get("artifacts")
        if not isinstance(artifacts, dict):
            continue
        reports = artifacts.get("reports")
        if isinstance(reports, dict) and reports:
            return True
    return False


def _declared_module_artifact_paths(run_manifest: dict[str, Any]) -> list[Path]:
    paths: list[Path] = []
    modules = run_manifest.get("modules")
    if not isinstance(modules, list):
        return paths
    for module in modules:
        if not isinstance(module, dict):
            continue
        artifacts = module.get("artifacts")
        if not isinstance(artifacts, dict):
            continue
        paths.extend(_artifact_paths_from_value(artifacts))
    return paths


def _artifact_paths_from_value(value: Any) -> list[Path]:
    if isinstance(value, dict):
        paths: list[Path] = []
        for nested in value.values():
            paths.extend(_artifact_paths_from_value(nested))
        return paths
    if isinstance(value, list):
        paths: list[Path] = []
        for nested in value:
            paths.extend(_artifact_paths_from_value(nested))
        return paths
    if isinstance(value, str) and value:
        path = Path(value)
        if path.suffix or path.exists():
            return [path]
    return []


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
    if production_requested and approval.get("delivery_scope") not in {"internal_rehearsal", "customer_delivery"}:
        return "production_approval_scope_missing", "production modules require delivery_scope=internal_rehearsal or customer_delivery"
    return "ready", f"modules={len(modules)}"


def _same_json_file(left: Path, right: Path) -> bool:
    if not _nonempty(left) or not _nonempty(right):
        return False
    return _read_json(left) == _read_json(right)


def _same_file_bytes(left: Path, right: Path) -> bool:
    if not _nonempty(left) or not _nonempty(right):
        return False
    try:
        return left.read_bytes() == right.read_bytes()
    except OSError:
        return False


def _tsv_header(path: Path) -> list[str]:
    if not _nonempty(path):
        return []
    try:
        with path.open("r", encoding="utf-8") as handle:
            first_line = handle.readline().rstrip("\n")
    except OSError:
        return []
    return first_line.split("\t") if first_line else []


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
