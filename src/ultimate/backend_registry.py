from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ultimate.constants import MODULE_ORDER


BACKEND_ROLES = ("default_backend", "optional_backend", "licensed_backend", "handoff_backend")

AUTOMATIC_STATUSES = {
    "fully_automatic_mvp",
    "fully_automatic_validated_entrypoint",
}


@dataclass(frozen=True)
class BackendSpec:
    backend_id: str
    module: str
    backend_role: str
    preset: str
    label: str
    tool: str
    input_types: tuple[str, ...]
    environment: str
    slurm_profile: str
    output_contract: tuple[str, ...]
    validation_dataset: str
    known_limitations: tuple[str, ...]
    production_allowed: bool
    requires_license: bool = False
    requires_slurm: bool = True
    backend_status: str = "planned_fully_automatic"
    skip_reason: str = ""
    resource_profile: str = "standard"
    interpretation_warning: str = ""


def _backend(
    backend_id: str,
    module: str,
    backend_role: str,
    preset: str,
    label: str,
    tool: str,
    input_types: tuple[str, ...],
    environment: str,
    slurm_profile: str,
    output_contract: tuple[str, ...],
    validation_dataset: str,
    known_limitations: tuple[str, ...],
    *,
    production_allowed: bool,
    requires_license: bool = False,
    requires_slurm: bool = True,
    backend_status: str = "planned_fully_automatic",
    skip_reason: str = "",
    resource_profile: str = "standard",
    interpretation_warning: str = "",
) -> BackendSpec:
    if backend_role not in BACKEND_ROLES:
        raise ValueError(f"Unsupported backend role: {backend_role}")
    return BackendSpec(
        backend_id=backend_id,
        module=module,
        backend_role=backend_role,
        preset=preset,
        label=label,
        tool=tool,
        input_types=input_types,
        environment=environment,
        slurm_profile=slurm_profile,
        output_contract=output_contract,
        validation_dataset=validation_dataset,
        known_limitations=known_limitations,
        production_allowed=production_allowed,
        requires_license=requires_license,
        requires_slurm=requires_slurm,
        backend_status=backend_status,
        skip_reason=skip_reason,
        resource_profile=resource_profile,
        interpretation_warning=interpretation_warning,
    )


BACKEND_REGISTRY: tuple[BackendSpec, ...] = (
    _backend(
        "rnaseq.matrix.python_mvp",
        "rnaseq",
        "default_backend",
        "standard",
        "bulk RNA-seq count/abundance matrix MVP",
        "pandas + matplotlib + seaborn",
        ("count_matrix", "featurecounts", "salmon_quant", "normalized_matrix"),
        "ultimate-core",
        "slurm/bulk_validation_suite.sbatch",
        ("counts_raw.tsv", "counts_normalized.tsv", "sample_qc.tsv", "de_design_ready.tsv", "report.html"),
        "airway public count matrix",
        ("已用 airway 公开 count matrix 完成 matrix-level validation；正式 DESeq2/edgeR 后端仍需单独启用。",),
        production_allowed=True,
        backend_status="fully_automatic_validated_entrypoint",
        resource_profile="small_matrix",
    ),
    _backend(
        "rnaseq.de.deseq2_edger",
        "rnaseq",
        "optional_backend",
        "publication",
        "DESeq2/edgeR differential expression backend",
        "DESeq2 + edgeR",
        ("raw_count_matrix",),
        "ultimate-rnaseq",
        "slurm/bulk_validation_suite.sbatch",
        ("de_results.tsv", "deseq2_edgeR_de_results.tsv", "de_backend_status.tsv", "de_backend_manifest.json", "deseq2_edgeR_volcano.png", "rnaseq_de_backend.rds"),
        "airway public count matrix with Slurm DESeq2/edgeR validation",
        ("不能用 TPM/FPKM 直接跑 DESeq2；没有生物学重复时只能导出 design-ready。",),
        production_allowed=True,
        backend_status="fully_automatic_validated_entrypoint",
        skip_reason="",
        resource_profile="medium_r",
        interpretation_warning="DESeq2/edgeR 结果依赖 raw counts、重复数和设计矩阵审核，不写成机制证明。",
    ),
    _backend(
        "rnaseq.upstream.nfcore_rnaseq",
        "rnaseq",
        "handoff_backend",
        "raw",
        "nf-core/rnaseq FASTQ-to-matrix handoff",
        "nf-core/rnaseq",
        ("fastq", "bcl_handoff"),
        "ultimate-workflow",
        "slurm/nfcore_rnaseq_handoff.sbatch",
        ("samplesheet.csv", "params.yaml", "nextflow.config", "command_plan.md"),
        "nf-core test profile",
        ("本轮只生成 handoff 模板，不自动运行 Nextflow 全流程。",),
        production_allowed=False,
        backend_status="handoff_ready",
        skip_reason="External workflow handoff only until Slurm/container validation is complete.",
        resource_profile="external_nextflow",
    ),
    _backend(
        "scrna.mvp.validate_scrna",
        "scrna",
        "default_backend",
        "standard",
        "scRNA MVP validation entrypoint",
        "scanpy/anndata validate-scrna",
        ("h5ad", "10x_h5", "10x_mtx"),
        "ultimate-scrna",
        "slurm/scrna_mvp_validation.sbatch",
        ("objects/scrna_mvp.h5ad", "qc_metrics.tsv", "marker_genes.tsv", "pseudobulk_counts.tsv", "report.html"),
        "PBMC3k public 10x matrix + h5ad",
        ("cluster label 不是 cell type；pseudobulk 第一版只保证 design-ready。",),
        production_allowed=True,
        backend_status="fully_automatic_validated_entrypoint",
        resource_profile="medium_scrna",
        interpretation_warning="自动聚类标签必须写成 cluster，不得伪装成细胞类型注释。",
    ),
    _backend(
        "scrna.annotation.celltypist",
        "scrna",
        "optional_backend",
        "standard",
        "CellTypist cell type annotation",
        "celltypist",
        ("h5ad", "10x_h5", "10x_mtx"),
        "ultimate-scrna",
        "slurm/scrna_mvp_validation.sbatch",
        ("celltypist_annotation.tsv", "annotation_confidence.tsv", "annotation_warning.tsv"),
        "PBMC3k public validation with local CellTypist Immune_All_Low model",
        ("reference/model 决定可解释范围；低置信度 annotation 不作为最终结论。",),
        production_allowed=True,
        backend_status="fully_automatic_validated_entrypoint",
        skip_reason="",
        resource_profile="medium_scrna",
    ),
    _backend(
        "scrna.qc.scrublet",
        "scrna",
        "optional_backend",
        "standard",
        "Scrublet doublet detection",
        "scrublet",
        ("h5ad", "10x_h5", "10x_mtx"),
        "ultimate-scrna",
        "slurm/scrna_mvp_validation.sbatch",
        ("doublet_scores.tsv", "doublet_summary.tsv", "doublet_score_histogram.png"),
        "PBMC3k public validation",
        ("doublet 阈值是模型/数据依赖参数，必须进入 methods 和 manifest。",),
        production_allowed=True,
        backend_status="fully_automatic_validated_entrypoint",
        skip_reason="",
    ),
    _backend(
        "scrna.functional.decoupler_gseapy",
        "scrna",
        "optional_backend",
        "standard",
        "Signature/pathway/TF activity",
        "decoupler-py + GSEApy",
        ("h5ad",),
        "ultimate-scrna",
        "slurm/scrna_mvp_validation.sbatch",
        ("signature_scores.tsv", "pathway_activity.tsv", "tf_activity.tsv", "signature_heatmap.png"),
        "PBMC3k public 10x matrix + h5ad validation with decoupler 2.1.6 and GSEApy 1.2.1",
        ("signature score 不是功能实验；gene set 来源和 overlap 必须记录。",),
        production_allowed=True,
        backend_status="fully_automatic_validated_entrypoint",
        skip_reason="",
        interpretation_warning="Signature/pathway/TF activity scores are expression-derived and must not be written as functional assay, mechanism proof, or clinical advice.",
    ),
    _backend(
        "scrna.communication.liana",
        "scrna",
        "optional_backend",
        "communication",
        "Ligand-receptor communication",
        "LIANA",
        ("h5ad_with_annotation",),
        "ultimate-scrna",
        "slurm/scrna_mvp_validation.sbatch",
        ("liana_interactions.tsv", "communication_network.tsv", "communication_backend_status.tsv", "communication_dotplot.png"),
        "PBMC3k public validation with CellTypist labels and LIANA 1.7.3 consensus resource",
        ("配体-受体结果是统计推断，不是直接机制证明。",),
        production_allowed=True,
        backend_status="fully_automatic_validated_entrypoint",
        skip_reason="",
        resource_profile="medium_scrna_optional",
        interpretation_warning="通信结果只能作为候选互作，不写成确定机制。",
    ),
    _backend(
        "scrna.tumor.copykat",
        "scrna",
        "optional_backend",
        "tumor",
        "Tumor CNV inference",
        "CopyKAT",
        ("raw_counts_h5ad", "count_matrix"),
        "ultimate-scrna-r",
        "slurm/tumor_sc_copykat_small_validation.sbatch",
        ("copykat_predictions.tsv", "copykat_backend_manifest.json", "copykat_versions.tsv", "copykat_cna_preview.tsv"),
        "NSCLC Maynard raw-count h5ad guarded CopyKAT small validation",
        ("transcriptome-inferred CNV 不是 DNA-level CNV；需要原始 count 和基因位置。",),
        production_allowed=True,
        backend_status="fully_automatic_validated_entrypoint",
        skip_reason="",
        resource_profile="large_r",
        interpretation_warning="CNV 推断只能辅助 malignant calling，不能作为 DNA 金标准。",
    ),
    _backend(
        "scrna.velocity.scvelo",
        "scrna",
        "optional_backend",
        "trajectory",
        "RNA velocity",
        "scVelo",
        ("loom", "h5ad_with_spliced_unspliced"),
        "ultimate-scrna-heavy",
        "slurm/scrna_velocity.sbatch",
        ("velocity_graph.tsv", "velocity_embedding.png", "velocity_report_fragment.md"),
        "public spliced/unspliced fixture required",
        ("没有 spliced/unspliced 层时必须跳过；velocity 是动态趋势推断。",),
        production_allowed=True,
        backend_status="planned_fully_automatic",
        skip_reason="Input-gated velocity backend not implemented.",
        resource_profile="large_scrna",
    ),
    _backend(
        "scrna.upstream.nfcore_scrnaseq",
        "scrna",
        "handoff_backend",
        "raw",
        "nf-core/scrnaseq FASTQ-to-matrix handoff",
        "nf-core/scrnaseq",
        ("fastq", "smartseq_fastq"),
        "ultimate-workflow",
        "slurm/nfcore_scrnaseq_handoff.sbatch",
        ("samplesheet.csv", "params.yaml", "nextflow.config", "command_plan.md"),
        "nf-core test profile",
        ("只负责 FASTQ 到矩阵，上游结果再进入 validate-scrna 或 ultimate run。",),
        production_allowed=False,
        backend_status="handoff_ready",
        skip_reason="External workflow handoff only until full Slurm/container validation.",
        resource_profile="external_nextflow",
    ),
    _backend(
        "scatac.matrix.signac_or_snapatac2_mvp",
        "scatac",
        "default_backend",
        "standard",
        "scATAC matrix/fragments MVP",
        "Signac or SnapATAC2",
        ("peak_matrix", "fragments", "cellranger_atac_output", "h5ad"),
        "ultimate-scatac-multiome",
        "slurm/scatac_backend_validation.sbatch",
        ("cell_qc.tsv", "peak_matrix_summary.tsv", "lsi_umap.png", "scatac_mvp.h5ad"),
        "10x PBMC ATAC public data",
        ("没有 fragments 不能声称完成 TSS/FRiP/peak calling；gene activity 是推断值。",),
        production_allowed=True,
        backend_status="fully_automatic_validated_entrypoint",
        skip_reason="",
        resource_profile="large_chromatin",
    ),
    _backend(
        "multiome.default.muon_mvp",
        "multiome",
        "default_backend",
        "multiome",
        "RNA+ATAC MuData MVP",
        "muon/mudata",
        ("10x_arc_h5", "h5mu", "rna_matrix_atac_matrix"),
        "ultimate-scatac-multiome",
        "slurm/multiome_backend_validation.sbatch",
        ("barcode_overlap.tsv", "rna_qc.tsv", "atac_qc.tsv", "multiome_mvp.h5mu"),
        "10x PBMC Multiome public data",
        ("Multiome 不是 scRNA+scATAC 简单拼接；必须检查 barcode overlap。",),
        production_allowed=True,
        backend_status="fully_automatic_validated_entrypoint",
        skip_reason="",
        resource_profile="large_multiome",
    ),
    _backend(
        "spatial.visium.squidpy_mvp",
        "spatial",
        "default_backend",
        "standard",
        "Visium spatial transcriptomics MVP",
        "squidpy",
        ("spaceranger_output", "visium_h5ad", "spatialdata"),
        "ultimate-spatial-py",
        "slurm/spatial_backend_validation.sbatch",
        ("spatial_qc.tsv", "coordinate_check.tsv", "spatial_cluster.png", "spatial_mvp.h5ad"),
        "Squidpy public Visium H&E",
        ("Visium spot 不是单细胞；空间通讯和解卷积必须依赖 reference 并标警示。",),
        production_allowed=True,
        backend_status="fully_automatic_validated_entrypoint",
        skip_reason="",
        resource_profile="large_spatial",
    ),
    _backend(
        "spatial.upstream.spaceranger",
        "spatial",
        "licensed_backend",
        "raw",
        "Space Ranger licensed upstream",
        "Space Ranger",
        ("visium_fastq", "bcl_handoff"),
        "user-provided",
        "slurm/spaceranger_handoff.sbatch",
        ("spaceranger_output_dir", "multiqc_report.html"),
        "user-provided license path",
        ("授权工具只检测和调用用户提供路径，不能伪装成开源后端。",),
        production_allowed=True,
        requires_license=True,
        backend_status="licensed_path_detection",
        skip_reason="Requires user-provided Space Ranger path.",
        resource_profile="licensed_large",
    ),
    _backend(
        "vdj.default.scirpy_mvp",
        "vdj",
        "default_backend",
        "standard",
        "10x VDJ contig/clonotype MVP",
        "scirpy + pandas",
        ("filtered_contig_annotations", "clonotypes", "airr", "mixcr_output"),
        "ultimate-vdj",
        "slurm/vdj_backend_validation.sbatch",
        ("clonotype_summary.tsv", "clone_expansion.tsv", "v_gene_usage.tsv", "clone_size_distribution.png"),
        "10x PBMC VDJ public data",
        ("clonotype 相同不等于抗原相同；clone-state association 依赖外部 scRNA metadata。",),
        production_allowed=True,
        backend_status="fully_automatic_validated_entrypoint",
        skip_reason="",
        resource_profile="medium_vdj",
    ),
    _backend(
        "cite_seq.default.clr_mvp",
        "cite_seq",
        "default_backend",
        "standard",
        "RNA+ADT CLR MVP",
        "muon/anndata + CLR",
        ("10x_feature_barcode_h5", "rna_adt_matrix", "h5mu"),
        "ultimate-scrna",
        "slurm/cite_seq_backend_validation.sbatch",
        ("adt_qc.tsv", "adt_normalized_matrix.tsv", "adt_marker_summary.tsv", "cite_mvp.h5mu"),
        "10x PBMC CITE-seq public data",
        ("ADT 不是全蛋白组；抗体 panel 决定可解释范围。",),
        production_allowed=True,
        backend_status="fully_automatic_validated_entrypoint",
        skip_reason="",
        resource_profile="medium_cite",
    ),
    _backend(
        "cite_seq.optional.dsb",
        "cite_seq",
        "optional_backend",
        "publication",
        "DSB ADT background correction",
        "dsb",
        ("adt_matrix_with_controls",),
        "ultimate-scrna-r",
        "slurm/cite_seq_validation.sbatch",
        ("dsb_normalized_matrix.tsv", "background_summary.tsv"),
        "10x PBMC CITE-seq public data",
        ("需要 isotype/empty/background 信息；缺失时不能伪装完成 DSB。",),
        production_allowed=True,
        backend_status="planned_fully_automatic",
        skip_reason="DSB optional backend wrapper not wired.",
    ),
    _backend(
        "functional_state.default.signature_scoring",
        "functional_state",
        "default_backend",
        "standard",
        "Generic signature scoring",
        "decoupler/GSEApy compatible Python scoring",
        ("expression_matrix", "h5ad", "gmt"),
        "ultimate-core",
        "slurm/bulk_validation_suite.sbatch",
        ("geneset_overlap.tsv", "signature_scores.tsv", "signature_heatmap.png"),
        "airway public expression matrix + NSCLC internal h5ad derived signature validation",
        ("signature score 不是代谢通量；不同评分方法不可直接混比。",),
        production_allowed=True,
        backend_status="fully_automatic_validated_entrypoint",
        resource_profile="small_matrix",
    ),
    _backend(
        "tumor_sc.default.summary_handoff",
        "tumor_sc",
        "default_backend",
        "tumor",
        "Tumor scRNA specialty summary",
        "scanpy summary + CopyKAT/inferCNV handoff",
        ("h5ad", "seurat_handoff", "cnv_result"),
        "ultimate-scrna",
        "slurm/tumor_sc_maynard_raw_counts.sbatch",
        ("malignant_cell_candidates.tsv", "tme_composition.tsv", "immune_state_scores.tsv"),
        "NSCLC internal raw-count h5ad",
        ("malignant calling 不能只靠 marker；CNV 推断不是 DNA 金标准。",),
        production_allowed=True,
        backend_status="planned_fully_automatic",
        skip_reason="Specialty validation script exists; unified tumor preset backend not complete.",
    ),
    _backend(
        "publicdb.cached_tables.python_mvp",
        "publicdb",
        "default_backend",
        "standard",
        "Cached public table validation",
        "pandas",
        ("cached_expression_table", "cached_clinical_table"),
        "ultimate-core",
        "slurm/bulk_validation_suite.sbatch",
        ("public_dataset_manifest.tsv", "sample_inclusion.tsv", "validation_results.tsv"),
        "airway cached public-style table",
        ("GEO metadata 需要人工核对；TCGA bulk 验证不能证明单细胞机制。",),
        production_allowed=True,
        backend_status="fully_automatic_validated_entrypoint",
        resource_profile="small_matrix",
    ),
    _backend(
        "clinical_assoc.default.sample_level_stats",
        "clinical_assoc",
        "default_backend",
        "standard",
        "Sample-level clinical association MVP",
        "pandas/statsmodels-compatible summaries",
        ("sample_feature_matrix", "clinical_metadata"),
        "ultimate-core",
        "slurm/bulk_validation_suite.sbatch",
        ("clinical_qc.tsv", "merged_feature_clinical.tsv", "correlation_results.tsv"),
        "airway sample-level metadata validation",
        ("clinical association 是样本级统计；correlation 不等于 causation。",),
        production_allowed=True,
        backend_status="fully_automatic_validated_entrypoint",
        resource_profile="small_matrix",
    ),
    _backend(
        "wgcna.default.ready_matrix",
        "wgcna",
        "default_backend",
        "standard",
        "WGCNA-ready matrix QC",
        "Python QC + WGCNA R handoff",
        ("bulk_expression_matrix", "pseudobulk_expression_matrix"),
        "ultimate-core",
        "slurm/bulk_validation_suite.sbatch",
        ("wgcna_input_qc.tsv", "soft_threshold.tsv", "module_trait_correlation.tsv"),
        "airway pseudobulk-style matrix",
        ("WGCNA 更适合 bulk/pseudobulk；样本数太少必须阻断正式 WGCNA。",),
        production_allowed=True,
        backend_status="fully_automatic_validated_entrypoint",
        resource_profile="small_matrix",
    ),
    _backend(
        "proteomics.default.abundance_python_mvp",
        "proteomics",
        "default_backend",
        "standard",
        "Proteomics abundance-table MVP",
        "pandas + limma handoff",
        ("maxquant_table", "proteome_discoverer_table", "abundance_table"),
        "ultimate-core",
        "slurm/proteomics_backend_validation.sbatch",
        ("abundance_qc.tsv", "missingness_summary.tsv", "differential_proteins.tsv", "volcano.png"),
        "LFQ-Analyst public MaxQuant proteinGroups table",
        ("已用 LFQ-Analyst 公开 MaxQuant proteinGroups 完成 matrix-level validation；publication-grade limma/富集仍为后续增强。",),
        production_allowed=True,
        backend_status="fully_automatic_validated_entrypoint",
        skip_reason="",
        resource_profile="small_matrix",
    ),
    _backend(
        "methylation.default.beta_matrix_python_mvp",
        "methylation",
        "default_backend",
        "standard",
        "Methylation beta/region matrix MVP",
        "pandas + minfi/ChAMP handoff",
        ("beta_matrix", "idat_handoff", "region_matrix"),
        "ultimate-core",
        "slurm/bulk_validation_suite.sbatch",
        ("feature_qc.tsv", "sample_qc.tsv", "differential_regions.tsv", "region_heatmap.png"),
        "ARRmData public beta matrix",
        ("DMR 需要分组和重复数；IDAT/minfi 第一版仍是 handoff/optional。",),
        production_allowed=True,
        backend_status="fully_automatic_validated_entrypoint",
        resource_profile="small_matrix",
    ),
    _backend(
        "single_gene.default.gene_report_mvp",
        "single_gene",
        "default_backend",
        "standard",
        "Single-gene expression report MVP",
        "pandas + scanpy-compatible extraction",
        ("gene_symbol", "expression_matrix", "h5ad", "clinical_table"),
        "ultimate-core",
        "slurm/bulk_validation_suite.sbatch",
        ("gene_validation.tsv", "gene_expression_summary.tsv", "coexpression_results.tsv", "gene_expression_boxplot.png"),
        "airway public expression matrix",
        ("单基因差异和共表达不等于机制；公共验证依赖队列质量。",),
        production_allowed=True,
        backend_status="fully_automatic_validated_entrypoint",
        resource_profile="small_matrix",
    ),
    _backend(
        "scdna.default.matrix_ready_handoff",
        "scdna",
        "default_backend",
        "standard",
        "scDNA BAM/VCF/table matrix-ready MVP",
        "samtools/bcftools handoff + table summary",
        ("bam", "vcf", "cell_variant_matrix", "missionbio_output"),
        "ultimate-genome-mtdna",
        "slurm/scdna_validation.sbatch",
        ("coverage_qc.tsv", "variant_qc.tsv", "cell_variant_matrix.tsv", "phylogeny_input.tsv"),
        "0518 internal DNA baseline",
        ("allele dropout、低覆盖、amplicon bias 必须写入限制；克隆树不是唯一真实历史。",),
        production_allowed=True,
        backend_status="planned_fully_automatic",
        skip_reason="Existing validation is specialty script/table import; unified scDNA backend runner not complete.",
        resource_profile="large_genome",
    ),
    _backend(
        "mtdna.default.lineage_ready_mvp",
        "mtdna",
        "default_backend",
        "standard",
        "mtDNA depth/heteroplasmy lineage-ready MVP",
        "pandas + samtools/cellsnp handoff",
        ("bam", "base_count_table", "variant_table", "vaf_matrix"),
        "ultimate-genome-mtdna",
        "slurm/singlecell_validation_suite.sbatch",
        ("mtdna_depth_by_cell.tsv", "high_confidence_variants.tsv", "lineage_input.tsv", "vaf_heatmap.png"),
        "0518 internal mtDNA results",
        ("NUMTs、homopolymer、低深度和 dropout 必须警示；shared variant 不能自动当作克隆关系。",),
        production_allowed=True,
        backend_status="planned_fully_automatic",
        skip_reason="Internal validation exists; unified BAM/base-count backend runner not complete.",
        resource_profile="large_genome",
    ),
    _backend(
        "scepi.default.matrix_handoff_mvp",
        "scepi",
        "default_backend",
        "standard",
        "single-cell epigenomics matrix-level MVP",
        "Signac/ArchR/minfi handoff",
        ("scbs_output", "cuttag_peak_matrix", "cutrun_peak_matrix", "bed_region_table"),
        "ultimate-scatac-multiome",
        "slurm/singlecell_validation_suite.sbatch",
        ("feature_qc.tsv", "sample_qc.tsv", "differential_regions.tsv", "region_heatmap.png"),
        "derived scATAC public validation",
        ("scBS/CUT&Tag/CUT&RUN 不能混用同一统计套路；peak calling 依赖实验类型。",),
        production_allowed=True,
        backend_status="planned_fully_automatic",
        skip_reason="Mapped to matrix-level MVP/handoff; full modality-specific backend not implemented.",
        resource_profile="large_epigenomics",
    ),
    _backend(
        "perturb_seq.default.guide_assignment_mvp",
        "perturb_seq",
        "default_backend",
        "standard",
        "Perturb-seq guide assignment MVP",
        "pertpy/Mixscape/SCEPTRE handoff",
        ("expression_matrix", "guide_count_matrix", "guide_assignment_table", "h5ad"),
        "ultimate-scrna",
        "slurm/gapfill_specialty_validation.sbatch",
        ("guide_qc.tsv", "guide_assignment.tsv", "pseudobulk_by_perturbation.tsv"),
        "Adamson public Perturb-seq h5ad",
        ("guide assignment 错误会污染结论；扰动 effect 不能自动写成机制。",),
        production_allowed=True,
        backend_status="planned_fully_automatic",
        skip_reason="Validation script exists; formal perturbation model backend not wired.",
        resource_profile="medium_scrna",
    ),
    _backend(
        "hto_demux.default.matrix_assignment_mvp",
        "hto_demux",
        "default_backend",
        "standard",
        "HTO/Cell Hashing assignment MVP",
        "matrix thresholding + Seurat HTODemux handoff",
        ("hto_count_matrix", "10x_antibody_capture", "sample_hashtag_mapping"),
        "ultimate-scrna",
        "slurm/hto_demux_backend_validation.sbatch",
        ("hto_qc.tsv", "hto_assignment.tsv", "sample_assignment_summary.tsv"),
        "Seurat public HTO matrix",
        ("negative 不能强行分样本；doublet 阈值必须记录。",),
        production_allowed=True,
        backend_status="fully_automatic_validated_entrypoint",
        skip_reason="",
        resource_profile="small_matrix",
    ),
    _backend(
        "genotype_demux.default.result_import_mvp",
        "genotype_demux",
        "default_backend",
        "standard",
        "Genotype demultiplex result import MVP",
        "cellsnp-lite/vireo/souporcell handoff",
        ("cellsnp_output", "vireo_output", "souporcell_output", "bam_vcf_barcode"),
        "ultimate-genome-mtdna",
        "slurm/gapfill_specialty_validation.sbatch",
        ("snp_qc.tsv", "assignment.tsv", "doublet_summary.tsv", "cell_metadata_with_genotype.tsv"),
        "Vireo/cellSNP public fixture",
        ("SNP 覆盖不足时不能强行 assignment；reference VCF 错配必须警示。",),
        production_allowed=True,
        backend_status="planned_fully_automatic",
        skip_reason="Existing result import validated; automatic BAM/VCF demux runner not complete.",
        resource_profile="large_genotype",
    ),
    _backend(
        "method_tools.default.delivery_manifest_mvp",
        "method_tools",
        "default_backend",
        "publication",
        "Interactive/static delivery manifest MVP",
        "cellxgene/Vitessce/Quarto handoff",
        ("h5ad", "h5mu", "spatialdata", "figures_tables_manifest"),
        "ultimate-browser",
        "slurm/method_tools_validation.sbatch",
        ("figure_index.tsv", "table_index.tsv", "sensitive_metadata_scan.tsv", "cellxgene_compatibility.tsv", "delivery_manifest.json", "cellxgene_ready.h5ad"),
        "NSCLC h5ad internal validation through unified ultimate run",
        ("交互式浏览器只是展示；公开交付前必须脱敏 metadata。",),
        production_allowed=True,
        backend_status="fully_automatic_validated_entrypoint",
        skip_reason="",
        resource_profile="medium_browser",
    ),
)


def backend_registry_rows() -> list[dict[str, Any]]:
    return [_row(spec) for spec in BACKEND_REGISTRY]


def backends_for_module(module_name: str) -> list[BackendSpec]:
    return [spec for spec in BACKEND_REGISTRY if spec.module == module_name]


def build_backend_plan(module_name: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or {}
    module_cfg = ((config.get("modules") or {}).get(module_name) or {}) if isinstance(config.get("modules"), dict) else {}
    preset = str(module_cfg.get("preset") or _default_preset(module_name))
    requested = module_cfg.get("backends") if isinstance(module_cfg.get("backends"), dict) else {}
    specs = backends_for_module(module_name)
    selected = _select_default_backend(specs, preset)
    requested_matches, unknown_requested = _requested_matches(module_name, specs, requested)
    active = _dedupe_specs([selected] + requested_matches if selected else requested_matches)
    skipped_optional = [spec.backend_id for spec in specs if spec.backend_role == "optional_backend" and spec not in active]
    licensed = [_licensed_status(spec, config) for spec in specs if spec.requires_license or spec.backend_role == "licensed_backend"]
    warnings = [spec.interpretation_warning for spec in active if spec.interpretation_warning]
    warnings.extend([f"requested_backend_unknown:{key}={value}" for key, value in unknown_requested.items()])
    if selected is None:
        warnings.append(f"no_default_backend_registered:{module_name}")
    for spec in active:
        if spec.backend_status not in AUTOMATIC_STATUSES:
            warnings.append(f"backend_not_fully_automatic:{spec.backend_id}:{spec.backend_status}")
        if spec.requires_license and not _licensed_status(spec, config)["available"]:
            warnings.append(f"licensed_backend_path_missing:{spec.backend_id}")
    return {
        "module": module_name,
        "preset": preset,
        "selected_backend_id": selected.backend_id if selected else "",
        "selected_backend_status": selected.backend_status if selected else "missing",
        "selected_backend_role": selected.backend_role if selected else "missing",
        "selected_backend_label": selected.label if selected else "",
        "backend_analysis_level": "production_backend" if str(module_cfg.get("analysis_level") or "") == "production_backend" else "smoke_backend",
        "backend_delivery_allowed": False,
        "backend_validation_evidence_allowed": False,
        "backend_skip_reason": selected.skip_reason if selected else f"no_backend_registered:{module_name}",
        "backend_versions": [],
        "backend_resource_profile": selected.resource_profile if selected else "not_recorded",
        "backend_slurm_job_id": "",
        "active_backends": [_row(spec) for spec in active],
        "requested_backends": {str(k): str(v) for k, v in requested.items()},
        "unknown_requested_backends": {str(k): str(v) for k, v in unknown_requested.items()},
        "skipped_optional_backends": skipped_optional,
        "licensed_backend_status": licensed,
        "interpretation_warnings": warnings,
        "all_module_backends": [_row(spec) for spec in specs],
    }


def enrich_backend_plan_for_run(
    plan: dict[str, Any],
    *,
    analysis_level: str,
    delivery_allowed: bool,
    validation_evidence_allowed: bool,
    slurm_context: dict[str, str] | None = None,
) -> dict[str, Any]:
    enriched = dict(plan)
    slurm_context = slurm_context or {}
    enriched["backend_analysis_level"] = analysis_level
    enriched["backend_delivery_allowed"] = bool(delivery_allowed)
    enriched["backend_validation_evidence_allowed"] = bool(validation_evidence_allowed)
    enriched["backend_slurm_job_id"] = str(slurm_context.get("slurm_job_id") or "")
    if analysis_level in {"validated_backend", "production_backend"} and enriched["selected_backend_status"] in AUTOMATIC_STATUSES:
        enriched["backend_skip_reason"] = ""
    elif not enriched.get("backend_skip_reason"):
        enriched["backend_skip_reason"] = "backend_maturity_not_validated_for_delivery"
    return enriched


def write_backend_plan_table(module_name: str, config: dict[str, Any], tables_dir: Path) -> Path:
    path = tables_dir / "backend_plan.tsv"
    rows = build_backend_plan(module_name, config)["all_module_backends"]
    pd.DataFrame(rows).to_csv(path, sep="\t", index=False)
    return path


def run_audit_backends(root: Path, output_dir: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    output_dir = (output_dir or root / "audits" / "backends").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = backend_registry_rows()
    registry_path = output_dir / "backend_registry.tsv"
    registry_json_path = output_dir / "backend_registry.json"
    pd.DataFrame(rows).to_csv(registry_path, sep="\t", index=False)
    registry_json_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    maturity_rows = backend_maturity_rows(root)
    maturity_path = output_dir / "backend_maturity_table.tsv"
    pd.DataFrame(maturity_rows).to_csv(maturity_path, sep="\t", index=False)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "output_dir": str(output_dir),
        "backend_count": len(rows),
        "summary": _summary(rows),
        "backend_registry": str(registry_path),
        "backend_registry_json": str(registry_json_path),
        "backend_maturity_table": str(maturity_path),
    }
    manifest_path = output_dir / "backend_audit.json"
    manifest["manifest_path"] = str(manifest_path)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def backend_maturity_rows(root: Path | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for spec in BACKEND_REGISTRY:
        maturity = _backend_maturity(spec)
        rows.append(
            {
                "module": spec.module,
                "backend_id": spec.backend_id,
                "backend_role": spec.backend_role,
                "preset": spec.preset,
                "tool": spec.tool,
                "backend_status": spec.backend_status,
                "maturity_level": maturity,
                "production_allowed": str(spec.production_allowed).lower(),
                "requires_license": str(spec.requires_license).lower(),
                "requires_slurm": str(spec.requires_slurm).lower(),
                "validation_dataset": spec.validation_dataset,
                "slurm_profile": spec.slurm_profile,
                "resource_profile": spec.resource_profile,
                "skip_reason": spec.skip_reason,
                "known_limitations": "; ".join(spec.known_limitations),
                "output_contract": ",".join(spec.output_contract),
                "next_required_evidence": _next_required_evidence(spec),
            }
        )
    return rows


def _row(spec: BackendSpec) -> dict[str, Any]:
    row = asdict(spec)
    for key in ("input_types", "output_contract", "known_limitations"):
        row[key] = ",".join(row[key])
    return row


def _default_preset(module_name: str) -> str:
    if module_name == "tumor_sc":
        return "tumor"
    if module_name == "multiome":
        return "multiome"
    return "standard"


def _select_default_backend(specs: list[BackendSpec], preset: str) -> BackendSpec | None:
    defaults = [spec for spec in specs if spec.backend_role == "default_backend"]
    for spec in defaults:
        if spec.preset == preset:
            return spec
    for spec in defaults:
        if spec.preset in {"standard", "basic"}:
            return spec
    return defaults[0] if defaults else None


def _requested_matches(module_name: str, specs: list[BackendSpec], requested: dict[str, Any]) -> tuple[list[BackendSpec], dict[str, Any]]:
    matches: list[BackendSpec] = []
    unknown: dict[str, Any] = {}
    by_suffix = {spec.backend_id.split(".")[-1]: spec for spec in specs}
    by_id = {spec.backend_id: spec for spec in specs}
    for key, value in requested.items():
        if value in {None, False, ""}:
            continue
        value_str = str(value)
        candidates = [
            by_id.get(str(key)),
            by_id.get(f"{module_name}.{key}"),
            by_id.get(value_str),
            by_id.get(f"{module_name}.{key}.{value_str}"),
            by_suffix.get(value_str),
        ]
        matched = next((candidate for candidate in candidates if candidate is not None), None)
        if matched is None:
            unknown[str(key)] = value
            continue
        matches.append(matched)
    return matches, unknown


def _dedupe_specs(specs: list[BackendSpec]) -> list[BackendSpec]:
    seen: set[str] = set()
    result: list[BackendSpec] = []
    for spec in specs:
        if spec.backend_id in seen:
            continue
        seen.add(spec.backend_id)
        result.append(spec)
    return result


def _licensed_status(spec: BackendSpec, config: dict[str, Any]) -> dict[str, Any]:
    resources = config.get("resources") if isinstance(config.get("resources"), dict) else {}
    licensed = resources.get("licensed_tools") if isinstance(resources.get("licensed_tools"), dict) else {}
    aliases = {
        "spatial.upstream.spaceranger": ("spaceranger", "space_ranger"),
    }
    values = [licensed.get(key) for key in aliases.get(spec.backend_id, (spec.tool.lower().replace(" ", "_"), spec.tool.lower()))]
    configured = next((str(value) for value in values if value), "")
    return {
        "backend_id": spec.backend_id,
        "tool": spec.tool,
        "configured_path": configured,
        "available": bool(configured and Path(configured).exists()),
        "policy": "user_provided_path_only",
    }


def _backend_maturity(spec: BackendSpec) -> str:
    if spec.backend_status in AUTOMATIC_STATUSES:
        return "2_mvp_automatic"
    if spec.backend_status == "handoff_ready":
        return "1_handoff_ready"
    if spec.backend_status == "licensed_path_detection":
        return "1_licensed_path_detection"
    return "0_planned"


def _next_required_evidence(spec: BackendSpec) -> str:
    if spec.backend_status in AUTOMATIC_STATUSES:
        return "Add/refresh Slurm validation evidence and keep regression tests current."
    if spec.backend_status == "handoff_ready":
        return "Validate external workflow handoff with Slurm/container profile before marking automatic."
    if spec.backend_status == "licensed_path_detection":
        return "User must provide licensed tool path; run Slurm validation before production use."
    return "Implement backend runner, preflight failure mode, Slurm validation, and report warning."


def _summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for row in rows:
        key = str(row.get("backend_status") or "unknown")
        summary[key] = summary.get(key, 0) + 1
    return summary


def modules_without_backend() -> list[str]:
    registered = {spec.module for spec in BACKEND_REGISTRY}
    return [module for module in MODULE_ORDER if module not in registered]
