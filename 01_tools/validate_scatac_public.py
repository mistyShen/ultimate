#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import anndata as ad
import h5py
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import sparse


DEFAULT_H5 = Path(
    "/shared/shen/2026/ultimate/public_data/scatac/"
    "10k_pbmc_ATACv2_nextgem_Chromium_Controller_filtered_peak_bc_matrix.h5"
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a public 10x scATAC filtered peak matrix.")
    parser.add_argument("--input-h5", type=Path, default=DEFAULT_H5)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--public-data-dir", type=Path, default=Path("/shared/shen/2026/ultimate/public_data/scatac"))
    parser.add_argument("--max-cells-object", type=int, default=3000)
    parser.add_argument("--max-peaks-object", type=int, default=2000)
    args = parser.parse_args()
    manifest = run_validation(args.input_h5, args.output_dir, args.public_data_dir, args.max_cells_object, args.max_peaks_object)
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


def run_validation(
    input_h5: Path,
    output_dir: Path,
    public_data_dir: Path,
    max_cells_object: int,
    max_peaks_object: int,
) -> dict:
    if not input_h5.exists():
        raise FileNotFoundError(f"Missing scATAC input H5: {input_h5}")

    figures = output_dir / "results" / "figures"
    tables = output_dir / "results" / "tables"
    objects = output_dir / "objects"
    reports = output_dir / "reports"
    for directory in (figures, tables, objects, reports):
        directory.mkdir(parents=True, exist_ok=True)

    matrix = _read_10x_h5(input_h5)
    feature_summary = _feature_summary(matrix)
    cell_qc = _cell_qc(matrix)
    top_features = _top_features(matrix, max_peaks_object)

    cell_qc.to_csv(tables / "cell_qc_summary.tsv", sep="\t", index=False)
    feature_summary.to_csv(tables / "feature_type_counts.tsv", sep="\t", index=False)
    top_features.head(1000).to_csv(tables / "top_peak_counts.tsv", sep="\t", index=False)

    _plot_hist(cell_qc["total_counts"], figures / "atac_total_counts_per_cell.png", "ATAC total counts per cell")
    _plot_hist(cell_qc["n_accessible_peaks"], figures / "atac_accessible_peaks_per_cell.png", "Accessible peaks per cell")
    _plot_top_features(top_features, figures / "top_accessible_peaks.png")

    object_path = objects / "scatac_validation_object.h5ad"
    _write_h5ad_object(matrix, object_path, max_cells_object, max_peaks_object)

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_h5": str(input_h5),
        "output_dir": str(output_dir),
        "status": "ready",
        "validation_scope": "10x filtered peak matrix: cell QC, peak quantification, sparse object export. Fragments-level TSS/FRiP/peak-calling requires optional fragments input.",
        "n_cells": int(matrix["shape"][1]),
        "n_peaks": int(matrix["shape"][0]),
        "median_total_counts": float(cell_qc["total_counts"].median()),
        "median_accessible_peaks": float(cell_qc["n_accessible_peaks"].median()),
        "figures": [str(path) for path in sorted(figures.glob("*.png"))],
        "tables": [str(path) for path in sorted(tables.glob("*.tsv"))],
        "objects": {"h5ad": str(object_path)},
    }
    (output_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_report(manifest, reports / "report.md", reports / "report.html")
    _mark_public_data_ready(public_data_dir, manifest)
    return manifest


def _read_10x_h5(path: Path) -> dict:
    with h5py.File(path, "r") as handle:
        group = handle["matrix"]
        features = group["features"]
        feature_type_key = "feature_type" if "feature_type" in features else "feature_types"
        return {
            "data": group["data"][:],
            "indices": group["indices"][:],
            "indptr": group["indptr"][:],
            "shape": tuple(int(x) for x in group["shape"][:]),
            "barcodes": _decode(group["barcodes"][:]),
            "feature_ids": _decode(features["id"][:]),
            "feature_names": _decode(features["name"][:]),
            "feature_types": _decode(features[feature_type_key][:]),
        }


def _decode(values) -> list[str]:
    return [value.decode("utf-8") if isinstance(value, bytes) else str(value) for value in values]


def _cell_qc(matrix: dict) -> pd.DataFrame:
    data = matrix["data"]
    indptr = matrix["indptr"]
    total_counts = np.asarray([data[int(start) : int(end)].sum() for start, end in zip(indptr[:-1], indptr[1:])], dtype=float)
    return pd.DataFrame(
        {
            "barcode": matrix["barcodes"],
            "total_counts": total_counts.astype(float),
            "n_accessible_peaks": np.diff(indptr).astype(int),
        }
    )


def _feature_summary(matrix: dict) -> pd.DataFrame:
    feature_types = pd.Series(matrix["feature_types"], name="feature_type")
    return feature_types.value_counts().rename_axis("feature_type").reset_index(name="n_features")


def _feature_counts(matrix: dict) -> np.ndarray:
    return np.bincount(matrix["indices"], weights=matrix["data"], minlength=matrix["shape"][0])


def _top_features(matrix: dict, max_features: int) -> pd.DataFrame:
    counts = _feature_counts(matrix)
    frame = pd.DataFrame(
        {
            "peak_id": matrix["feature_ids"],
            "peak_name": matrix["feature_names"],
            "feature_type": matrix["feature_types"],
            "total_counts": counts,
        }
    )
    return frame.sort_values("total_counts", ascending=False).head(max_features)


def _write_h5ad_object(matrix: dict, path: Path, max_cells: int, max_features: int) -> None:
    rng = np.random.default_rng(11)
    cell_idx = np.arange(matrix["shape"][1])
    if cell_idx.size > max_cells:
        cell_idx = np.sort(rng.choice(cell_idx, size=max_cells, replace=False))
    peak_idx = _top_features(matrix, max_features).index.to_numpy()
    full = sparse.csc_matrix((matrix["data"], matrix["indices"], matrix["indptr"]), shape=matrix["shape"])
    subset = full[peak_idx, :][:, cell_idx].T.tocsr()
    var = pd.DataFrame(
        {"feature_type": np.asarray(matrix["feature_types"])[peak_idx]},
        index=np.asarray(matrix["feature_names"])[peak_idx],
    )
    obs = pd.DataFrame(index=np.asarray(matrix["barcodes"])[cell_idx])
    ad.AnnData(X=subset, obs=obs, var=var).write_h5ad(path)


def _plot_hist(values: pd.Series, path: Path, title: str) -> None:
    plt.figure(figsize=(6, 4))
    plt.hist(np.log10(values.astype(float) + 1), bins=60)
    plt.xlabel("log10(value + 1)")
    plt.ylabel("Cells")
    plt.title(title)
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def _plot_top_features(frame: pd.DataFrame, path: Path) -> None:
    top = frame.head(30).copy()
    plt.figure(figsize=(9, 6))
    plt.barh(top["peak_name"].astype(str)[::-1], top["total_counts"][::-1])
    plt.xlabel("Total counts")
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def _write_report(manifest: dict, md_path: Path, html_path: Path) -> None:
    md = [
        "# scATAC 公开数据验证报告",
        "",
        f"输入文件：`{manifest['input_h5']}`",
        f"状态：`{manifest['status']}`",
        "",
        "## 摘要",
        f"- 细胞数：{manifest['n_cells']}",
        f"- peak 数：{manifest['n_peaks']}",
        f"- 每细胞 ATAC counts 中位数：{manifest['median_total_counts']:.1f}",
        f"- 每细胞开放 peak 中位数：{manifest['median_accessible_peaks']:.1f}",
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
            "dataset_key": "scatac",
            "download_status": "ready",
            "validation_status": "ready",
            "validation_manifest": str(Path(run_manifest["output_dir"]) / "run_manifest.json"),
            "reason": "scATAC public filtered peak matrix validation completed.",
        }
    )
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
