# Ultimate raw QC workflows

This directory contains Snakemake skeleton rules for the first raw-data handoff layer.
The production entry point remains:

```bash
ultimate run --config config/project.yaml
```

The rules document the intended raw paths and toolchains for each modality:

- RNA-seq: FastQC/MultiQC, fastp, STAR/HISAT2, featureCounts/Salmon.
- scRNA-seq: 10x H5/MTX, STARsolo/alevin-fry fallback, scanpy/Seurat handoff.
- scATAC/Multiome: fragments or peak matrix, MACS3, bedtools/samtools, Signac/snapatac2/muon.
- Methylation: IDAT or beta matrix, minfi/ChAMP/limma.
- Proteomics/metabolomics/public cohorts and other modules: tabular QC contract and standard matrix/object handoff.

Licensed tools such as Cell Ranger, Space Ranger, and CIBERSORT are detected by path when users provide them; they are not installed automatically.
