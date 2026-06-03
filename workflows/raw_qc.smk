import json
from pathlib import Path

PROJECT = config.get("project", {})
MODULES = [name for name, cfg in (config.get("modules") or {}).items() if cfg.get("enabled", False)]
OUTDIR = Path(PROJECT.get("output_dir", "runs/ultimate_project"))


rule all:
    input:
        expand(str(OUTDIR / "raw_qc" / "{module}" / "raw_qc_manifest.json"), module=MODULES)


rule raw_qc_contract:
    output:
        str(OUTDIR / "raw_qc" / "{module}" / "raw_qc_manifest.json")
    run:
        module = wildcards.module
        module_cfg = (config.get("modules") or {}).get(module, {})
        raw_cfg = module_cfg.get("raw") or {}
        target = Path(output[0])
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "module": module,
            "status": "contract_ready",
            "raw": raw_cfg,
            "note": "This skeleton records raw input/QC handoff. Formal execution is delegated to ultimate run and module-specific rules.",
        }
        target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


rule rnaseq_raw_qc:
    input:
        samplesheet=lambda wc: (config["modules"]["rnaseq"]["raw"] or {}).get("samplesheet", "")
    output:
        matrix=str(OUTDIR / "raw_qc" / "rnaseq" / "objects" / "rnaseq_counts.tsv")
    params:
        tools="FastQC, MultiQC, fastp, STAR/HISAT2, featureCounts/Salmon"
    shell:
        "mkdir -p $(dirname {output.matrix}) && printf 'feature_id\\tS1\\nGENE_DEMO\\t1\\n' > {output.matrix}"


rule scrna_raw_qc:
    output:
        object=str(OUTDIR / "raw_qc" / "scrna" / "objects" / "scrna_object.h5ad")
    params:
        tools="10x H5/MTX/h5ad reader, non-10x matrix standardization, BCL/FASTQ adapter, STARsolo/alevin-fry fallback, scanpy/Seurat"
    shell:
        "mkdir -p $(dirname {output.object}) && printf 'placeholder h5ad handoff\\n' > {output.object}"


rule atac_multiome_raw_qc:
    output:
        object=str(OUTDIR / "raw_qc" / "{module}" / "objects" / "{module}_object.h5ad")
    wildcard_constraints:
        module="scatac|multiome"
    params:
        tools="Cell Ranger ATAC/ARC output adapter, MACS3, bedtools, samtools, Signac, snapatac2, muon"
    shell:
        "mkdir -p $(dirname {output.object}) && printf 'placeholder ATAC/Multiome handoff\\n' > {output.object}"


rule methylation_raw_qc:
    output:
        matrix=str(OUTDIR / "raw_qc" / "methylation" / "objects" / "beta_matrix.tsv")
    params:
        tools="minfi/ChAMP/limma for IDAT or beta matrix QC"
    shell:
        "mkdir -p $(dirname {output.matrix}) && printf 'probe_id\\tS1\\ncg00000029\\t0.5\\n' > {output.matrix}"


rule tabular_raw_qc:
    output:
        matrix=str(OUTDIR / "raw_qc" / "{module}" / "objects" / "{module}_standard_matrix.tsv")
    wildcard_constraints:
        module="proteomics|publicdb|wgcna|single_gene|vdj|scdna|mtdna|scepi|cite_seq|spatial|perturb_seq|hto_demux|genotype_demux|functional_state|tumor_sc|clinical_assoc|method_tools"
    shell:
        "mkdir -p $(dirname {output.matrix}) && printf 'feature_id\\tS1\\nFEATURE_DEMO\\t1\\n' > {output.matrix}"
