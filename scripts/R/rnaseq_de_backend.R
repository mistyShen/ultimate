#!/usr/bin/env Rscript

parse_args <- function(argv) {
  out <- list()
  i <- 1
  while (i <= length(argv)) {
    key <- argv[[i]]
    if (!startsWith(key, "--")) {
      stop(sprintf("Unexpected argument: %s", key))
    }
    name <- sub("^--", "", key)
    if (i == length(argv) || startsWith(argv[[i + 1]], "--")) {
      out[[name]] <- TRUE
      i <- i + 1
    } else {
      out[[name]] <- argv[[i + 1]]
      i <- i + 2
    }
  }
  out
}

required_arg <- function(args, name) {
  value <- args[[name]]
  if (is.null(value) || !nzchar(value)) {
    stop(sprintf("Missing required argument --%s", name))
  }
  value
}

write_tsv <- function(x, path) {
  utils::write.table(x, file = path, sep = "\t", quote = FALSE, row.names = FALSE, col.names = TRUE)
}

safe_mkdir <- function(path) {
  if (!dir.exists(path)) {
    dir.create(path, recursive = TRUE, showWarnings = FALSE)
  }
}

package_version_or_na <- function(pkg) {
  if (requireNamespace(pkg, quietly = TRUE)) {
    as.character(utils::packageVersion(pkg))
  } else {
    NA_character_
  }
}

plot_volcano <- function(results, path) {
  png(path, width = 1100, height = 780, res = 160)
  on.exit(dev.off(), add = TRUE)
  padj <- results$padj
  padj[is.na(padj)] <- 1
  y <- -log10(pmax(padj, 1e-300))
  x <- results$log2FoldChange
  cls <- ifelse(padj < 0.05 & x > 0, "up", ifelse(padj < 0.05 & x < 0, "down", "ns"))
  colors <- c(up = "#B65F63", down = "#4E79A7", ns = "#96A0AA")
  plot(x, y, pch = 16, col = adjustcolor(colors[cls], alpha.f = 0.78), cex = 0.65,
       xlab = "log2 fold change", ylab = "-log10 adjusted p", main = "DESeq2/edgeR volcano")
  abline(v = c(-1, 1), lty = 2, col = "#7A8793")
  grid(col = "#E6E9ED")
  legend("topright", legend = c("up", "down", "ns"), col = colors[c("up", "down", "ns")], pch = 16, bty = "n")
}

plot_heatmap <- function(log_matrix, results, path) {
  top <- head(results$feature_id[order(results$padj, na.last = TRUE)], 35)
  top <- top[top %in% rownames(log_matrix)]
  if (length(top) < 2) {
    top <- head(rownames(log_matrix), min(20, nrow(log_matrix)))
  }
  mat <- as.matrix(log_matrix[top, , drop = FALSE])
  mat <- t(scale(t(mat)))
  mat[is.na(mat)] <- 0
  png(path, width = 1100, height = 900, res = 160)
  on.exit(dev.off(), add = TRUE)
  heatmap(mat, Colv = NA, scale = "none", col = colorRampPalette(c("#416C9B", "#F7F7F4", "#B65F63"))(128),
          margins = c(8, 8), main = "Top DE genes")
}

run_deseq2 <- function(counts, samples, condition_column, control, case) {
  suppressPackageStartupMessages(library(DESeq2))
  condition <- factor(samples[[condition_column]], levels = c(control, case))
  coldata <- data.frame(row.names = samples$sample_id, condition = condition)
  dds <- DESeqDataSetFromMatrix(countData = round(counts), colData = coldata, design = ~ condition)
  keep <- rowSums(counts(dds)) >= 10
  dds <- dds[keep, ]
  dds <- DESeq(dds, quiet = TRUE)
  res <- as.data.frame(results(dds, contrast = c("condition", case, control)))
  res$feature_id <- rownames(res)
  res <- res[, c("feature_id", setdiff(colnames(res), "feature_id"))]
  vsd <- vst(dds, blind = TRUE)
  list(method = "DESeq2", results = res, log_matrix = assay(vsd), object = dds)
}

run_edger <- function(counts, samples, condition_column, control, case) {
  suppressPackageStartupMessages(library(edgeR))
  group <- factor(samples[[condition_column]], levels = c(control, case))
  y <- DGEList(counts = round(counts), group = group)
  keep <- filterByExpr(y, group = group)
  y <- y[keep, , keep.lib.sizes = FALSE]
  y <- calcNormFactors(y)
  design <- model.matrix(~ group)
  y <- estimateDisp(y, design)
  fit <- glmQLFit(y, design)
  qlf <- glmQLFTest(fit, coef = 2)
  tab <- topTags(qlf, n = Inf)$table
  tab$feature_id <- rownames(tab)
  names(tab)[names(tab) == "logFC"] <- "log2FoldChange"
  names(tab)[names(tab) == "PValue"] <- "pvalue"
  names(tab)[names(tab) == "FDR"] <- "padj"
  log_matrix <- cpm(y, log = TRUE, prior.count = 1)
  list(method = "edgeR", results = tab[, c("feature_id", setdiff(colnames(tab), "feature_id"))], log_matrix = log_matrix, object = y)
}

args <- parse_args(commandArgs(trailingOnly = TRUE))
counts_path <- required_arg(args, "counts")
samples_path <- required_arg(args, "samples")
tables_dir <- required_arg(args, "tables-dir")
figures_dir <- required_arg(args, "figures-dir")
objects_dir <- required_arg(args, "objects-dir")
condition_column <- if (!is.null(args[["condition-column"]])) args[["condition-column"]] else "condition"
control <- if (!is.null(args[["control"]])) args[["control"]] else "control"
case <- if (!is.null(args[["case"]])) args[["case"]] else "treated"
backend_id <- if (!is.null(args[["backend-id"]])) args[["backend-id"]] else "rnaseq.de.deseq2_edger"
analysis_level <- if (!is.null(args[["analysis-level"]])) args[["analysis-level"]] else "smoke_backend"

safe_mkdir(tables_dir)
safe_mkdir(figures_dir)
safe_mkdir(objects_dir)

counts_frame <- utils::read.table(counts_path, sep = "\t", header = TRUE, check.names = FALSE, comment.char = "", quote = "")
if (!"feature_id" %in% names(counts_frame)) {
  names(counts_frame)[[1]] <- "feature_id"
}
feature_id <- make.unique(as.character(counts_frame$feature_id))
counts <- as.matrix(counts_frame[, setdiff(names(counts_frame), "feature_id"), drop = FALSE])
mode(counts) <- "numeric"
rownames(counts) <- feature_id
samples <- utils::read.table(samples_path, sep = "\t", header = TRUE, check.names = FALSE, comment.char = "", quote = "")
if (!"sample_id" %in% names(samples)) {
  stop("samplesheet_missing_column:sample_id")
}
if (!condition_column %in% names(samples)) {
  stop(sprintf("samplesheet_missing_column:%s", condition_column))
}
samples$sample_id <- as.character(samples$sample_id)
matched <- intersect(samples$sample_id, colnames(counts))
if (length(matched) < 4) {
  stop(sprintf("too_few_matched_samples:%s", length(matched)))
}
samples <- samples[match(matched, samples$sample_id), , drop = FALSE]
counts <- counts[, matched, drop = FALSE]
groups <- table(as.character(samples[[condition_column]]))
if (is.na(groups[[control]]) || groups[[control]] < 2 || is.na(groups[[case]]) || groups[[case]] < 2) {
  stop(sprintf("insufficient_biological_replicates:%s=%s,%s=%s", control, groups[[control]], case, groups[[case]]))
}

backend <- NULL
method <- NA_character_
if (requireNamespace("DESeq2", quietly = TRUE)) {
  backend <- run_deseq2(counts, samples, condition_column, control, case)
  method <- backend$method
} else if (requireNamespace("edgeR", quietly = TRUE)) {
  backend <- run_edger(counts, samples, condition_column, control, case)
  method <- backend$method
} else {
  stop("dependency_missing:DESeq2_or_edgeR")
}

results <- backend$results
if (!"log2FoldChange" %in% names(results) && "logFC" %in% names(results)) {
  names(results)[names(results) == "logFC"] <- "log2FoldChange"
}
if (!"pvalue" %in% names(results) && "PValue" %in% names(results)) {
  names(results)[names(results) == "PValue"] <- "pvalue"
}
if (!"padj" %in% names(results) && "FDR" %in% names(results)) {
  names(results)[names(results) == "FDR"] <- "padj"
}
results$backend_id <- backend_id
results$backend_method <- method
results$comparison <- paste(case, "vs", control, sep = "_")
results$analysis_level <- analysis_level
results$interpretation_warning <- "DE result is statistical evidence from raw counts and replicate-aware design; it is not mechanism proof."
results <- results[order(results$padj, results$pvalue, na.last = TRUE), , drop = FALSE]

de_results <- file.path(tables_dir, "de_results.tsv")
backend_results <- file.path(tables_dir, "deseq2_edgeR_de_results.tsv")
write_tsv(results, de_results)
write_tsv(results, backend_results)
plot_volcano(results, file.path(figures_dir, "deseq2_edgeR_volcano.png"))
plot_heatmap(backend$log_matrix, results, file.path(figures_dir, "deseq2_edgeR_top_gene_heatmap.png"))
saveRDS(list(results = results, samples = samples, method = method, object = backend$object), file.path(objects_dir, "rnaseq_de_backend.rds"))

versions <- data.frame(
  package = c("DESeq2", "edgeR", "limma", "ggplot2", "jsonlite"),
  version = vapply(c("DESeq2", "edgeR", "limma", "ggplot2", "jsonlite"), package_version_or_na, character(1)),
  stringsAsFactors = FALSE
)
write_tsv(versions, file.path(tables_dir, "de_backend_versions.tsv"))

status <- data.frame(
  backend_id = backend_id,
  status = "ready",
  analysis_level = analysis_level,
  backend_method = method,
  comparison = paste(case, "vs", control, sep = "_"),
  n_features_tested = nrow(results),
  n_samples = ncol(counts),
  control_replicates = unname(groups[[control]]),
  case_replicates = unname(groups[[case]]),
  interpretation_warning = "DESeq2/edgeR results require raw counts, biological replicates, and design review.",
  stringsAsFactors = FALSE
)
write_tsv(status, file.path(tables_dir, "de_backend_status.tsv"))

manifest <- list(
  backend_id = backend_id,
  status = "ready",
  analysis_level = analysis_level,
  backend_method = method,
  generated_at = format(Sys.time(), "%Y-%m-%dT%H:%M:%SZ", tz = "UTC"),
  counts_path = normalizePath(counts_path, mustWork = FALSE),
  samplesheet_path = normalizePath(samples_path, mustWork = FALSE),
  condition_column = condition_column,
  control = control,
  case = case,
  n_features_tested = nrow(results),
  n_samples = ncol(counts),
  artifacts = list(
    de_results = de_results,
    deseq2_edgeR_de_results = backend_results,
    de_backend_status = file.path(tables_dir, "de_backend_status.tsv"),
    de_backend_versions = file.path(tables_dir, "de_backend_versions.tsv"),
    volcano = file.path(figures_dir, "deseq2_edgeR_volcano.png"),
    top_gene_heatmap = file.path(figures_dir, "deseq2_edgeR_top_gene_heatmap.png"),
    rds = file.path(objects_dir, "rnaseq_de_backend.rds")
  ),
  versions = as.list(stats::setNames(versions$version, versions$package)),
  interpretation_warning = "DESeq2/edgeR output is a statistical differential-expression result, not a direct mechanism claim."
)
jsonlite::write_json(manifest, file.path(tables_dir, "de_backend_manifest.json"), pretty = TRUE, auto_unbox = TRUE)
