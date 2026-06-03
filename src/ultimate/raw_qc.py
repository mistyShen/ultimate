from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ultimate.plot_style import apply_clinical_journal_style, save_figure

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns


@dataclass(frozen=True)
class RawContract:
    input_types: tuple[str, ...]
    required_columns: tuple[str, ...]
    output_kind: str
    tools: tuple[str, ...]
    open_replacements: tuple[str, ...]


PATH_COLUMNS = (
    "input_path",
    "fastq_1",
    "fastq_2",
    "fastq_dir",
    "bcl_dir",
    "fragments",
    "peak_matrix",
    "matrix_path",
    "matrix_dir",
    "feature_matrix",
    "count_matrix",
    "idat_dir",
    "visium_dir",
    "spatial_dir",
    "spatialdata_zarr",
    "sopa_project",
    "cellranger_out",
    "cellranger_atac_out",
    "cellranger_arc_out",
    "cellranger_vdj_out",
    "spaceranger_out",
    "airr_table",
    "clonotypes",
    "contig_annotations",
    "guide_counts",
    "guide_assignments",
    "hashtag_counts",
    "adt_counts",
    "bam",
    "vcf",
    "barcode_file",
    "variant_table",
    "cnv_table",
    "demux_result",
    "reference",
    "gtf",
    "genome_dir",
    "clinical_table",
    "signature_matrix",
)

MATRIX_INPUT_KEYS = (
    "matrix_path",
    "feature_matrix",
    "count_matrix",
    "peak_matrix",
    "clinical_table",
    "signature_matrix",
    "guide_counts",
    "guide_assignments",
    "hashtag_counts",
    "adt_counts",
    "airr_table",
    "clonotypes",
    "contig_annotations",
    "variant_table",
    "cnv_table",
    "demux_result",
)

MATRIX_LIKE_INPUT_TYPES = {
    "count_matrix",
    "beta_matrix",
    "abundance_table",
    "downloaded_matrix",
    "expression_matrix",
    "matrix",
    "clinical_table",
    "peak_matrix",
    "rna_adt_matrix",
    "adt_counts",
    "hashtag_counts",
    "guide_counts",
    "guide_assignment",
    "airr_rearrangement",
    "clonotypes",
    "contig_annotations",
    "variant_table",
    "cnv_table",
    "cellsnp_matrix",
    "vireo_result",
    "demux_result",
    "bd_rhapsody_matrix",
    "parse_matrix",
    "dropseq_matrix",
    "seqwell_matrix",
    "smartseq2_matrix",
    "stereoseq_matrix",
    "slideseq_matrix",
    "merfish_matrix",
}


RAW_CONTRACTS: dict[str, RawContract] = {
    "rnaseq": RawContract(("fastq", "count_matrix"), ("sample_id", "condition", "fastq_1"), "count_matrix", ("fastqc", "multiqc", "fastp", "STAR", "hisat2", "featureCounts", "salmon"), ("STAR", "HISAT2", "Salmon")),
    "scrna": RawContract(
        ("10x_h5", "10x_mtx", "h5ad", "fastq", "bcl", "bd_rhapsody_matrix", "parse_matrix", "dropseq_matrix", "seqwell_matrix", "smartseq2_fastq", "smartseq2_matrix"),
        ("sample_id", "condition", "input_path"),
        "h5ad_or_rds",
        ("cellranger", "bcl-convert", "bcl2fastq", "STAR", "alevin-fry", "nextflow"),
        ("nf-core/scrnaseq", "STARsolo", "alevin-fry", "scanpy", "Seurat"),
    ),
    "scatac": RawContract(
        ("fastq", "fragments", "peak_matrix", "cellranger_atac_out"),
        ("sample_id", "condition", "input_path"),
        "peak_matrix_h5ad",
        ("cellranger-atac", "bwa", "macs2", "bedtools", "samtools"),
        ("MACS3", "Signac", "snapatac2", "nf-core/atacseq adapter"),
    ),
    "multiome": RawContract(
        ("multiome_h5", "arc_output", "fastq", "fragments", "rna_matrix_atac_fragments", "h5mu"),
        ("sample_id", "condition", "input_path"),
        "rna_atac_h5ad_or_h5mu",
        ("cellranger-arc", "bwa", "macs2", "bedtools", "samtools"),
        ("muon", "Signac", "snapatac2", "Cell Ranger ARC output reader"),
    ),
    "vdj": RawContract(
        ("contig_annotations", "clonotypes", "airr_rearrangement", "fastq", "cellranger_vdj_out", "mixcr_output"),
        ("sample_id", "condition", "input_path"),
        "clonotype_table",
        ("cellranger", "mixcr", "nextflow"),
        ("scirpy", "scRepertoire", "immunarch", "nf-core/airrflow"),
    ),
    "scdna": RawContract(
        ("bam", "fastq", "variant_table", "cnv_table", "missionbio_tapestri", "missionbio_mosaic"),
        ("sample_id", "condition", "input_path"),
        "variant_qc_tables",
        ("samtools", "bcftools", "bwa", "bedtools"),
        ("samtools", "bcftools", "cnvkit", "MissionBio mosaic optional adapter"),
    ),
    "mtdna": RawContract(
        ("bam", "fastq", "variant_table", "cellsnp_matrix", "mgatk_output", "mitotrace_output", "mitoclone2_output"),
        ("sample_id", "condition", "input_path"),
        "mtdna_variant_tables",
        ("samtools", "bcftools", "cellsnp-lite", "vireo"),
        ("samtools", "bcftools", "mgatk-like summary", "MitoTrace optional adapter", "mitoClone2 optional adapter"),
    ),
    "scepi": RawContract(
        ("fragments", "idat", "matrix", "scbs_fastq", "scnmt_matrix", "cuttag_fragments", "cutrun_fragments"),
        ("sample_id", "condition", "input_path"),
        "epigenomic_matrix",
        ("macs2", "bedtools", "samtools"),
        ("Signac", "chromVAR", "minfi", "specialty sc-epigenome adapter"),
    ),
    "cite_seq": RawContract(("10x_h5", "rna_adt_matrix", "adt_counts"), ("sample_id", "condition", "input_path"), "rna_adt_h5ad", (), ("scanpy", "Seurat", "dsb")),
    "spatial": RawContract(
        ("visium_dir", "spatial_h5ad", "xenium_dir", "cosmx_dir", "merscope_dir", "merfish_matrix", "slideseq_matrix", "stereoseq_matrix", "visium_hd_dir", "spatialdata_zarr", "sopa_project"),
        ("sample_id", "condition", "input_path"),
        "spatial_h5ad_or_spatialdata",
        ("spaceranger",),
        ("squidpy", "spatialdata", "spatialdata-io", "SOPA", "Seurat", "SpatialExperiment"),
    ),
    "perturb_seq": RawContract(("guide_counts", "guide_assignment", "expression_object", "matrix"), ("sample_id", "condition", "input_path"), "perturbation_tables", (), ("scanpy", "Seurat", "decoupler", "limma")),
    "hto_demux": RawContract(("hashtag_counts", "antibody_capture_matrix", "10x_h5"), ("sample_id", "condition", "input_path"), "demultiplexed_sample_table", (), ("Seurat HTODemux", "DropletUtils", "scanpy")),
    "genotype_demux": RawContract(("bam_vcf_barcode", "cellsnp_matrix", "vireo_result", "souporcell_result", "demuxlet_result", "popscle_result"), ("sample_id", "condition", "input_path"), "genotype_demux_table", ("cellsnp-lite", "vireo", "souporcell_pipeline.py", "demuxlet", "popscle"), ("cellsnp-lite", "vireo", "souporcell", "demuxlet/popscle optional adapter")),
    "functional_state": RawContract(("expression_object", "matrix"), ("sample_id", "condition", "input_path"), "score_matrix", (), ("GSVA", "AUCell", "decoupler")),
    "tumor_sc": RawContract(("expression_object", "matrix"), ("sample_id", "condition", "input_path"), "tumor_sc_object", (), ("inferCNV", "CopyKAT", "scanpy")),
    "clinical_assoc": RawContract(("clinical_table", "matrix"), ("sample_id", "condition", "input_path"), "clinical_matrix", (), ("survival", "survminer", "GSVA")),
    "method_tools": RawContract(("object", "matrix"), ("sample_id", "condition", "input_path"), "tool_manifest", ("snakemake",), ("scanpy", "Seurat", "cellxgene")),
    "methylation": RawContract(("idat", "beta_matrix"), ("sample_id", "condition", "input_path"), "beta_matrix", (), ("minfi", "ChAMP", "limma")),
    "proteomics": RawContract(("abundance_table", "maxquant", "proteome_discoverer"), ("sample_id", "condition", "input_path"), "abundance_matrix", (), ("limma", "ropls", "STRINGdb")),
    "publicdb": RawContract(("cohort_config", "downloaded_matrix"), ("cohort_id", "condition"), "cohort_matrix", (), ("TCGAbiolinks", "GEOquery", "GSVA", "open immune signatures")),
    "wgcna": RawContract(("expression_matrix",), ("sample_id", "condition", "input_path"), "expression_matrix", (), ("WGCNA", "dynamicTreeCut")),
    "single_gene": RawContract(("expression_matrix", "clinical_table"), ("sample_id", "condition", "input_path"), "single_gene_matrix", (), ("survival", "GSVA", "maftools")),
}


def run_raw_qc(*, module_name: str, config: dict[str, Any], output_dir: Path, samples: pd.DataFrame) -> dict[str, Any]:
    contract = RAW_CONTRACTS[module_name]
    module_cfg = (config.get("modules") or {}).get(module_name) or {}
    raw_cfg = module_cfg.get("raw") or {}
    enabled = bool(raw_cfg.get("enabled", True))
    module_dir = output_dir
    raw_dir = module_dir / "raw_qc" / module_name
    figures_dir = raw_dir / "figures"
    tables_dir = raw_dir / "tables"
    objects_dir = raw_dir / "objects"
    logs_dir = raw_dir / "logs"
    for directory in (figures_dir, tables_dir, objects_dir, logs_dir):
        directory.mkdir(parents=True, exist_ok=True)

    input_type = str(raw_cfg.get("input_type") or contract.input_types[0])
    toolchain = tuple(raw_cfg.get("toolchain") or contract.open_replacements)
    tool_checks = {tool: _tool_available(tool, config, output_dir) for tool in contract.tools}
    input_rows = _input_rows(samples, raw_cfg, input_type)
    missing_columns = [column for column in contract.required_columns if column not in input_rows.columns]
    input_table_path = tables_dir / "raw_input_contract.tsv"
    input_rows.to_csv(input_table_path, sep="\t", index=False)

    qc_table = _qc_summary(samples, input_rows, module_name, enabled, missing_columns)
    qc_table_path = tables_dir / "raw_qc_summary.tsv"
    qc_table.to_csv(qc_table_path, sep="\t", index=False)

    output_matrix, matrix_source = _write_standard_matrix(module_name, samples, raw_cfg, input_rows, input_type, objects_dir)
    output_object = _write_standard_object(module_name, samples, raw_cfg, objects_dir, output_matrix)
    command_plan = _write_command_plan(module_name, input_rows, raw_cfg, tables_dir)
    figure_paths = _write_raw_qc_figures(module_name, qc_table, figures_dir)
    skip_reasons = []
    if not enabled:
        skip_reasons.append("raw.enabled=false")
    if input_type not in contract.input_types:
        skip_reasons.append("unsupported_raw_input_type:" + input_type)
    if missing_columns:
        skip_reasons.append("missing_raw_sample_columns:" + ",".join(missing_columns))
    missing_tools = [tool for tool, ok in tool_checks.items() if not ok]
    status = "ready"
    if not enabled:
        status = "skipped"
    elif input_type not in contract.input_types:
        status = "partial:unsupported_input_type"
    elif missing_columns:
        status = "partial:sample_schema"
    elif missing_tools:
        status = "ready_with_open_replacement_or_missing_optional_tools"

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "module": module_name,
        "status": status,
        "raw_enabled": enabled,
        "input_type": input_type,
        "supported_input_types": list(contract.input_types),
        "required_columns": list(contract.required_columns),
        "missing_columns": missing_columns,
        "output_kind": contract.output_kind,
        "tool_checks": tool_checks,
        "open_replacements": list(contract.open_replacements),
        "selected_toolchain": list(toolchain),
        "licensed_policy": "licensed tools are detected only; open replacements are preferred",
        "matrix_source": matrix_source,
        "skip_reasons": skip_reasons,
        "artifacts": {
            "tables": {"raw_input_contract": str(input_table_path), "raw_qc_summary": str(qc_table_path), "external_command_plan": str(command_plan)},
            "figures": figure_paths,
            "objects": {"standard_matrix": str(output_matrix), "standard_object": str(output_object)},
        },
    }
    manifest_path = raw_dir / "raw_qc_manifest.json"
    manifest["manifest_path"] = str(manifest_path)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def _input_rows(samples: pd.DataFrame, raw_cfg: dict[str, Any], input_type: str) -> pd.DataFrame:
    if raw_cfg.get("samplesheet") and Path(raw_cfg["samplesheet"]).exists():
        rows = pd.read_csv(raw_cfg["samplesheet"], sep=None, engine="python")
        if "raw_input_type" not in rows.columns:
            rows["raw_input_type"] = input_type
        if "raw_input_exists" not in rows.columns:
            rows["raw_input_exists"] = rows.apply(_row_has_existing_input, axis=1)
        return rows
    rows = samples.copy()
    if rows.empty:
        rows = pd.DataFrame([{"sample_id": "DEMO_1", "condition": "control"}])
    rows["raw_input_type"] = input_type
    if "input_path" not in rows.columns:
        rows["input_path"] = raw_cfg.get("input_path", "")
    rows["raw_input_exists"] = rows.apply(_row_has_existing_input, axis=1)
    return rows


def _row_has_existing_input(row: pd.Series) -> bool:
    for column in PATH_COLUMNS:
        value = str(row.get(column, "") or "")
        if value and Path(value).exists():
            return True
    return False


def _qc_summary(samples: pd.DataFrame, input_rows: pd.DataFrame, module_name: str, enabled: bool, missing_columns: list[str]) -> pd.DataFrame:
    n_rows = int(input_rows.shape[0])
    n_existing = int(input_rows.get("raw_input_exists", pd.Series(dtype=bool)).fillna(False).sum())
    return pd.DataFrame(
        [
            {"metric": "raw_enabled", "value": str(enabled), "module": module_name},
            {"metric": "sample_rows", "value": n_rows, "module": module_name},
            {"metric": "existing_input_paths", "value": n_existing, "module": module_name},
            {"metric": "missing_required_columns", "value": ",".join(missing_columns) or "none", "module": module_name},
            {"metric": "conditions", "value": ",".join(sorted(map(str, samples.get("condition", pd.Series(dtype=str)).dropna().unique()))) or "unknown", "module": module_name},
        ]
    )


def _write_standard_matrix(
    module_name: str,
    samples: pd.DataFrame,
    raw_cfg: dict[str, Any],
    input_rows: pd.DataFrame,
    input_type: str,
    objects_dir: Path,
) -> tuple[Path, str]:
    configured = raw_cfg.get("output_matrix")
    if configured:
        configured_path = Path(configured)
        if configured_path.exists():
            return configured_path, "configured_existing_output_matrix"
        path = configured_path
    else:
        path = objects_dir / f"{module_name}_standard_matrix.tsv"
    existing = _existing_matrix_input(raw_cfg, input_rows, input_type)
    if existing is not None:
        frame = pd.read_csv(existing, sep=None, engine="python")
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path, sep="\t", index=False)
        return path, f"copied_existing_{input_type}:{existing}"
    sample_ids = list(samples["sample_id"].astype(str)) if "sample_id" in samples.columns else ["S1", "S2", "S3", "S4"]
    rng = np.random.default_rng(abs(hash(("raw", module_name))) % 2**32)
    values = rng.poisson(lam=80, size=(24, len(sample_ids))).astype(float)
    frame = pd.DataFrame(values, columns=sample_ids)
    frame.insert(0, "feature_id", [f"{module_name.upper()}_RAW_{idx:03d}" for idx in range(1, 25)])
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, sep="\t", index=False)
    return path, "demo_generated_standard_matrix"


def _existing_matrix_input(raw_cfg: dict[str, Any], input_rows: pd.DataFrame, input_type: str) -> Path | None:
    for key in MATRIX_INPUT_KEYS:
        value = raw_cfg.get(key)
        if value and Path(value).is_file() and _looks_tabular(Path(value)):
            return Path(value)
    if input_type not in MATRIX_LIKE_INPUT_TYPES:
        return None
    for _, row in input_rows.iterrows():
        for key in (*MATRIX_INPUT_KEYS, "input_path"):
            value = str(row.get(key, "") or "")
            if value and Path(value).is_file() and _looks_tabular(Path(value)):
                return Path(value)
    return None


def _looks_tabular(path: Path) -> bool:
    return path.suffix.lower() in {".csv", ".tsv", ".txt"} or path.name.endswith((".tsv.gz", ".csv.gz", ".txt.gz"))


def _write_standard_object(module_name: str, samples: pd.DataFrame, raw_cfg: dict[str, Any], objects_dir: Path, matrix_path: Path) -> Path:
    configured = raw_cfg.get("output_object")
    if configured:
        configured_path = Path(configured)
        if configured_path.exists():
            return configured_path
        path = configured_path
    else:
        path = objects_dir / f"{module_name}_standard_object.json"
    payload = {
        "module": module_name,
        "standard_matrix": str(matrix_path),
        "n_samples": int(samples.shape[0]),
        "note": "Raw QC handoff object placeholder; formal modality backends can replace this with h5ad/rds/RData.",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _write_raw_qc_figures(module_name: str, qc_table: pd.DataFrame, figures_dir: Path) -> dict[str, str]:
    tokens = apply_clinical_journal_style()
    counts = qc_table[qc_table["metric"].isin(["sample_rows", "existing_input_paths"])].copy()
    counts["value_numeric"] = pd.to_numeric(counts["value"], errors="coerce").fillna(0)
    plt.figure(figsize=(5.2, 3.8))
    sns.barplot(data=counts, x="metric", y="value_numeric", color=tokens["bar"])
    plt.title(f"{module_name} raw QC overview")
    plt.xlabel("")
    plt.ylabel("Count")
    plt.xticks(rotation=20, ha="right")
    plt.tight_layout()
    qc_bar = figures_dir / "raw_qc_overview.png"
    save_figure(qc_bar, style=tokens)

    return {"raw_qc_overview": str(qc_bar)}


def _write_command_plan(module_name: str, input_rows: pd.DataFrame, raw_cfg: dict[str, Any], tables_dir: Path) -> Path:
    path = tables_dir / "external_command_plan.tsv"
    rows = []
    for _, row in input_rows.iterrows():
        sample_id = str(row.get("sample_id") or row.get("cohort_id") or "sample")
        rows.append(
            {
                "sample_id": sample_id,
                "module": module_name,
                "status": "planned_not_executed_by_default",
                "command": _planned_command(module_name, row, raw_cfg),
            }
        )
    pd.DataFrame(rows).to_csv(path, sep="\t", index=False)
    return path


def _planned_command(module_name: str, row: pd.Series, raw_cfg: dict[str, Any]) -> str:
    input_type = str(row.get("raw_input_type") or row.get("input_type") or raw_cfg.get("input_type") or "")
    input_path = row.get("input_path", "<input>")
    fastq_1 = row.get("fastq_1", "<R1.fastq.gz>")
    fastq_2 = row.get("fastq_2", "<R2.fastq.gz>")
    sample_id = row.get("sample_id", "<sample_id>")
    bcl_dir = row.get("bcl_dir", input_path)
    reference = row.get("reference", raw_cfg.get("reference", "<reference>"))
    gtf = row.get("gtf", raw_cfg.get("gtf", "<genes.gtf>"))
    if module_name == "rnaseq":
        return f"fastp -i {fastq_1} -I {fastq_2} --stdout | salmon quant --libType A --mates1 {fastq_1} --mates2 {fastq_2}"
    if module_name == "scrna":
        if input_type == "bcl":
            return f"licensed adapter: bcl-convert or bcl2fastq demux {bcl_dir} to FASTQ under jobs/<job_id>/raw_links, then run nf-core/scrnaseq or STARsolo on Slurm"
        if input_type in {"fastq", "smartseq2_fastq"}:
            return f"Slurm adapter: nf-core/scrnaseq --input samplesheet.csv --genome {reference}; open fallback STARsolo/alevin-fry with {fastq_1} {fastq_2}"
        if input_type in {"bd_rhapsody_matrix", "parse_matrix", "dropseq_matrix", "seqwell_matrix", "smartseq2_matrix"}:
            return f"standardize non-10x matrix {input_path} to h5ad, then run scanpy/Seurat downstream"
        return f"read {input_type or '10x/h5ad'} input {input_path} and write standardized h5ad/RDS"
    if module_name == "scatac":
        if input_type == "fastq":
            return f"Slurm adapter: user Cell Ranger ATAC path if configured, otherwise bwa/samtools/bedtools/MACS3 to fragments and peak matrix for {sample_id}"
        return "read fragments/peak matrix or Cell Ranger ATAC output, compute QC handoff, then run Signac/SnapATAC2 backend"
    if module_name == "multiome":
        if input_type in {"fastq", "arc_output"}:
            return f"licensed adapter: Cell Ranger ARC output/FASTQ if configured; otherwise standardize RNA matrix + ATAC fragments to h5mu for {sample_id}"
        return "read multiome H5/h5mu/fragments, check RNA-ATAC barcode overlap, then export h5mu/h5ad handoff"
    if module_name == "vdj":
        if input_type == "fastq":
            return "Slurm adapter: nf-core/airrflow or MiXCR on FASTQ; Cell Ranger VDJ only when user provides licensed path"
        return "read 10x contig_annotations/clonotypes or AIRR table, then summarize clonotypes, V/J usage, sharing, and clone-state join keys"
    if module_name == "spatial":
        if input_type in {"xenium_dir", "cosmx_dir", "merscope_dir", "visium_hd_dir", "spatialdata_zarr", "sopa_project"}:
            return f"spatialdata/SOPA adapter: ingest {input_type} from {input_path}, export spatialdata/zarr plus h5ad summary"
        if input_type in {"merfish_matrix", "slideseq_matrix", "stereoseq_matrix"}:
            return f"matrix adapter: standardize {input_type} to AnnData/spatialdata with coordinate table"
        return "read Visium/Space Ranger output or spatial h5ad, then run squidpy/Seurat spatial QC"
    if module_name == "perturb_seq":
        return "read expression object plus guide_counts/guide_assignments, call guide assignment, compare perturbation groups, and score signatures/pathways"
    if module_name == "hto_demux":
        return "read hashtag/antibody capture count matrix, run HTO demultiplex, flag doublet/negative cells, and write sample composition table"
    if module_name == "genotype_demux":
        if input_type == "bam_vcf_barcode":
            return "Slurm adapter: cellsnp-lite on BAM+VCF+barcodes, then vireo; souporcell/demuxlet/popscle are optional project-level adapters"
        return "read cellsnp/vireo/souporcell/demuxlet/popscle result table and standardize demultiplex assignments"
    if module_name == "scdna":
        if input_type in {"missionbio_tapestri", "missionbio_mosaic"}:
            return "optional platform adapter: parse MissionBio/Tapestri export with user-provided format notes, then standardize variant/CNV tables"
        return "run or import BAM/FASTQ/variant/CNV QC with samtools/bcftools/cnvkit-compatible summaries"
    if module_name == "mtdna":
        if input_type in {"mgatk_output", "mitotrace_output", "mitoclone2_output"}:
            return "optional mtDNA specialty adapter: import mgatk/MitoTrace/mitoClone2 outputs and standardize heteroplasmy/depth/clone tables"
        return "run or import mtDNA BAM/variant QC; cellsnp-lite/vireo may be used when genotype-demux inputs are available"
    if module_name == "scepi":
        return "read fragments/matrix or specialty sc-epigenome output; raw scBS/scNMT/CUT&Tag/CUT&RUN FASTQ remains adapter-only"
    if module_name == "methylation":
        return "import beta matrix directly; IDAT processing uses optional methylation parser/minfi-compatible backend when configured"
    if module_name == "proteomics":
        return "import MaxQuant/Proteome Discoverer/generic abundance table and normalize to standard matrix"
    if module_name == "publicdb":
        return "download/cache public cohort expression and clinical tables, then merge by sample_id"
    if module_name == "wgcna":
        return "consume standardized expression matrix and compute module-trait correlation"
    if module_name == "single_gene":
        return "consume standardized expression matrix plus clinical table for gene-level association"
    if module_name == "clinical_assoc":
        return "consume standardized feature matrix plus clinical table for association testing"
    return "consume declared raw input and write standard matrix/object handoff"


def _tool_available(tool: str, config: dict[str, Any], output_dir: Path) -> bool:
    configured = _configured_tool_path(tool, config)
    if configured and configured.exists():
        return True
    root = _server_root_from_output(config, output_dir)
    candidates = [
        root / ".conda" / "envs" / "ultimate-core" / "bin" / tool,
        root / ".conda" / "envs" / "ultimate-rnaseq" / "bin" / tool,
        root / ".conda" / "envs" / "ultimate-methylation" / "bin" / tool,
        root / ".conda" / "envs" / "ultimate-proteomics" / "bin" / tool,
        root / ".conda" / "envs" / "ultimate-publicdb" / "bin" / tool,
        root / ".conda" / "envs" / "ultimate-wgcna" / "bin" / tool,
        root / ".conda" / "envs" / "ultimate-scrna-py" / "bin" / tool,
        root / ".conda" / "envs" / "ultimate-scrna-r" / "bin" / tool,
        root / ".conda" / "envs" / "ultimate-scatac-py" / "bin" / tool,
        root / ".conda" / "envs" / "ultimate-genome-mtdna" / "bin" / tool,
        root / ".conda" / "envs" / "ultimate-spatial-py" / "bin" / tool,
        root / ".conda" / "envs" / "ultimate-vdj" / "bin" / tool,
    ]
    return any(path.exists() for path in candidates) or shutil.which(tool) is not None


def _configured_tool_path(tool: str, config: dict[str, Any]) -> Path | None:
    resources = config.get("resources") or {}
    licensed = resources.get("licensed_tools") if isinstance(resources.get("licensed_tools"), dict) else {}
    aliases = {
        "cellranger": ("cellranger", "cellranger_vdj"),
        "cellranger-atac": ("cellranger_atac",),
        "cellranger-arc": ("cellranger_arc",),
        "spaceranger": ("spaceranger", "space_ranger"),
        "bcl-convert": ("bcl_convert",),
        "bcl2fastq": ("bcl2fastq",),
    }
    for key in aliases.get(tool, (tool.replace("-", "_"), tool)):
        value = licensed.get(key) if isinstance(licensed, dict) else None
        if value:
            return Path(str(value))
    return None


def _server_root_from_output(config: dict[str, Any], output_dir: Path) -> Path:
    configured = (config.get("project") or {}).get("server_root")
    if configured:
        return Path(configured)
    if "/shared/shen/2026/ultimate" in str(output_dir):
        return Path("/shared/shen/2026/ultimate")
    return Path.cwd() / "ultimate"
