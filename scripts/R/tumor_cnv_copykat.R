#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)

value_after <- function(flag, default = NULL) {
  idx <- match(flag, args)
  if (is.na(idx) || idx == length(args)) {
    return(default)
  }
  args[[idx + 1]]
}

counts_path <- value_after("--counts")
output_dir <- value_after("--output-dir")
sample_name <- value_after("--sample-name", "ultimate_copykat")
ncores <- as.integer(value_after("--ncores", "1"))

if (is.null(counts_path) || is.null(output_dir)) {
  stop("Usage: tumor_cnv_copykat.R --counts counts.tsv.gz --output-dir out --sample-name name --ncores 1")
}

dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)

write_json <- function(path, fields) {
  escape <- function(value) {
    value <- gsub("\\\\", "\\\\\\\\", as.character(value))
    gsub('"', '\\"', value)
  }
  lines <- c("{")
  names <- names(fields)
  for (i in seq_along(fields)) {
    value <- fields[[i]]
    text <- if (is.logical(value)) {
      if (isTRUE(value)) "true" else "false"
    } else if (is.numeric(value) && length(value) == 1 && !is.na(value)) {
      as.character(value)
    } else {
      paste0('"', escape(value), '"')
    }
    comma <- if (i < length(fields)) "," else ""
    lines <- c(lines, paste0('  "', names[[i]], '": ', text, comma))
  }
  lines <- c(lines, "}")
  writeLines(lines, path)
}

manifest_path <- file.path(output_dir, "copykat_backend_manifest.json")

tryCatch(
  {
    if (!requireNamespace("copykat", quietly = TRUE)) {
      stop("copykat package is not available")
    }
    suppressPackageStartupMessages(library(copykat))
    counts <- read.delim(counts_path, check.names = FALSE, stringsAsFactors = FALSE)
    if (ncol(counts) < 3 || !("gene" %in% colnames(counts))) {
      stop("counts table must contain gene plus at least two cell columns")
    }
    genes <- counts$gene
    mat <- as.matrix(counts[, setdiff(colnames(counts), "gene"), drop = FALSE])
    storage.mode(mat) <- "numeric"
    rownames(mat) <- make.unique(as.character(genes))
    mat <- mat[rowSums(mat) > 0, , drop = FALSE]
    if (nrow(mat) < 200 || ncol(mat) < 20) {
      stop(sprintf("CopyKAT input too small after filtering: %s genes x %s cells", nrow(mat), ncol(mat)))
    }

    old_wd <- setwd(output_dir)
    on.exit(setwd(old_wd), add = TRUE)
    result <- copykat(
      rawmat = mat,
      id.type = "S",
      cell.line = "no",
      ngene.chr = 5,
      min.gene.per.cell = 50,
      LOW.DR = 0.05,
      UP.DR = 0.1,
      win.size = 25,
      norm.cell.names = "",
      KS.cut = 0.1,
      sam.name = sample_name,
      distance = "euclidean",
      output.seg = "FALSE",
      plot.genes = "FALSE",
      genome = "hg20",
      n.cores = ncores
    )

    prediction <- result$prediction
    if (is.null(prediction) || nrow(as.data.frame(prediction)) == 0) {
      stop("CopyKAT returned no prediction table")
    }
    prediction <- as.data.frame(prediction)
    write.table(prediction, file.path(output_dir, "copykat_predictions.tsv"), sep = "\t", quote = FALSE, row.names = FALSE)

    if (!is.null(result$CNAmat)) {
      preview <- as.data.frame(result$CNAmat[seq_len(min(nrow(result$CNAmat), 500)), seq_len(min(ncol(result$CNAmat), 500)), drop = FALSE])
      write.table(preview, file.path(output_dir, "copykat_cna_preview.tsv"), sep = "\t", quote = FALSE, col.names = NA)
    }

    versions <- data.frame(
      tool = c("copykat", "R"),
      version = c(as.character(utils::packageVersion("copykat")), as.character(getRversion())),
      stringsAsFactors = FALSE
    )
    write.table(versions, file.path(output_dir, "copykat_versions.tsv"), sep = "\t", quote = FALSE, row.names = FALSE)
    write_json(
      manifest_path,
      list(
        status = "ready",
        tool = "CopyKAT",
        package_version = as.character(utils::packageVersion("copykat")),
        n_input_genes = nrow(mat),
        n_input_cells = ncol(mat),
        sample_name = sample_name,
        interpretation_warning = "transcriptome_inferred_CNV_not_DNA_level_CNV"
      )
    )
  },
  error = function(e) {
    write_json(
      manifest_path,
      list(
        status = "failed",
        tool = "CopyKAT",
        error = conditionMessage(e),
        interpretation_warning = "transcriptome_inferred_CNV_not_DNA_level_CNV"
      )
    )
    stop(e)
  }
)
