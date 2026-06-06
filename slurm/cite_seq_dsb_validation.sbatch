#!/usr/bin/env bash
#SBATCH --job-name=ult_cite_dsb
#SBATCH --output=/shared/shen/2026/ultimate/logs/%x_%j.out
#SBATCH --error=/shared/shen/2026/ultimate/logs/%x_%j.err
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --time=00:50:00

set -euo pipefail

PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
PY_ENV="${ULTIMATE_SCRNA_HEAVY_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-scrna-heavy}"
R_ENV="${ULTIMATE_SCRNA_R_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-scrna-r}"
PYTHON_BIN="${PY_ENV}/bin/python"
RSCRIPT_BIN="${R_ENV}/bin/Rscript"
OUT_DIR="${ULTIMATE_CITE_SEQ_DSB_OUT:-$PROJECT_ROOT/validations/slurm_cite_seq_dsb}"
DATA_DIR="$OUT_DIR/input"

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python"
fi
if [[ -d "$R_ENV/bin" ]]; then
  export PATH="$R_ENV/bin:$PATH"
fi
export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export MPLBACKEND=Agg

mkdir -p "$PROJECT_ROOT/logs" "$OUT_DIR/config" "$OUT_DIR/reports" "$DATA_DIR"

write_skip_manifest() {
  local status="$1"
  local reason="$2"
  "$PYTHON_BIN" - "$OUT_DIR" "$status" "$reason" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

out = Path(sys.argv[1])
status = sys.argv[2]
reason = sys.argv[3]
out.mkdir(parents=True, exist_ok=True)
(out / "reports").mkdir(exist_ok=True)
manifest = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "module": "cite_seq",
    "output_dir": str(out),
    "status": status,
    "analysis_level": "smoke_backend",
    "is_demo": False,
    "is_stub": True,
    "delivery_allowed": False,
    "validation_evidence_allowed": False,
    "non_delivery_reason": f"validation_not_completed:{reason}",
    "backend_id": "cite_seq.optional.dsb",
    "backend_status": "planned_fully_automatic",
    "backend_skip_reason": reason,
    "slurm_job_id": os.environ.get("SLURM_JOB_ID", ""),
    "slurm_job_name": os.environ.get("SLURM_JOB_NAME", ""),
    "slurm": {"job_id": os.environ.get("SLURM_JOB_ID", ""), "job_name": os.environ.get("SLURM_JOB_NAME", ""), "submit_dir": os.environ.get("SLURM_SUBMIT_DIR", "")},
}
(out / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
(out / "reports" / "methods.md").write_text("# CITE-seq DSB validation skipped\n\n" f"reason: {reason}\n", encoding="utf-8")
(out / "reports" / "report.html").write_text(f"<html><body><h1>CITE-seq DSB validation skipped</h1><p>{reason}</p></body></html>", encoding="utf-8")
PY
}

if [[ ! -x "$RSCRIPT_BIN" ]]; then
  write_skip_manifest "partial:dependency_required" "Rscript for ultimate-scrna-r was not found"
  exit 0
fi
if ! "$RSCRIPT_BIN" -e 'quit(status=ifelse(requireNamespace("dsb", quietly=TRUE), 0, 1))' >/dev/null 2>&1; then
  write_skip_manifest "partial:dependency_required" "R package dsb is not available in ultimate-scrna-r"
  exit 0
fi

"$RSCRIPT_BIN" - "$DATA_DIR" <<'RS'
args <- commandArgs(trailingOnly = TRUE)
out <- args[[1]]
dir.create(out, recursive = TRUE, showWarnings = FALSE)
suppressPackageStartupMessages(library(dsb))
cells <- cells_citeseq_mtx[, seq_len(min(360, ncol(cells_citeseq_mtx))), drop = FALSE]
empty <- empty_drop_citeseq_mtx[, seq_len(min(360, ncol(empty_drop_citeseq_mtx))), drop = FALSE]
write_matrix <- function(mat, path) {
  frame <- data.frame(feature_id = rownames(mat), as.data.frame(mat, check.names = FALSE), check.names = FALSE)
  utils::write.table(frame, file = path, sep = "\t", quote = FALSE, row.names = FALSE, col.names = TRUE)
}
set.seed(23)
rna <- matrix(rpois(6 * ncol(cells), lambda = 15), nrow = 6)
rownames(rna) <- c("CD3D", "MS4A1", "LYZ", "NKG7", "GNLY", "IL7R")
colnames(rna) <- colnames(cells)
write_matrix(rna, file.path(out, "rna_counts.tsv"))
write_matrix(cells, file.path(out, "adt_counts.tsv"))
write_matrix(empty, file.path(out, "empty_adt_counts.tsv"))
iso <- rownames(cells)[grepl("isotype", rownames(cells), ignore.case = TRUE)]
writeLines(paste(iso, collapse = ","), file.path(out, "isotype_controls.txt"))
RS

if [[ ! -s "$DATA_DIR/rna_counts.tsv" || ! -s "$DATA_DIR/adt_counts.tsv" || ! -s "$DATA_DIR/empty_adt_counts.tsv" ]]; then
  write_skip_manifest "partial:data_required" "Failed to prepare dsb package CITE-seq example matrices"
  exit 0
fi

ISOTYPE_CONTROLS="$(cat "$DATA_DIR/isotype_controls.txt" 2>/dev/null || true)"
cat > "$OUT_DIR/config/project.yaml" <<YAML
project:
  name: slurm_cite_seq_dsb
  organism: human
  output_dir: $OUT_DIR
  server_root: $PROJECT_ROOT
  run_mode: interactive
  overwrite: true
samples:
  items:
    - sample_id: dsb_package_cells
      condition: public_validation
      input_path: $DATA_DIR/adt_counts.tsv
design:
  condition_column: condition
  control: public_validation
  case: public_validation
modules:
  cite_seq:
    enabled: true
    preset: standard
    analysis_level: validated_backend
    public_dataset: true
    validation_dataset: dsb_package_citeseq_example
    max_cells_object: 500
    backends:
      normalization: dsb
    dsb:
      enabled: true
      empty_adt_matrix: $DATA_DIR/empty_adt_counts.tsv
      isotype_controls: [$ISOTYPE_CONTROLS]
    raw:
      enabled: false
      input_type: rna_adt_matrix
      count_matrix: $DATA_DIR/rna_counts.tsv
      adt_counts: $DATA_DIR/adt_counts.tsv
report:
  title: CITE-seq DSB backend validation
  style: soft_color
YAML

"$PYTHON_BIN" -m ultimate.cli preflight --config "$OUT_DIR/config/project.yaml" > "$OUT_DIR/preflight_stdout.json"
"$PYTHON_BIN" -m ultimate.cli run --config "$OUT_DIR/config/project.yaml" > "$OUT_DIR/run_stdout.json"
