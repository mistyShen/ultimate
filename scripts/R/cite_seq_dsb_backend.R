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

read_matrix <- function(path) {
  frame <- utils::read.table(path, sep = "\t", header = TRUE, check.names = FALSE, comment.char = "", quote = "")
  if (!"feature_id" %in% names(frame)) {
    names(frame)[[1]] <- "feature_id"
  }
  features <- make.unique(as.character(frame$feature_id))
  matrix <- as.matrix(frame[, setdiff(names(frame), "feature_id"), drop = FALSE])
  mode(matrix) <- "numeric"
  rownames(matrix) <- features
  matrix
}

write_tsv <- function(frame, path) {
  utils::write.table(frame, file = path, sep = "\t", quote = FALSE, row.names = FALSE, col.names = TRUE)
}

package_version_or_na <- function(pkg) {
  if (requireNamespace(pkg, quietly = TRUE)) {
    as.character(utils::packageVersion(pkg))
  } else {
    NA_character_
  }
}

args <- parse_args(commandArgs(trailingOnly = TRUE))
cell_path <- required_arg(args, "cell-adt")
empty_path <- required_arg(args, "empty-adt")
tables_dir <- required_arg(args, "tables-dir")
figures_dir <- required_arg(args, "figures-dir")
objects_dir <- required_arg(args, "objects-dir")
analysis_level <- if (!is.null(args[["analysis-level"]])) args[["analysis-level"]] else "smoke_backend"
source_dataset <- if (!is.null(args[["source-dataset"]])) args[["source-dataset"]] else "cite_seq"
input_artifact <- if (!is.null(args[["input-artifact"]])) args[["input-artifact"]] else ""
isotype_text <- if (!is.null(args[["isotype-controls"]])) args[["isotype-controls"]] else ""
backend_id <- "cite_seq.optional.dsb"
warning <- "DSB normalization depends on empty/background droplets and optional isotype controls; it is ADT panel correction, not whole-proteome quantification."

dir.create(tables_dir, recursive = TRUE, showWarnings = FALSE)
dir.create(figures_dir, recursive = TRUE, showWarnings = FALSE)
dir.create(objects_dir, recursive = TRUE, showWarnings = FALSE)

if (!requireNamespace("dsb", quietly = TRUE)) {
  stop("dependency_missing:dsb")
}

cell_matrix <- read_matrix(cell_path)
empty_matrix <- read_matrix(empty_path)
common <- intersect(rownames(cell_matrix), rownames(empty_matrix))
if (length(common) < 2) {
  stop("insufficient_shared_adt_features")
}
cell_matrix <- cell_matrix[common, , drop = FALSE]
empty_matrix <- empty_matrix[common, , drop = FALSE]
isotype_controls <- trimws(unlist(strsplit(isotype_text, ",", fixed = TRUE)))
isotype_controls <- isotype_controls[nzchar(isotype_controls) & isotype_controls %in% common]
use_isotype <- length(isotype_controls) > 0

suppressPackageStartupMessages(library(dsb))
result <- dsb::DSBNormalizeProtein(
  cell_protein_matrix = cell_matrix,
  empty_drop_matrix = empty_matrix,
  denoise.counts = use_isotype,
  use.isotype.control = use_isotype,
  isotype.control.name.vec = if (use_isotype) isotype_controls else NULL,
  return.stats = TRUE
)
normalized <- result$dsb_normalized_matrix
long <- data.frame(
  antibody_id = rep(rownames(normalized), times = ncol(normalized)),
  cell_id = rep(colnames(normalized), each = nrow(normalized)),
  dsb_normalized_adt = as.numeric(normalized),
  stringsAsFactors = FALSE
)
long$module <- "cite_seq"
long$backend_id <- backend_id
long$run_id <- source_dataset
long$source_dataset <- source_dataset
long$input_artifact <- input_artifact
long$analysis_level <- analysis_level
long$normalization_method <- if (use_isotype) "DSB_with_empty_droplets_and_isotype_controls" else "DSB_with_empty_droplets_no_isotype_controls"
long$interpretation_warning <- warning
long <- long[, c("module", "backend_id", "run_id", "source_dataset", "input_artifact", "cell_id", "antibody_id", "dsb_normalized_adt", "normalization_method", "analysis_level", "interpretation_warning")]
write_tsv(long, file.path(tables_dir, "dsb_normalized_matrix.tsv"))

background <- data.frame(
  module = "cite_seq",
  backend_id = backend_id,
  antibody_id = rownames(empty_matrix),
  empty_mean = rowMeans(empty_matrix),
  empty_sd = apply(empty_matrix, 1, stats::sd),
  n_empty_droplets = ncol(empty_matrix),
  analysis_level = analysis_level,
  interpretation_warning = warning,
  stringsAsFactors = FALSE
)
write_tsv(background, file.path(tables_dir, "background_summary.tsv"))

status <- data.frame(
  module = "cite_seq",
  backend_id = backend_id,
  status = "ready",
  analysis_level = analysis_level,
  n_cells = ncol(cell_matrix),
  n_empty_droplets = ncol(empty_matrix),
  n_adt_features = nrow(cell_matrix),
  use_isotype_control = use_isotype,
  isotype_controls = paste(isotype_controls, collapse = ","),
  normalization_method = if (use_isotype) "DSB_with_empty_droplets_and_isotype_controls" else "DSB_with_empty_droplets_no_isotype_controls",
  skip_reason = "",
  interpretation_warning = warning,
  stringsAsFactors = FALSE
)
write_tsv(status, file.path(tables_dir, "dsb_backend_status.tsv"))

versions <- data.frame(
  package = c("dsb", "jsonlite"),
  version = vapply(c("dsb", "jsonlite"), package_version_or_na, character(1)),
  status = c("present", ifelse(requireNamespace("jsonlite", quietly = TRUE), "present", "missing")),
  stringsAsFactors = FALSE
)
write_tsv(versions, file.path(tables_dir, "dsb_backend_versions.tsv"))

png(file.path(figures_dir, "dsb_heatmap.png"), width = 1200, height = 780, res = 160)
top_features <- head(order(rowMeans(normalized), decreasing = TRUE), min(20, nrow(normalized)))
top_cells <- seq_len(min(80, ncol(normalized)))
heatmap(
  normalized[top_features, top_cells, drop = FALSE],
  Colv = NA,
  scale = "none",
  col = grDevices::colorRampPalette(c("#3D5A80", "#F7F8FA", "#C75D59"))(101),
  main = "DSB normalized ADT"
)
dev.off()

saveRDS(list(normalized = normalized, background = background, status = status, dsb_result = result), file.path(objects_dir, "cite_seq_dsb_backend.rds"))

manifest <- list(
  backend_id = backend_id,
  status = "ready",
  analysis_level = analysis_level,
  generated_at = format(Sys.time(), "%Y-%m-%dT%H:%M:%SZ", tz = "UTC"),
  cell_adt_matrix = normalizePath(cell_path, mustWork = FALSE),
  empty_adt_matrix = normalizePath(empty_path, mustWork = FALSE),
  n_cells = ncol(cell_matrix),
  n_empty_droplets = ncol(empty_matrix),
  n_adt_features = nrow(cell_matrix),
  use_isotype_control = use_isotype,
  isotype_controls = isotype_controls,
  normalization_method = if (use_isotype) "DSB_with_empty_droplets_and_isotype_controls" else "DSB_with_empty_droplets_no_isotype_controls",
  artifacts = list(
    dsb_normalized_matrix = file.path(tables_dir, "dsb_normalized_matrix.tsv"),
    background_summary = file.path(tables_dir, "background_summary.tsv"),
    dsb_backend_status = file.path(tables_dir, "dsb_backend_status.tsv"),
    dsb_backend_versions = file.path(tables_dir, "dsb_backend_versions.tsv"),
    dsb_heatmap = file.path(figures_dir, "dsb_heatmap.png"),
    dsb_rds = file.path(objects_dir, "cite_seq_dsb_backend.rds")
  ),
  interpretation_warning = warning
)
if (requireNamespace("jsonlite", quietly = TRUE)) {
  jsonlite::write_json(manifest, file.path(tables_dir, "dsb_backend_manifest.json"), pretty = TRUE, auto_unbox = TRUE)
} else {
  writeLines("{\"backend_id\":\"cite_seq.optional.dsb\",\"status\":\"ready\"}", file.path(tables_dir, "dsb_backend_manifest.json"))
}
