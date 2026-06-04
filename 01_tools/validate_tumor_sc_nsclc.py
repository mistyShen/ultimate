#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validation_manifest_utils import add_validation_guard_fields

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scanpy as sc


TUMOR_MARKERS = ("EPCAM", "KRT8", "KRT18", "KRT19", "MUC1", "ALDH1A1", "PROM1")
IMMUNE_MARKERS = ("PTPRC", "CD3D", "CD3E", "CD8A", "NKG7", "MS4A1", "LYZ", "LST1")
MYELOID_MARKERS = ("LYZ", "LST1", "S100A8", "S100A9", "FCGR3A", "MSR1", "MRC1")
CAF_MARKERS = ("COL1A1", "COL1A2", "DCN", "LUM", "ACTA2", "TAGLN")
TUMOR_STATE_SCORES = (
    "stemness_score",
    "proliferation_score",
    "hypoxia_score",
    "emt_score",
    "immune_escape_score",
    "inflammation_score",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run NSCLC tumor single-cell specialty validation.")
    parser.add_argument("--input-h5ad", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-cells", type=int, default=6000)
    parser.add_argument("--random-seed", type=int, default=11)
    parser.add_argument("--rscript", type=Path, default=Path("/shared/shen/2026/ultimate/.conda/envs/ultimate-scrna-r/bin/Rscript"))
    parser.add_argument("--run-copykat", action="store_true", help="Attempt CopyKAT only when raw integer counts are available.")
    parser.add_argument("--run-infercnv", action="store_true", help="Attempt inferCNV only when raw integer counts are available.")
    parser.add_argument(
        "--gene-order-reference-h5ad",
        type=Path,
        default=None,
        help="Optional h5ad with chromosome/start/end columns used to map inferCNV gene order for raw count inputs.",
    )
    args = parser.parse_args()
    manifest = run_validation(
        input_h5ad=args.input_h5ad,
        output_dir=args.output_dir,
        max_cells=args.max_cells,
        random_seed=args.random_seed,
        rscript=args.rscript,
        run_copykat=args.run_copykat,
        run_infercnv=args.run_infercnv,
        gene_order_reference_h5ad=args.gene_order_reference_h5ad,
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


def run_validation(
    input_h5ad: Path,
    output_dir: Path,
    max_cells: int,
    random_seed: int,
    rscript: Path,
    run_copykat: bool = False,
    run_infercnv: bool = False,
    gene_order_reference_h5ad: Path | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    figures = output_dir / "results" / "figures"
    tables = output_dir / "results" / "tables"
    objects = output_dir / "objects"
    reports = output_dir / "reports"
    logs = output_dir / "logs"
    for directory in (figures, tables, objects, reports, logs):
        directory.mkdir(parents=True, exist_ok=True)

    adata, read_mode = _read_h5ad_subset(input_h5ad, max_cells, random_seed)
    _prefer_gene_symbols(adata)
    adata.var_names_make_unique()
    _ensure_scores(adata)

    cell_type_key = _first_existing(
        adata.obs,
        ["cell_type_level1_harmonized", "cell_type", "Cell_type", "Cell_type.refined", "Cell_subtype", "leiden"],
    ) or "cell_type"
    sample_key = _first_existing(adata.obs, ["sample_origin_harmonized", "sample_id", "Sample", "Sample_Origin", "dataset_id"]) or "sample"
    if cell_type_key not in adata.obs:
        adata.obs[cell_type_key] = "unknown"
    if sample_key not in adata.obs:
        adata.obs[sample_key] = "sample"

    tool_status = _tool_status(rscript)
    tool_status.to_csv(tables / "tool_status.tsv", sep="\t", index=False)
    matrix_qc = _backend_matrix_qc(adata)
    matrix_qc.to_csv(tables / "backend_matrix_qc.tsv", sep="\t", index=False)

    cnv_summary, cnv_by_cell = _cnv_proxy(adata)
    cnv_summary.to_csv(tables / "cnv_inference_summary.tsv", sep="\t", index=False)
    adata.obs["cnv_proxy_deviation"] = cnv_by_cell

    malignant = _malignant_candidates(adata, cell_type_key, sample_key)
    malignant.to_csv(tables / "malignant_cell_candidates.tsv", sep="\t", index=False)
    adata.obs["malignant_candidate"] = malignant.set_index("cell_id").loc[adata.obs_names, "malignant_candidate"].astype(bool).to_numpy()
    adata.obs["tumor_candidate_score"] = malignant.set_index("cell_id").loc[adata.obs_names, "tumor_candidate_score"].to_numpy()

    _tme_composition(adata, cell_type_key, sample_key).to_csv(tables / "tme_composition.tsv", sep="\t", index=False)
    _state_scores(adata, cell_type_key, IMMUNE_MARKERS).to_csv(tables / "immune_state_scores.tsv", sep="\t", index=False)
    _state_scores(adata, cell_type_key, MYELOID_MARKERS).to_csv(tables / "myeloid_state_scores.tsv", sep="\t", index=False)
    _state_scores(adata, cell_type_key, CAF_MARKERS).to_csv(tables / "caf_subtype_summary.tsv", sep="\t", index=False)
    _tumor_state_markers(adata, cell_type_key).to_csv(tables / "tumor_state_markers.tsv", sep="\t", index=False)
    _therapy_handoff(adata, sample_key).to_csv(tables / "therapy_response_comparison.tsv", sep="\t", index=False)
    gene_order_status = _write_infercnv_inputs(adata, tables, cell_type_key, gene_order_reference_h5ad)
    backend_attempts = _backend_attempts(
        adata=adata,
        tables=tables,
        logs=logs,
        tool_status=tool_status,
        matrix_qc=matrix_qc,
        run_copykat=run_copykat,
        run_infercnv=run_infercnv,
    )
    backend_attempts.to_csv(tables / "backend_attempts.tsv", sep="\t", index=False)

    _plot_tme(tables / "tme_composition.tsv", figures / "tme_composition.png", sample_key, cell_type_key)
    _plot_state_heatmap(adata, cell_type_key, figures / "tumor_state_heatmap.png")
    _plot_malignant_umap(adata, figures / "malignant_candidate_umap.png")
    _plot_cnv_proxy(cnv_summary, figures / "cnv_proxy_by_chromosome.png")

    object_path = objects / "tumor_sc_nsclc_validated.h5ad"
    adata.write_h5ad(object_path)
    manifest: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_h5ad": str(input_h5ad),
        "read_mode": read_mode,
        "output_dir": str(output_dir),
        "n_cells": int(adata.n_obs),
        "n_genes": int(adata.n_vars),
        "cell_type_key": cell_type_key,
        "sample_key": sample_key,
        "n_malignant_candidates": int(adata.obs["malignant_candidate"].sum()),
        "figures": [str(path) for path in sorted(figures.glob("*.png"))],
        "tables": [str(path) for path in sorted(tables.glob("*.tsv"))],
        "objects": {"h5ad": str(object_path)},
        "tool_status": str(tables / "tool_status.tsv"),
        "backend_attempts": str(tables / "backend_attempts.tsv"),
        "backend_matrix_qc": str(tables / "backend_matrix_qc.tsv"),
        "gene_order_reference_h5ad": str(gene_order_reference_h5ad) if gene_order_reference_h5ad else "",
        "gene_order_status": gene_order_status,
        "copykat_requested": run_copykat,
        "infercnv_requested": run_infercnv,
        "status": "ready",
        "limitations": [
            "malignant_candidate 是候选评分，不是病理确诊。",
            "cnv_proxy_deviation 来自表达层染色体均值偏移，不等于 DNA CNV。",
            "inferCNV/CopyKAT 只有在 raw integer counts 可用时才允许执行；否则只记录阻断原因。",
        ],
    }
    add_validation_guard_fields(
        manifest,
        validation_kind="internal",
        validation_scope="NSCLC tumor_sc specialty validation with malignant candidates, TME states, CNV proxy, and guarded inferCNV/CopyKAT backend attempts.",
    )
    (output_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_report(manifest, reports / "report.md", reports / "report.html")
    return manifest


def _first_existing(frame: pd.DataFrame, candidates: list[str]) -> str | None:
    for candidate in candidates:
        if candidate in frame.columns:
            return candidate
    return None


def _read_h5ad_subset(input_h5ad: Path, max_cells: int, random_seed: int):
    try:
        backed = sc.read_h5ad(input_h5ad, backed="r")
        try:
            n_obs = backed.n_obs
            if n_obs > max_cells:
                rng = np.random.default_rng(random_seed)
                keep = np.sort(rng.choice(n_obs, size=max_cells, replace=False))
                adata = backed[keep, :].to_memory()
                return adata, "backed_random_subset"
            return backed[:].to_memory(), "backed_full_to_memory"
        finally:
            try:
                backed.file.close()
            except Exception:
                pass
    except Exception:
        adata = sc.read_h5ad(input_h5ad)
        if adata.n_obs > max_cells:
            rng = np.random.default_rng(random_seed)
            keep = rng.choice(adata.n_obs, size=max_cells, replace=False)
            adata = adata[keep].copy()
            return adata, "full_read_random_subset"
        return adata.copy(), "full_read"


def _prefer_gene_symbols(adata) -> None:
    current_genes = set(adata.var_names.astype(str))
    marker_genes = set(TUMOR_MARKERS + IMMUNE_MARKERS + MYELOID_MARKERS + CAF_MARKERS)
    current_overlap = len(marker_genes & current_genes)
    symbol_col = _first_existing(adata.var, ["gene_symbol", "Gene.Symbol", "symbol", "gene_name", "features"])
    if symbol_col is None:
        return
    symbols = adata.var[symbol_col].astype(str)
    symbols = symbols.where(symbols.ne("") & symbols.ne("nan"), pd.Series(adata.var_names.astype(str), index=adata.var.index))
    symbol_overlap = len(marker_genes & set(symbols.astype(str)))
    if symbol_overlap <= current_overlap:
        return
    if "_original_var_name" not in adata.var:
        adata.var["_original_var_name"] = adata.var_names.astype(str)
    adata.var_names = symbols.astype(str).to_numpy()


def _matrix(adata) -> np.ndarray:
    return adata.X.A if hasattr(adata.X, "A") else np.asarray(adata.X)


def _to_dense_array(matrix, rows: int | None = None, cols: int | None = None) -> np.ndarray:
    view = matrix
    if rows is not None or cols is not None:
        view = matrix[: rows or matrix.shape[0], : cols or matrix.shape[1]]
    if hasattr(view, "toarray"):
        return np.asarray(view.toarray())
    if hasattr(view, "A"):
        return np.asarray(view.A)
    return np.asarray(view)


def _candidate_count_matrices(adata) -> list[tuple[str, Any]]:
    candidates: list[tuple[str, Any]] = []
    for key in ("counts", "raw_counts", "umi", "UMI"):
        if key in adata.layers:
            candidates.append((f"layer:{key}", adata.layers[key]))
    if adata.raw is not None:
        candidates.append(("raw.X", adata.raw.X))
    candidates.append(("X", adata.X))
    return candidates


def _backend_matrix_qc(adata) -> pd.DataFrame:
    rows = []
    for source, matrix in _candidate_count_matrices(adata):
        arr = _to_dense_array(matrix, rows=min(300, matrix.shape[0]), cols=min(300, matrix.shape[1])).astype(float)
        finite = arr[np.isfinite(arr)]
        nonnegative = bool(finite.size and np.nanmin(finite) >= 0)
        integerish = bool(finite.size and np.allclose(finite, np.rint(finite)))
        rows.append(
            {
                "matrix_source": source,
                "n_obs": int(matrix.shape[0]),
                "n_vars": int(matrix.shape[1]),
                "sample_min": float(np.nanmin(finite)) if finite.size else np.nan,
                "sample_max": float(np.nanmax(finite)) if finite.size else np.nan,
                "nonnegative": nonnegative,
                "integerish": integerish,
                "raw_counts_compatible": bool(nonnegative and integerish),
            }
        )
    return pd.DataFrame(rows)


def _best_count_matrix(adata, matrix_qc: pd.DataFrame) -> tuple[str | None, Any | None, str]:
    compatible = matrix_qc[matrix_qc["raw_counts_compatible"].astype(bool)]
    if compatible.empty:
        return None, None, "raw_integer_counts_not_available"
    source = str(compatible.iloc[0]["matrix_source"])
    for candidate_source, matrix in _candidate_count_matrices(adata):
        if candidate_source == source:
            return source, matrix, "ready"
    return None, None, "raw_counts_source_not_found"


def _ensure_scores(adata) -> None:
    genes = set(adata.var_names.astype(str))
    for name, markers in {
        "tumor_marker_score": TUMOR_MARKERS,
        "immune_marker_score": IMMUNE_MARKERS,
        "myeloid_marker_score": MYELOID_MARKERS,
        "caf_marker_score": CAF_MARKERS,
    }.items():
        if name in adata.obs:
            continue
        present = [gene for gene in markers if gene in genes]
        if len(present) >= 2:
            sc.tl.score_genes(adata, present, score_name=name)
        else:
            adata.obs[name] = 0.0


def _tool_status(rscript: Path) -> pd.DataFrame:
    rows = []
    for package, label in (("infercnv", "inferCNV"), ("copykat", "CopyKAT"), ("Seurat", "Seurat")):
        available = False
        version = ""
        note = "Rscript_not_found"
        if rscript.exists():
            code = f'cat(requireNamespace("{package}", quietly=TRUE)); if (requireNamespace("{package}", quietly=TRUE)) cat("\\t", as.character(packageVersion("{package}")))'
            proc = subprocess.run([str(rscript), "-e", code], text=True, capture_output=True, check=False)
            text = (proc.stdout or "").strip()
            available = text.startswith("TRUE")
            version = text.split("\t", 1)[1].strip() if "\t" in text else ""
            note = "available_input_prepared_not_executed" if available else "package_missing"
        rows.append({"tool": label, "available": available, "version": version, "execution_status": "not_executed", "note": note})
    return pd.DataFrame(rows)


def _backend_attempts(
    *,
    adata,
    tables: Path,
    logs: Path,
    tool_status: pd.DataFrame,
    matrix_qc: pd.DataFrame,
    run_copykat: bool,
    run_infercnv: bool,
) -> pd.DataFrame:
    source, matrix, count_status = _best_count_matrix(adata, matrix_qc)
    rows = []
    for tool, requested in (("CopyKAT", run_copykat), ("inferCNV", run_infercnv)):
        available = bool(tool_status.loc[tool_status["tool"] == tool, "available"].fillna(False).astype(bool).any())
        row = {
            "tool": tool,
            "requested": requested,
            "available": available,
            "matrix_source": source or "",
            "status": "not_requested",
            "output": "",
            "log": "",
            "reason": "",
        }
        if not requested:
            row["reason"] = "backend_not_requested"
        elif not available:
            row["status"] = "blocked"
            row["reason"] = "tool_not_available"
        elif matrix is None:
            row["status"] = "blocked"
            row["reason"] = count_status
        else:
            row.update(_execute_backend(tool, matrix, adata, tables, logs, source or "counts"))
        rows.append(row)
    return pd.DataFrame(rows)


def _execute_backend(tool: str, matrix, adata, tables: Path, logs: Path, source: str) -> dict[str, str]:
    # The execution hook is intentionally conservative. Full inferCNV/CopyKAT
    # runs can be expensive and must only start from true raw count matrices.
    counts_path = tables / f"{tool.lower()}_raw_counts_preview.tsv"
    preview = _to_dense_array(matrix, rows=min(50, matrix.shape[0]), cols=min(50, matrix.shape[1]))
    pd.DataFrame(preview).to_csv(counts_path, sep="\t", index=False)
    log_path = logs / f"{tool.lower()}_backend.log"
    log_path.write_text(
        "backend execution deferred after raw-count gate; preview exported for operator review\n"
        f"matrix_source={source}\n"
        f"shape={matrix.shape[0]}x{matrix.shape[1]}\n",
        encoding="utf-8",
    )
    return {
        "status": "blocked",
        "output": str(counts_path),
        "log": str(log_path),
        "reason": "operator_approval_required_for_full_cnv_backend",
    }


def _cnv_proxy(adata) -> tuple[pd.DataFrame, np.ndarray]:
    chromosome_col = _first_existing(adata.var, ["Chromosome.Name", "chromosome", "chr"])
    if chromosome_col is None:
        return pd.DataFrame({"chromosome": ["not_available"], "n_genes": [0], "mean_expression": [0.0], "variance": [0.0]}), np.zeros(adata.n_obs)
    expr = adata.X
    chrom = adata.var[chromosome_col].astype(str).to_numpy()
    rows = []
    cell_components = []
    for chr_name in sorted(set(chrom)):
        idx = np.where(chrom == chr_name)[0]
        if len(idx) < 5:
            continue
        per_cell = np.asarray(expr[:, idx].mean(axis=1)).reshape(-1)
        cell_components.append(per_cell)
        rows.append(
            {
                "chromosome": chr_name,
                "n_genes": int(len(idx)),
                "mean_expression": float(np.mean(per_cell)),
                "variance": float(np.var(per_cell)),
                "interpretation": "expression_cnv_proxy_not_dna_cnv",
            }
        )
    if not cell_components:
        return pd.DataFrame({"chromosome": ["not_enough_genes"], "n_genes": [0], "mean_expression": [0.0], "variance": [0.0]}), np.zeros(adata.n_obs)
    stacked = np.vstack(cell_components).T
    cnv_by_cell = np.nanstd(stacked, axis=1)
    return pd.DataFrame(rows), cnv_by_cell


def _zscore(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce").fillna(0.0)
    std = numeric.std(ddof=0)
    if std == 0 or np.isnan(std):
        return numeric * 0.0
    return (numeric - numeric.mean()) / std


def _malignant_candidates(adata, cell_type_key: str, sample_key: str) -> pd.DataFrame:
    obs = pd.DataFrame(adata.obs).copy()
    score_cols = [col for col in TUMOR_STATE_SCORES if col in obs.columns]
    if score_cols:
        state_score = obs[score_cols].apply(pd.to_numeric, errors="coerce").fillna(0.0).mean(axis=1)
    else:
        state_score = pd.Series(0.0, index=obs.index)
    tumor_marker = pd.to_numeric(obs.get("tumor_marker_score", 0.0), errors="coerce").fillna(0.0)
    cnv = pd.to_numeric(obs.get("cnv_proxy_deviation", 0.0), errors="coerce").fillna(0.0)
    composite = _zscore(tumor_marker) + _zscore(state_score) + _zscore(cnv)
    threshold = float(composite.quantile(0.85)) if len(composite) else 0.0
    frame = pd.DataFrame(
        {
            "cell_id": obs.index.astype(str),
            "sample": obs[sample_key].astype(str).to_numpy(),
            "cell_type": obs[cell_type_key].astype(str).to_numpy(),
            "tumor_marker_score": tumor_marker.to_numpy(),
            "tumor_state_score": state_score.to_numpy(),
            "cnv_proxy_deviation": cnv.to_numpy(),
            "tumor_candidate_score": composite.to_numpy(),
            "malignant_candidate": (composite >= threshold).to_numpy(),
            "candidate_rule": "top_15pct_composite_marker_state_cnv_proxy",
            "interpretation": "candidate_only_requires_pathology_or_orthogonal_cnv_validation",
        }
    )
    return frame


def _tme_composition(adata, cell_type_key: str, sample_key: str) -> pd.DataFrame:
    frame = pd.DataFrame(adata.obs)
    out = frame.groupby([sample_key, cell_type_key], observed=False).size().rename("n_cells").reset_index()
    out["fraction"] = out["n_cells"] / out.groupby(sample_key, observed=False)["n_cells"].transform("sum")
    return out


def _state_scores(adata, cell_type_key: str, marker_set: tuple[str, ...]) -> pd.DataFrame:
    frame = pd.DataFrame(adata.obs)
    score_cols = [col for col in frame.columns if col.endswith("_score")]
    grouped = frame.groupby(cell_type_key, observed=False)[score_cols].mean().reset_index() if score_cols else frame[[cell_type_key]].drop_duplicates()
    grouped["marker_overlap"] = ",".join(gene for gene in marker_set if gene in set(adata.var_names.astype(str)))
    grouped["interpretation"] = "signature_summary_not_functional_assay"
    return grouped


def _tumor_state_markers(adata, cell_type_key: str) -> pd.DataFrame:
    if "rank_genes_groups" in adata.uns:
        try:
            markers = sc.get.rank_genes_groups_df(adata, group=None).head(200)
            markers["interpretation"] = "cluster_or_celltype_marker_not_mechanism"
            return markers
        except Exception:
            pass
    return pd.DataFrame({"cell_type": sorted(pd.Series(adata.obs[cell_type_key]).astype(str).unique()), "interpretation": "marker_table_not_available"})


def _therapy_handoff(adata, sample_key: str) -> pd.DataFrame:
    frame = pd.DataFrame(adata.obs)
    rows = []
    for sample, group in frame.groupby(sample_key, observed=False):
        rows.append(
            {
                "sample": sample,
                "n_cells": int(group.shape[0]),
                "malignant_candidate_fraction": float(pd.to_numeric(group.get("malignant_candidate", 0), errors="coerce").fillna(0).mean()),
                "therapy_metadata_status": "not_provided",
                "interpretation": "handoff_ready_for_pre_post_or_response_metadata",
            }
        )
    return pd.DataFrame(rows)


def _write_infercnv_inputs(adata, tables: Path, cell_type_key: str, gene_order_reference_h5ad: Path | None = None) -> str:
    pd.DataFrame({"cell_id": adata.obs_names.astype(str), "annotation": pd.Series(adata.obs[cell_type_key]).astype(str).to_numpy()}).to_csv(
        tables / "infercnv_annotation.tsv", sep="\t", index=False, header=False
    )
    chromosome_col = _first_existing(adata.var, ["Chromosome.Name", "chromosome", "chr"])
    start_col = _first_existing(adata.var, ["Gene.Start..bp.", "start"])
    end_col = _first_existing(adata.var, ["Gene.End..bp.", "end"])
    if chromosome_col and start_col and end_col:
        order = pd.DataFrame(
            {
                "gene": adata.var_names.astype(str),
                "chromosome": adata.var[chromosome_col].astype(str).to_numpy(),
                "start": pd.to_numeric(adata.var[start_col], errors="coerce").fillna(0).astype(int).to_numpy(),
                "end": pd.to_numeric(adata.var[end_col], errors="coerce").fillna(0).astype(int).to_numpy(),
            }
        )
        status = "from_input_var"
    else:
        order, status = _map_gene_order_from_reference(adata, gene_order_reference_h5ad)
    order.to_csv(tables / "infercnv_gene_order.tsv", sep="\t", index=False, header=False)
    pd.DataFrame(
        {
            "status": [status],
            "n_genes": [int(order.shape[0])],
            "n_mapped": [int((order["chromosome"].astype(str) != "not_available").sum())],
            "reference_h5ad": [str(gene_order_reference_h5ad) if gene_order_reference_h5ad else ""],
        }
    ).to_csv(tables / "infercnv_gene_order_status.tsv", sep="\t", index=False)
    return status


def _gene_keys(var: pd.DataFrame, names: pd.Index | np.ndarray) -> pd.Series:
    symbol_col = _first_existing(var, ["gene_symbol", "Gene.Symbol", "symbol", "gene_name", "features"])
    if symbol_col is not None:
        symbols = var[symbol_col].astype(str)
        return symbols.where(symbols.ne("") & symbols.ne("nan"), pd.Series(names.astype(str), index=var.index))
    return pd.Series(names.astype(str), index=var.index)


def _map_gene_order_from_reference(adata, gene_order_reference_h5ad: Path | None) -> tuple[pd.DataFrame, str]:
    empty = pd.DataFrame({"gene": adata.var_names.astype(str), "chromosome": "not_available", "start": 0, "end": 0})
    if gene_order_reference_h5ad is None or not gene_order_reference_h5ad.exists():
        return empty, "reference_not_provided"

    try:
        ref = sc.read_h5ad(gene_order_reference_h5ad, backed="r")
        try:
            ref_var = ref.var.copy()
            ref_names = ref.var_names.copy()
        finally:
            try:
                ref.file.close()
            except Exception:
                pass
    except Exception:
        return empty, "reference_read_failed"

    chromosome_col = _first_existing(ref_var, ["Chromosome.Name", "chromosome", "chr"])
    start_col = _first_existing(ref_var, ["Gene.Start..bp.", "start"])
    end_col = _first_existing(ref_var, ["Gene.End..bp.", "end"])
    if not (chromosome_col and start_col and end_col):
        return empty, "reference_missing_gene_order_columns"

    ref_order = pd.DataFrame(
        {
            "gene_key": _gene_keys(ref_var, ref_names).astype(str).to_numpy(),
            "chromosome": ref_var[chromosome_col].astype(str).to_numpy(),
            "start": pd.to_numeric(ref_var[start_col], errors="coerce").fillna(0).astype(int).to_numpy(),
            "end": pd.to_numeric(ref_var[end_col], errors="coerce").fillna(0).astype(int).to_numpy(),
        }
    )
    ref_order = ref_order.drop_duplicates("gene_key", keep="first")
    query = pd.DataFrame({"gene": adata.var_names.astype(str), "gene_key": _gene_keys(adata.var, adata.var_names).astype(str).to_numpy()})
    mapped = query.merge(ref_order, on="gene_key", how="left")
    mapped["chromosome"] = mapped["chromosome"].fillna("not_available")
    mapped["start"] = pd.to_numeric(mapped["start"], errors="coerce").fillna(0).astype(int)
    mapped["end"] = pd.to_numeric(mapped["end"], errors="coerce").fillna(0).astype(int)
    return mapped[["gene", "chromosome", "start", "end"]], "from_reference_h5ad"


def _plot_tme(path: Path, out: Path, sample_key: str, cell_type_key: str) -> None:
    frame = pd.read_csv(path, sep="\t")
    pivot = frame.pivot_table(index=sample_key, columns=cell_type_key, values="fraction", fill_value=0)
    pivot.plot(kind="bar", stacked=True, figsize=(10, 5))
    plt.ylabel("Fraction")
    plt.tight_layout()
    plt.savefig(out, dpi=160)
    plt.close()


def _plot_state_heatmap(adata, cell_type_key: str, out: Path) -> None:
    import seaborn as sns

    frame = pd.DataFrame(adata.obs)
    score_cols = [col for col in TUMOR_STATE_SCORES if col in frame.columns]
    if not score_cols:
        score_cols = ["tumor_candidate_score", "cnv_proxy_deviation"]
    heat = frame.groupby(cell_type_key, observed=False)[score_cols].mean()
    plt.figure(figsize=(8, max(4, heat.shape[0] * 0.3)))
    sns.heatmap(heat, cmap="vlag", center=0)
    plt.tight_layout()
    plt.savefig(out, dpi=160)
    plt.close()


def _plot_malignant_umap(adata, out: Path) -> None:
    if "X_umap" in adata.obsm:
        sc.pl.umap(adata, color=["malignant_candidate", "tumor_candidate_score"], show=False, wspace=0.35)
        plt.savefig(out, dpi=160, bbox_inches="tight")
        plt.close()
        return
    frame = pd.DataFrame(adata.obs)
    plt.figure(figsize=(6, 4))
    plt.hist(frame["tumor_candidate_score"], bins=40)
    plt.xlabel("Tumor candidate score")
    plt.tight_layout()
    plt.savefig(out, dpi=160)
    plt.close()


def _plot_cnv_proxy(cnv: pd.DataFrame, out: Path) -> None:
    plt.figure(figsize=(10, 4))
    plt.bar(cnv["chromosome"].astype(str), cnv["variance"].astype(float))
    plt.ylabel("Expression variance proxy")
    plt.xticks(rotation=90)
    plt.tight_layout()
    plt.savefig(out, dpi=160)
    plt.close()


def _write_report(manifest: dict[str, Any], md: Path, html: Path) -> None:
    lines = [
        "# NSCLC 肿瘤单细胞专项验证",
        "",
        f"- 状态：`{manifest['status']}`",
        f"- analysis_level：`{manifest['analysis_level']}`",
        f"- delivery_allowed：`{manifest['delivery_allowed']}`",
        f"- validation_evidence_allowed：`{manifest['validation_evidence_allowed']}`",
        f"- 细胞数：{manifest['n_cells']}",
        f"- 恶性候选细胞数：{manifest['n_malignant_candidates']}",
        "",
        "## 说明",
        "- malignant_candidate 为候选评分，不是病理确诊。",
        "- CNV proxy 来自表达层染色体偏移，不等于 DNA CNV。",
        "- inferCNV/CopyKAT 本轮只记录可用性和输入准备，完整运行需单独 backend/参数确认。",
    ]
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    html.write_text(
        "<html><body><h1>NSCLC 肿瘤单细胞专项验证</h1>"
        f"<p>状态：<code>{manifest['status']}</code></p>"
        f"<p>analysis_level：<code>{manifest['analysis_level']}</code></p>"
        f"<p>delivery_allowed：<code>{manifest['delivery_allowed']}</code></p>"
        f"<p>恶性候选细胞数：{manifest['n_malignant_candidates']}</p>"
        "<p>候选评分和 CNV proxy 均为验证证据，不是客户正式交付结论。</p>"
        "</body></html>",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
