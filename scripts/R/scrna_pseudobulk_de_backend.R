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

safe_mkdir <- function(path) {
  if (!dir.exists(path)) {
    dir.create(path, recursive = TRUE, showWarnings = FALSE)
  }
}

write_tsv <- function(x, path) {
  utils::write.table(x, file = path, sep = "\t", quote = FALSE, row.names = FALSE, col.names = TRUE)
}

package_version_or_na <- function(pkg) {
  if (requireNamespace(pkg, quietly = TRUE)) {
    as.character(utils::packageVersion(pkg))
  } else {
    NA_character_
  }
}

run_deseq2 <- function(counts, design, condition_column, control, case) {
  suppressPackageStartupMessages(library(DESeq2))
  condition <- factor(as.character(design[[condition_column]]), levels = c(control, case))
  coldata <- data.frame(row.names = design$pseudobulk_id, condition = condition)
  dds <- DESeqDataSetFromMatrix(countData = round(counts), colData = coldata, design = ~ condition)
  keep <- rowSums(counts(dds)) >= 10
  dds <- dds[keep, ]
  if (nrow(dds) < 2) {
    stop("too_few_features_after_filter")
  }
  dds <- DESeq(dds, quiet = TRUE)
  res <- as.data.frame(results(dds, contrast = c("condition", case, control)))
  res$feature_id <- rownames(res)
  res <- res[, c("feature_id", setdiff(colnames(res), "feature_id"))]
  list(method = "DESeq2", results = res, object = dds)
}

run_edger <- function(counts, design, condition_column, control, case) {
  suppressPackageStartupMessages(library(edgeR))
  group <- factor(as.character(design[[condition_column]]), levels = c(control, case))
  y <- DGEList(counts = round(counts), group = group)
  keep <- filterByExpr(y, group = group)
  y <- y[keep, , keep.lib.sizes = FALSE]
  if (nrow(y) < 2) {
    stop("too_few_features_after_filter")
  }
  y <- calcNormFactors(y)
  model <- model.matrix(~ group)
  y <- estimateDisp(y, model)
  fit <- glmQLFit(y, model)
  qlf <- glmQLFTest(fit, coef = 2)
  tab <- topTags(qlf, n = Inf)$table
  tab$feature_id <- rownames(tab)
  names(tab)[names(tab) == "logFC"] <- "log2FoldChange"
  names(tab)[names(tab) == "PValue"] <- "pvalue"
  names(tab)[names(tab) == "FDR"] <- "padj"
  list(method = "edgeR", results = tab[, c("feature_id", setdiff(colnames(tab), "feature_id"))], object = y)
}

plot_summary <- function(results, path) {
  png(path, width = 1100, height = 780, res = 160)
  on.exit(dev.off(), add = TRUE)
  padj <- results$padj
  padj[is.na(padj)] <- 1
  y <- -log10(pmax(padj, 1e-300))
  x <- results$log2FoldChange
  cls <- ifelse(padj < 0.05 & x > 0, "up", ifelse(padj < 0.05 & x < 0, "down", "ns"))
  colors <- c(up = "#B65F63", down = "#4E79A7", ns = "#96A0AA")
  plot(x, y, pch = 16, col = adjustcolor(colors[cls], alpha.f = 0.72), cex = 0.55,
       xlab = "log2 fold change", ylab = "-log10 adjusted p", main = "Pseudobulk DESeq2/edgeR")
  abline(v = c(-1, 1), lty = 2, col = "#7A8793")
  grid(col = "#E6E9ED")
}

args <- parse_args(commandArgs(trailingOnly = TRUE))
counts_path <- required_arg(args, "counts")
design_path <- required_arg(args, "design")
tables_dir <- required_arg(args, "tables-dir")
backend_id <- if (!is.null(args[["backend-id"]])) args[["backend-id"]] else "scrna.pseudobulk.deseq2_edger"
analysis_level <- if (!is.null(args[["analysis-level"]])) args[["analysis-level"]] else "smoke_backend"
condition_column <- if (!is.null(args[["condition-column"]])) args[["condition-column"]] else "condition"
control <- if (!is.null(args[["control"]])) args[["control"]] else "control"
case <- if (!is.null(args[["case"]])) args[["case"]] else "case"

safe_mkdir(tables_dir)
figures_dir <- normalizePath(file.path(tables_dir, "..", "figures"), mustWork = FALSE)
objects_dir <- normalizePath(file.path(tables_dir, "..", "..", "objects"), mustWork = FALSE)
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
design <- utils::read.table(design_path, sep = "\t", header = TRUE, check.names = FALSE, comment.char = "", quote = "")
required_cols <- c("pseudobulk_id", "sample_id", condition_column, "cluster")
missing_cols <- setdiff(required_cols, names(design))
if (length(missing_cols) > 0) {
  stop(sprintf("design_missing_columns:%s", paste(missing_cols, collapse = ",")))
}
design$pseudobulk_id <- as.character(design$pseudobulk_id)
design$sample_id <- as.character(design$sample_id)
design[[condition_column]] <- as.character(design[[condition_column]])
if (!control %in% unique(design[[condition_column]]) || !case %in% unique(design[[condition_column]])) {
  conditions <- sort(unique(design[[condition_column]]))
  if (length(conditions) < 2) {
    stop("need_two_conditions")
  }
  control <- conditions[[1]]
  case <- conditions[[2]]
}

versions <- data.frame(
  package = c("DESeq2", "edgeR", "limma", "jsonlite"),
  version = vapply(c("DESeq2", "edgeR", "limma", "jsonlite"), package_version_or_na, character(1)),
  stringsAsFactors = FALSE
)
write_tsv(versions, file.path(tables_dir, "pseudobulk_de_backend_versions.tsv"))
if (!requireNamespace("jsonlite", quietly = TRUE)) {
  stop("dependency_missing:jsonlite")
}

method_available <- if (requireNamespace("DESeq2", quietly = TRUE)) "DESeq2" else if (requireNamespace("edgeR", quietly = TRUE)) "edgeR" else ""
if (!nzchar(method_available)) {
  stop("dependency_missing:DESeq2_or_edgeR")
}

all_results <- list()
status_rows <- list()
objects <- list()
for (cluster in sort(unique(as.character(design$cluster)))) {
  cluster_design <- design[as.character(design$cluster) == cluster, , drop = FALSE]
  reps <- tapply(cluster_design$sample_id, cluster_design[[condition_column]], function(x) length(unique(x)))
  control_reps <- if (!is.na(reps[[control]])) reps[[control]] else 0
  case_reps <- if (!is.na(reps[[case]])) reps[[case]] else 0
  matched <- intersect(cluster_design$pseudobulk_id, colnames(counts))
  if (control_reps < 2 || case_reps < 2 || length(matched) < 4) {
    status_rows[[length(status_rows) + 1]] <- data.frame(
      backend_id = backend_id,
      cluster = cluster,
      status = "skipped",
      analysis_level = analysis_level,
      backend_method = method_available,
      comparison = paste(case, "vs", control, sep = "_"),
      n_features_tested = 0,
      n_samples = length(matched),
      control_replicates = control_reps,
      case_replicates = case_reps,
      reason = "insufficient_cluster_replicates",
      interpretation_warning = "No formal pseudobulk DE conclusion was generated for this cluster.",
      stringsAsFactors = FALSE
    )
    next
  }
  cluster_design <- cluster_design[match(matched, cluster_design$pseudobulk_id), , drop = FALSE]
  cluster_counts <- counts[, matched, drop = FALSE]
  result <- if (method_available == "DESeq2") {
    run_deseq2(cluster_counts, cluster_design, condition_column, control, case)
  } else {
    run_edger(cluster_counts, cluster_design, condition_column, control, case)
  }
  tab <- result$results
  if (!"log2FoldChange" %in% names(tab) && "logFC" %in% names(tab)) {
    names(tab)[names(tab) == "logFC"] <- "log2FoldChange"
  }
  if (!"pvalue" %in% names(tab) && "PValue" %in% names(tab)) {
    names(tab)[names(tab) == "PValue"] <- "pvalue"
  }
  if (!"padj" %in% names(tab) && "FDR" %in% names(tab)) {
    names(tab)[names(tab) == "FDR"] <- "padj"
  }
  tab$cluster <- cluster
  tab$backend_id <- backend_id
  tab$backend_method <- result$method
  tab$comparison <- paste(case, "vs", control, sep = "_")
  tab$analysis_level <- analysis_level
  tab$interpretation_warning <- "Pseudobulk DE is sample-level statistical evidence, not cell-level independent testing."
  all_results[[length(all_results) + 1]] <- tab
  status_rows[[length(status_rows) + 1]] <- data.frame(
    backend_id = backend_id,
    cluster = cluster,
    status = "ready",
    analysis_level = analysis_level,
    backend_method = result$method,
    comparison = paste(case, "vs", control, sep = "_"),
    n_features_tested = nrow(tab),
    n_samples = ncol(cluster_counts),
    control_replicates = control_reps,
    case_replicates = case_reps,
    reason = "",
    interpretation_warning = "DESeq2/edgeR results require raw counts, biological replicates, and design review.",
    stringsAsFactors = FALSE
  )
  objects[[cluster]] <- result$object
}

if (length(all_results) < 1) {
  stop("no_valid_cluster_de_results")
}
results <- do.call(rbind, all_results)
status <- do.call(rbind, status_rows)
results <- results[order(results$cluster, results$padj, results$pvalue, na.last = TRUE), , drop = FALSE]
write_tsv(results, file.path(tables_dir, "pseudobulk_de_results.tsv"))
write_tsv(status, file.path(tables_dir, "pseudobulk_de_backend_status.tsv"))
plot_summary(results, file.path(figures_dir, "pseudobulk_de_volcano.png"))
saveRDS(list(results = results, status = status, objects = objects), file.path(objects_dir, "scrna_pseudobulk_de_backend.rds"))

manifest <- list(
  backend_id = backend_id,
  status = "ready",
  analysis_level = analysis_level,
  backend_method = method_available,
  generated_at = format(Sys.time(), "%Y-%m-%dT%H:%M:%SZ", tz = "UTC"),
  counts_path = normalizePath(counts_path, mustWork = FALSE),
  design_path = normalizePath(design_path, mustWork = FALSE),
  condition_column = condition_column,
  control = control,
  case = case,
  n_clusters_ready = sum(status$status == "ready"),
  n_clusters_skipped = sum(status$status != "ready"),
  n_results = nrow(results),
  artifacts = list(
    pseudobulk_de_results = file.path(tables_dir, "pseudobulk_de_results.tsv"),
    pseudobulk_de_backend_status = file.path(tables_dir, "pseudobulk_de_backend_status.tsv"),
    pseudobulk_de_backend_versions = file.path(tables_dir, "pseudobulk_de_backend_versions.tsv"),
    pseudobulk_de_volcano = file.path(figures_dir, "pseudobulk_de_volcano.png"),
    rds = file.path(objects_dir, "scrna_pseudobulk_de_backend.rds")
  ),
  versions = as.list(stats::setNames(versions$version, versions$package)),
  interpretation_warning = "Pseudobulk DESeq2/edgeR output is a sample-level statistical result, not a cell-level or causal mechanism claim."
)
jsonlite::write_json(manifest, file.path(tables_dir, "pseudobulk_de_backend_manifest.json"), pretty = TRUE, auto_unbox = TRUE)
