#!/usr/bin/env bash
#SBATCH --job-name=ult_scrna_pbde
#SBATCH --output=/shared/shen/2026/ultimate/logs/%x_%j.out
#SBATCH --error=/shared/shen/2026/ultimate/logs/%x_%j.err
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --time=00:40:00

set -euo pipefail

PROJECT_ROOT="${ULTIMATE_ROOT:-/shared/shen/2026/ultimate}"
PYTHON_BIN="${ULTIMATE_CORE_PYTHON:-$PROJECT_ROOT/.conda/envs/ultimate-core/bin/python}"
R_ENV="${ULTIMATE_RNASEQ_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-rnaseq}"
OUT_DIR="${ULTIMATE_SCRNA_PSEUDOBULK_DE_OUT:-$PROJECT_ROOT/validations/slurm_scrna_pseudobulk_de}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python"
fi
if [[ -d "$R_ENV/bin" ]]; then
  export PATH="$R_ENV/bin:$PATH"
fi
export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

mkdir -p "$PROJECT_ROOT/logs" "$OUT_DIR/results/tables" "$OUT_DIR/results/figures" "$OUT_DIR/objects" "$OUT_DIR/reports" "$OUT_DIR/logs"

"$PYTHON_BIN" - "$OUT_DIR" <<'PY'
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ultimate.scrna_smoke import _run_pseudobulk_de_backend

out = Path(os.sys.argv[1])
tables = out / "results" / "tables"
figures = out / "results" / "figures"
objects = out / "objects"
reports = out / "reports"
for path in (tables, figures, objects, reports, out / "logs"):
    path.mkdir(parents=True, exist_ok=True)

rng = np.random.default_rng(19)
genes = [f"Gene{i:03d}" for i in range(1, 81)]
columns = []
design_rows = []
for cluster in ("0", "1"):
    for sample_id, condition in (("S1", "control"), ("S2", "control"), ("S3", "case"), ("S4", "case")):
        pseudobulk_id = f"{sample_id}__{condition}__cluster{cluster}"
        columns.append(pseudobulk_id)
        design_rows.append(
            {
                "pseudobulk_id": pseudobulk_id,
                "sample_id": sample_id,
                "condition": condition,
                "cluster": cluster,
                "n_cells": 25,
                "analysis_level": "validated_backend",
            }
        )
counts = rng.poisson(35, size=(len(genes), len(columns))).astype(int)
counts[:8, [2, 3, 6, 7]] += 70
counts[8:16, [0, 1, 4, 5]] += 55
counts_frame = pd.DataFrame(counts, columns=columns)
counts_frame.insert(0, "feature_id", genes)
counts_frame.to_csv(tables / "pseudobulk_counts.tsv", sep="\t", index=False)
pd.DataFrame(design_rows).to_csv(tables / "pseudobulk_design.tsv", sep="\t", index=False)

row, artifacts = _run_pseudobulk_de_backend(tables=tables, analysis_level="validated_backend")
status = "ready" if row.get("status") == "ready" else "partial"
manifest = {
    "run_id": "slurm_scrna_pseudobulk_de",
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "status": status,
    "analysis_level": "validated_backend" if status == "ready" else "smoke_backend",
    "is_demo": False,
    "is_stub": status != "ready",
    "delivery_allowed": False,
    "validation_evidence_allowed": status == "ready",
    "non_delivery_reason": "validation_evidence_only_not_customer_delivery" if status == "ready" else f"validation_not_completed:{row.get('skip_reason', '')}",
    "module": "scrna",
    "backend_ids": ["scrna.pseudobulk.deseq2_edger"],
    "backend_statuses": ["fully_automatic_validated_entrypoint" if status == "ready" else "planned_fully_automatic"],
    "backend_slurm_job_ids": [os.environ.get("SLURM_JOB_ID", "")],
    "slurm_job_id": os.environ.get("SLURM_JOB_ID", ""),
    "slurm_job_name": os.environ.get("SLURM_JOB_NAME", ""),
    "slurm": {
        "job_id": os.environ.get("SLURM_JOB_ID", ""),
        "job_name": os.environ.get("SLURM_JOB_NAME", ""),
        "submit_dir": os.environ.get("SLURM_SUBMIT_DIR", ""),
    },
    "modules": [
        {
            "module": "scrna",
            "status": "complete_scrna_pseudobulk_de_backend" if status == "ready" else "partial:scrna_pseudobulk_de_backend",
            "analysis_level": "validated_backend" if status == "ready" else "smoke_backend",
            "is_demo": False,
            "is_stub": status != "ready",
            "delivery_allowed": False,
            "validation_evidence_allowed": status == "ready",
            "non_delivery_reason": "validation_evidence_only_not_customer_delivery" if status == "ready" else f"validation_not_completed:{row.get('skip_reason', '')}",
            "backend_id": "scrna.pseudobulk.deseq2_edger",
            "backend_status": "fully_automatic_validated_entrypoint" if status == "ready" else "planned_fully_automatic",
            "backend_skip_reason": row.get("skip_reason", ""),
            "artifacts": {"tables": artifacts},
            "formal_backend": {
                "python_entrypoint": "ultimate.scrna_smoke._run_pseudobulk_de_backend",
                "r_entrypoint": "ultimate/scripts/R/scrna_pseudobulk_de_backend.R",
                "status": "fully_automatic_validated_entrypoint" if status == "ready" else "partial_or_skipped",
            },
            "warnings": [
                "pseudobulk DESeq2/edgeR 是样本层统计结果，不是 cell-level 独立检验。",
                "需要 raw counts、重复数和设计矩阵审核。",
            ],
        }
    ],
    "artifacts": {
        "tables": str(tables),
        "figures": str(figures),
        "objects": str(objects),
        "reports": str(reports),
    },
}
(out / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
(reports / "methods.md").write_text(
    "# scRNA pseudobulk DE validation\n\n"
    "- backend_id: `scrna.pseudobulk.deseq2_edger`\n"
    f"- status: `{status}`\n"
    "- analysis_level: `validated_backend` when ready; never customer delivery.\n"
    "- warning: pseudobulk DE uses sample-level aggregate counts and replicate-aware design.\n",
    encoding="utf-8",
)
(reports / "report.html").write_text(
    "<html><body><h1>scRNA pseudobulk DE validation</h1>"
    f"<p>status: {status}</p><p>backend: scrna.pseudobulk.deseq2_edger</p>"
    "<p>validated evidence only; not customer delivery.</p></body></html>",
    encoding="utf-8",
)
print(json.dumps({"status": status, "artifacts": artifacts}, indent=2, ensure_ascii=False))
PY
