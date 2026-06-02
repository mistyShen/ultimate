#!/usr/bin/env Rscript

# Formal backend placeholder for RNA-seq.
# Expected arguments:
#   Rscript scripts/R/rnaseq.R <config.yaml> <run_dir>
# Responsibilities:
#   FastQC/MultiQC logs, count matrix import, DESeq2/edgeR differential testing,
#   PCA, heatmap, volcano, GO/KEGG, GSEA, optional time-course analysis,
#   and native .rds/.RData object export.
message("rnaseq.R backend interface is ready; install DESeq2/edgeR/clusterProfiler to enable formal execution.")
