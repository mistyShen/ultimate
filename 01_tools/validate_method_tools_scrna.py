#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scanpy as sc
import seaborn as sns


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate method-tool basics on an existing scRNA AnnData object.")
    parser.add_argument("--input-h5ad", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--max-cells", type=int, default=3000)
    parser.add_argument("--random-seed", type=int, default=11)
    args = parser.parse_args()
    manifest = run_validation(args.input_h5ad, args.output_dir, args.max_cells, args.random_seed)
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


def run_validation(input_h5ad: Path, output_dir: Path, max_cells: int, random_seed: int) -> dict:
    if not input_h5ad.exists():
        raise FileNotFoundError(f"Missing method-tools input h5ad: {input_h5ad}")
    figures = output_dir / "results" / "figures"
    tables = output_dir / "results" / "tables"
    objects = output_dir / "objects"
    reports = output_dir / "reports"
    for directory in (figures, tables, objects, reports):
        directory.mkdir(parents=True, exist_ok=True)

    adata = sc.read_h5ad(input_h5ad)
    if adata.n_obs > max_cells:
        rng = np.random.default_rng(random_seed)
        selected = np.sort(rng.choice(adata.n_obs, size=max_cells, replace=False))
        adata = adata[selected].copy()
    else:
        adata = adata.copy()
    adata.var_names_make_unique()

    sample_key = _first_existing(adata.obs, ["sample_origin_harmonized", "Patient", "sample_id", "dataset_id", "batch"]) or "sample_id"
    if sample_key not in adata.obs:
        adata.obs[sample_key] = "sample"
    batch_key = _first_existing(adata.obs, ["dataset_id", "batch", "sample_origin_harmonized", sample_key]) or sample_key

    _add_qc_metrics(adata)
    qc = pd.DataFrame(adata.obs[[sample_key, batch_key, "n_counts", "n_genes", "pct_mt"]]).copy()
    qc.insert(0, "barcode", adata.obs_names.astype(str))
    qc["passes_basic_filter"] = (qc["n_genes"] >= 100) & (qc["n_counts"] > 0) & (qc["pct_mt"] <= 25)
    qc["doublet_proxy_score"] = _scaled(qc["n_counts"]) + _scaled(qc["n_genes"])
    threshold = float(qc["doublet_proxy_score"].quantile(0.98))
    qc["doublet_proxy_flag"] = qc["doublet_proxy_score"] >= threshold
    qc.to_csv(tables / "method_tools_cell_qc.tsv", sep="\t", index=False)

    sample_composition = (
        qc.groupby(sample_key, observed=False)
        .agg(
            n_cells=("barcode", "size"),
            pass_rate=("passes_basic_filter", "mean"),
            doublet_proxy_rate=("doublet_proxy_flag", "mean"),
            median_genes=("n_genes", "median"),
            median_counts=("n_counts", "median"),
            median_pct_mt=("pct_mt", "median"),
        )
        .reset_index()
    )
    sample_composition.to_csv(tables / "method_tools_sample_composition.tsv", sep="\t", index=False)

    _run_light_embedding(adata, random_seed)
    centroids = _pca_centroids(adata, sample_key)
    centroids.to_csv(tables / "method_tools_pca_sample_centroids.tsv", sep="\t", index=False)

    summary = {
        "input_h5ad": str(input_h5ad),
        "n_cells": int(adata.n_obs),
        "n_genes": int(adata.n_vars),
        "sample_key": sample_key,
        "batch_key": batch_key,
        "n_samples": int(qc[sample_key].astype(str).nunique()),
        "basic_filter_pass_rate": float(qc["passes_basic_filter"].mean()),
        "doublet_proxy_threshold": threshold,
        "doublet_proxy_rate": float(qc["doublet_proxy_flag"].mean()),
        "status": "ready",
    }
    pd.DataFrame([summary]).to_csv(tables / "method_tools_summary.tsv", sep="\t", index=False)

    _plot_qc(qc, figures / "method_tools_qc_violin.png")
    _plot_doublet_proxy(qc, figures / "method_tools_doublet_proxy.png")
    _plot_pca(adata, sample_key, figures / "method_tools_pca_by_sample.png")

    object_path = objects / "method_tools_cellxgene_ready.h5ad"
    adata.write_h5ad(object_path)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **summary,
        "validation_scope": "Method-tools baseline: QC metrics, basic filtering summary, doublet proxy, sample/batch composition, PCA visualization, and cellxgene-ready AnnData handoff.",
        "figures": [str(path) for path in sorted(figures.glob("*.png"))],
        "tables": [str(path) for path in sorted(tables.glob("*.tsv"))],
        "objects": {"h5ad": str(object_path)},
    }
    (output_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_report(manifest, reports / "report.md", reports / "report.html")
    return manifest


def _first_existing(frame: pd.DataFrame, candidates: list[str]) -> str | None:
    for candidate in candidates:
        if candidate in frame.columns:
            return candidate
    return None


def _add_qc_metrics(adata) -> None:
    adata.obs["n_counts"] = np.asarray(adata.X.sum(axis=1)).reshape(-1)
    if hasattr(adata.X, "getnnz"):
        adata.obs["n_genes"] = np.asarray(adata.X.getnnz(axis=1)).reshape(-1)
    else:
        adata.obs["n_genes"] = np.asarray((adata.X > 0).sum(axis=1)).reshape(-1)
    mt_mask = pd.Index(adata.var_names.astype(str)).str.upper().str.startswith("MT-")
    if mt_mask.any():
        mt_counts = np.asarray(adata[:, mt_mask].X.sum(axis=1)).reshape(-1)
        adata.obs["pct_mt"] = mt_counts / np.maximum(adata.obs["n_counts"].to_numpy(), 1) * 100
    else:
        adata.obs["pct_mt"] = 0.0


def _scaled(values: pd.Series) -> pd.Series:
    values = pd.to_numeric(values, errors="coerce").fillna(0.0).astype(float)
    spread = float(values.max() - values.min())
    if spread == 0:
        return pd.Series(np.zeros(values.shape[0]), index=values.index)
    return (values - values.min()) / spread


def _run_light_embedding(adata, random_seed: int) -> None:
    if np.nanmax(np.asarray(adata.X.sum(axis=1)).reshape(-1)) > 100:
        sc.pp.normalize_total(adata, target_sum=1e4)
        sc.pp.log1p(adata)
    sc.pp.highly_variable_genes(adata, n_top_genes=min(2000, adata.n_vars), flavor="seurat")
    if "highly_variable" in adata.var.columns and adata.var["highly_variable"].astype(bool).any():
        adata._inplace_subset_var(adata.var["highly_variable"].astype(bool).to_numpy())
    sc.pp.scale(adata, max_value=10)
    sc.tl.pca(adata, n_comps=min(30, max(2, adata.n_vars - 1)), svd_solver="arpack", random_state=random_seed)


def _pca_centroids(adata, sample_key: str) -> pd.DataFrame:
    coords = pd.DataFrame(adata.obsm["X_pca"][:, :2], columns=["PC1", "PC2"], index=adata.obs_names)
    coords[sample_key] = adata.obs[sample_key].astype(str).to_numpy()
    return coords.groupby(sample_key, observed=False)[["PC1", "PC2"]].mean().reset_index()


def _plot_qc(qc: pd.DataFrame, path: Path) -> None:
    frame = qc[["n_counts", "n_genes", "pct_mt"]].melt(var_name="metric", value_name="value")
    plt.figure(figsize=(8, 4))
    sns.violinplot(data=frame, x="metric", y="value", cut=0, inner="quartile", color="#31B7C5")
    plt.tight_layout()
    plt.savefig(path, dpi=180)
    plt.close()


def _plot_doublet_proxy(qc: pd.DataFrame, path: Path) -> None:
    colors = np.where(qc["doublet_proxy_flag"].to_numpy(), "#F26F8F", "#4EA4F5")
    plt.figure(figsize=(5.5, 4.4))
    plt.scatter(qc["n_counts"], qc["n_genes"], c=colors, s=8, alpha=0.6, linewidth=0)
    plt.xlabel("Total counts")
    plt.ylabel("Detected genes")
    plt.tight_layout()
    plt.savefig(path, dpi=180)
    plt.close()


def _plot_pca(adata, sample_key: str, path: Path) -> None:
    coords = np.asarray(adata.obsm["X_pca"][:, :2])
    labels = pd.Categorical(adata.obs[sample_key].astype(str))
    plt.figure(figsize=(6, 4.8))
    plt.scatter(coords[:, 0], coords[:, 1], c=labels.codes, s=8, cmap="tab20", alpha=0.7, linewidth=0)
    plt.xlabel("PC1")
    plt.ylabel("PC2")
    plt.tight_layout()
    plt.savefig(path, dpi=180)
    plt.close()


def _write_report(manifest: dict, md_path: Path, html_path: Path) -> None:
    md = [
        "# 方法学工具基础验证报告",
        "",
        f"输入：`{manifest['input_h5ad']}`",
        f"状态：`{manifest['status']}`",
        "",
        "## 摘要",
        f"- 细胞数：{manifest['n_cells']}",
        f"- 基因数：{manifest['n_genes']}",
        f"- 样本列：{manifest['sample_key']}",
        f"- 样本数：{manifest['n_samples']}",
        f"- 基础过滤通过率：{manifest['basic_filter_pass_rate']:.3f}",
        f"- 双细胞 proxy 比例：{manifest['doublet_proxy_rate']:.3f}",
        "",
        "## 验证范围",
        f"- {manifest['validation_scope']}",
    ]
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    html_path.write_text("<html><body>" + "".join(f"<p>{line}</p>" for line in md) + "</body></html>", encoding="utf-8")


if __name__ == "__main__":
    main()
