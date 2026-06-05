from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DECISIONS = (
    "keep_default",
    "keep_optional",
    "adapter_only",
    "reference_only",
    "licensed_path_only",
    "rejected_cleaned",
)

DECISION_TO_V2_DISPOSITION = {
    "keep_default": "default_backend",
    "keep_optional": "optional_backend",
    "adapter_only": "handoff_adapter",
    "reference_only": "reference_only",
    "licensed_path_only": "licensed_path_detection",
    "rejected_cleaned": "rejected_cleaned",
}

SIZE_GB = {
    "none": 0.0,
    "tiny": 0.1,
    "small": 0.8,
    "medium": 3.0,
    "large": 8.0,
    "xlarge": 20.0,
    "external": 0.0,
}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    url: str
    module: str
    decision: str
    batch: str
    env: str = ""
    install_method: str = "registry"
    python_import: str = ""
    r_package: str = ""
    command: str = ""
    size_class: str = "small"
    validation_data: str = "smoke"
    reason_cn: str = ""


def _tool(
    name: str,
    url: str,
    module: str,
    decision: str,
    batch: str,
    *,
    env: str = "",
    install_method: str = "conda/mamba",
    python_import: str = "",
    r_package: str = "",
    command: str = "",
    size_class: str = "small",
    validation_data: str = "smoke",
    reason_cn: str = "",
) -> ToolSpec:
    if decision not in DECISIONS:
        raise ValueError(f"Unsupported tool decision: {decision}")
    return ToolSpec(
        name=name,
        url=url,
        module=module,
        decision=decision,
        batch=batch,
        env=env,
        install_method=install_method,
        python_import=python_import,
        r_package=r_package,
        command=command,
        size_class=size_class,
        validation_data=validation_data,
        reason_cn=reason_cn,
    )


TOOL_REGISTRY: tuple[ToolSpec, ...] = (
    # Indexes and reference collections.
    _tool("awesome-single-cell", "https://github.com/seandavi/awesome-single-cell", "reference", "reference_only", "registry", install_method="reference", size_class="none", reason_cn="综合索引，只用于持续选型。"),
    _tool("Spatial_transcriptomics_tools", "https://github.com/p-gueguen/Spatial_transcriptomics_tools", "reference", "reference_only", "registry", install_method="reference", size_class="none", reason_cn="空间工具索引，只用于查新。"),
    _tool("awesome-nextflow", "https://github.com/nextflow-io/awesome-nextflow", "workflow", "reference_only", "registry", install_method="reference", size_class="none", reason_cn="Nextflow 生态索引，不进入运行环境。"),
    _tool("snakemake-workflows", "https://github.com/snakemake-workflows", "workflow", "reference_only", "registry", install_method="reference", size_class="none", reason_cn="Snakemake workflow 参考集合。"),
    # Workflow foundation.
    _tool("nextflow", "https://github.com/nextflow-io/nextflow", "workflow", "keep_default", "workflow_core", env="ultimate-workflow", command="nextflow", size_class="medium", reason_cn="nf-core 上游适配和 Slurm workflow 标准入口。"),
    _tool("nf-core/tools", "https://github.com/nf-core/tools", "workflow", "keep_default", "workflow_core", env="ultimate-workflow", python_import="nf_core", command="nf-core", size_class="small", reason_cn="生成/验证 nf-core samplesheet、schema、运行配置。"),
    _tool("snakemake", "https://github.com/snakemake/snakemake", "workflow", "keep_default", "workflow_core", env="ultimate-core", python_import="snakemake", command="snakemake", size_class="medium", reason_cn="平台内置轻量 workflow 和 raw handoff 骨架。"),
    _tool("snakemake-executor-plugin-slurm", "https://github.com/snakemake/snakemake-executor-plugin-slurm", "workflow", "keep_optional", "workflow_core", env="ultimate-workflow", python_import="snakemake_executor_plugin_slurm", size_class="tiny", reason_cn="需要 Snakemake 直接投 Slurm 时启用。"),
    _tool("conda", "https://github.com/conda/conda", "workflow", "keep_default", "workflow_core", command="conda", install_method="system", size_class="external", reason_cn="环境基础工具，复用服务器现有安装。"),
    _tool("mamba", "https://github.com/mamba-org/mamba", "workflow", "keep_default", "workflow_core", command="mamba", install_method="system", size_class="external", reason_cn="优先使用 mamba 创建和更新环境。"),
    _tool("apptainer", "https://github.com/apptainer/apptainer", "workflow", "keep_default", "workflow_core", command="apptainer", install_method="system/path", size_class="external", reason_cn="nf-core 容器运行首选；服务器已有 singularity 时复用。"),
    _tool("singularity", "https://github.com/apptainer/singularity", "workflow", "keep_default", "workflow_core", command="singularity", install_method="system/path", size_class="external", reason_cn="Apptainer 兼容路径，服务器已有时直接记录。"),
    _tool("MultiQC", "https://github.com/MultiQC/MultiQC", "report", "keep_default", "workflow_core", env="ultimate-workflow", python_import="multiqc", command="multiqc", size_class="small", reason_cn="原始 QC 和 workflow 日志统一汇总。"),
    _tool("Quarto", "https://github.com/quarto-dev/quarto-cli", "report", "keep_default", "workflow_core", env="ultimate-workflow", command="quarto", size_class="medium", reason_cn="生产级 HTML/PDF 报告渲染器。"),
    _tool("jupyter-book", "https://github.com/jupyter-book/jupyter-book", "report", "reference_only", "registry", python_import="jupyter_book", size_class="medium", reason_cn="偏文档站点，不作为接单报告默认依赖。"),
    # Production workflow adapters.
    _tool("nf-core/scrnaseq", "https://github.com/nf-core/scrnaseq", "scrna_upstream", "adapter_only", "upstream_adapter", env="ultimate-workflow", command="nextflow", size_class="external", validation_data="nf-core test profile", reason_cn="10x/Smart-seq FASTQ 到矩阵首选外部生产 workflow。"),
    _tool("nf-core/rnaseq", "https://github.com/nf-core/rnaseq", "bulk_rnaseq", "adapter_only", "upstream_adapter", env="ultimate-workflow", command="nextflow", size_class="external", reason_cn="bulk RNA-seq 上游外部 adapter。"),
    _tool("nf-core/rnafusion", "https://github.com/nf-core/rnafusion", "fusion", "adapter_only", "upstream_adapter", env="ultimate-workflow", command="nextflow", size_class="external", reason_cn="融合基因检测外部 adapter。"),
    _tool("nf-core/airrflow", "https://github.com/nf-core/airrflow", "vdj", "adapter_only", "upstream_adapter", env="ultimate-workflow", command="nextflow", size_class="external", reason_cn="AIRR/VDJ 上游生产 workflow。"),
    _tool("nf-core/sarek", "https://github.com/nf-core/sarek", "scdna", "adapter_only", "upstream_adapter", env="ultimate-workflow", command="nextflow", size_class="external", reason_cn="DNA/SNV/Indel/CNV/LOH 生产流程参考与外部 adapter。"),
    _tool("nf-core/atacseq", "https://github.com/nf-core/atacseq", "atac", "adapter_only", "upstream_adapter", env="ultimate-workflow", command="nextflow", size_class="external", reason_cn="bulk ATAC 参考，不作为完整 scATAC 主线。"),
    _tool("nf-core/spatialvi", "https://github.com/nf-core/spatialvi", "spatial", "adapter_only", "upstream_adapter", env="ultimate-workflow", command="nextflow", size_class="external", reason_cn="Visium 上游/Space Ranger 输出外部 adapter。"),
    _tool("nf-core/sopa", "https://github.com/nf-core/sopa", "spatial", "adapter_only", "upstream_adapter", env="ultimate-workflow", command="nextflow", size_class="external", reason_cn="Xenium/CosMX/MERSCOPE/Visium HD 外部 adapter。"),
    _tool("bcl-convert", "https://support.illumina.com/sequencing/sequencing_software/bcl-convert.html", "upstream_demux", "licensed_path_only", "licensed", command="bcl-convert", install_method="user_provided_path", size_class="external", reason_cn="Illumina BCL demux，只检测用户提供路径。"),
    _tool("bcl2fastq", "https://support.illumina.com/sequencing/sequencing_software/bcl2fastq-conversion-software.html", "upstream_demux", "licensed_path_only", "licensed", command="bcl2fastq", install_method="user_provided_path", size_class="external", reason_cn="旧版 Illumina BCL demux，只检测用户提供路径。"),
    _tool("Parse Biosciences pipeline", "https://support.parsebiosciences.com/", "scrna_non10x", "adapter_only", "upstream_adapter", install_method="external_vendor_pipeline", size_class="external", reason_cn="Parse Evercode 原始数据建议先按厂商流程生成矩阵，再由 ultimate 下游接管。"),
    _tool("BD Rhapsody pipeline", "https://www.bd.com/en-us/products-and-solutions/products/product-families/bd-rhapsody-single-cell-analysis-system", "scrna_non10x", "adapter_only", "upstream_adapter", install_method="external_vendor_pipeline", size_class="external", reason_cn="BD Rhapsody 原始数据建议先按厂商流程生成矩阵，再由 ultimate 下游接管。"),
    _tool("Drop-seq tools", "https://github.com/broadinstitute/Drop-seq", "scrna_non10x", "keep_optional", "upstream_adapter", install_method="optional_deferred: Java toolkit", size_class="medium", reason_cn="Drop-seq 上游候选；接单主线优先矩阵/h5ad 入口。"),
    _tool("bollito", "https://github.com/cnio-bu/bollito", "scrna", "reference_only", "registry", install_method="reference", size_class="none", reason_cn="参考 Snakemake 模块拆分，不整体引入。"),
    _tool("scrnaseq_processing_seurat", "https://github.com/epigen/scrnaseq_processing_seurat", "scrna", "reference_only", "registry", install_method="reference", size_class="none", reason_cn="参考 Seurat 多样本流程，不整体引入。"),
    _tool("snakemake-single-cell-rna-seq", "https://github.com/snakemake-workflows/single-cell-rna-seq", "scrna", "reference_only", "registry", install_method="reference", size_class="none", reason_cn="参考官方 Snakemake rule 组织。"),
    _tool("scRNAseq_analysis_workflow", "https://github.com/metavannier/scRNAseq_analysis_workflow", "scrna", "reference_only", "registry", install_method="reference", size_class="none", reason_cn="教程型 workflow，仅参考。"),
    # scRNA core.
    _tool("scanpy", "https://github.com/scverse/scanpy", "scrna", "keep_default", "scrna_core", env="ultimate-scrna", python_import="scanpy", size_class="medium", reason_cn="Python scRNA 主分析内核。"),
    _tool("anndata", "https://github.com/scverse/anndata", "data_format", "keep_default", "scrna_core", env="ultimate-scrna", python_import="anndata", size_class="small", reason_cn="h5ad 单模态对象标准。"),
    _tool("Seurat", "https://github.com/satijalab/seurat", "scrna_r", "keep_default", "r_compat", env="ultimate-scrna-r", r_package="Seurat", size_class="large", reason_cn="客户和论文常用 R 单细胞生态。"),
    _tool("single-cell-tutorial", "https://github.com/theislab/single-cell-tutorial", "reference", "reference_only", "registry", install_method="reference", size_class="none", reason_cn="标准步骤参考，不安装。"),
    _tool("scvi-tools", "https://github.com/scverse/scvi-tools", "integration", "keep_optional", "specialized_heavy_py", env="ultimate-scrna-heavy", python_import="scvi", size_class="xlarge", reason_cn="scVI/scANVI/totalVI/multiVI，重依赖，隔离环境按项目启用。"),
    _tool("muon", "https://github.com/scverse/muon", "multiome", "keep_optional", "specialized_light", env="ultimate-scrna", python_import="muon", size_class="medium", reason_cn="多模态分析框架。"),
    _tool("mudata", "https://github.com/scverse/mudata", "data_format", "keep_optional", "specialized_light", env="ultimate-scrna", python_import="mudata", size_class="small", reason_cn="h5mu/MuData 数据结构。"),
    _tool("rapids_singlecell", "https://github.com/scverse/rapids_singlecell", "acceleration", "keep_optional", "gpu_optional", env="ultimate-gpu", python_import="rapids_singlecell", install_method="optional_deferred: GPU/CUDA required", size_class="xlarge", reason_cn="GPU 加速；当前 sinfo 未见 GPU GRES 且登录节点无 nvidia-smi，保留为 GPU 节点专项候选。"),
    _tool("cellrank", "https://github.com/scverse/cellrank", "trajectory", "keep_optional", "specialized_heavy_py", env="ultimate-scrna-heavy", python_import="cellrank", size_class="large", reason_cn="命运概率和 velocity 后续建模，隔离环境按项目启用。"),
    _tool("scarches", "https://github.com/theislab/scarches", "mapping", "keep_optional", "specialized_heavy_py", env="ultimate-scrna-heavy", python_import="scarches", size_class="large", reason_cn="reference/atlas mapping，隔离环境按项目启用。"),
    _tool("celltypist", "https://github.com/Teichlab/celltypist", "annotation", "keep_default", "scrna_core", env="ultimate-scrna", python_import="celltypist", size_class="medium", reason_cn="自动细胞类型注释候选。"),
    _tool("cellxgene-census", "https://github.com/chanzuckerberg/cellxgene-census", "reference", "keep_optional", "reference_data", env="ultimate-scrna", python_import="cellxgene_census", size_class="large", reason_cn="大型参考数据查询；默认不缓存全库。"),
    _tool("cellxgene", "https://github.com/chanzuckerberg/cellxgene", "browser", "keep_optional", "visualization", env="ultimate-browser", command="cellxgene", size_class="medium", reason_cn="h5ad 客户浏览器，隔离到浏览器环境，避免污染 scRNA 主分析环境。"),
    # QC / contamination / doublets.
    _tool("scrublet", "https://github.com/swolock/scrublet", "qc", "keep_default", "scrna_core", env="ultimate-scrna", python_import="scrublet", size_class="small", reason_cn="Python 双细胞检测。"),
    _tool("DoubletFinder", "https://github.com/chris-mcginnis-ucsf/DoubletFinder", "qc", "keep_optional", "r_compat", env="ultimate-scrna-r", r_package="DoubletFinder", install_method="optional_deferred: no conda package", size_class="small", reason_cn="Seurat/R 双细胞检测；无稳定 conda 包，按项目用 R remotes 隔离安装。"),
    _tool("SoupX", "https://github.com/constantAmateur/SoupX", "qc", "keep_default", "r_compat", env="ultimate-scrna-r", r_package="SoupX", size_class="small", reason_cn="ambient RNA 去污染常用工具。"),
    _tool("DecontX", "https://github.com/JCVenterInstitute/DecontX", "qc", "keep_optional", "r_compat", env="ultimate-scrna-r", r_package="celda", install_method="optional_deferred: R4.4 main env conflict", size_class="medium", reason_cn="污染校正候选；celda 在当前 R 4.4 主环境会触发 Bioconductor 代际冲突，按项目隔离安装。"),
    _tool("souporcell", "https://github.com/wheaton5/souporcell", "demultiplex", "keep_optional", "genome_tools", env="ultimate-genome-mtdna", command="souporcell_pipeline.py", install_method="optional_deferred: Python pystan legacy conflict", size_class="large", reason_cn="无 genotype demultiplex 和 doublet 检测；当前 conda 包依赖旧 pystan/Python，按项目隔离安装。"),
    _tool("scFlow", "https://github.com/combiz/scflow", "workflow", "reference_only", "registry", install_method="reference", size_class="none", reason_cn="QC workflow 参考，不安装。"),
    _tool("scPipe", "https://github.com/LuyiTian/scPipe", "workflow", "reference_only", "registry", install_method="reference", size_class="none", reason_cn="preprocessing pipeline 参考。"),
    _tool("DropletUtils", "https://github.com/MarioniLab/DropletUtils", "qc", "keep_default", "r_compat", env="ultimate-scrna-r", r_package="DropletUtils", size_class="medium", reason_cn="empty droplets 和 droplet QC。"),
    # Batch correction / integration.
    _tool("harmony", "https://github.com/immunogenomics/harmony", "integration", "keep_default", "r_compat", env="ultimate-scrna-r", r_package="harmony", size_class="small", reason_cn="批次校正常用 R 路线。"),
    _tool("harmonypy", "https://github.com/slowkow/harmonypy", "integration", "keep_default", "scrna_core", env="ultimate-scrna", python_import="harmonypy", size_class="small", reason_cn="Python Harmony 兼容路线。"),
    _tool("bbknn", "https://github.com/Teichlab/bbknn", "integration", "keep_default", "scrna_core", env="ultimate-scrna", python_import="bbknn", size_class="small", reason_cn="轻量 Scanpy 批次邻接图校正。"),
    _tool("scanorama", "https://github.com/brianhie/scanorama", "integration", "keep_optional", "scrna_core", env="ultimate-scrna", python_import="scanorama", size_class="medium", reason_cn="跨数据集整合候选。"),
    # Annotation references.
    _tool("single-cell-curation", "https://github.com/chanzuckerberg/single-cell-curation", "reference", "reference_only", "registry", install_method="reference", size_class="none", reason_cn="注释规范参考。"),
    _tool("azimuth", "https://github.com/satijalab/azimuth", "annotation", "keep_optional", "r_compat", env="ultimate-scrna-r", r_package="Azimuth", install_method="R remotes", size_class="large", reason_cn="Seurat reference mapping，按组织参考库启用。"),
    _tool("Azimuth Hub", "https://azimuth.hubmapconsortium.org/", "reference", "reference_only", "registry", install_method="web_reference", size_class="none", reason_cn="在线参考入口，不安装。"),
    _tool("Human Cell Atlas", "https://www.humancellatlas.org/", "reference", "reference_only", "registry", install_method="web_reference", size_class="none", reason_cn="公共 atlas 来源，不默认下载。"),
    _tool("PanglaoDB", "https://panglaodb.se/", "reference", "reference_only", "registry", install_method="web_reference", size_class="none", reason_cn="marker 参考库。"),
    _tool("CellMarker", "http://bio-bigdata.hrbmu.edu.cn/CellMarker/", "reference", "reference_only", "registry", install_method="web_reference", size_class="none", reason_cn="marker 参考库。"),
    # Statistics.
    _tool("glmGamPoi", "https://github.com/const-ae/glmGamPoi", "statistics", "keep_optional", "r_compat", env="ultimate-scrna-r", r_package="glmGamPoi", size_class="medium", reason_cn="伪 bulk/Seurat 差异统计加速。"),
    _tool("DESeq2", "https://github.com/thelovelab/DESeq2", "statistics", "keep_default", "r_compat", env="ultimate-rnaseq", r_package="DESeq2", size_class="large", reason_cn="bulk 和 pseudobulk 标准差异分析。"),
    _tool("edgeR", "https://bioconductor.org/packages/release/bioc/html/edgeR.html", "statistics", "keep_default", "r_compat", env="ultimate-rnaseq", r_package="edgeR", size_class="medium", reason_cn="bulk/pseudobulk 差异分析。"),
    _tool("limma", "https://bioconductor.org/packages/release/bioc/html/limma.html", "statistics", "keep_default", "core", env="ultimate-core", r_package="limma", size_class="small", reason_cn="线性模型和多组学矩阵统计基础。"),
    _tool("muscat", "https://github.com/HelenaLC/muscat", "statistics", "keep_optional", "r_compat", env="ultimate-scrna-r", r_package="muscat", install_method="optional_deferred: R4.4 main env conflict", size_class="medium", reason_cn="多样本单细胞 pseudobulk 统计；当前主 R 环境 dry-run 要求大换血，按项目隔离安装。"),
    _tool("dreamlet", "https://github.com/DiseaseNeuroGenomics/dreamlet", "statistics", "keep_optional", "r_compat", env="ultimate-scrna-r", r_package="dreamlet", install_method="optional_deferred: R4.4 main env conflict", size_class="medium", reason_cn="复杂设计 pseudobulk/混合模型；保留为隔离环境候选，避免污染主线 Seurat/Monocle 环境。"),
    # Enrichment / scoring.
    _tool("decoupler-py", "https://github.com/saezlab/decoupler-py", "pathway", "keep_default", "scrna_core", env="ultimate-scrna", python_import="decoupler", size_class="medium", reason_cn="通路/TF/功能状态活性评分主线。"),
    _tool("GSEApy", "https://github.com/zqfang/GSEApy", "pathway", "keep_default", "scrna_core", env="ultimate-scrna", python_import="gseapy", size_class="medium", reason_cn="Python GSEA/Enrichr/prerank/ssGSEA。"),
    _tool("clusterProfiler", "https://github.com/YuLab-SMU/clusterProfiler", "pathway", "keep_default", "r_compat", env="ultimate-scrna-r", r_package="clusterProfiler", size_class="large", reason_cn="R 生态 GO/KEGG/GSEA 标准工具。"),
    _tool("GSVA", "https://github.com/rcastelo/GSVA", "pathway", "keep_default", "r_compat", env="ultimate-scrna-r", r_package="GSVA", size_class="medium", reason_cn="GSVA/ssGSEA。"),
    _tool("AUCell", "https://github.com/aertslab/AUCell", "pathway", "keep_default", "r_compat", env="ultimate-scrna-r", r_package="AUCell", size_class="medium", reason_cn="单细胞 gene set activity。"),
    _tool("progeny", "https://github.com/saezlab/progeny", "pathway", "keep_optional", "r_compat", env="ultimate-scrna-r", r_package="progeny", install_method="optional_deferred: R4.4 main env conflict", size_class="small", reason_cn="R 侧通路活性候选；Python decoupler 已作为默认路线，R progeny 按项目隔离安装。"),
    _tool("dorothea", "https://github.com/saezlab/dorothea", "pathway", "keep_optional", "r_compat", env="ultimate-scrna-r", r_package="dorothea", size_class="small", reason_cn="TF-target regulon。"),
    _tool("UCell", "https://github.com/carmonalab/UCell", "pathway", "keep_default", "r_compat", env="ultimate-scrna-r", r_package="UCell", size_class="small", reason_cn="稳健 signature scoring。"),
    _tool("VISION", "https://github.com/YosefLab/VISION", "pathway", "keep_optional", "r_compat", env="ultimate-scrna-r", r_package="VISION", size_class="medium", reason_cn="signature exploration。"),
    # Regulatory and communication.
    _tool("pySCENIC", "https://github.com/aertslab/pySCENIC", "regulatory", "keep_optional", "specialized_heavy_py", env="ultimate-scrna-heavy", python_import="pyscenic", command="pyscenic", size_class="xlarge", reason_cn="SCENIC regulon/TF activity，重依赖隔离环境按需启用。"),
    _tool("SCENIC", "https://github.com/aertslab/SCENIC", "regulatory", "reference_only", "registry", install_method="reference", size_class="none", reason_cn="旧 R 路线参考，生产优先 pySCENIC/SCENIC+ 生态。"),
    _tool("CellChat", "https://github.com/jinworks/CellChat", "communication", "keep_optional", "r_compat", env="ultimate-scrna-r", r_package="CellChat", install_method="optional_deferred: no conda package", size_class="large", reason_cn="细胞通讯常用 R 工具；无稳定 conda 包，正式项目按 CellChat 专项环境/容器安装。"),
    _tool("CellPhoneDB", "https://github.com/ventolab/CellphoneDB", "communication", "keep_optional", "specialized_light", env="ultimate-scrna", python_import="cellphonedb", command="cellphonedb", install_method="optional_deferred: no conda package", size_class="large", reason_cn="配体-受体通讯候选；未发现稳定 conda 包，按项目隔离 pip/容器安装。"),
    _tool("NicheNet", "https://github.com/saeyslab/nichenetr", "communication", "keep_optional", "r_compat", env="ultimate-scrna-r", r_package="nichenetr", install_method="optional_deferred: no conda package", size_class="medium", reason_cn="ligand-target 机制假设生成；无稳定 conda 包，按项目隔离安装。"),
    _tool("LIANA", "https://github.com/saezlab/liana-py", "communication", "keep_optional", "specialized_light", env="ultimate-scrna", python_import="liana", install_method="optional_deferred: would downgrade numpy/numba", size_class="medium", reason_cn="整合多通讯方法；dry-run 会降级 numpy/numba，保留为隔离环境候选。"),
    _tool("OmnipathR", "https://github.com/saezlab/OmnipathR", "communication", "keep_optional", "r_compat", env="ultimate-scrna-r", r_package="OmnipathR", install_method="optional_deferred: R4.4 main env conflict", size_class="small", reason_cn="OmniPath R 接口；主线优先 Python omnipath/decoupler，R 侧按项目隔离安装。"),
    _tool("omnipath", "https://github.com/saezlab/omnipath", "communication", "keep_optional", "specialized_light", env="ultimate-scrna", python_import="omnipath", size_class="small", reason_cn="OmniPath Python 接口。"),
    _tool("stLearn", "https://github.com/BiomedicalMachineLearning/stLearn", "spatial", "keep_optional", "spatial", env="ultimate-spatial-py", python_import="stlearn", install_method="optional_deferred: slow/conflicting spatial solve", size_class="large", reason_cn="空间通讯/形态整合候选；与当前 squidpy/spatialdata 栈求解较慢，后续隔离旧空间栈验证。"),
    # Trajectory / velocity.
    _tool("monocle3", "https://github.com/cole-trapnell-lab/monocle3", "trajectory", "keep_optional", "r_compat", env="ultimate-scrna-r", r_package="monocle3", size_class="large", reason_cn="R 生态拟时序。"),
    _tool("slingshot", "https://github.com/kstreet13/slingshot", "trajectory", "keep_optional", "r_compat", env="ultimate-scrna-r", r_package="slingshot", size_class="medium", reason_cn="轨迹推断常用 Bioconductor 工具。"),
    _tool("dyno", "https://github.com/dynverse/dyno", "trajectory", "keep_optional", "specialized_heavy", env="ultimate-scrna-r", r_package="dyno", install_method="optional_deferred: no conda package", size_class="xlarge", reason_cn="轨迹方法集合，重依赖；未发现稳定 conda 包，按项目隔离安装。"),
    _tool("paga", "https://github.com/theislab/paga", "trajectory", "reference_only", "registry", install_method="covered_by_scanpy", size_class="none", reason_cn="PAGA 已在 Scanpy 主线内覆盖。"),
    _tool("Palantir", "https://github.com/dpeerlab/Palantir", "trajectory", "keep_optional", "specialized_light", env="ultimate-scrna", python_import="palantir", install_method="optional_deferred: would downgrade scientific stack", size_class="medium", reason_cn="分化状态和命运概率候选；dry-run 会降级 numpy/pyarrow/TileDB 等，按项目隔离安装。"),
    _tool("SPRING", "https://github.com/AllonKleinLab/SPRING", "trajectory", "rejected_cleaned", "registry", install_method="none", size_class="none", reason_cn="交互工具较旧，和现有 h5ad/cellxgene/Vitessce 重叠。"),
    _tool("scvelo", "https://github.com/theislab/scvelo", "velocity", "keep_optional", "specialized_heavy_py", env="ultimate-scrna-heavy", python_import="scvelo", size_class="large", reason_cn="RNA velocity 下游分析，隔离环境按需启用。"),
    _tool("velocyto.py", "https://github.com/velocyto-team/velocyto.py", "velocity", "rejected_cleaned", "registry", python_import="velocyto", command="velocyto", size_class="none", reason_cn="上游提示已不维护；优先 STARsolo/alevin-fry 或已有 spliced/unspliced。"),
    _tool("kallisto", "https://github.com/pachterlab/kallisto", "upstream", "keep_optional", "upstream_adapter", env="ultimate-workflow", command="kallisto", size_class="medium", reason_cn="BUS/velocity 上游可选。"),
    _tool("bustools", "https://github.com/BUStools/bustools", "upstream", "keep_optional", "upstream_adapter", env="ultimate-workflow", command="bustools", size_class="small", reason_cn="kallisto/bustools 生态。"),
    _tool("alevin-fry", "https://github.com/COMBINE-lab/alevin-fry", "upstream", "keep_default", "upstream_adapter", env="ultimate-workflow", command="alevin-fry", size_class="medium", reason_cn="开源 FASTQ 到矩阵路线之一。"),
    # scATAC and multiome.
    _tool("ArchR", "https://github.com/GreenleafLab/ArchR", "scatac", "keep_optional", "specialized_heavy", env="ultimate-scatac-r", r_package="ArchR", install_method="R remotes", size_class="large", reason_cn="完整 scATAC R 分析路线。"),
    _tool("Signac", "https://github.com/stuart-lab/signac", "scatac", "keep_default", "specialized_light", env="ultimate-scatac-r", r_package="Signac", size_class="large", reason_cn="Seurat 生态 scATAC/multiome。"),
    _tool("SnapATAC2", "https://github.com/scverse/SnapATAC2", "scatac", "keep_default", "specialized_light", env="ultimate-scatac-py", python_import="snapatac2", size_class="large", reason_cn="Python/scverse 大规模 scATAC 主线。"),
    _tool("SnapATAC", "https://github.com/r3fang/SnapATAC", "scatac", "rejected_cleaned", "registry", install_method="none", size_class="none", reason_cn="v1 路线被 SnapATAC2 替代。"),
    _tool("pycisTopic", "https://github.com/aertslab/pycisTopic", "scatac", "keep_optional", "specialized_heavy", env="ultimate-scatac-py", python_import="pycisTopic", install_method="optional_deferred: would remove SnapATAC2/MACS3", size_class="large", reason_cn="topic/motif 调控分析候选；dry-run 会移除 SnapATAC2/MACS3 并降级 AnnData/Scanpy，按项目隔离安装。"),
    _tool("pycistarget", "https://github.com/aertslab/pycistarget", "scatac", "keep_optional", "specialized_heavy", env="ultimate-scatac-py", python_import="pycistarget", install_method="optional_deferred: would remove SnapATAC2/MACS3", size_class="large", reason_cn="motif target enrichment 候选；dry-run 会破坏 scATAC Python 主环境，按项目隔离安装。"),
    _tool("chromVAR", "https://github.com/GreenleafLab/chromVAR", "scatac", "keep_default", "specialized_light", env="ultimate-scatac-r", r_package="chromVAR", size_class="medium", reason_cn="TF motif deviation 标准工具。"),
    _tool("Cell Ranger", "https://www.10xgenomics.com/support/software/cell-ranger", "scrna_upstream", "licensed_path_only", "licensed", command="cellranger", install_method="user_provided_path", size_class="external", reason_cn="10x scRNA/VDJ 原厂上游，只检测路径。"),
    _tool("Cell Ranger ATAC", "https://www.10xgenomics.com/support/software/cell-ranger-atac", "scatac_upstream", "licensed_path_only", "licensed", command="cellranger-atac", install_method="user_provided_path", size_class="external", reason_cn="10x scATAC 原厂上游，只检测路径。"),
    _tool("Cell Ranger ARC", "https://www.10xgenomics.com/support/software/cell-ranger-arc", "multiome_upstream", "licensed_path_only", "licensed", command="cellranger-arc", install_method="user_provided_path", size_class="external", reason_cn="10x Multiome 上游，只检测路径。"),
    _tool("dsb", "https://github.com/niaid/dsb", "cite_seq", "keep_default", "r_compat", env="ultimate-scrna-r", r_package="dsb", size_class="small", reason_cn="ADT 背景校正。"),
    _tool("MAGeCK", "https://github.com/liulab-dfci/MAGeCK", "perturb_seq", "keep_optional", "specialized_light", env="ultimate-scrna", command="mageck", install_method="optional_deferred: project-level CRISPR screen tool", size_class="medium", reason_cn="CRISPR screen 统计候选；Perturb-seq v1 默认先做 guide assignment 和分组差异。"),
    # VDJ / immune repertoire.
    _tool("scirpy", "https://github.com/scverse/scirpy", "vdj", "keep_default", "specialized_light", env="ultimate-vdj", python_import="scirpy", size_class="medium", reason_cn="AnnData/MuData 免疫组库主线。"),
    _tool("dandelion", "https://github.com/tuonglab/dandelion", "vdj", "keep_optional", "specialized_light", env="ultimate-vdj", python_import="dandelion", size_class="large", reason_cn="BCR/TCR contig 注释和轨迹候选。"),
    _tool("immunarch", "https://github.com/immunomind/immunarch", "vdj", "keep_default", "specialized_light", env="ultimate-vdj-r", r_package="immunarch", size_class="medium", reason_cn="R 生态 AIRR 多样性和 V/J 使用分析。"),
    _tool("scRepertoire", "https://github.com/BorchLab/scRepertoire", "vdj", "keep_default", "specialized_light", env="ultimate-vdj-r", r_package="scRepertoire", size_class="medium", reason_cn="单细胞 TCR/BCR 与 Seurat 整合。"),
    _tool("MiXCR", "https://github.com/milaboratory/mixcr", "vdj", "keep_optional", "upstream_adapter", env="ultimate-vdj", command="mixcr", install_method="optional_deferred: no conda package", size_class="large", reason_cn="VDJ 上游组装/注释；未发现稳定 conda 包，保留为外部二进制/容器 adapter。"),
    _tool("tcrdist3", "https://github.com/kmayerb/tcrdist3", "vdj", "keep_optional", "specialized_light", env="ultimate-vdj", python_import="tcrdist", install_method="optional_deferred: no conda package", size_class="medium", reason_cn="TCR 距离和相似性分析；未发现稳定 conda 包，按项目隔离 pip 安装。"),
    _tool("Cell Ranger VDJ", "https://www.10xgenomics.com/support/software/cell-ranger", "vdj_upstream", "licensed_path_only", "licensed", command="cellranger", install_method="user_provided_path", size_class="external", reason_cn="10x VDJ 上游，只检测路径。"),
    # Spatial.
    _tool("squidpy", "https://github.com/scverse/squidpy", "spatial", "keep_default", "specialized_light", env="ultimate-spatial-py", python_import="squidpy", size_class="large", reason_cn="Scanpy/AnnData 空间分析主线。"),
    _tool("Space Ranger", "https://www.10xgenomics.com/support/software/space-ranger", "spatial_upstream", "licensed_path_only", "licensed", command="spaceranger", install_method="user_provided_path", size_class="external", reason_cn="10x Visium/Visium HD 原厂上游，只检测路径。"),
    _tool("spatialdata", "https://github.com/scverse/spatialdata", "spatial", "keep_default", "specialized_light", env="ultimate-spatial-py", python_import="spatialdata", size_class="large", reason_cn="空间多组学数据结构。"),
    _tool("spatialdata-io", "https://github.com/scverse/spatialdata-io", "spatial", "keep_default", "specialized_light", env="ultimate-spatial-py", python_import="spatialdata_io", size_class="medium", reason_cn="空间平台数据读取。"),
    _tool("Giotto", "https://github.com/giottosuite/Giotto", "spatial", "keep_optional", "specialized_heavy", env="ultimate-spatial-r", r_package="Giotto", install_method="optional_deferred: no conda package", size_class="large", reason_cn="R 空间生态候选；未发现稳定 conda 包，按项目隔离安装。"),
    _tool("Giotto-legacy", "https://github.com/drieslab/Giotto", "spatial", "reference_only", "registry", install_method="reference", size_class="none", reason_cn="旧仓库，仅参考。"),
    _tool("Vitessce", "https://github.com/vitessce/vitessce", "visualization", "keep_optional", "visualization", env="ultimate-browser", install_method="optional_deferred: JS app external adapter", size_class="large", reason_cn="空间/多模态交互交付；无稳定 conda 包，保留为外部静态交付/项目级 adapter。"),
    _tool("easy-vitessce", "https://github.com/vitessce/easy-vitessce", "visualization", "keep_optional", "visualization", env="ultimate-browser", python_import="vitessce", install_method="optional_deferred: pip source-build risk", size_class="medium", reason_cn="Vitessce 配置生成；当前服务器 pip 依赖链有源码编译风险，按项目隔离安装。"),
    _tool("STdeconvolve", "https://github.com/JEFworks-Lab/STdeconvolve", "spatial", "keep_optional", "specialized_light", env="ultimate-spatial-r", r_package="STdeconvolve", install_method="optional_deferred: requires older R/Bioc", size_class="medium", reason_cn="空间解卷积候选；conda 包要求 R 4.2，按项目隔离安装。"),
    _tool("MuSiC", "https://github.com/xuranw/MuSiC", "spatial", "keep_optional", "specialized_light", env="ultimate-spatial-r", r_package="MuSiC", size_class="medium", reason_cn="bulk/空间解卷积候选。"),
    _tool("spacexr", "https://github.com/dmcable/spacexr", "spatial", "keep_optional", "specialized_light", env="ultimate-spatial-r", r_package="spacexr", install_method="optional_deferred: requires older R/Bioc", size_class="medium", reason_cn="RCTD 空间解卷积候选；conda 包要求 R 4.3，按项目隔离安装。"),
    _tool("BayesSpace", "https://github.com/edward130603/BayesSpace", "spatial", "keep_optional", "specialized_light", env="ultimate-spatial-r", r_package="BayesSpace", install_method="optional_deferred: incompatible Bioc generation", size_class="medium", reason_cn="空间 domain 聚类候选；当前 R 4.4 主环境无法干净求解，按项目隔离安装。"),
    # Tumor and genome.
    _tool("inferCNV", "https://github.com/broadinstitute/infercnv", "tumor_sc", "keep_default", "r_compat", env="ultimate-scrna-r", r_package="infercnv", size_class="large", reason_cn="scRNA 推断大尺度 CNV。"),
    _tool("CopyKAT", "https://github.com/navinlabcode/copykat", "tumor_sc", "keep_default", "r_compat", env="ultimate-scrna-r", r_package="copykat", install_method="R remotes", size_class="medium", reason_cn="scRNA aneuploidy/恶性细胞辅助识别。"),
    _tool("HoneyBADGER", "https://github.com/JEFworks-Lab/HoneyBADGER", "tumor_sc", "keep_optional", "specialized_heavy", env="ultimate-scrna-r", r_package="HoneyBADGER", install_method="optional_deferred: no conda package", size_class="large", reason_cn="CNV/LOH 候选，低频；未发现稳定 conda 包，按项目隔离安装。"),
    _tool("ASCAT", "https://github.com/VanLoo-lab/ascat", "genome", "keep_optional", "genome_tools", env="ultimate-genome-mtdna", r_package="ascat", install_method="optional_deferred: no conda package", size_class="medium", reason_cn="bulk tumor-normal CNV purity/ploidy 参考；未发现稳定 conda 包，按项目外部 R 脚本安装。"),
    _tool("PhylogicNDT", "https://github.com/broadinstitute/PhylogicNDT", "genome", "reference_only", "registry", install_method="reference", size_class="none", reason_cn="肿瘤进化参考，当前接单主线不默认安装。"),
    _tool("MissionBio mosaic", "https://github.com/MissionBio/mosaic", "scdna", "keep_optional", "genome_tools", env="ultimate-genome-mtdna", python_import="mosaic", install_method="optional_deferred: conda name collision", size_class="large", reason_cn="MissionBio 单细胞 DNA 数据候选；conda 的 mosaic 包疑似同名异物，按 MissionBio 项目文档隔离安装。"),
    _tool("SiCloneFit", "https://github.com/compbio-mallory/SiCloneFit", "scdna", "reference_only", "registry", install_method="reference", size_class="none", reason_cn="克隆进化参考算法，暂不默认安装。"),
    _tool("SPhyR", "https://github.com/raphael-group/SPhyR", "scdna", "reference_only", "registry", install_method="reference", size_class="none", reason_cn="谱系/克隆结构参考。"),
    _tool("PhISCS", "https://github.com/elkebir-group/PhISCS", "scdna", "reference_only", "registry", install_method="reference", size_class="none", reason_cn="谱系推断参考。"),
    _tool("SingleCellMultiOmics", "https://github.com/BuysDB/SingleCellMultiOmics", "genome", "keep_optional", "genome_tools", env="ultimate-genome-mtdna", python_import="singlecellmultiomics", install_method="optional_deferred: no conda package", size_class="large", reason_cn="单细胞多组学/mtDNA/genotyping 候选；未发现稳定 conda 包，按项目隔离安装。"),
    _tool("MitoTrace", "https://github.com/LareauCA/MitoTrace", "mtdna", "keep_optional", "genome_tools", env="ultimate-genome-mtdna", install_method="optional_deferred: project scripts", size_class="medium", reason_cn="mtDNA lineage tracing 候选；项目脚本型工具，按项目数据和参考资源隔离配置。"),
    _tool("mitoClone", "https://github.com/veltenlab/mitoClone", "mtdna", "reference_only", "registry", install_method="reference", size_class="none", reason_cn="mtDNA 克隆分析参考。"),
    _tool("mitoClone2", "https://github.com/caleblareau/mitoClone2", "mtdna", "keep_optional", "genome_tools", env="ultimate-genome-mtdna", r_package="mitoClone2", install_method="optional_deferred: no conda package", size_class="medium", reason_cn="mtDNA 克隆分析候选；未发现稳定 conda 包，按项目 R remotes 隔离安装。"),
    _tool("cellsnp-lite", "https://github.com/single-cell-genetics/cellsnp-lite", "genotype", "keep_default", "genome_tools", env="ultimate-genome-mtdna", command="cellsnp-lite", size_class="medium", reason_cn="SNP/mtDNA demultiplex 基础工具。"),
    _tool("vireo", "https://github.com/single-cell-genetics/vireo", "genotype", "keep_default", "genome_tools", env="ultimate-genome-mtdna", python_import="vireoSNP", command="vireo", size_class="medium", reason_cn="genotype demultiplex。"),
    _tool("demuxlet", "https://github.com/statgen/demuxlet", "genotype", "keep_optional", "genome_tools", env="ultimate-genome-mtdna", command="demuxlet", install_method="optional_deferred: would downgrade genome stack", size_class="medium", reason_cn="有 genotype 时 demultiplex；当前 dry-run 会降级 samtools/bcftools/cellsnp/vireo，按项目隔离安装。"),
    _tool("popscle", "https://github.com/statgen/popscle", "genotype", "keep_optional", "genome_tools", env="ultimate-genome-mtdna", command="popscle", install_method="optional_deferred: would downgrade genome stack", size_class="medium", reason_cn="demuxlet 相关工具集；当前 dry-run 会降级 genome 主环境，按项目隔离安装。"),
    # Visualization and formats.
    _tool("Dash", "https://github.com/plotly/dash", "visualization", "keep_optional", "visualization", env="ultimate-browser", python_import="dash", size_class="medium", reason_cn="客户交互 dashboard 候选，和 cellxgene 共同放在浏览器环境。"),
    _tool("Shiny", "https://github.com/rstudio/shiny", "visualization", "keep_optional", "r_compat", env="ultimate-scrna-r", r_package="shiny", size_class="medium", reason_cn="R 交互报告候选。"),
    _tool("seurat-data", "https://github.com/satijalab/seurat-data", "reference", "keep_optional", "r_compat", env="ultimate-scrna-r", r_package="SeuratData", size_class="medium", reason_cn="Seurat 教程/参考数据；由 r-azimuth 稳定带入。"),
    _tool("sceasy", "https://github.com/cellgeni/sceasy", "interop", "keep_optional", "r_compat", env="ultimate-scrna-r", r_package="sceasy", install_method="optional_deferred: would downgrade Monocle3", size_class="small", reason_cn="Seurat/SCE/h5ad 互转候选；dry-run 会降级 Monocle3，默认改用 zellkonverter/SeuratDisk。"),
    _tool("seurat-disk", "https://github.com/mojaveazure/seurat-disk", "interop", "keep_optional", "r_compat", env="ultimate-scrna-r", r_package="SeuratDisk", size_class="medium", reason_cn="Seurat/h5Seurat/h5ad 互转；由 r-azimuth 稳定带入，zellkonverter 仍为默认互转路线。"),
    _tool("zellkonverter", "https://bioconductor.org/packages/release/bioc/html/zellkonverter.html", "interop", "keep_default", "r_compat", env="ultimate-scrna-r", r_package="zellkonverter", size_class="medium", reason_cn="Bioconductor h5ad/SCE 互转默认路线，替代旧 SeuratDisk 主路径。"),
    _tool("seurat-object", "https://github.com/satijalab/seurat-object", "interop", "keep_default", "r_compat", env="ultimate-scrna-r", r_package="SeuratObject", size_class="medium", reason_cn="Seurat 对象基础。"),
    _tool("SingleCellExperiment", "https://bioconductor.org/packages/release/bioc/html/SingleCellExperiment.html", "interop", "keep_default", "r_compat", env="ultimate-scrna-r", r_package="SingleCellExperiment", size_class="medium", reason_cn="Bioconductor 单细胞对象标准。"),
    # Plan-completeness additions surfaced by the multiomics module audit.
    _tool("WGCNA", "https://horvath.genetics.ucla.edu/html/CoexpressionNetwork/Rpackages/WGCNA/", "wgcna", "keep_optional", "r_compat", env="ultimate-rnaseq", r_package="WGCNA", size_class="medium", reason_cn="bulk/pseudobulk 共表达网络 R backend；样本数不足时只做 handoff。"),
    _tool("GEOquery", "https://bioconductor.org/packages/release/bioc/html/GEOquery.html", "publicdb", "keep_optional", "r_compat", env="ultimate-rnaseq", r_package="GEOquery", size_class="medium", reason_cn="GEO 数据下载和元数据读取；默认先支持 cached table。"),
    _tool("TCGAbiolinks", "https://github.com/BioinformaticsFMRP/TCGAbiolinks", "publicdb", "keep_optional", "r_compat", env="ultimate-rnaseq", r_package="TCGAbiolinks", size_class="large", reason_cn="TCGA 下载和整理；大下载走 Slurm/cache。"),
    _tool("lifelines", "https://github.com/CamDavidsonPilon/lifelines", "clinical_assoc", "keep_optional", "core", env="ultimate-core", python_import="lifelines", size_class="small", reason_cn="Python 生存分析候选；样本量不足时只输出 handoff。"),
    _tool("statsmodels", "https://github.com/statsmodels/statsmodels", "clinical_assoc", "keep_default", "core", env="ultimate-core", python_import="statsmodels", size_class="medium", reason_cn="临床关联、协变量和基础统计模型。"),
    _tool("MACS3", "https://github.com/macs3-project/MACS", "scatac", "keep_default", "specialized_light", env="ultimate-scatac-py", python_import="MACS3", command="macs3", size_class="medium", reason_cn="ATAC peak calling 标准工具；第一版 fragments/peak matrix 优先。"),
    _tool("bedtools", "https://github.com/arq5x/bedtools2", "scatac", "keep_default", "genome_tools", env="ultimate-genome-mtdna", command="bedtools", size_class="medium", reason_cn="区间交集、FRiP、peak/gene annotation 基础命令。"),
    _tool("samtools", "https://github.com/samtools/samtools", "genome", "keep_default", "genome_tools", env="ultimate-genome-mtdna", command="samtools", size_class="medium", reason_cn="BAM/CRAM 读写、depth、index 基础命令。"),
    _tool("bcftools", "https://github.com/samtools/bcftools", "genome", "keep_default", "genome_tools", env="ultimate-genome-mtdna", command="bcftools", size_class="medium", reason_cn="VCF/BCF variant QC 和过滤基础命令。"),
    _tool("pysam", "https://github.com/pysam-developers/pysam", "genome", "keep_default", "genome_tools", env="ultimate-genome-mtdna", python_import="pysam", size_class="medium", reason_cn="Python BAM/VCF 读取，mtDNA/scDNA 轻量 backend。"),
    _tool("pertpy", "https://github.com/scverse/pertpy", "perturb_seq", "keep_optional", "specialized_heavy_py", env="ultimate-scrna-heavy", python_import="pertpy", size_class="large", reason_cn="Perturb-seq/scverse 专项模型；MVP 先做 guide assignment 和 design-ready 输出。"),
    _tool("SCEPTRE", "https://github.com/Katsevich-Lab/sceptre", "perturb_seq", "keep_optional", "specialized_heavy", env="ultimate-scrna-r", r_package="sceptre", install_method="optional_deferred: project-specific R backend", size_class="medium", reason_cn="CRISPR perturbation effect 专项统计；第一版只做 handoff。"),
    _tool("hashsolo", "https://github.com/calico/solo", "hto_demux", "keep_optional", "scrna_core", env="ultimate-scrna", python_import="solo", install_method="optional_deferred: package naming varies", size_class="medium", reason_cn="HTO/cell hashing demux 候选；MVP 保持矩阵级 assignment summary。"),
    _tool("sopa", "https://github.com/gustaveroussy/sopa", "spatial", "keep_optional", "specialized_heavy_py", env="ultimate-spatial-py", python_import="sopa", size_class="large", reason_cn="Xenium/CosMX/MERSCOPE/Visium HD 空间生态；第一版作为 handoff/optional backend。"),
)


BATCH_ENV_FILES = {
    "workflow_core": [("ultimate-workflow", "environment.workflow.yml")],
    "upstream_adapter": [
        ("ultimate-workflow", "environment.workflow.yml"),
        ("ultimate-vdj", "environment.vdj.yml"),
    ],
    "scrna_core": [("ultimate-scrna", "environment.scrna.py.yml")],
    "r_compat": [
        ("ultimate-scrna-r", "environment.scrna.r.yml"),
        ("ultimate-rnaseq", "environment.rnaseq.yml"),
    ],
    "specialized_light": [
        ("ultimate-scrna", "environment.scrna.py.yml"),
        ("ultimate-scatac-py", "environment.scatac.py.yml"),
        ("ultimate-scatac-r", "environment.scatac.r.yml"),
        ("ultimate-vdj", "environment.vdj.yml"),
        ("ultimate-vdj-r", "environment.vdj.r.yml"),
        ("ultimate-spatial-py", "environment.spatial.py.yml"),
        ("ultimate-spatial-r", "environment.spatial.r.yml"),
    ],
    "spatial": [("ultimate-spatial-py", "environment.spatial.py.yml")],
    "genome_tools": [("ultimate-genome-mtdna", "environment.genome_mtdna.yml")],
    "specialized_heavy_py": [("ultimate-scrna-heavy", "environment.scrna.heavy.yml")],
    "visualization": [("ultimate-browser", "environment.browser.yml")],
}


def available_tool_batches() -> list[str]:
    return sorted({tool.batch for tool in TOOL_REGISTRY})


def run_audit_tools(root: Path, output_dir: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    output_dir = (output_dir or root / "audits" / "tools").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    registry_rows = [asdict(tool) for tool in TOOL_REGISTRY]
    env_paths = _env_paths(root)
    checks = _collect_checks(env_paths, TOOL_REGISTRY)
    audit_rows = [_audit_row(tool, checks) for tool in TOOL_REGISTRY]
    install_rows = [row for row in audit_rows if _needs_install(row)]
    storage = _storage_estimate(root, audit_rows)

    registry_tsv = output_dir / "tool_registry.tsv"
    registry_json = output_dir / "tool_registry.json"
    audit_tsv = output_dir / "tool_audit_matrix.tsv"
    dependency_tsv = output_dir / "dependency_report.tsv"
    install_tsv = output_dir / "install_plan.tsv"
    storage_tsv = output_dir / "storage_estimate.tsv"
    report_html = output_dir / "tool_audit_report.html"
    manifest_path = output_dir / "tool_audit_manifest.json"

    _write_tsv(registry_tsv, registry_rows)
    registry_json.write_text(json.dumps(registry_rows, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_tsv(audit_tsv, audit_rows)
    _write_tsv(dependency_tsv, _dependency_rows(audit_rows))
    _write_tsv(install_tsv, install_rows)
    _write_tsv(storage_tsv, storage["rows"])
    _write_tool_report(report_html, audit_rows, storage)

    summary = _summarize(audit_rows)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "output_dir": str(output_dir),
        "tool_count": len(TOOL_REGISTRY),
        "summary": summary,
        "storage": storage["summary"],
        "registry_tsv": str(registry_tsv),
        "registry_json": str(registry_json),
        "tool_audit_matrix": str(audit_tsv),
        "dependency_report": str(dependency_tsv),
        "install_plan": str(install_tsv),
        "storage_estimate": str(storage_tsv),
        "report_html": str(report_html),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest["manifest_path"] = str(manifest_path)
    return manifest


def run_trial_tools(
    *,
    root: Path,
    batch: str,
    output_dir: Path | None = None,
    install: bool = False,
    project_root: Path | None = None,
) -> dict[str, Any]:
    if batch not in available_tool_batches():
        raise ValueError(f"Unsupported batch {batch!r}; expected one of {available_tool_batches()}")
    root = root.resolve()
    project_root = (project_root or root).resolve()
    output_dir = (output_dir or root / "audits" / "tool_trials" / batch).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    before = _storage_estimate(root, [], detailed=False)
    selected = [tool for tool in TOOL_REGISTRY if tool.batch == batch]
    install_logs = _install_batch(root=root, project_root=project_root, batch=batch, output_dir=output_dir) if install else []
    checks = _collect_checks(_env_paths(root), selected)
    rows = [_audit_row(tool, checks) for tool in selected]
    after = _storage_estimate(root, [], detailed=False)

    trial_tsv = output_dir / "trial_tools.tsv"
    install_log_tsv = output_dir / "install_logs.tsv"
    before_tsv = output_dir / "storage_before.tsv"
    after_tsv = output_dir / "storage_after.tsv"
    manifest_path = output_dir / "trial_manifest.json"
    _write_tsv(trial_tsv, rows)
    _write_tsv(install_log_tsv, install_logs)
    _write_tsv(before_tsv, before["rows"])
    _write_tsv(after_tsv, after["rows"])
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "batch": batch,
        "install_requested": install,
        "tool_count": len(selected),
        "summary": _summarize(rows),
        "storage_before": before["summary"],
        "storage_after": after["summary"],
        "trial_tools": str(trial_tsv),
        "install_logs": str(install_log_tsv),
        "storage_before_tsv": str(before_tsv),
        "storage_after_tsv": str(after_tsv),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest["manifest_path"] = str(manifest_path)
    return manifest


def run_prune_tools(root: Path, output_dir: Path | None = None, yes: bool = False) -> dict[str, Any]:
    root = root.resolve()
    output_dir = (output_dir or root / "audits" / "tool_prune").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    rejected = [asdict(tool) for tool in TOOL_REGISTRY if tool.decision == "rejected_cleaned"]
    cleanup_rows: list[dict[str, Any]] = []
    if yes:
        cleanup_rows.extend(_run_cleanup_command(["mamba", "clean", "--tarballs", "--packages", "-y"], "mamba_cache"))
    else:
        cleanup_rows.append({"target": "mamba_cache", "status": "planned_only", "command": "mamba clean --tarballs --packages -y"})
    prune_plan = output_dir / "prune_plan.tsv"
    cleanup_tsv = output_dir / "cleanup_actions.tsv"
    manifest_path = output_dir / "prune_manifest.json"
    _write_tsv(prune_plan, rejected)
    _write_tsv(cleanup_tsv, cleanup_rows)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "executed": yes,
        "rejected_count": len(rejected),
        "prune_plan": str(prune_plan),
        "cleanup_actions": str(cleanup_tsv),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest["manifest_path"] = str(manifest_path)
    return manifest


def _env_paths(root: Path) -> dict[str, Path]:
    env_names = sorted({tool.env for tool in TOOL_REGISTRY if tool.env})
    return {env: root / ".conda" / "envs" / env for env in env_names}


def _collect_checks(env_paths: dict[str, Path], specs: tuple[ToolSpec, ...] | list[ToolSpec]) -> dict[str, dict[str, bool]]:
    python_checks: dict[str, bool] = {}
    r_checks: dict[str, bool] = {}
    command_checks: dict[str, bool] = {}

    py_by_env: dict[str, list[str]] = {}
    r_by_env: dict[str, list[str]] = {}
    commands: set[str] = set()
    for tool in specs:
        if tool.python_import and tool.env:
            py_by_env.setdefault(tool.env, []).append(tool.python_import)
        if tool.r_package and tool.env:
            r_by_env.setdefault(tool.env, []).append(tool.r_package)
        if tool.command:
            commands.add(tool.command)

    for env, packages in py_by_env.items():
        python_checks.update({f"{env}:{pkg}": ok for pkg, ok in _check_python(env_paths.get(env), sorted(set(packages))).items()})
    for env, packages in r_by_env.items():
        r_checks.update({f"{env}:{pkg}": ok for pkg, ok in _check_r(env_paths.get(env), sorted(set(packages))).items()})
    for command in sorted(commands):
        command_checks[command] = _command_available(command, env_paths)
    return {"python": python_checks, "r": r_checks, "command": command_checks}


def _check_python(env_path: Path | None, packages: list[str]) -> dict[str, bool]:
    found = {pkg: False for pkg in packages}
    python = env_path / "bin" / "python" if env_path else None
    if not python or not python.exists():
        return found
    code = (
        "import importlib.util\n"
        f"pkgs={packages!r}\n"
        "for pkg in pkgs:\n"
        "    print(pkg + '\\t' + str(bool(importlib.util.find_spec(pkg))))\n"
    )
    try:
        proc = subprocess.run([str(python), "-c", code], text=True, capture_output=True, timeout=90, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return found
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 2 and parts[0] in found:
            found[parts[0]] = parts[1] == "True"
    return found


def _check_r(env_path: Path | None, packages: list[str]) -> dict[str, bool]:
    found = {pkg: False for pkg in packages}
    rscript = env_path / "bin" / "Rscript" if env_path else None
    if not rscript or not rscript.exists():
        return found
    code = (
        f"pkgs <- c({','.join(repr(pkg) for pkg in packages)})\n"
        "installed <- rownames(installed.packages())\n"
        "for (pkg in pkgs) { cat(pkg, pkg %in% installed, sep='\\t'); cat('\\n') }\n"
    )
    try:
        proc = subprocess.run([str(rscript), "-e", code], text=True, capture_output=True, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return found
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0] in found:
            found[parts[0]] = parts[1].upper() == "TRUE"
    return found


def _command_available(command: str, env_paths: dict[str, Path]) -> bool:
    if command == "apptainer" and shutil.which("singularity") is not None:
        return True
    for env_path in env_paths.values():
        candidate = env_path / "bin" / command
        if candidate.exists():
            return True
    return shutil.which(command) is not None


def _audit_row(tool: ToolSpec, checks: dict[str, dict[str, bool]]) -> dict[str, Any]:
    check_kind = "none"
    installed = False
    check_key = ""
    if tool.python_import and tool.env:
        check_kind = "python"
        check_key = f"{tool.env}:{tool.python_import}"
        installed = checks["python"].get(check_key, False)
    elif tool.r_package and tool.env:
        check_kind = "r"
        check_key = f"{tool.env}:{tool.r_package}"
        installed = checks["r"].get(check_key, False)
    elif tool.command:
        check_kind = "command"
        check_key = tool.command
        installed = checks["command"].get(tool.command, False)

    if tool.decision == "reference_only":
        status = "reference_only"
    elif tool.decision == "rejected_cleaned":
        status = "rejected_cleaned"
    elif tool.decision == "licensed_path_only":
        status = "licensed_path_available" if installed else "licensed_path_missing"
    elif tool.decision == "adapter_only":
        if installed or tool.install_method in {"external_vendor_pipeline", "web_reference"} or tool.size_class == "external":
            status = "adapter_ready"
        else:
            status = "adapter_pending"
    elif installed:
        status = "installed"
    elif tool.decision == "keep_optional" and tool.install_method.startswith("optional_deferred"):
        status = "optional_deferred"
    else:
        status = "needs_trial_install"

    return {
        **asdict(tool),
        "check_kind": check_kind,
        "check_key": check_key,
        "check_passed": installed,
        "status": status,
        "v2_disposition": DECISION_TO_V2_DISPOSITION.get(tool.decision, tool.decision),
        "estimated_gb": SIZE_GB.get(tool.size_class, 1.0),
        "final_disposition_cn": _disposition_cn(tool.decision),
    }


def _disposition_cn(decision: str) -> str:
    return {
        "keep_default": "保留默认",
        "keep_optional": "保留可选",
        "adapter_only": "外部适配",
        "reference_only": "仅参考",
        "licensed_path_only": "授权路径检测",
        "rejected_cleaned": "清理淘汰",
    }[decision]


def _needs_install(row: dict[str, Any]) -> bool:
    return row["decision"] in {"keep_default", "keep_optional", "adapter_only"} and row["status"] in {"needs_trial_install", "adapter_pending"}


def _storage_estimate(root: Path, audit_rows: list[dict[str, Any]], *, detailed: bool = True) -> dict[str, Any]:
    target = root if root.exists() else root.parent
    usage = shutil.disk_usage(target)
    paths = {
        "conda_envs": root / ".conda" / "envs",
        "conda_pkgs": root / ".conda" / "pkgs",
        "public_data": root / "public_data",
        "validations": root / "validations",
        "nextflow_cache": root / ".nextflow",
        "apptainer_cache": root / ".apptainer",
    }
    rows = [
        {"metric": "filesystem_total_gb", "path": str(target), "value": _bytes_to_gb(usage.total), "note": ""},
        {"metric": "filesystem_used_gb", "path": str(target), "value": _bytes_to_gb(usage.used), "note": ""},
        {"metric": "filesystem_available_gb", "path": str(target), "value": _bytes_to_gb(usage.free), "note": ""},
    ]
    for name, path in paths.items():
        if detailed:
            rows.append({"metric": f"{name}_gb", "path": str(path), "value": _du_gb(path), "note": "du -sk"})
        else:
            rows.append({"metric": f"{name}_gb", "path": str(path), "value": "", "note": "skipped_in_fast_trial_snapshot"})
    rows.append({"metric": "ultimate_root_full_scan_gb", "path": str(root), "value": "", "note": "skipped_to_avoid_heavy_shared_filesystem_scan"})
    pending_gb = round(sum(float(row["estimated_gb"]) for row in audit_rows if _needs_install(row)), 2)
    rows.append({"metric": "pending_trial_install_estimated_gb", "path": str(root), "value": pending_gb, "note": "registry estimate; references and licensed paths excluded"})
    rows.append({"metric": "storage_guard_min_available_gb", "path": str(target), "value": 800.0, "note": "below this only audit should run"})
    summary = {
        "filesystem_available_gb": _bytes_to_gb(usage.free),
        "pending_trial_install_estimated_gb": pending_gb,
        "guard_status": "ok" if _bytes_to_gb(usage.free) >= 800 else "hold_install_low_space",
    }
    return {"summary": summary, "rows": rows}


def _du_gb(path: Path) -> float:
    if not path.exists():
        return 0.0
    try:
        proc = subprocess.run(["du", "-sk", str(path)], text=True, capture_output=True, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return -1.0
    if proc.returncode != 0 or not proc.stdout.strip():
        return -1.0
    kb = float(proc.stdout.split()[0])
    return round(kb / 1024 / 1024, 3)


def _bytes_to_gb(value: int) -> float:
    return round(float(value) / 1024 / 1024 / 1024, 3)


def _dependency_rows(audit_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in audit_rows:
        if row["check_kind"] != "none":
            rows.append(
                {
                    "name": row["name"],
                    "env": row["env"],
                    "check_kind": row["check_kind"],
                    "check_key": row["check_key"],
                    "check_passed": row["check_passed"],
                    "status": row["status"],
                }
            )
    return rows


def _summarize(rows: list[dict[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for row in rows:
        key = str(row["status"])
        summary[key] = summary.get(key, 0) + 1
    return summary


def _install_batch(root: Path, project_root: Path, batch: str, output_dir: Path) -> list[dict[str, Any]]:
    if batch not in BATCH_ENV_FILES:
        return [{"batch": batch, "status": "install_not_supported_for_batch", "log": "", "command": ""}]
    mamba = shutil.which("mamba") or "mamba"
    (root / ".conda" / "pkgs").mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for env_name, env_file_name in BATCH_ENV_FILES[batch]:
        env_file = project_root / "envs" / env_file_name
        prefix = root / ".conda" / "envs" / env_name
        log_path = output_dir / f"install_{batch}_{env_name}.log"
        if not env_file.exists():
            rows.append({"batch": batch, "env": env_name, "status": "missing_env_file", "log": str(log_path), "command": str(env_file), "condarc": ""})
            continue
        if prefix.exists() and not (prefix / "conda-meta").exists() and not (prefix / "bin" / "python").exists():
            shutil.rmtree(prefix)
        prefix.parent.mkdir(parents=True, exist_ok=True)
        for attempt_idx, condarc in enumerate(_condarc_candidates(project_root), start=1):
            env_exists = (prefix / "conda-meta").exists() or (prefix / "bin" / "python").exists()
            command = [mamba, "env", "update" if env_exists else "create", "-p", str(prefix), "-f", str(env_file), "-y"]
            if env_exists:
                command.append("--prune")
            env = os.environ.copy()
            env["CONDA_PKGS_DIRS"] = str(root / ".conda" / "pkgs")
            if condarc is None:
                env.pop("CONDARC", None)
                condarc_label = "default_channels"
            else:
                env["CONDARC"] = str(condarc)
                condarc_label = condarc.name
            attempt_log = output_dir / f"install_{batch}_{env_name}_{attempt_idx}_{condarc_label}.log"
            with attempt_log.open("w", encoding="utf-8") as log:
                log.write(f"CONDARC={env.get('CONDARC', 'unset')}\n")
                log.write(f"COMMAND={' '.join(command)}\n\n")
                proc = subprocess.run(command, text=True, stdout=log, stderr=subprocess.STDOUT, env=env, check=False)
            rows.append(
                {
                    "batch": batch,
                    "env": env_name,
                    "status": "ok" if proc.returncode == 0 else f"failed:{proc.returncode}",
                    "log": str(attempt_log),
                    "command": " ".join(command),
                    "condarc": env.get("CONDARC", ""),
                }
            )
            if proc.returncode == 0:
                break
    return rows


def _condarc_candidates(project_root: Path) -> list[Path | None]:
    candidates: list[Path | None] = []
    current = os.environ.get("CONDARC")
    if current and Path(current).exists():
        candidates.append(Path(current))
    for name in (
        "condarc.mirrors.bfsu.yml",
        "condarc.mirrors.sjtu.yml",
        "condarc.mirrors.aliyun.yml",
        "condarc.mirrors.tuna.yml",
    ):
        path = project_root / "config" / name
        if path.exists() and path not in candidates:
            candidates.append(path)
    candidates.append(None)
    return candidates


def _run_cleanup_command(command: list[str], target: str) -> list[dict[str, Any]]:
    try:
        proc = subprocess.run(command, text=True, capture_output=True, timeout=600, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [{"target": target, "status": f"failed:{type(exc).__name__}", "command": " ".join(command)}]
    return [{"target": target, "status": "ok" if proc.returncode == 0 else f"failed:{proc.returncode}", "command": " ".join(command)}]


def _write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row}) if rows else ["empty"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_tool_report(path: Path, rows: list[dict[str, Any]], storage: dict[str, Any]) -> None:
    summary = _summarize(rows)
    decision_counts: dict[str, int] = {}
    for row in rows:
        decision_counts[str(row["decision"])] = decision_counts.get(str(row["decision"]), 0) + 1
    table_rows = "\n".join(
        f"<tr><td>{row['name']}</td><td>{row['module']}</td><td>{row['final_disposition_cn']}</td><td>{row['status']}</td><td>{row['env']}</td><td>{row['reason_cn']}</td></tr>"
        for row in rows
    )
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>Ultimate 工具审计报告</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; color: #3f4758; }}
    h1, h2 {{ color: #5b5fc7; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #e6eaf2; padding: 7px; font-size: 13px; text-align: left; }}
    th {{ background: #eef1fb; }}
    code {{ background: #f6f8fb; padding: 2px 4px; border-radius: 4px; }}
  </style>
</head>
<body>
  <h1>Ultimate 工具审计报告</h1>
  <p>生成时间：{datetime.now(timezone.utc).isoformat()}</p>
  <h2>概览</h2>
  <p>工具数量：{len(rows)}；状态统计：<code>{json.dumps(summary, ensure_ascii=False)}</code></p>
  <p>处置统计：<code>{json.dumps(decision_counts, ensure_ascii=False)}</code></p>
  <p>存储守卫：<code>{json.dumps(storage['summary'], ensure_ascii=False)}</code></p>
  <h2>工具矩阵</h2>
  <table>
    <thead><tr><th>工具</th><th>模块</th><th>处置</th><th>状态</th><th>环境</th><th>理由</th></tr></thead>
    <tbody>{table_rows}</tbody>
  </table>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")
