from __future__ import annotations

from dataclasses import dataclass


SUPPORTED_ORGANISMS = {"human", "mouse"}

PROJECT_TYPES = (
    "all",
    "rnaseq",
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
    "clinical_assoc",
    "method_tools",
    "methylation",
    "proteomics",
    "publicdb",
    "wgcna",
    "single_gene",
)

MODULE_ORDER = (
    "rnaseq",
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
    "clinical_assoc",
    "method_tools",
    "methylation",
    "proteomics",
    "publicdb",
    "wgcna",
    "single_gene",
)


@dataclass(frozen=True)
class ModuleSpec:
    name: str
    title_cn: str
    input_kind: str
    required_columns: tuple[str, ...]
    optional_commands: tuple[str, ...]
    optional_r_packages: tuple[str, ...]


MODULE_SPECS: dict[str, ModuleSpec] = {
    "rnaseq": ModuleSpec(
        name="rnaseq",
        title_cn="转录组分析",
        input_kind="fastq_or_count_matrix",
        required_columns=("sample_id", "condition"),
        optional_commands=("fastqc", "multiqc", "fastp", "STAR", "hisat2", "featureCounts", "salmon", "Rscript"),
        optional_r_packages=("DESeq2", "edgeR", "clusterProfiler", "fgsea", "org.Hs.eg.db", "org.Mm.eg.db"),
    ),
    "scrna": ModuleSpec(
        name="scrna",
        title_cn="单细胞分析",
        input_kind="10x_h5_or_mtx",
        required_columns=("sample_id", "condition"),
        optional_commands=("Rscript",),
        optional_r_packages=("Seurat", "SingleR", "monocle3", "CellChat", "NicheNet", "GSVA", "AUCell", "WGCNA"),
    ),
    "scatac": ModuleSpec(
        name="scatac",
        title_cn="单细胞ATAC分析",
        input_kind="fragments_or_peak_matrix",
        required_columns=("sample_id", "condition"),
        optional_commands=("macs2", "bedtools", "samtools", "Rscript"),
        optional_r_packages=("Signac", "Seurat", "chromVAR", "GenomicRanges"),
    ),
    "multiome": ModuleSpec(
        name="multiome",
        title_cn="单细胞Multiome分析",
        input_kind="rna_atac_multiome",
        required_columns=("sample_id", "condition"),
        optional_commands=("macs2", "bedtools", "samtools", "Rscript"),
        optional_r_packages=("Signac", "Seurat", "chromVAR", "GenomicRanges"),
    ),
    "vdj": ModuleSpec(
        name="vdj",
        title_cn="单细胞免疫组库分析",
        input_kind="10x_vdj_contig_annotations",
        required_columns=("sample_id", "condition"),
        optional_commands=("Rscript",),
        optional_r_packages=("scRepertoire", "immunarch"),
    ),
    "scdna": ModuleSpec(
        name="scdna",
        title_cn="单细胞DNA/基因组分析",
        input_kind="bam_or_variant_tables",
        required_columns=("sample_id", "condition"),
        optional_commands=("samtools", "bcftools", "bwa", "bedtools"),
        optional_r_packages=(),
    ),
    "mtdna": ModuleSpec(
        name="mtdna",
        title_cn="单细胞线粒体基因组分析",
        input_kind="bam_or_mtdna_variant_tables",
        required_columns=("sample_id", "condition"),
        optional_commands=("samtools", "bcftools"),
        optional_r_packages=(),
    ),
    "scepi": ModuleSpec(
        name="scepi",
        title_cn="单细胞表观遗传组分析",
        input_kind="single_cell_epigenomics",
        required_columns=("sample_id", "condition"),
        optional_commands=("samtools", "bedtools", "macs2", "Rscript"),
        optional_r_packages=("Signac", "chromVAR", "minfi", "GenomicRanges"),
    ),
    "cite_seq": ModuleSpec(
        name="cite_seq",
        title_cn="CITE-seq/单细胞蛋白组分析",
        input_kind="rna_adt_matrix",
        required_columns=("sample_id", "condition"),
        optional_commands=("Rscript",),
        optional_r_packages=("Seurat", "dsb"),
    ),
    "spatial": ModuleSpec(
        name="spatial",
        title_cn="空间转录组分析",
        input_kind="visium_or_spatial_matrix",
        required_columns=("sample_id", "condition"),
        optional_commands=("Rscript",),
        optional_r_packages=("SpatialExperiment", "TENxVisiumData", "Seurat"),
    ),
    "functional_state": ModuleSpec(
        name="functional_state",
        title_cn="单细胞代谢/功能状态分析",
        input_kind="single_cell_expression",
        required_columns=("sample_id", "condition"),
        optional_commands=("Rscript",),
        optional_r_packages=("GSVA", "AUCell", "Seurat"),
    ),
    "tumor_sc": ModuleSpec(
        name="tumor_sc",
        title_cn="肿瘤单细胞专项分析",
        input_kind="tumor_single_cell_expression",
        required_columns=("sample_id", "condition"),
        optional_commands=("Rscript",),
        optional_r_packages=("infercnv", "CopyKAT", "Seurat", "survival"),
    ),
    "clinical_assoc": ModuleSpec(
        name="clinical_assoc",
        title_cn="跨样本/临床关联分析",
        input_kind="single_cell_plus_clinical",
        required_columns=("sample_id", "condition"),
        optional_commands=("Rscript",),
        optional_r_packages=("survival", "survminer", "GSVA"),
    ),
    "method_tools": ModuleSpec(
        name="method_tools",
        title_cn="方法学/工具类分析",
        input_kind="single_cell_objects",
        required_columns=("sample_id", "condition"),
        optional_commands=("Rscript",),
        optional_r_packages=("Seurat", "SingleR"),
    ),
    "methylation": ModuleSpec(
        name="methylation",
        title_cn="甲基化分析",
        input_kind="idat_or_beta_matrix",
        required_columns=("sample_id", "condition"),
        optional_commands=("Rscript",),
        optional_r_packages=("minfi", "ChAMP", "limma", "IlluminaHumanMethylationEPICanno.ilm10b4.hg19"),
    ),
    "proteomics": ModuleSpec(
        name="proteomics",
        title_cn="蛋白组/代谢组分析",
        input_kind="abundance_table",
        required_columns=("sample_id", "condition"),
        optional_commands=("Rscript",),
        optional_r_packages=("limma", "ropls", "clusterProfiler", "STRINGdb"),
    ),
    "publicdb": ModuleSpec(
        name="publicdb",
        title_cn="公共数据库挖掘",
        input_kind="cohort_config_or_matrix",
        required_columns=("cohort_id", "condition"),
        optional_commands=("Rscript",),
        optional_r_packages=("TCGAbiolinks", "GEOquery", "survival", "survminer", "GSVA"),
    ),
    "wgcna": ModuleSpec(
        name="wgcna",
        title_cn="WGCNA共表达网络",
        input_kind="expression_matrix",
        required_columns=("sample_id", "condition"),
        optional_commands=("Rscript",),
        optional_r_packages=("WGCNA", "dynamicTreeCut", "clusterProfiler"),
    ),
    "single_gene": ModuleSpec(
        name="single_gene",
        title_cn="单基因分析",
        input_kind="expression_matrix",
        required_columns=("sample_id", "condition"),
        optional_commands=("Rscript",),
        optional_r_packages=("survival", "survminer", "maftools", "GSVA"),
    ),
}
