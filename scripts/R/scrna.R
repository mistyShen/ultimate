#!/usr/bin/env Rscript

# Formal backend placeholder for scRNA-seq.
# Responsibilities:
#   Seurat QC/integration/clustering, marker discovery, SingleR/manual marker
#   annotation, UMAP/tSNE, Monocle3/PAGA-compatible exports, CellChat, and
#   optional NicheNet outputs with .rds/.RData handoff objects.
message("scrna.R backend interface is ready; install Seurat/SingleR/CellChat to enable formal execution.")
