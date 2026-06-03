from __future__ import annotations

from dataclasses import asdict, dataclass
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
    "scrna": "scrna_mvp.h5ad",
    "scatac": "scatac_mvp.h5ad",
    "multiome": "multiome_mvp.h5mu",
    "vdj": "vdj_mvp.h5ad",
    "cite_seq": "cite_mvp.h5mu",
    "spatial": "spatial_mvp.h5ad",
    "method_tools": "cellxgene_ready.h5ad",
}


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
    }


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
    return {
        "module": module_name,
        "handoff_status": "template_ready",
        "handoff_tools": list(contract.handoff_tools),
        "optional_backends": list(contract.primary_tools),
        "tool_decision_summary": tool_decision_summary(module_name),
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


def write_tool_coverage_table(module_name: str, tables_dir: Path) -> str:
    path = tables_dir / "tool_coverage.tsv"
    pd.DataFrame(tool_coverage_rows(module_name)).to_csv(path, sep="\t", index=False)
    return str(path)


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


def write_mvp_tables(
    *,
    module_name: str,
    tables_dir: Path,
    matrix: pd.DataFrame | None = None,
    stats: pd.DataFrame | None = None,
    samples: pd.DataFrame | None = None,
) -> dict[str, str]:
    tables_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}
    base = _base_mvp_frame(module_name, matrix=matrix, stats=stats, samples=samples)
    for filename in MODULE_MVP_TABLES.get(module_name, ("mvp_summary.tsv",)):
        path = tables_dir / filename
        frame = _table_frame_for_name(module_name, filename, base, matrix=matrix, stats=stats, samples=samples)
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
        aliases.update({"scrna_core", "scrna_r", "scrna_upstream", "scrna_non10x", "annotation", "qc", "integration", "mapping", "pathway", "trajectory", "velocity"})
    if module_name in {"scatac", "scepi"}:
        aliases.update({"scatac", "scatac_upstream", "atac", "specialized_light"})
    if module_name == "multiome":
        aliases.update({"multiome", "multiome_upstream", "scatac"})
    if module_name == "vdj":
        aliases.update({"vdj", "vdj_upstream", "demultiplex"})
    if module_name in {"scdna", "mtdna", "genotype_demux"}:
        aliases.update({"genome", "genotype", "mtdna", "scdna"})
    if module_name == "cite_seq":
        aliases.update({"cite_seq", "multiome"})
    if module_name == "spatial":
        aliases.update({"spatial", "spatial_upstream"})
    if module_name in {"functional_state", "tumor_sc", "clinical_assoc", "single_gene", "wgcna", "publicdb"}:
        aliases.update({"statistics", "pathway"})
    return aliases
