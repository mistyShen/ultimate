#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from validation_manifest_utils import add_validation_guard_fields

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Squidpy public Visium H&E spatial transcriptomics data.")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--public-data-dir", type=Path, default=Path("/shared/shen/2026/ultimate/public_data/spatial"))
    parser.add_argument("--max-spots-object", type=int, default=3000)
    args = parser.parse_args()
    manifest = run_validation(args.output_dir, args.public_data_dir, args.max_spots_object)
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


def run_validation(output_dir: Path, public_data_dir: Path, max_spots_object: int) -> dict:
    figures = output_dir / "results" / "figures"
    tables = output_dir / "results" / "tables"
    objects = output_dir / "objects"
    reports = output_dir / "reports"
    for directory in (figures, tables, objects, reports):
        directory.mkdir(parents=True, exist_ok=True)
    cache_dir = public_data_dir / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("XDG_CACHE_HOME", str(cache_dir / "xdg"))
    os.environ.setdefault("POOCH_HOME", str(cache_dir / "pooch"))

    import scanpy as sc
    import squidpy as sq

    adata_path = cache_dir / "anndata" / "visium_hne_adata.h5ad"
    adata = sq.datasets.visium_hne_adata(path=adata_path)
    adata.var_names_make_unique()
    if "spatial" not in adata.obsm:
        raise ValueError("Squidpy Visium H&E data did not contain obsm['spatial'].")

    if "total_counts" not in adata.obs or "n_genes_by_counts" not in adata.obs:
        sc.pp.calculate_qc_metrics(adata, inplace=True, percent_top=None)
    cluster_col = _cluster_column(adata.obs)
    if cluster_col is None:
        _add_basic_clusters(adata, sc)
        cluster_col = "leiden"

    sq.gr.spatial_neighbors(adata)
    try:
        sq.gr.nhood_enrichment(adata, cluster_key=cluster_col)
        nhood_key = f"{cluster_col}_nhood_enrichment"
    except Exception as exc:  # noqa: BLE001
        adata.uns["nhood_enrichment_error"] = f"{type(exc).__name__}: {exc}"
        nhood_key = None

    qc = adata.obs[["total_counts", "n_genes_by_counts", cluster_col]].copy()
    qc.insert(0, "spot", adata.obs_names.astype(str))
    qc.to_csv(tables / "spot_qc_summary.tsv", sep="\t", index=False)

    cluster_counts = adata.obs[cluster_col].astype(str).value_counts().rename_axis("cluster").reset_index(name="n_spots")
    cluster_counts.to_csv(tables / "spatial_cluster_counts.tsv", sep="\t", index=False)

    neighbor_summary = {
        "n_spots": int(adata.n_obs),
        "n_genes": int(adata.n_vars),
        "spatial_connectivities_nnz": int(adata.obsp["spatial_connectivities"].nnz),
        "cluster_column": cluster_col,
        "nhood_enrichment_key": nhood_key,
    }
    pd.DataFrame([neighbor_summary]).to_csv(tables / "spatial_neighbor_summary.tsv", sep="\t", index=False)

    _plot_spatial_numeric(adata, "total_counts", figures / "spatial_total_counts.png")
    _plot_spatial_cluster(adata, cluster_col, figures / "spatial_clusters.png")
    _plot_cluster_counts(cluster_counts, figures / "spatial_cluster_counts.png")

    object_path = objects / "spatial_validation_object.h5ad"
    object_adata = adata.copy()
    if object_adata.n_obs > max_spots_object:
        rng = np.random.default_rng(17)
        selected = np.sort(rng.choice(object_adata.n_obs, size=max_spots_object, replace=False))
        object_adata = object_adata[selected].copy()
    object_adata.write_h5ad(object_path)

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": "squidpy.datasets.visium_hne_adata",
        "output_dir": str(output_dir),
        "status": "ready",
        "validation_scope": "Squidpy public Visium H&E AnnData: spot QC, spatial coordinates, spatial neighbor graph, cluster summary and spatial plots.",
        "n_spots": int(adata.n_obs),
        "n_genes": int(adata.n_vars),
        "cluster_column": cluster_col,
        "n_clusters": int(cluster_counts.shape[0]),
        "spatial_connectivities_nnz": int(adata.obsp["spatial_connectivities"].nnz),
        "figures": [str(path) for path in sorted(figures.glob("*.png"))],
        "tables": [str(path) for path in sorted(tables.glob("*.tsv"))],
        "objects": {"h5ad": str(object_path)},
    }
    add_validation_guard_fields(
        manifest,
        validation_kind="public",
        validation_scope="Spatial transcriptomics public Visium/Squidpy validation",
    )
    (output_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_report(manifest, reports / "report.md", reports / "report.html")
    _mark_public_data_ready(public_data_dir, manifest)
    return manifest


def _cluster_column(obs: pd.DataFrame) -> str | None:
    for column in ("cluster", "clusters", "leiden", "region", "annotation"):
        if column in obs.columns:
            return column
    return None


def _add_basic_clusters(adata, sc) -> None:
    sc.pp.normalize_total(adata, target_sum=1e4)
    sc.pp.log1p(adata)
    sc.pp.highly_variable_genes(adata, n_top_genes=2000, subset=True)
    sc.pp.pca(adata, n_comps=30)
    sc.pp.neighbors(adata, n_neighbors=12)
    try:
        sc.tl.leiden(adata, resolution=0.6, key_added="leiden")
    except Exception:  # noqa: BLE001
        from sklearn.cluster import KMeans

        labels = KMeans(n_clusters=8, random_state=19, n_init=10).fit_predict(adata.obsm["X_pca"][:, :15])
        adata.obs["leiden"] = pd.Categorical(labels.astype(str))


def _plot_spatial_numeric(adata, column: str, path: Path) -> None:
    coords = np.asarray(adata.obsm["spatial"])
    values = adata.obs[column].astype(float).to_numpy()
    plt.figure(figsize=(6, 5))
    scatter = plt.scatter(coords[:, 0], coords[:, 1], c=np.log10(values + 1), s=8, cmap="viridis")
    plt.gca().invert_yaxis()
    plt.axis("equal")
    plt.axis("off")
    plt.colorbar(scatter, label=f"log10({column} + 1)")
    plt.tight_layout()
    plt.savefig(path, dpi=180)
    plt.close()


def _plot_spatial_cluster(adata, column: str, path: Path) -> None:
    coords = np.asarray(adata.obsm["spatial"])
    codes = pd.Categorical(adata.obs[column].astype(str)).codes
    plt.figure(figsize=(6, 5))
    plt.scatter(coords[:, 0], coords[:, 1], c=codes, s=8, cmap="tab20")
    plt.gca().invert_yaxis()
    plt.axis("equal")
    plt.axis("off")
    plt.tight_layout()
    plt.savefig(path, dpi=180)
    plt.close()


def _plot_cluster_counts(frame: pd.DataFrame, path: Path) -> None:
    plt.figure(figsize=(8, 5))
    plt.barh(frame["cluster"].astype(str)[::-1], frame["n_spots"][::-1])
    plt.xlabel("Spots")
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def _write_report(manifest: dict, md_path: Path, html_path: Path) -> None:
    md = [
        "# 空间转录组公开数据验证报告",
        "",
        f"数据集：`{manifest['dataset']}`",
        f"状态：`{manifest['status']}`",
        "",
        "## 摘要",
        f"- spot 数：{manifest['n_spots']}",
        f"- 基因数：{manifest['n_genes']}",
        f"- 空间 cluster 列：{manifest['cluster_column']}",
        f"- cluster 数：{manifest['n_clusters']}",
        f"- 空间邻接边数：{manifest['spatial_connectivities_nnz']}",
        "",
        "## 说明",
        f"- {manifest['validation_scope']}",
    ]
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    html_path.write_text("<html><body>" + "".join(f"<p>{line}</p>" for line in md) + "</body></html>", encoding="utf-8")


def _mark_public_data_ready(public_data_dir: Path, run_manifest: dict) -> None:
    public_data_dir.mkdir(parents=True, exist_ok=True)
    path = public_data_dir / "manifest.json"
    manifest = {}
    if path.exists():
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {}
    manifest.update(
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "dataset_key": "spatial",
            "download_status": "ready",
            "validation_status": "ready",
            "validation_manifest": str(Path(run_manifest["output_dir"]) / "run_manifest.json"),
            "reason": "Squidpy Visium H&E public spatial validation completed.",
        }
    )
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
