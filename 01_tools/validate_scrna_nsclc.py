#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from validation_manifest_utils import add_validation_guard_fields

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scanpy as sc


SIGNATURES = {
    "stemness": ["SOX2", "PROM1", "ALDH1A1", "EPCAM", "KRT19"],
    "proliferation": ["MKI67", "TOP2A", "PCNA", "TYMS", "MCM5"],
    "inflammation": ["IL6", "CXCL8", "CXCL10", "TNF", "NFKBIA"],
    "hypoxia": ["HIF1A", "VEGFA", "CA9", "SLC2A1", "LDHA"],
    "emt": ["VIM", "ZEB1", "ZEB2", "SNAI1", "FN1"],
    "glycolysis": ["HK2", "PFKP", "PKM", "LDHA", "SLC2A1"],
    "oxphos": ["NDUFA1", "COX5A", "ATP5F1A", "UQCRC1", "SDHA"],
    "immune_escape": ["CD274", "PDCD1LG2", "LGALS9", "IDO1", "TGFBI"],
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a production scRNA validation on an NSCLC h5ad file.")
    parser.add_argument("--input-h5ad", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--max-cells", type=int, default=8000)
    parser.add_argument("--random-seed", type=int, default=7)
    args = parser.parse_args()
    manifest = run_validation(args.input_h5ad, args.output_dir, args.max_cells, args.random_seed)
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


def run_validation(input_h5ad: Path, output_dir: Path, max_cells: int, random_seed: int) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    figures = output_dir / "results" / "figures"
    tables = output_dir / "results" / "tables"
    objects = output_dir / "objects"
    reports = output_dir / "reports"
    for directory in (figures, tables, objects, reports):
        directory.mkdir(parents=True, exist_ok=True)

    adata = sc.read_h5ad(input_h5ad)
    if adata.n_obs > max_cells:
        rng = np.random.default_rng(random_seed)
        selected = rng.choice(adata.n_obs, size=max_cells, replace=False)
        adata = adata[selected].copy()
    else:
        adata = adata.copy()
    adata.var_names_make_unique()
    _prefer_gene_symbols(adata)

    adata.obs["n_counts"] = np.asarray(adata.X.sum(axis=1)).reshape(-1)
    adata.obs["n_genes"] = np.asarray((adata.X > 0).sum(axis=1)).reshape(-1)
    mt_mask = pd.Index(adata.var_names.astype(str)).str.upper().str.startswith("MT-")
    if mt_mask.any():
        mt_counts = np.asarray(adata[:, mt_mask].X.sum(axis=1)).reshape(-1)
        adata.obs["pct_mt"] = mt_counts / np.maximum(adata.obs["n_counts"].to_numpy(), 1) * 100
    else:
        adata.obs["pct_mt"] = 0.0

    _plot_qc(adata, figures / "qc_violin.png")
    sc.pp.filter_cells(adata, min_genes=100)
    sc.pp.filter_genes(adata, min_cells=3)
    if np.nanmax(np.asarray(adata.X.sum(axis=1)).reshape(-1)) > 100:
        sc.pp.normalize_total(adata, target_sum=1e4)
        sc.pp.log1p(adata)
    sc.pp.highly_variable_genes(adata, n_top_genes=min(2000, adata.n_vars), flavor="seurat")
    _score_signatures(adata)
    adata.raw = adata
    if "highly_variable" in adata.var.columns:
        adata = adata[:, adata.var["highly_variable"].astype(bool)].copy()
    sc.pp.scale(adata, max_value=10)
    sc.tl.pca(adata, svd_solver="arpack", random_state=random_seed)
    sc.pp.neighbors(adata, n_neighbors=15, n_pcs=min(30, adata.obsm["X_pca"].shape[1]))
    sc.tl.umap(adata, random_state=random_seed)
    try:
        sc.tl.tsne(adata, random_state=random_seed, n_pcs=min(30, adata.obsm["X_pca"].shape[1]))
    except Exception as exc:
        adata.uns["tsne_skip_reason"] = f"{type(exc).__name__}: {exc}"
    try:
        sc.tl.leiden(adata, resolution=0.8, key_added="leiden")
    except Exception:
        try:
            sc.tl.louvain(adata, resolution=0.8, key_added="leiden")
        except Exception:
            from sklearn.cluster import KMeans

            labels = KMeans(n_clusters=min(8, max(2, adata.n_obs // 200)), random_state=random_seed, n_init=10).fit_predict(
                adata.obsm["X_pca"][:, : min(20, adata.obsm["X_pca"].shape[1])]
            )
            adata.obs["leiden"] = pd.Categorical([str(label) for label in labels])

    cell_type_key = _first_existing(adata.obs, ["cell_type_level1_harmonized", "Major cell type", "cell_type", "leiden"]) or "leiden"
    sample_key = _first_existing(adata.obs, ["sample_origin_harmonized", "Patient", "dataset_id", "sample_id"]) or "dataset_id"
    if sample_key not in adata.obs:
        adata.obs[sample_key] = "sample"
    sc.tl.rank_genes_groups(adata, groupby=cell_type_key, method="wilcoxon", pts=True)

    _write_tables(adata, tables, cell_type_key, sample_key)
    _write_figures(adata, figures, cell_type_key, sample_key)
    _write_cnv_proxy(adata, tables, figures)
    final_h5ad = objects / "nsclc_scrna_validated.h5ad"
    adata.write_h5ad(final_h5ad)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_h5ad": str(input_h5ad),
        "output_dir": str(output_dir),
        "n_cells": int(adata.n_obs),
        "n_genes": int(adata.n_vars),
        "cell_type_key": cell_type_key,
        "sample_key": sample_key,
        "figures": [str(path) for path in sorted(figures.glob("*.png"))],
        "tables": [str(path) for path in sorted(tables.glob("*.tsv"))],
        "objects": {"h5ad": str(final_h5ad)},
        "status": "ready",
    }
    add_validation_guard_fields(
        manifest,
        validation_kind="internal",
        validation_scope="NSCLC scRNA internal h5ad validation",
    )
    (output_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_report(manifest, reports / "report.md", reports / "report.html")
    return manifest


def _prefer_gene_symbols(adata) -> None:
    for col in ("gene_symbol", "Associated.Gene.Name"):
        if col in adata.var.columns:
            symbols = adata.var[col].astype(str)
            valid = symbols.notna() & (symbols != "") & (symbols != "nan")
            if valid.mean() > 0.5:
                adata.var["original_var_name"] = adata.var_names
                adata.var_names = pd.Index(np.where(valid, symbols, adata.var_names)).astype(str)
                adata.var_names_make_unique()
                return


def _first_existing(frame: pd.DataFrame, candidates: list[str]) -> str | None:
    for candidate in candidates:
        if candidate in frame.columns:
            return candidate
    return None


def _plot_qc(adata, path: Path) -> None:
    obs = adata.obs[["n_counts", "n_genes", "pct_mt"]].copy()
    melted = obs.melt(var_name="metric", value_name="value")
    plt.figure(figsize=(8, 4))
    import seaborn as sns

    sns.violinplot(data=melted, x="metric", y="value", cut=0)
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def _score_signatures(adata) -> None:
    genes = set(adata.var_names.astype(str))
    for name, gene_set in SIGNATURES.items():
        present = [gene for gene in gene_set if gene in genes]
        if len(present) >= 2:
            sc.tl.score_genes(adata, present, score_name=f"{name}_score")
        else:
            adata.obs[f"{name}_score"] = 0.0


def _write_tables(adata, tables: Path, cell_type_key: str, sample_key: str) -> None:
    pd.DataFrame(adata.obs).to_csv(tables / "cell_metadata.tsv", sep="\t")
    proportions = (
        pd.DataFrame(adata.obs)
        .groupby([sample_key, cell_type_key], observed=False)
        .size()
        .rename("n_cells")
        .reset_index()
    )
    totals = proportions.groupby(sample_key)["n_cells"].transform("sum")
    proportions["fraction"] = proportions["n_cells"] / totals
    proportions.to_csv(tables / "cell_type_proportions.tsv", sep="\t", index=False)

    markers = sc.get.rank_genes_groups_df(adata, group=None)
    markers.to_csv(tables / "marker_genes.tsv", sep="\t", index=False)

    score_cols = [col for col in adata.obs.columns if col.endswith("_score")]
    if score_cols:
        score_summary = pd.DataFrame(adata.obs).groupby(cell_type_key, observed=False)[score_cols].mean().reset_index()
        score_summary.to_csv(tables / "signature_scores_by_cell_type.tsv", sep="\t", index=False)

    expr = pd.DataFrame(adata.X.A if hasattr(adata.X, "A") else np.asarray(adata.X), index=adata.obs_names, columns=adata.var_names)
    labels = pd.DataFrame(adata.obs[[sample_key, cell_type_key]]).astype(str)
    pseudobulk = expr.groupby([labels[sample_key], labels[cell_type_key]]).mean()
    pseudobulk.to_csv(tables / "pseudobulk_mean_expression.tsv", sep="\t")


def _write_figures(adata, figures: Path, cell_type_key: str, sample_key: str) -> None:
    sc.pl.umap(adata, color=[cell_type_key, "leiden"], show=False, wspace=0.4)
    plt.savefig(figures / "umap_cell_types_clusters.png", dpi=160, bbox_inches="tight")
    plt.close()
    if "X_tsne" in adata.obsm:
        sc.pl.tsne(adata, color=[cell_type_key], show=False)
        plt.savefig(figures / "tsne_cell_types.png", dpi=160, bbox_inches="tight")
        plt.close()
    sc.pl.pca(adata, color=cell_type_key, show=False)
    plt.savefig(figures / "pca_cell_types.png", dpi=160, bbox_inches="tight")
    plt.close()

    prop = pd.read_csv(figures.parent / "tables" / "cell_type_proportions.tsv", sep="\t")
    pivot = prop.pivot_table(index=sample_key, columns=cell_type_key, values="fraction", fill_value=0)
    pivot.plot(kind="bar", stacked=True, figsize=(10, 5))
    plt.ylabel("Fraction")
    plt.tight_layout()
    plt.savefig(figures / "cell_composition_by_sample.png", dpi=160)
    plt.close()

    score_path = figures.parent / "tables" / "signature_scores_by_cell_type.tsv"
    if score_path.exists():
        import seaborn as sns

        scores = pd.read_csv(score_path, sep="\t").set_index(cell_type_key)
        plt.figure(figsize=(10, max(4, scores.shape[0] * 0.3)))
        sns.heatmap(scores, cmap="vlag", center=0)
        plt.tight_layout()
        plt.savefig(figures / "signature_score_heatmap.png", dpi=160)
        plt.close()


def _write_cnv_proxy(adata, tables: Path, figures: Path) -> None:
    chromosome_col = _first_existing(adata.var, ["Chromosome.Name", "chromosome", "chr"])
    if chromosome_col is None:
        pd.DataFrame({"reason": ["no_chromosome_annotation"]}).to_csv(tables / "tumor_cnv_proxy.tsv", sep="\t", index=False)
        return
    expr = adata.X.A if hasattr(adata.X, "A") else np.asarray(adata.X)
    frame = pd.DataFrame(expr, columns=adata.var_names)
    chrom = adata.var[chromosome_col].astype(str).to_numpy()
    rows = []
    for chr_name in sorted(set(chrom)):
        idx = np.where(chrom == chr_name)[0]
        if len(idx) < 10:
            continue
        rows.append({"chromosome": chr_name, "mean_expression": float(expr[:, idx].mean()), "variance": float(expr[:, idx].var())})
    out = pd.DataFrame(rows)
    out.to_csv(tables / "tumor_cnv_proxy.tsv", sep="\t", index=False)
    if not out.empty:
        plt.figure(figsize=(10, 4))
        plt.bar(out["chromosome"].astype(str), out["mean_expression"])
        plt.xticks(rotation=90)
        plt.ylabel("Mean scaled expression")
        plt.tight_layout()
        plt.savefig(figures / "tumor_cnv_proxy_by_chromosome.png", dpi=160)
        plt.close()


def _write_report(manifest: dict, md_path: Path, html_path: Path) -> None:
    md = [
        "# NSCLC scRNA 生产验证报告",
        "",
        f"输入：`{manifest['input_h5ad']}`",
        f"细胞数：{manifest['n_cells']}；基因数：{manifest['n_genes']}",
        f"细胞类型字段：`{manifest['cell_type_key']}`；样本字段：`{manifest['sample_key']}`",
        "",
        "## 主要结果",
        "- QC、过滤、归一化、高变基因、PCA、UMAP、t-SNE/跳过原因、聚类已执行。",
        "- marker gene、细胞比例、pseudobulk、功能 signature、CNV proxy 已输出。",
    ]
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    html_path.write_text("<html><body>" + "".join(f"<p>{line}</p>" for line in md) + "</body></html>", encoding="utf-8")


if __name__ == "__main__":
    main()
