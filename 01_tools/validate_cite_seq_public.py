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


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a public 10x CITE-seq feature-barcode matrix.")
    parser.add_argument("--input-h5", type=Path, default=Path("/shared/shen/2026/ultimate/public_data/cite_seq/pbmc_10k_protein_v3_filtered_feature_bc_matrix.h5"))
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--max-cells-object", type=int, default=3000)
    args = parser.parse_args()
    manifest = run_validation(args.input_h5, args.output_dir, args.max_cells_object)
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


def run_validation(input_h5: Path, output_dir: Path, max_cells_object: int) -> dict:
    if not input_h5.exists():
        raise FileNotFoundError(f"Missing CITE-seq input H5: {input_h5}")

    figures = output_dir / "results" / "figures"
    tables = output_dir / "results" / "tables"
    objects = output_dir / "objects"
    reports = output_dir / "reports"
    for directory in (figures, tables, objects, reports):
        directory.mkdir(parents=True, exist_ok=True)

    adata = sc.read_10x_h5(input_h5, gex_only=False)
    adata.var_names_make_unique()
    feature_type_col = _feature_type_column(adata.var)
    feature_types = adata.var[feature_type_col].astype(str)
    rna_mask = feature_types.str.lower().eq("gene expression").to_numpy()
    adt_mask = feature_types.str.lower().isin({"antibody capture", "antibody"}).to_numpy()
    if not rna_mask.any() or not adt_mask.any():
        raise ValueError(f"Expected both Gene Expression and Antibody Capture features in {input_h5}")

    rna_counts = _row_sum(adata[:, rna_mask].X)
    adt_counts = _row_sum(adata[:, adt_mask].X)
    n_rna_features = _row_nnz(adata[:, rna_mask].X)
    n_adt_features = _row_nnz(adata[:, adt_mask].X)
    qc = pd.DataFrame(
        {
            "barcode": adata.obs_names.astype(str),
            "rna_total_counts": rna_counts,
            "adt_total_counts": adt_counts,
            "n_rna_features": n_rna_features,
            "n_adt_features": n_adt_features,
        }
    )
    qc.to_csv(tables / "cell_qc_summary.tsv", sep="\t", index=False)

    feature_summary = (
        adata.var.assign(feature_type=feature_types)
        .groupby("feature_type", observed=False)
        .size()
        .rename("n_features")
        .reset_index()
    )
    feature_summary.to_csv(tables / "feature_type_counts.tsv", sep="\t", index=False)

    adt = adata[:, adt_mask]
    adt_means = np.asarray(adt.X.mean(axis=0)).reshape(-1)
    adt_summary = pd.DataFrame({"adt_feature": adt.var_names.astype(str), "mean_counts": adt_means})
    adt_summary.sort_values("mean_counts", ascending=False).to_csv(tables / "adt_feature_mean_counts.tsv", sep="\t", index=False)

    _plot_feature_types(feature_summary, figures / "feature_type_counts.png")
    _plot_rna_vs_adt(qc, figures / "rna_vs_adt_total_counts.png")
    _plot_top_adt(adt_summary, figures / "top_adt_features.png")

    if adata.n_obs > max_cells_object:
        rng = np.random.default_rng(7)
        selected = rng.choice(adata.n_obs, size=max_cells_object, replace=False)
        object_adata = adata[selected].copy()
    else:
        object_adata = adata.copy()
    object_path = objects / "cite_seq_validation_object.h5ad"
    object_adata.write_h5ad(object_path)

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_h5": str(input_h5),
        "output_dir": str(output_dir),
        "status": "ready",
        "n_cells": int(adata.n_obs),
        "n_features": int(adata.n_vars),
        "n_rna_features": int(rna_mask.sum()),
        "n_adt_features": int(adt_mask.sum()),
        "median_rna_total_counts": float(np.median(rna_counts)),
        "median_adt_total_counts": float(np.median(adt_counts)),
        "figures": [str(path) for path in sorted(figures.glob("*.png"))],
        "tables": [str(path) for path in sorted(tables.glob("*.tsv"))],
        "objects": {"h5ad": str(object_path)},
    }
    (output_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_report(manifest, reports / "report.md", reports / "report.html")
    return manifest


def _feature_type_column(var: pd.DataFrame) -> str:
    for column in ("feature_types", "feature_type", "type"):
        if column in var.columns:
            return column
    raise ValueError("10x H5 did not contain a feature type column.")


def _row_sum(matrix) -> np.ndarray:
    return np.asarray(matrix.sum(axis=1)).reshape(-1)


def _row_nnz(matrix) -> np.ndarray:
    if hasattr(matrix, "getnnz"):
        return np.asarray(matrix.getnnz(axis=1)).reshape(-1)
    return np.asarray((matrix > 0).sum(axis=1)).reshape(-1)


def _plot_feature_types(frame: pd.DataFrame, path: Path) -> None:
    plt.figure(figsize=(6, 4))
    plt.bar(frame["feature_type"].astype(str), frame["n_features"])
    plt.ylabel("Features")
    plt.xticks(rotation=20, ha="right")
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def _plot_rna_vs_adt(frame: pd.DataFrame, path: Path) -> None:
    plt.figure(figsize=(5, 4))
    plt.scatter(frame["rna_total_counts"], frame["adt_total_counts"], s=5, alpha=0.45)
    plt.xscale("log")
    plt.yscale("log")
    plt.xlabel("RNA total counts")
    plt.ylabel("ADT total counts")
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def _plot_top_adt(frame: pd.DataFrame, path: Path) -> None:
    top = frame.sort_values("mean_counts", ascending=False).head(20)
    plt.figure(figsize=(8, 5))
    plt.barh(top["adt_feature"].astype(str)[::-1], top["mean_counts"][::-1])
    plt.xlabel("Mean ADT counts")
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def _write_report(manifest: dict, md_path: Path, html_path: Path) -> None:
    md = [
        "# CITE-seq 公开数据验证报告",
        "",
        f"输入文件：`{manifest['input_h5']}`",
        f"状态：`{manifest['status']}`",
        "",
        "## 摘要",
        f"- 细胞数：{manifest['n_cells']}",
        f"- RNA features：{manifest['n_rna_features']}",
        f"- ADT features：{manifest['n_adt_features']}",
        f"- RNA 中位总 counts：{manifest['median_rna_total_counts']:.1f}",
        f"- ADT 中位总 counts：{manifest['median_adt_total_counts']:.1f}",
    ]
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    html_path.write_text("<html><body>" + "".join(f"<p>{line}</p>" for line in md) + "</body></html>", encoding="utf-8")


if __name__ == "__main__":
    main()
