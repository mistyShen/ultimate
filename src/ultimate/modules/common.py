from __future__ import annotations

from dataclasses import asdict, dataclass
import html
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

from ultimate.constants import MODULE_SPECS
from ultimate.manifest_schema import STANDARD_ARTIFACT_ROOTS, build_module_manifest
from ultimate.plot_style import apply_clinical_journal_style, continuous_cmap, save_figure
from ultimate.raw_qc import RAW_CONTRACTS
from ultimate.report_contract import report_contract_status
from ultimate.tool_registry import TOOL_REGISTRY

HANDOFF_STATUSES: tuple[str, ...] = (
    "template_only",
    "path_detection",
    "import_validated_output",
    "command_plan_generated",
    "slurm_adapter_ready",
    "fully_executable_backend",
)

TOOL_DECISION_TO_V2_DISPOSITION: dict[str, str] = {
    "keep_default": "default_backend",
    "keep_optional": "optional_backend",
    "adapter_only": "handoff_adapter",
    "licensed_path_only": "licensed_path_detection",
    "reference_only": "reference_only",
    "rejected_cleaned": "rejected_cleaned",
}


@dataclass(frozen=True)
class ModuleContract:
    module_name: str
    title_cn: str
    input_kind: str
    supported_input_types: tuple[str, ...]
    required_columns: tuple[str, ...]
    standard_output: str
    required_artifact_roots: tuple[str, ...]
    primary_tools: tuple[str, ...]
    handoff_tools: tuple[str, ...]
    known_limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


MODULE_LIMITATIONS: dict[str, tuple[str, ...]] = {
    "rnaseq": (
        "没有生物学重复时不得输出正式 DE 结论。",
        "TPM/FPKM 不能直接作为 DESeq2 输入。",
        "nf-core/rnaseq 第一阶段只提供 handoff 模板。",
    ),
    "scrna": (
        "cluster label 不是 cell type annotation。",
        "pseudobulk design-ready matrix 不是已完成 DESeq2/edgeR。",
        "CellChat/inferCNV/SCENIC/velocity 未接入时只能作为 handoff。",
    ),
    "scatac": (
        "scATAC 不套用 scRNA normalize/log1p/HVG 逻辑。",
        "没有 fragments 时不能声称完成 TSS/FRiP/peak calling。",
        "motif enrichment 不等于 TF 活性实验证明。",
    ),
    "multiome": (
        "Multiome 不等于 scRNA 与 scATAC 简单拼接。",
        "必须检查 RNA 与 ATAC barcode overlap。",
        "peak-gene linkage 是统计关联，不是实验证明。",
    ),
    "vdj": (
        "clonotype 相同不等于抗原相同。",
        "抗原特异性不能自动断言。",
        "clone-state association 依赖外部 scRNA metadata。",
    ),
    "scdna": (
        "allele dropout、低覆盖、amplicon bias 必须写入报告。",
        "克隆树是模型结果，不是唯一真实进化历史。",
        "第一阶段不做 full phylogeny。",
    ),
    "mtdna": (
        "低深度细胞不能进入 lineage-ready 输出。",
        "homopolymer、NUMTs、mapping bias、dropout 必须作为限制。",
        "shared variant 不能自动当作真实克隆关系。",
    ),
    "scepi": (
        "beta matrix、scBS-seq、CUT&Tag、CUT&RUN、scATAC 不混用同一套路。",
        "DMR 需要分组和重复数。",
        "第一阶段只做 matrix-level MVP 和 handoff。",
    ),
    "cite_seq": (
        "ADT 不是全蛋白组。",
        "抗体 panel 决定可解释范围。",
        "RNA/protein 不一致不能自动解释为机制。",
    ),
    "spatial": (
        "Visium spot 不是单细胞。",
        "Visium、Xenium、CosMX、MERSCOPE 不强行走同一输入逻辑。",
        "空间通讯是推断，不是实验证明。",
    ),
    "perturb_seq": (
        "Perturb-seq 不能当普通 scRNA 加一列 metadata 处理。",
        "guide assignment 错误会污染全部结论，必须单独 QC。",
        "perturbation effect 不能自动写成直接机制。",
    ),
    "hto_demux": (
        "HTO 模块只负责 sample assignment，不负责 cell type。",
        "negative 不能强行分样本。",
        "doublet 阈值必须记录。",
    ),
    "genotype_demux": (
        "genotype demux 不能替代 biological replicate design。",
        "SNP 覆盖不足时不能强行 assignment。",
        "reference VCF 错配必须警示。",
    ),
    "functional_state": (
        "signature score 不是代谢通量。",
        "药物敏感性预测不能写成临床建议。",
        "gene set 来源必须记录。",
    ),
    "tumor_sc": (
        "malignant calling 不能只靠一个 marker。",
        "inferCNV/CopyKAT 是 transcriptome-inferred CNV，不是 DNA CNV。",
        "survival association 不能写成因果。",
    ),
    "clinical_assoc": (
        "clinical association 是样本级统计，不是细胞级随便相关。",
        "样本量不足时不能构建稳定风险模型。",
        "correlation 不等于 causation。",
    ),
    "method_tools": (
        "交互式浏览器只是展示，不改变分析结论。",
        "公开交付前必须脱敏 metadata。",
        "大对象不重复拷贝，优先 reference-first。",
    ),
    "methylation": (
        "DMR 需要分组和重复数。",
        "IDAT、beta matrix、peak matrix 不混用同一统计假设。",
        "第一阶段不声称 full single-cell epigenomics。",
    ),
    "proteomics": (
        "本轮不扩展真实单细胞质谱蛋白组。",
        "abundance table 统计依赖缺失值和批次处理。",
        "OPLS-DA 等模型必须记录交叉验证限制。",
    ),
    "publicdb": (
        "公共数据库必须记录来源、版本、下载时间和筛选规则。",
        "TCGA bulk 验证不能直接证明单细胞机制。",
        "GEO metadata 有人工核对风险。",
    ),
    "wgcna": (
        "WGCNA 更适合 bulk 或 pseudobulk，不默认硬跑 cell-level sparse matrix。",
        "样本数太少必须阻断 production_backend。",
        "hub gene 不是自动靶点。",
    ),
    "single_gene": (
        "单基因表达差异不能直接推出机制。",
        "coexpression 不等于 regulation。",
        "单基因预后模型稳定性有限。",
    ),
}

MODULE_MVP_TABLES: dict[str, tuple[str, ...]] = {
    "rnaseq": ("counts_raw.tsv", "counts_normalized.tsv", "sample_qc.tsv", "design_check.tsv", "de_design_ready.tsv", "enrichment_handoff.tsv"),
    "scrna": ("qc_metrics.tsv", "marker_genes.tsv", "de_condition.tsv", "cell_type_composition.tsv", "cell_type_annotation_placeholder.tsv", "pseudobulk_counts.tsv", "pseudobulk_design.tsv", "pseudobulk_feature_metadata.tsv", "basic_enrichment.tsv"),
    "scatac": ("cell_qc.tsv", "fragment_qc.tsv", "peak_matrix_summary.tsv", "tss_handoff.tsv", "frip_handoff.tsv", "marker_peaks.tsv", "gene_activity_handoff.tsv", "motif_enrichment_handoff.tsv"),
    "multiome": ("rna_qc.tsv", "atac_qc.tsv", "barcode_overlap.tsv", "modality_consistency.tsv", "rna_marker_handoff.tsv", "atac_marker_peak_handoff.tsv", "peak_gene_link_handoff.tsv"),
    "vdj": ("vdj_qc.tsv", "clonotype_summary.tsv", "clone_expansion.tsv", "clone_sharing.tsv", "v_gene_usage.tsv", "j_gene_usage.tsv", "cdr3_length.tsv", "clone_condition_summary.tsv"),
    "scdna": ("coverage_qc.tsv", "variant_qc.tsv", "cell_variant_matrix.tsv", "cell_vaf_matrix.tsv", "cell_cnv_matrix.tsv", "clone_summary.tsv", "mutation_cooccurrence.tsv", "phylogeny_input.tsv"),
    "mtdna": ("mtdna_depth_by_cell.tsv", "mtdna_depth_by_position.tsv", "variant_candidates.tsv", "high_confidence_variants.tsv", "cell_variant_vaf_matrix.tsv", "cell_variant_alt_count_matrix.tsv", "shared_variant_matrix.tsv", "lineage_input.tsv"),
    "scepi": ("feature_qc.tsv", "sample_qc.tsv", "missing_value_summary.tsv", "differential_region_handoff.tsv", "promoter_summary.tsv", "enhancer_summary.tsv", "annotation_summary.tsv"),
    "cite_seq": ("adt_qc.tsv", "antibody_panel.tsv", "adt_normalized_matrix.tsv", "adt_marker_summary.tsv", "rna_protein_consistency.tsv"),
    "spatial": ("spatial_qc.tsv", "spot_metadata.tsv", "coordinate_check.tsv", "domain_summary.tsv", "spatial_marker_handoff.tsv", "deconvolution_handoff.tsv", "spatial_neighbors.tsv"),
    "perturb_seq": ("guide_qc.tsv", "guide_assignment.tsv", "perturbation_summary.tsv", "perturbation_expression_effect.tsv", "pseudobulk_by_perturbation.tsv", "target_response.tsv"),
    "hto_demux": ("hto_qc.tsv", "hto_assignment.tsv", "sample_assignment_summary.tsv", "doublet_summary.tsv", "cell_metadata_with_sample.tsv"),
    "genotype_demux": ("snp_qc.tsv", "assignment.tsv", "doublet_summary.tsv", "sample_composition.tsv", "assignment_confidence.tsv", "cell_metadata_with_genotype.tsv"),
    "functional_state": ("geneset_overlap.tsv", "signature_scores.tsv", "signature_by_group.tsv", "signature_by_cluster.tsv", "signature_correlation.tsv"),
    "tumor_sc": ("malignant_cell_candidates.tsv", "cnv_inference_summary.tsv", "tme_composition.tsv", "immune_state_scores.tsv", "myeloid_state_scores.tsv", "caf_subtype_summary.tsv", "tumor_state_markers.tsv", "therapy_response_comparison.tsv"),
    "clinical_assoc": ("clinical_qc.tsv", "merged_feature_clinical.tsv", "group_comparison.tsv", "correlation_results.tsv", "cox_model_handoff.tsv", "risk_score_placeholder.tsv"),
    "method_tools": ("figure_index.tsv", "table_index.tsv", "sensitive_metadata_scan.tsv", "cellxgene_compatibility.tsv", "delivery_manifest_index.tsv"),
    "methylation": ("feature_qc.tsv", "sample_qc.tsv", "missing_value_summary.tsv", "differential_region_handoff.tsv", "promoter_summary.tsv", "enhancer_summary.tsv", "annotation_summary.tsv"),
    "proteomics": ("abundance_qc.tsv", "normalized_abundance.tsv", "differential_abundance.tsv", "ppi_handoff.tsv", "oplsda_handoff.tsv", "correlation_network_handoff.tsv"),
    "publicdb": ("public_dataset_manifest.tsv", "sample_inclusion.tsv", "expression_matrix_summary.tsv", "clinical_table_summary.tsv", "validation_results.tsv", "survival_results_handoff.tsv"),
    "wgcna": ("wgcna_input_qc.tsv", "soft_threshold.tsv", "module_assignment.tsv", "module_eigengenes.tsv", "module_trait_correlation.tsv", "hub_genes.tsv", "network_export.tsv"),
    "single_gene": ("gene_validation.tsv", "gene_expression_summary.tsv", "group_comparison.tsv", "celltype_expression.tsv", "coexpression_results.tsv", "pathway_association_handoff.tsv", "clinical_association_handoff.tsv"),
}

MODULE_MVP_FIGURES: dict[str, tuple[str, ...]] = {
    "rnaseq": ("pca.png", "sample_correlation_heatmap.png", "volcano.png", "top_gene_heatmap.png"),
    "scrna": ("qc_violin.png", "pca_condition.png", "umap_cluster_condition.png", "cell_composition.png"),
    "scatac": ("lsi_umap.png", "fragment_qc.png", "peak_accessibility_heatmap.png"),
    "multiome": ("joint_embedding_placeholder.png", "modality_qc.png"),
    "vdj": ("clone_size_distribution.png", "v_gene_usage.png", "clone_sharing_heatmap.png"),
    "scdna": ("coverage_distribution.png", "vaf_heatmap.png", "clone_summary.png"),
    "mtdna": ("depth_distribution.png", "vaf_heatmap.png", "shared_variant_heatmap.png"),
    "scepi": ("pca.png", "sample_correlation_heatmap.png", "region_heatmap.png"),
    "cite_seq": ("adt_count_distribution.png", "adt_heatmap.png", "rna_protein_consistency.png"),
    "spatial": ("spatial_qc_plot.png", "spatial_cluster.png", "domain_map.png"),
    "perturb_seq": ("guide_distribution.png", "perturbation_umap_placeholder.png"),
    "hto_demux": ("hto_density.png", "hto_heatmap.png"),
    "genotype_demux": ("sample_assignment_barplot.png", "confidence_distribution.png"),
    "functional_state": ("signature_heatmap.png", "signature_boxplot.png"),
    "tumor_sc": ("tme_composition.png", "tumor_state_heatmap.png"),
    "clinical_assoc": ("missingness_plot.png", "correlation_heatmap.png", "kaplan_meier_placeholder.png"),
    "method_tools": ("figure_index_overview.png",),
    "methylation": ("pca.png", "sample_correlation_heatmap.png", "region_heatmap.png"),
    "proteomics": ("pca.png", "sample_correlation_heatmap.png", "volcano.png", "top_feature_heatmap.png"),
    "publicdb": ("public_validation_boxplot.png", "public_survival_placeholder.png"),
    "wgcna": ("sample_clustering.png", "module_trait_heatmap.png", "soft_threshold_plot.png"),
    "single_gene": ("gene_expression_boxplot.png", "celltype_expression_dotplot.png", "coexpression_heatmap.png"),
}

MODULE_MVP_OBJECTS: dict[str, str] = {
    "rnaseq": "rnaseq_mvp_object.rds",
    "scrna": "scrna_mvp.h5ad",
    "scatac": "scatac_mvp.h5ad",
    "multiome": "multiome_mvp.h5mu",
    "vdj": "vdj_mvp.h5ad",
    "scdna": "scdna_mvp_object.rds",
    "mtdna": "mtdna_mvp_object.rds",
    "scepi": "scepi_mvp_object.rds",
    "cite_seq": "cite_mvp.h5mu",
    "spatial": "spatial_mvp.h5ad",
    "perturb_seq": "perturb_seq_mvp_object.rds",
    "hto_demux": "hto_demux_mvp_object.rds",
    "genotype_demux": "genotype_demux_mvp_object.rds",
    "functional_state": "functional_state_mvp_object.rds",
    "tumor_sc": "tumor_sc_mvp_object.rds",
    "clinical_assoc": "clinical_assoc_mvp_object.rds",
    "method_tools": "cellxgene_ready.h5ad",
    "methylation": "methylation_mvp_object.rds",
    "proteomics": "proteomics_mvp_object.rds",
    "publicdb": "publicdb_mvp_object.rds",
    "wgcna": "wgcna_mvp_object.rds",
    "single_gene": "single_gene_mvp_object.rds",
}

GLOBAL_MVP_TABLE_COLUMNS: tuple[str, ...] = (
    "module",
    "run_id",
    "sample_id",
    "source_dataset",
    "input_artifact",
    "input_modality",
    "analysis_level",
    "result_scope",
    "method_status",
    "delivery_allowed",
)


def module_contract(module_name: str) -> ModuleContract:
    spec = MODULE_SPECS[module_name]
    raw = RAW_CONTRACTS[module_name]
    tools = _tools_for_module(module_name)
    return ModuleContract(
        module_name=module_name,
        title_cn=spec.title_cn,
        input_kind=spec.input_kind,
        supported_input_types=raw.input_types,
        required_columns=raw.required_columns,
        standard_output=raw.output_kind,
        required_artifact_roots=STANDARD_ARTIFACT_ROOTS,
        primary_tools=tuple(tool["name"] for tool in tools if tool["decision"] in {"keep_default", "keep_optional"}),
        handoff_tools=tuple(tool["name"] for tool in tools if tool["decision"] in {"adapter_only", "licensed_path_only"}),
        known_limitations=known_limitations(module_name),
    )


def module_mvp_output_spec(module_name: str) -> dict[str, Any]:
    return {
        "tables": list(MODULE_MVP_TABLES.get(module_name, ("mvp_summary.tsv",))),
        "figures": list(MODULE_MVP_FIGURES.get(module_name, ("mvp_overview.png",))),
        "object": MODULE_MVP_OBJECTS.get(module_name, f"{module_name}_mvp_object.rds"),
        "table_schemas": module_mvp_table_schemas(module_name),
    }


def module_mvp_table_schemas(module_name: str) -> dict[str, list[str]]:
    return {filename: _mvp_table_schema(module_name, filename) for filename in MODULE_MVP_TABLES.get(module_name, ("mvp_summary.tsv",))}


def preflight_contract(module_name: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    contract = module_contract(module_name)
    return {
        "module": module_name,
        "status": "ready",
        "input_contract": contract.to_dict(),
        "config_keys_checked": sorted((config or {}).keys()),
        "production_policy": "production_backend requires approval gate; large compute requires Slurm",
    }


def demo_manifest(module_name: str) -> dict[str, Any]:
    return build_module_manifest(
        module_name=module_name,
        status="ready:demo_contract_only",
        analysis_level="demo_result",
        is_demo=True,
        is_stub=True,
        limitations=list(known_limitations(module_name)),
        handoff=handoff_plan(module_name),
        extra={"demo_scope": "contract/preflight/report skeleton; not biological evidence"},
    )


def validation_plan(module_name: str) -> dict[str, Any]:
    return {
        "module": module_name,
        "status": "planned",
        "analysis_level_after_success": "validated_backend",
        "delivery_allowed_after_success": False,
        "validation_data_policy": "public_or_internal_data_only; generated demo data cannot be validation evidence",
        "slurm_policy": "large public/internal validations must be submitted through Slurm",
    }


def handoff_plan(module_name: str) -> dict[str, Any]:
    contract = module_contract(module_name)
    capabilities = _handoff_capabilities(module_name)
    status = _primary_handoff_status(capabilities)
    return {
        "module": module_name,
        "handoff_status": status,
        "handoff_statuses": capabilities,
        "legacy_handoff_status": "template_ready",
        "handoff_tools": list(contract.handoff_tools),
        "optional_backends": list(contract.primary_tools),
        "tool_decision_summary": tool_decision_summary(module_name),
        "v2_disposition_summary": v2_disposition_summary(module_name),
        "status_definitions": {
            "template_only": "仅有输入输出契约和模板文档。",
            "path_detection": "可检测用户提供的授权工具或外部二进制路径。",
            "import_validated_output": "可引用已验证 run 或成熟上游输出，不重复拷贝大对象。",
            "command_plan_generated": "已生成可人工复查的命令计划或 Slurm/Nextflow handoff 模板。",
            "slurm_adapter_ready": "已有 Slurm wrapper 或 sbatch 模板，可用于正式验证/演练。",
            "fully_executable_backend": "已接入并验证为平台内可执行 backend。",
        },
        "note": "未正式接入的高级工具只作为 handoff/optional backend，不写成 fully automatic。",
    }


def tool_coverage_rows(module_name: str) -> list[dict[str, str]]:
    aliases = ",".join(sorted(_module_aliases(module_name)))
    rows = []
    for tool in _tools_for_module(module_name):
        rows.append(
            {
                "module": module_name,
                "tool_name": tool["name"],
                "decision": tool["decision"],
                "v2_disposition": TOOL_DECISION_TO_V2_DISPOSITION.get(tool["decision"], tool["decision"]),
                "environment": tool["env"],
                "install_method": tool["install_method"],
                "module_aliases": aliases,
            }
        )
    if not rows:
        rows.append(
            {
                "module": module_name,
                "tool_name": "none_registered",
                "decision": "missing",
                "v2_disposition": "missing",
                "environment": "",
                "install_method": "",
                "module_aliases": aliases,
            }
        )
    return rows


def tool_decision_summary(module_name: str) -> dict[str, list[str]]:
    summary: dict[str, list[str]] = {
        "keep_default": [],
        "keep_optional": [],
        "adapter_only": [],
        "licensed_path_only": [],
        "reference_only": [],
        "rejected_cleaned": [],
    }
    for row in tool_coverage_rows(module_name):
        decision = row["decision"]
        if decision in summary:
            summary[decision].append(row["tool_name"])
    return summary


def v2_disposition_summary(module_name: str) -> dict[str, list[str]]:
    summary: dict[str, list[str]] = {
        "default_backend": [],
        "optional_backend": [],
        "handoff_adapter": [],
        "licensed_path_detection": [],
        "reference_only": [],
        "rejected_cleaned": [],
    }
    for row in tool_coverage_rows(module_name):
        disposition = row.get("v2_disposition", "")
        if disposition in summary:
            summary[disposition].append(row["tool_name"])
    return summary


def write_tool_coverage_table(module_name: str, tables_dir: Path) -> str:
    path = tables_dir / "tool_coverage.tsv"
    pd.DataFrame(tool_coverage_rows(module_name)).to_csv(path, sep="\t", index=False)
    return str(path)


def _handoff_capabilities(module_name: str) -> list[str]:
    statuses = {"template_only"}
    decisions = {row["decision"] for row in tool_coverage_rows(module_name)}
    if "licensed_path_only" in decisions:
        statuses.add("path_detection")
    if "adapter_only" in decisions:
        statuses.add("command_plan_generated")
    if _module_has_slurm_adapter(module_name):
        statuses.add("slurm_adapter_ready")
    return [status for status in HANDOFF_STATUSES if status in statuses]


def _primary_handoff_status(statuses: list[str]) -> str:
    priority = {
        "fully_executable_backend": 6,
        "slurm_adapter_ready": 5,
        "command_plan_generated": 4,
        "import_validated_output": 3,
        "path_detection": 2,
        "template_only": 1,
    }
    return max(statuses or ["template_only"], key=lambda status: priority.get(status, 0))


def _module_has_slurm_adapter(module_name: str) -> bool:
    slurm_dir = Path(__file__).resolve().parents[3] / "slurm"
    if not slurm_dir.exists():
        return False
    aliases = _module_aliases(module_name)
    for script in slurm_dir.glob("*.sbatch"):
        name = script.name.lower()
        if module_name in name:
            return True
        if module_name == "rnaseq" and "bulk" in name:
            return True
        if module_name == "scrna" and ("scrna" in name or "singlecell" in name):
            return True
        if module_name == "functional_state" and "singlecell" in name:
            return True
        if module_name == "spatial" and "singlecell" in name:
            return True
        if aliases.intersection({"scdna", "mtdna"}) and ("scdna" in name or "mtdna" in name or "genome_mtdna" in name):
            return True
    return False


def write_module_qc_manifest(
    *,
    module_name: str,
    tables_dir: Path,
    status: str,
    artifacts: dict[str, Any],
    analysis_fields: dict[str, Any],
    warnings: list[str] | None = None,
    skip_reasons: list[str] | None = None,
) -> str:
    path = tables_dir / "module_qc_manifest.json"
    manifest = {
        "module": module_name,
        "status": status,
        "analysis_level": analysis_fields.get("analysis_level"),
        "is_demo": analysis_fields.get("is_demo"),
        "is_stub": analysis_fields.get("is_stub"),
        "delivery_allowed": analysis_fields.get("delivery_allowed"),
        "validation_evidence_allowed": analysis_fields.get("validation_evidence_allowed"),
        "non_delivery_reason": analysis_fields.get("non_delivery_reason"),
        "mvp_output_spec": module_mvp_output_spec(module_name),
        "artifacts": artifacts,
        "warnings": warnings or [],
        "skip_reasons": skip_reasons or [],
    }
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(path)


def write_module_methods_fragment(module_name: str, reports_dir: Path) -> str:
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"{module_name}_methods.md"
    contract = module_contract(module_name)
    spec = module_mvp_output_spec(module_name)
    lines = [
        f"# {contract.title_cn} (`{module_name}`) MVP 方法片段",
        "",
        "## 输入契约",
        "",
        f"- 支持输入：`{', '.join(contract.supported_input_types)}`",
        f"- 标准输出：`{contract.standard_output}`",
        "",
        "## MVP 产物",
        "",
        f"- 表格：`{', '.join(spec['tables'])}`",
        f"- 图表：`{', '.join(spec['figures'])}`",
        f"- 对象/交接文件：`{spec['object']}`",
        "",
        "## 限制",
        "",
        *[f"- {item}" for item in contract.known_limitations],
        "",
        "未正式接入的高级工具只作为 handoff/optional backend，不写成 fully automatic。",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


def write_module_report_bundle(module_manifest: dict[str, Any], reports_dir: Path) -> dict[str, str]:
    """Write module-local report, methods, and manifest files for independent review."""

    reports_dir.mkdir(parents=True, exist_ok=True)
    module_name = str(module_manifest.get("module", "unknown"))
    contract = module_contract(module_name) if module_name in MODULE_MVP_TABLES else None
    title = str(module_manifest.get("title_cn") or (contract.title_cn if contract else module_name))
    analysis_level = str(module_manifest.get("analysis_level", "unknown"))
    delivery_allowed = bool(module_manifest.get("delivery_allowed", False))
    validation_allowed = bool(module_manifest.get("validation_evidence_allowed", False))
    non_delivery_reason = str(module_manifest.get("non_delivery_reason") or "")
    status = str(module_manifest.get("status", "unknown"))
    artifacts = module_manifest.setdefault("artifacts", {})
    tables = (artifacts.get("tables") or {}) if isinstance(artifacts.get("tables"), dict) else {}
    figures = (artifacts.get("figures") or {}) if isinstance(artifacts.get("figures"), dict) else {}
    objects = (artifacts.get("objects") or {}) if isinstance(artifacts.get("objects"), dict) else {}
    limitations = [str(item) for item in module_manifest.get("limitations", [])]
    handoff = module_manifest.get("handoff") if isinstance(module_manifest.get("handoff"), dict) else {}

    methods_path = reports_dir / "methods.md"
    report_path = reports_dir / "report.html"
    run_manifest_path = reports_dir / "run_manifest.json"

    methods_lines = [
        f"# {title} (`{module_name}`) 模块方法与交付说明",
        "",
        "## 运行级别",
        "",
        f"- status: `{status}`",
        f"- analysis_level: `{analysis_level}`",
        f"- delivery_allowed: `{str(delivery_allowed).lower()}`",
        f"- validation_evidence_allowed: `{str(validation_allowed).lower()}`",
        f"- non_delivery_reason: `{non_delivery_reason or 'none'}`",
        "",
        "## 输入与输出契约",
        "",
    ]
    if contract is not None:
        methods_lines.extend(
            [
                f"- 支持输入：`{', '.join(contract.supported_input_types)}`",
                f"- 标准输出：`{contract.standard_output}`",
            ]
        )
    methods_lines.extend(
        [
            "",
            "## 本模块产物",
            "",
            f"- 表格数量：`{len(tables)}`",
            f"- 图表数量：`{len(figures)}`",
            f"- 对象数量：`{len(objects)}`",
            f"- 模块 manifest：`{run_manifest_path}`",
            "",
            "## 解释边界",
            "",
        ]
    )
    methods_lines.extend([f"- {item}" for item in limitations] or ["- 未记录额外限制。"])
    methods_lines.extend(
        [
            "",
            "## 高级工具状态",
            "",
            f"- handoff_status: `{handoff.get('handoff_status', 'not_recorded')}`",
            "- 未正式接入的高级工具只作为 handoff/optional backend，不写成 fully automatic。",
            "",
        ]
    )
    methods_path.write_text("\n".join(methods_lines), encoding="utf-8")

    def list_items(values: dict[str, Any]) -> str:
        if not values:
            return "<li>none</li>"
        return "\n".join(f"<li><code>{html.escape(str(key))}</code>: {html.escape(str(value))}</li>" for key, value in sorted(values.items()))

    report_html = f"""<!doctype html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"utf-8\">
  <title>{html.escape(title)} - {html.escape(module_name)}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 32px; color: #243142; background: #ffffff; }}
    h1 {{ color: #1f4e79; }}
    .badge {{ display: inline-block; padding: 4px 8px; border-radius: 6px; background: #e8eef5; margin-right: 8px; }}
    .warn {{ color: #8a2d2d; }}
    code {{ background: #f3f6f9; padding: 1px 4px; border-radius: 4px; }}
  </style>
</head>
<body>
  <h1>{html.escape(title)} <code>{html.escape(module_name)}</code></h1>
  <p>
    <span class=\"badge\">status: {html.escape(status)}</span>
    <span class=\"badge\">analysis_level: {html.escape(analysis_level)}</span>
    <span class=\"badge\">delivery_allowed: {str(delivery_allowed).lower()}</span>
  </p>
  <p class=\"warn\">{html.escape(non_delivery_reason or 'production_backend requires approval gate; validated_backend is evidence only.')}</p>
  <h2>Tables</h2>
  <ul>{list_items(tables)}</ul>
  <h2>Figures</h2>
  <ul>{list_items(figures)}</ul>
  <h2>Objects</h2>
  <ul>{list_items(objects)}</ul>
  <h2>Known Limitations</h2>
  <ul>{''.join(f'<li>{html.escape(item)}</li>' for item in limitations) or '<li>未记录额外限制。</li>'}</ul>
</body>
</html>
"""
    report_path.write_text(report_html, encoding="utf-8")

    report_artifacts = artifacts.setdefault("reports", {})
    report_artifacts.update(
        {
            "report_html": str(report_path),
            "methods_md": str(methods_path),
            "run_manifest": str(run_manifest_path),
        }
    )
    module_manifest["module_report"] = {
        "report_html": str(report_path),
        "methods_md": str(methods_path),
        "run_manifest": str(run_manifest_path),
    }
    run_manifest_path.write_text(json.dumps(module_manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return dict(report_artifacts)


def write_mvp_tables(
    *,
    module_name: str,
    tables_dir: Path,
    matrix: pd.DataFrame | None = None,
    stats: pd.DataFrame | None = None,
    samples: pd.DataFrame | None = None,
    analysis_fields: dict[str, Any] | None = None,
    run_id: str | None = None,
    source_dataset: str | None = None,
    input_artifact: str | None = None,
    input_modality: str | None = None,
) -> dict[str, str]:
    tables_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}
    base = _base_mvp_frame(module_name, matrix=matrix, stats=stats, samples=samples)
    for filename in MODULE_MVP_TABLES.get(module_name, ("mvp_summary.tsv",)):
        path = tables_dir / filename
        frame = _table_frame_for_name(module_name, filename, base, matrix=matrix, stats=stats, samples=samples)
        frame = _coerce_mvp_table_schema(
            module_name,
            filename,
            frame,
            matrix=matrix,
            samples=samples,
            analysis_fields=analysis_fields,
            run_id=run_id,
            source_dataset=source_dataset,
            input_artifact=input_artifact,
            input_modality=input_modality,
        )
        frame.to_csv(path, sep="\t", index=False)
        paths[_artifact_key(filename)] = str(path)
    return paths


def write_mvp_figures(*, module_name: str, figures_dir: Path, matrix: pd.DataFrame | None = None) -> dict[str, str]:
    figures_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}
    for filename in MODULE_MVP_FIGURES.get(module_name, ("mvp_overview.png",)):
        path = figures_dir / filename
        _plot_mvp_figure(module_name, filename, path, matrix=matrix)
        paths[_artifact_key(filename)] = str(path)
    return paths


def write_mvp_object(
    *,
    module_name: str,
    objects_dir: Path,
    matrix: pd.DataFrame | None = None,
    stats: pd.DataFrame | None = None,
) -> dict[str, str]:
    objects_dir.mkdir(parents=True, exist_ok=True)
    object_name = MODULE_MVP_OBJECTS.get(module_name, f"{module_name}_mvp_object.rds")
    object_path = objects_dir / object_name
    manifest_path = objects_dir / "mvp_object_manifest.json"
    payload = {
        "module": module_name,
        "object_name": object_name,
        "status": "mvp_object_or_handoff",
        "matrix_shape": list(matrix.shape) if matrix is not None else [],
        "top_features": stats.head(10)["feature_id"].astype(str).tolist() if stats is not None and "feature_id" in stats.columns else [],
        "note": "MVP object/handoff placeholder; not a full advanced backend result unless a validated backend records otherwise.",
    }
    object_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    manifest_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"mvp_object": str(object_path), "mvp_object_manifest": str(manifest_path)}


def report_contract(module_name: str) -> dict[str, Any]:
    manifest = demo_manifest(module_name)
    return {"module": module_name, **report_contract_status(manifest)}


def known_limitations(module_name: str) -> tuple[str, ...]:
    return MODULE_LIMITATIONS.get(
        module_name,
        (
            "validated_backend 不等于客户正式交付。",
            "production_backend 必须经过 approval gate。",
            "高级工具未接入时只能作为 handoff。",
        ),
    )


def run_contract_smoke(module_name: str, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = demo_manifest(module_name)
    manifest["contract"] = module_contract(module_name).to_dict()
    manifest_path = output_dir / "module_contract_smoke_manifest.json"
    import json

    manifest["manifest_path"] = str(manifest_path)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def _base_mvp_frame(
    module_name: str,
    *,
    matrix: pd.DataFrame | None,
    stats: pd.DataFrame | None,
    samples: pd.DataFrame | None,
) -> pd.DataFrame:
    if stats is not None and not stats.empty:
        frame = stats.head(12).copy()
        if "feature_id" not in frame.columns:
            frame.insert(0, "feature_id", [f"{module_name}_feature_{idx+1}" for idx in range(len(frame))])
    elif matrix is not None and not matrix.empty:
        frame = pd.DataFrame(
            {
                "feature_id": matrix.index.astype(str)[:12],
                "mean_value": matrix.mean(axis=1).to_numpy()[:12],
                "detected_samples": (matrix > 0).sum(axis=1).to_numpy()[:12],
            }
        )
    else:
        frame = pd.DataFrame({"feature_id": [f"{module_name}_feature_1"], "value": [1.0]})
    frame.insert(0, "module", module_name)
    frame["mvp_status"] = "design_ready_or_handoff"
    frame["delivery_allowed"] = False
    return frame


def _table_frame_for_name(
    module_name: str,
    filename: str,
    base: pd.DataFrame,
    *,
    matrix: pd.DataFrame | None,
    stats: pd.DataFrame | None,
    samples: pd.DataFrame | None,
) -> pd.DataFrame:
    if "placeholder" in filename or "handoff" in filename:
        return pd.DataFrame(
            [
                {
                    "module": module_name,
                    "artifact": filename,
                    "status": "handoff_or_placeholder_not_biological_conclusion",
                    "delivery_allowed": False,
                    "note": "高级工具未正式接入时只作为 handoff/optional backend。",
                }
            ]
        )
    if "sample" in filename or "composition" in filename or "assignment" in filename:
        if samples is not None and not samples.empty:
            frame = samples.copy()
        elif matrix is not None and not matrix.empty:
            frame = pd.DataFrame({"sample_id": matrix.columns.astype(str)})
        else:
            frame = pd.DataFrame({"sample_id": ["sample_1"]})
        frame.insert(0, "module", module_name)
        frame["artifact"] = filename
        frame["delivery_allowed"] = False
        return frame
    if "matrix" in filename or "counts" in filename or "scores" in filename:
        if matrix is not None and not matrix.empty:
            frame = matrix.head(12).reset_index().rename(columns={matrix.index.name or "index": "feature_id"})
            frame.insert(0, "module", module_name)
            return frame
    return base.assign(artifact=filename)


def _mvp_table_schema(module_name: str, filename: str) -> list[str]:
    exact: dict[tuple[str, str], list[str]] = {
        ("vdj", "vdj_qc.tsv"): ["module", "sample_id", "productive_contig_count", "paired_chain_count", "vdj_input_status", "delivery_allowed"],
        ("vdj", "clonotype_summary.tsv"): ["module", "clonotype_id", "chain", "cdr3_aa", "cell_count", "sample_count", "antigen_specificity_status", "delivery_allowed"],
        ("vdj", "clone_expansion.tsv"): ["module", "sample_id", "clonotype_id", "clone_size", "expansion_class", "delivery_allowed"],
        ("vdj", "clone_sharing.tsv"): ["module", "sample_id_a", "sample_id_b", "shared_clonotype_count", "sharing_metric", "interpretation_warning"],
        ("vdj", "v_gene_usage.tsv"): ["module", "sample_id", "v_gene", "productive_chain_count", "usage_fraction", "delivery_allowed"],
        ("vdj", "j_gene_usage.tsv"): ["module", "sample_id", "j_gene", "productive_chain_count", "usage_fraction", "delivery_allowed"],
        ("vdj", "cdr3_length.tsv"): ["module", "sample_id", "chain", "cdr3_length_aa", "cell_count", "delivery_allowed"],
        ("vdj", "clone_condition_summary.tsv"): ["module", "condition", "clonotype_id", "clone_size", "clone_state_handoff_status", "delivery_allowed"],
        ("scdna", "coverage_qc.tsv"): ["module", "cell_id", "mean_depth", "covered_loci", "dropout_warning", "delivery_allowed"],
        ("scdna", "variant_qc.tsv"): ["module", "variant_id", "chrom", "pos", "ref", "alt", "depth", "vaf", "filter_status"],
        ("scdna", "cell_variant_matrix.tsv"): ["module", "cell_id", "variant_id", "genotype_call", "alt_count", "ref_count", "assay_limitation"],
        ("scdna", "cell_vaf_matrix.tsv"): ["module", "cell_id", "variant_id", "chrom", "pos", "ref", "alt", "vaf", "depth", "assay_limitation"],
        ("scdna", "cell_cnv_matrix.tsv"): ["module", "cell_id", "chrom", "start", "end", "copy_number_state", "confidence"],
        ("scdna", "clone_summary.tsv"): ["module", "clone_id", "cell_count", "marker_variants", "clone_call_status", "interpretation_warning"],
        ("scdna", "mutation_cooccurrence.tsv"): ["module", "variant_id_a", "variant_id_b", "cooccurrence_count", "cooccurrence_status"],
        ("scdna", "phylogeny_input.tsv"): ["module", "cell_id", "variant_id", "binary_state", "phylogeny_handoff_status"],
        ("mtdna", "mtdna_depth_by_cell.tsv"): ["module", "cell_id", "mt_chromosome", "mean_mtdna_depth", "dropout_flag", "lineage_ready"],
        ("mtdna", "mtdna_depth_by_position.tsv"): ["module", "mt_chromosome", "position", "depth", "homopolymer_warning"],
        ("mtdna", "variant_candidates.tsv"): ["module", "variant_id", "mt_chromosome", "position", "ref", "alt", "heteroplasmy", "filter_status"],
        ("mtdna", "high_confidence_variants.tsv"): ["module", "variant_id", "mt_chromosome", "position", "ref", "alt", "heteroplasmy", "high_confidence_status"],
        ("mtdna", "cell_variant_vaf_matrix.tsv"): ["module", "cell_id", "variant_id", "vaf", "depth", "lineage_ready"],
        ("mtdna", "cell_variant_alt_count_matrix.tsv"): ["module", "cell_id", "variant_id", "alt_count", "depth", "lineage_ready"],
        ("mtdna", "shared_variant_matrix.tsv"): ["module", "cell_id", "paired_cell_id", "variant_id", "shared_high_confidence", "interpretation_warning"],
        ("mtdna", "lineage_input.tsv"): ["module", "cell_id", "variant_id", "binary_state", "lineage_handoff_status"],
        ("hto_demux", "hto_assignment.tsv"): ["module", "cell_id", "hashtag_id", "assigned_sample", "assignment_class", "confidence", "threshold_note"],
        ("hto_demux", "hto_qc.tsv"): ["module", "cell_id", "total_hto_counts", "background_status", "positive_hashtag_count", "delivery_allowed"],
        ("hto_demux", "sample_assignment_summary.tsv"): ["module", "sample_id", "singlet_count", "doublet_count", "negative_count", "assignment_status"],
        ("hto_demux", "doublet_summary.tsv"): ["module", "sample_id", "hto_doublet_count", "doublet_rate", "threshold_note"],
        ("hto_demux", "cell_metadata_with_sample.tsv"): ["module", "cell_id", "assigned_sample", "assignment_class", "confidence", "metadata_handoff_status"],
        ("genotype_demux", "snp_qc.tsv"): ["module", "snp_id", "chrom", "pos", "covered_cell_count", "reference_vcf_status"],
        ("genotype_demux", "assignment.tsv"): ["module", "cell_id", "assigned_genotype", "doublet_status", "assignment_probability", "snp_count", "reference_vcf_status"],
        ("genotype_demux", "doublet_summary.tsv"): ["module", "assigned_genotype", "doublet_count", "doublet_rate", "method_status"],
        ("genotype_demux", "sample_composition.tsv"): ["module", "assigned_genotype", "cell_count", "composition_fraction", "assignment_status"],
        ("genotype_demux", "assignment_confidence.tsv"): ["module", "cell_id", "assigned_genotype", "assignment_probability", "confidence_class"],
        ("genotype_demux", "cell_metadata_with_genotype.tsv"): ["module", "cell_id", "assigned_genotype", "doublet_status", "assignment_probability", "metadata_handoff_status"],
        ("perturb_seq", "guide_qc.tsv"): ["module", "cell_id", "guide_id", "guide_count", "assignment_status", "multiplet_warning"],
        ("perturb_seq", "guide_assignment.tsv"): ["module", "cell_id", "guide_id", "target_gene", "assignment_class", "confidence", "multiplet_strategy"],
        ("perturb_seq", "perturbation_summary.tsv"): ["module", "perturbation", "target_gene", "cell_count", "control_status", "delivery_allowed"],
        ("perturb_seq", "perturbation_expression_effect.tsv"): ["module", "perturbation", "target_gene", "feature_id", "effect_size", "model_status"],
        ("perturb_seq", "pseudobulk_by_perturbation.tsv"): ["module", "perturbation", "sample_id", "feature_id", "count_value", "design_ready_status"],
        ("perturb_seq", "target_response.tsv"): ["module", "target_gene", "response_feature", "effect_size", "mechanism_warning"],
        ("cite_seq", "adt_qc.tsv"): ["module", "cell_id", "adt_total_counts", "background_status", "isotype_control_status"],
        ("cite_seq", "antibody_panel.tsv"): ["module", "antibody_id", "target_protein", "isotype_control", "panel_scope_note"],
        ("cite_seq", "adt_normalized_matrix.tsv"): ["module", "cell_id", "antibody_id", "normalized_adt", "normalization_method"],
        ("cite_seq", "adt_marker_summary.tsv"): ["module", "cluster_id", "antibody_id", "target_protein", "marker_score", "delivery_allowed"],
        ("cite_seq", "rna_protein_consistency.tsv"): ["module", "cell_id", "gene_symbol", "antibody_id", "correlation_proxy", "mechanism_warning"],
        ("spatial", "spatial_qc.tsv"): ["module", "spot_id", "total_counts", "detected_genes", "in_tissue", "platform_note"],
        ("spatial", "spot_metadata.tsv"): ["module", "spot_id", "array_row", "array_col", "pxl_row", "pxl_col", "in_tissue"],
        ("spatial", "coordinate_check.tsv"): ["module", "spot_id", "coordinate_status", "image_status", "coordinate_system"],
        ("spatial", "domain_summary.tsv"): ["module", "domain_id", "spot_count", "domain_method_status", "visium_spot_warning"],
        ("spatial", "spatial_neighbors.tsv"): ["module", "spot_id", "neighbor_spot_id", "distance", "graph_status"],
        ("scatac", "cell_qc.tsv"): ["module", "cell_id", "n_fragments", "peak_region_fragments", "tss_enrichment_status", "frip_status"],
        ("scatac", "fragment_qc.tsv"): ["module", "fragments_file", "fragment_count", "barcode_count", "fragments_available"],
        ("scatac", "peak_matrix_summary.tsv"): ["module", "peak_id", "chrom", "start", "end", "detected_cell_count", "accessibility_status"],
        ("scatac", "marker_peaks.tsv"): ["module", "cluster_id", "peak_id", "log2fc", "accessibility_not_expression_warning"],
        ("multiome", "barcode_overlap.tsv"): ["module", "rna_barcode_count", "atac_barcode_count", "overlap_count", "overlap_fraction", "overlap_status"],
        ("multiome", "modality_consistency.tsv"): ["module", "cell_id", "rna_qc_status", "atac_qc_status", "joint_object_status", "modality_warning"],
    }
    if (module_name, filename) in exact:
        return _with_global_mvp_columns(exact[(module_name, filename)])
    if "handoff" in filename or "placeholder" in filename:
        return _with_global_mvp_columns(["module", "artifact", "status", "handoff_tool", "required_input", "delivery_allowed", "note"])
    if "qc" in filename:
        return _with_global_mvp_columns(["module", "sample_id", "qc_metric", "qc_value", "qc_status", "delivery_allowed"])
    if "matrix" in filename or "counts" in filename or "scores" in filename:
        return _with_global_mvp_columns(["module", "feature_id", "sample_id", "value", "matrix_status", "delivery_allowed"])
    if "summary" in filename:
        return _with_global_mvp_columns(["module", "summary_id", "summary_metric", "summary_value", "summary_status", "delivery_allowed"])
    if "correlation" in filename:
        return _with_global_mvp_columns(["module", "feature_id_a", "feature_id_b", "correlation", "correlation_warning", "delivery_allowed"])
    return _with_global_mvp_columns(["module", "artifact", "feature_id", "value", "mvp_status", "delivery_allowed"])


def _with_global_mvp_columns(columns: list[str]) -> list[str]:
    deduped = list(dict.fromkeys([*GLOBAL_MVP_TABLE_COLUMNS, *columns]))
    return deduped


def _coerce_mvp_table_schema(
    module_name: str,
    filename: str,
    frame: pd.DataFrame,
    *,
    matrix: pd.DataFrame | None,
    samples: pd.DataFrame | None,
    analysis_fields: dict[str, Any] | None = None,
    run_id: str | None = None,
    source_dataset: str | None = None,
    input_artifact: str | None = None,
    input_modality: str | None = None,
) -> pd.DataFrame:
    schema = _mvp_table_schema(module_name, filename)
    frame = frame.copy()
    if frame.empty:
        frame = pd.DataFrame(index=range(1))
    for column in schema:
        if column not in frame.columns:
            frame[column] = _default_schema_column(
                column,
                module_name,
                filename,
                len(frame),
                matrix=matrix,
                samples=samples,
                analysis_fields=analysis_fields,
                run_id=run_id,
                source_dataset=source_dataset,
                input_artifact=input_artifact,
                input_modality=input_modality,
            )
    extras = [column for column in frame.columns if column not in schema]
    return frame[schema + extras]


def _default_schema_column(
    column: str,
    module_name: str,
    filename: str,
    n_rows: int,
    *,
    matrix: pd.DataFrame | None,
    samples: pd.DataFrame | None,
    analysis_fields: dict[str, Any] | None = None,
    run_id: str | None = None,
    source_dataset: str | None = None,
    input_artifact: str | None = None,
    input_modality: str | None = None,
) -> list[Any]:
    sample_ids = _sample_ids(samples=samples, matrix=matrix)
    feature_ids = _feature_ids(module_name, matrix=matrix)
    def cycle(values: list[Any]) -> list[Any]:
        return [values[idx % len(values)] for idx in range(n_rows)] if values else [""] * n_rows

    if column == "module":
        return [module_name] * n_rows
    if column == "run_id":
        return [run_id or "not_recorded"] * n_rows
    if column == "source_dataset":
        return [source_dataset or "not_recorded"] * n_rows
    if column == "input_artifact":
        return [input_artifact or "not_recorded"] * n_rows
    if column == "input_modality":
        return [input_modality or module_name] * n_rows
    if column == "analysis_level":
        return [str((analysis_fields or {}).get("analysis_level") or "not_recorded")] * n_rows
    if column == "result_scope":
        return [_result_scope(filename)] * n_rows
    if column == "method_status":
        return [_method_status(filename)] * n_rows
    if column == "delivery_allowed":
        allowed = bool((analysis_fields or {}).get("delivery_allowed")) and not _is_handoff_or_placeholder_table(filename)
        return [allowed] * n_rows
    if column in {"lineage_ready", "fragments_available", "in_tissue", "isotype_control", "shared_high_confidence"}:
        return [False] * n_rows
    if column in {"sample_id", "sample_id_a", "assigned_sample", "condition"}:
        return cycle(sample_ids)
    if column == "sample_id_b":
        return cycle(list(reversed(sample_ids)))
    if column in {"cell_id", "paired_cell_id", "spot_id", "neighbor_spot_id"}:
        prefix = "SPOT" if "spatial" in module_name else "CELL"
        return [f"{prefix}_{idx+1:04d}" for idx in range(n_rows)]
    if column in {"feature_id", "response_feature"}:
        return cycle(feature_ids)
    if column in {"gene_symbol", "target_gene"}:
        return cycle(["TP53", "MKI67", "IFNG", "EPCAM"])
    if column in {"variant_id", "variant_id_a", "variant_id_b"}:
        return [f"VAR_{idx+1:04d}" for idx in range(n_rows)]
    if column == "snp_id":
        return [f"rs{100000+idx}" for idx in range(n_rows)]
    if column == "peak_id":
        return [f"chr1:{1000+idx*100}-{1050+idx*100}" for idx in range(n_rows)]
    if column == "region_id":
        return [f"region_{idx+1:04d}" for idx in range(n_rows)]
    if column in {"chrom", "mt_chromosome"}:
        return ["chrM" if module_name == "mtdna" else "chr1"] * n_rows
    if column in {"pos", "position", "start"}:
        return [1000 + idx * 10 for idx in range(n_rows)]
    if column == "end":
        return [1050 + idx * 10 for idx in range(n_rows)]
    if column == "ref":
        return ["A"] * n_rows
    if column == "alt":
        return ["G"] * n_rows
    if column in {"chain"}:
        return cycle(["TRA", "TRB"])
    if column == "clonotype_id":
        return [f"clonotype_{idx+1}" for idx in range(n_rows)]
    if column == "clone_id":
        return [f"clone_{idx+1}" for idx in range(n_rows)]
    if column in {"cdr3_aa"}:
        return [f"CASSLGQG{idx}EQYF" for idx in range(n_rows)]
    if column == "v_gene":
        return cycle(["TRBV7-2", "TRBV20-1", "IGHV3-23"])
    if column == "j_gene":
        return cycle(["TRBJ2-7", "TRBJ1-2", "IGHJ4"])
    if column in {"hashtag_id", "antibody_id", "guide_id"}:
        prefix = {"hashtag_id": "HTO", "antibody_id": "ADT", "guide_id": "gRNA"}[column]
        return [f"{prefix}_{idx+1}" for idx in range(n_rows)]
    if column == "assigned_genotype":
        return cycle(["donor_1", "donor_2", "unassigned"])
    if column == "perturbation":
        return cycle(["non_targeting", "TP53_KO", "IFNG_KO"])
    if column in {"status", "mvp_status", "matrix_status", "summary_status", "qc_status", "filter_status", "assignment_status", "metadata_handoff_status", "lineage_handoff_status", "phylogeny_handoff_status", "vdj_input_status", "joint_object_status", "overlap_status", "normalization_method", "domain_method_status", "graph_status", "clone_call_status", "model_status", "design_ready_status", "high_confidence_status", "reference_vcf_status", "coordinate_status", "image_status", "background_status", "tss_enrichment_status", "frip_status"}:
        return ["mvp_design_ready_or_handoff"] * n_rows
    if column in {"note", "interpretation_warning", "mechanism_warning", "assay_limitation", "dropout_warning", "homopolymer_warning", "modality_warning", "accessibility_not_expression_warning", "visium_spot_warning", "threshold_note", "panel_scope_note", "correlation_warning", "multiplet_warning"}:
        return ["MVP/handoff field; not a final biological conclusion."] * n_rows
    if column in {"handoff_tool"}:
        return ["optional_backend"] * n_rows
    if column in {"required_input"}:
        return [filename] * n_rows
    if column in {"artifact", "qc_metric", "summary_metric"}:
        return [Path(filename).stem] * n_rows
    if column in {"assignment_class", "doublet_status", "confidence_class", "expansion_class", "clone_state_handoff_status", "control_status", "antigen_specificity_status", "multiplet_strategy", "copy_number_state", "coordinate_system"}:
        return ["not_asserted_mvp"] * n_rows
    if column in {"cell_count", "sample_count", "productive_contig_count", "paired_chain_count", "clone_size", "productive_chain_count", "cdr3_length_aa", "shared_clonotype_count", "mean_depth", "covered_loci", "depth", "alt_count", "ref_count", "covered_cell_count", "snp_count", "doublet_count", "singlet_count", "negative_count", "hto_doublet_count", "guide_count", "total_hto_counts", "positive_hashtag_count", "adt_total_counts", "detected_genes", "total_counts", "spot_count", "detected_cell_count", "fragment_count", "barcode_count", "n_fragments", "peak_region_fragments", "rna_barcode_count", "atac_barcode_count", "overlap_count"}:
        return [idx + 1 for idx in range(n_rows)]
    if column in {"usage_fraction", "sharing_metric", "vaf", "heteroplasmy", "confidence", "assignment_probability", "composition_fraction", "doublet_rate", "effect_size", "count_value", "normalized_adt", "marker_score", "correlation_proxy", "distance", "overlap_fraction", "log2fc", "qc_value", "summary_value", "value", "correlation"}:
        return [round((idx + 1) / max(n_rows, 1), 4) for idx in range(n_rows)]
    return [f"{column}_{idx+1}" for idx in range(n_rows)]


def _is_handoff_or_placeholder_table(filename: str) -> bool:
    name = filename.lower()
    return "handoff" in name or "placeholder" in name


def _result_scope(filename: str) -> str:
    if _is_handoff_or_placeholder_table(filename):
        return "mvp_handoff_not_biological_conclusion"
    return "mvp_smoke_or_design_ready"


def _method_status(filename: str) -> str:
    if _is_handoff_or_placeholder_table(filename):
        return "handoff_or_placeholder_not_fully_automatic"
    return "mvp_design_ready_or_basic_backend"


def _sample_ids(*, samples: pd.DataFrame | None, matrix: pd.DataFrame | None) -> list[str]:
    if samples is not None and "sample_id" in samples.columns and not samples.empty:
        return samples["sample_id"].astype(str).tolist()
    if matrix is not None and not matrix.empty:
        return matrix.columns.astype(str).tolist()
    return ["sample_1"]


def _feature_ids(module_name: str, *, matrix: pd.DataFrame | None) -> list[str]:
    if matrix is not None and not matrix.empty:
        return matrix.index.astype(str).tolist()
    return [f"{module_name}_feature_{idx+1}" for idx in range(12)]


def _plot_mvp_figure(module_name: str, filename: str, path: Path, *, matrix: pd.DataFrame | None) -> None:
    tokens = apply_clinical_journal_style()
    values = _plot_matrix_values(matrix)
    plt.figure(figsize=(6, 4))
    lower = filename.lower()
    if "heatmap" in lower or "map" in lower or "correlation" in lower:
        sns.heatmap(values, cmap=continuous_cmap(tokens), cbar_kws={"label": "MVP value"})
    elif "umap" in lower or "pca" in lower or "embedding" in lower:
        coords = _coords_from_values(values)
        plt.scatter(coords[:, 0], coords[:, 1], c=tokens["primary"], s=40, edgecolors="white", linewidths=0.4)
        plt.xlabel("Axis 1")
        plt.ylabel("Axis 2")
    else:
        means = values.mean(axis=0)
        plt.bar(range(len(means)), means, color=tokens["primary"], edgecolor="white", linewidth=0.4)
        plt.xlabel("Group")
        plt.ylabel("MVP value")
    plt.title(f"{module_name} {filename.replace('_', ' ').replace('.png', '')}")
    plt.tight_layout()
    save_figure(path, style=tokens)


def _plot_matrix_values(matrix: pd.DataFrame | None) -> np.ndarray:
    if matrix is None or matrix.empty:
        rng = np.random.default_rng(7)
        return rng.normal(size=(8, 4))
    values = matrix.iloc[:12, : min(8, matrix.shape[1])].to_numpy(dtype=float)
    if values.ndim != 2 or values.size == 0:
        return np.zeros((2, 2))
    return values


def _coords_from_values(values: np.ndarray) -> np.ndarray:
    rows = values.T
    rows = rows - rows.mean(axis=0, keepdims=True)
    if rows.shape[0] < 2:
        return np.c_[np.arange(rows.shape[0]), np.zeros(rows.shape[0])]
    _, _, vt = np.linalg.svd(rows, full_matrices=False)
    if vt.shape[0] < 2:
        return np.c_[rows @ vt[0], np.zeros(rows.shape[0])]
    return rows @ vt[:2].T


def _artifact_key(filename: str) -> str:
    return Path(filename).stem.replace("-", "_")


def _tools_for_module(module_name: str) -> list[dict[str, str]]:
    aliases = _module_aliases(module_name)
    rows = []
    for tool in TOOL_REGISTRY:
        if tool.module in aliases:
            rows.append(
                {
                    "name": tool.name,
                    "decision": tool.decision,
                    "env": tool.env,
                    "install_method": tool.install_method,
                }
            )
    return rows


def _module_aliases(module_name: str) -> set[str]:
    aliases = {module_name}
    aliases.update(
        {
            "workflow",
            "report",
            "visualization",
            "data_format",
            "interop",
        }
    )
    if module_name == "rnaseq":
        aliases.update({"bulk_rnaseq", "statistics", "pathway", "upstream"})
    if module_name == "scrna":
        aliases.update({"scrna_core", "scrna_r", "scrna_upstream", "scrna_non10x", "annotation", "qc", "integration", "mapping", "pathway", "trajectory", "velocity", "communication", "regulatory", "browser", "reference"})
    if module_name in {"scatac", "scepi"}:
        aliases.update({"scatac", "scatac_upstream", "atac", "genome"})
    if module_name == "multiome":
        aliases.update({"multiome", "multiome_upstream", "scatac", "genome", "regulatory"})
    if module_name == "vdj":
        aliases.update({"vdj", "vdj_upstream", "demultiplex"})
    if module_name in {"scdna", "mtdna", "genotype_demux"}:
        aliases.update({"genome", "genotype", "mtdna", "scdna"})
    if module_name == "cite_seq":
        aliases.update({"cite_seq", "multiome"})
    if module_name == "spatial":
        aliases.update({"spatial", "spatial_upstream", "browser"})
    if module_name in {"functional_state", "tumor_sc", "clinical_assoc", "single_gene", "wgcna", "publicdb"}:
        aliases.update({"statistics", "pathway"})
    if module_name in {"functional_state", "tumor_sc"}:
        aliases.update({"regulatory", "communication"})
    if module_name == "method_tools":
        aliases.update({"browser", "reference"})
    return aliases
