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
    "/shared/shen/2026/ultimate/public_data/multiome/"
    "10k_PBMC_Multiome_nextgem_Chromium_Controller_filtered_feature_bc_matrix.h5"
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a public 10x Multiome RNA+ATAC feature matrix.")
    parser.add_argument("--input-h5", type=Path, default=DEFAULT_H5)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--public-data-dir", type=Path, default=Path("/shared/shen/2026/ultimate/public_data/multiome"))
    parser.add_argument("--max-cells-object", type=int, default=3000)
    parser.add_argument("--max-features-object", type=int, default=2500)
    args = parser.parse_args()
    manifest = run_validation(args.input_h5, args.output_dir, args.public_data_dir, args.max_cells_object, args.max_features_object)
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


def run_validation(
    input_h5: Path,
    output_dir: Path,
    public_data_dir: Path,
    max_cells_object: int,
    max_features_object: int,
) -> dict:
    if not input_h5.exists():
        raise FileNotFoundError(f"Missing Multiome input H5: {input_h5}")

    figures = output_dir / "results" / "figures"
    tables = output_dir / "results" / "tables"
    objects = output_dir / "objects"
    reports = output_dir / "reports"
    for directory in (figures, tables, objects, reports):
        directory.mkdir(parents=True, exist_ok=True)

    matrix = _read_10x_h5(input_h5)
    feature_summary = _feature_summary(matrix)
    cell_qc = _cell_qc_by_modality(matrix)
    top_features = _top_features(matrix, max_features_object)

    feature_summary.to_csv(tables / "feature_type_counts.tsv", sep="\t", index=False)
    cell_qc.to_csv(tables / "cell_qc_by_modality.tsv", sep="\t", index=False)
    top_features.head(1000).to_csv(tables / "top_features_by_counts.tsv", sep="\t", index=False)

    _plot_feature_types(feature_summary, figures / "feature_type_counts.png")
    _plot_rna_vs_atac(cell_qc, figures / "rna_vs_atac_total_counts.png")
    _plot_detected_features(cell_qc, figures / "detected_features_by_modality.png")

    object_path = objects / "multiome_validation_object.h5ad"
    _write_h5ad_object(matrix, object_path, max_cells_object, max_features_object)

    rna_mask = _feature_type_mask(matrix, {"gene expression"})
    atac_mask = _feature_type_mask(matrix, {"peaks", "peak"})
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_h5": str(input_h5),
        "output_dir": str(output_dir),
        "status": "ready",
        "validation_scope": "10x RNA+ATAC filtered feature matrix: modality QC, joint sparse object export. WNN/linkage/fragments-level analysis requires downstream Signac/muon inputs and optional fragments.",
        "n_cells": int(matrix["shape"][1]),
        "n_features": int(matrix["shape"][0]),
        "n_rna_features": int(rna_mask.sum()),
        "n_atac_features": int(atac_mask.sum()),
        "median_rna_total_counts": float(cell_qc["rna_total_counts"].median()),
        "median_atac_total_counts": float(cell_qc["atac_total_counts"].median()),
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


def _feature_type_mask(matrix: dict, accepted: set[str]) -> np.ndarray:
    normalized = np.asarray([value.strip().lower() for value in matrix["feature_types"]])
    return np.isin(normalized, list(accepted))


def _feature_summary(matrix: dict) -> pd.DataFrame:
    return (
        pd.Series(matrix["feature_types"], name="feature_type")
        .value_counts()
        .rename_axis("feature_type")
        .reset_index(name="n_features")
    )


def _cell_qc_by_modality(matrix: dict) -> pd.DataFrame:
    rna_mask = _feature_type_mask(matrix, {"gene expression"})
    atac_mask = _feature_type_mask(matrix, {"peaks", "peak"})
    rna_totals = np.zeros(matrix["shape"][1], dtype=float)
    atac_totals = np.zeros(matrix["shape"][1], dtype=float)
    rna_features = np.zeros(matrix["shape"][1], dtype=int)
    atac_features = np.zeros(matrix["shape"][1], dtype=int)
    data = matrix["data"]
    indices = matrix["indices"]
    indptr = matrix["indptr"]
    for cell_index in range(matrix["shape"][1]):
        start, end = int(indptr[cell_index]), int(indptr[cell_index + 1])
        cell_features = indices[start:end]
        cell_counts = data[start:end]
        rna = rna_mask[cell_features]
        atac = atac_mask[cell_features]
        rna_totals[cell_index] = float(cell_counts[rna].sum())
        atac_totals[cell_index] = float(cell_counts[atac].sum())
        rna_features[cell_index] = int(rna.sum())
        atac_features[cell_index] = int(atac.sum())
    return pd.DataFrame(
        {
            "barcode": matrix["barcodes"],
            "rna_total_counts": rna_totals,
            "atac_total_counts": atac_totals,
            "n_rna_features": rna_features,
            "n_atac_features": atac_features,
        }
    )


def _feature_counts(matrix: dict) -> np.ndarray:
    return np.bincount(matrix["indices"], weights=matrix["data"], minlength=matrix["shape"][0])


def _top_features(matrix: dict, max_features: int) -> pd.DataFrame:
    counts = _feature_counts(matrix)
    frame = pd.DataFrame(
        {
            "feature_id": matrix["feature_ids"],
            "feature_name": matrix["feature_names"],
            "feature_type": matrix["feature_types"],
            "total_counts": counts,
        }
    )
    return frame.sort_values(["feature_type", "total_counts"], ascending=[True, False]).groupby("feature_type", observed=False).head(max_features)


def _write_h5ad_object(matrix: dict, path: Path, max_cells: int, max_features: int) -> None:
    rng = np.random.default_rng(13)
    cell_idx = np.arange(matrix["shape"][1])
    if cell_idx.size > max_cells:
        cell_idx = np.sort(rng.choice(cell_idx, size=max_cells, replace=False))
    counts = _feature_counts(matrix)
    selected = []
    for feature_type in sorted(set(matrix["feature_types"])):
        mask = np.asarray(matrix["feature_types"]) == feature_type
        candidates = np.where(mask)[0]
        top = candidates[np.argsort(counts[candidates])[::-1][: max(1, max_features // 2)]]
        selected.extend(top.tolist())
    feature_idx = np.asarray(sorted(set(selected)))[:max_features]
    full = sparse.csc_matrix((matrix["data"], matrix["indices"], matrix["indptr"]), shape=matrix["shape"])
    subset = full[feature_idx, :][:, cell_idx].T.tocsr()
    var = pd.DataFrame(
        {"feature_type": np.asarray(matrix["feature_types"])[feature_idx]},
        index=np.asarray(matrix["feature_names"])[feature_idx],
    )
    obs = pd.DataFrame(index=np.asarray(matrix["barcodes"])[cell_idx])
    ad.AnnData(X=subset, obs=obs, var=var).write_h5ad(path)


def _plot_feature_types(frame: pd.DataFrame, path: Path) -> None:
    plt.figure(figsize=(6, 4))
    plt.bar(frame["feature_type"].astype(str), frame["n_features"])
    plt.ylabel("Features")
    plt.xticks(rotation=20, ha="right")
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def _plot_rna_vs_atac(frame: pd.DataFrame, path: Path) -> None:
    plt.figure(figsize=(5, 4))
    plt.scatter(frame["rna_total_counts"] + 1, frame["atac_total_counts"] + 1, s=5, alpha=0.45)
    plt.xscale("log")
    plt.yscale("log")
    plt.xlabel("RNA total counts + 1")
    plt.ylabel("ATAC total counts + 1")
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def _plot_detected_features(frame: pd.DataFrame, path: Path) -> None:
    plt.figure(figsize=(7, 4))
    plt.hist(np.log10(frame["n_rna_features"] + 1), bins=50, alpha=0.65, label="RNA")
    plt.hist(np.log10(frame["n_atac_features"] + 1), bins=50, alpha=0.65, label="ATAC")
    plt.xlabel("log10(detected features + 1)")
    plt.ylabel("Cells")
    plt.legend()
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def _write_report(manifest: dict, md_path: Path, html_path: Path) -> None:
    md = [
        "# Multiome 公开数据验证报告",
        "",
        f"输入文件：`{manifest['input_h5']}`",
        f"状态：`{manifest['status']}`",
        "",
        "## 摘要",
        f"- 细胞数：{manifest['n_cells']}",
        f"- RNA features：{manifest['n_rna_features']}",
        f"- ATAC features：{manifest['n_atac_features']}",
        f"- RNA counts 中位数：{manifest['median_rna_total_counts']:.1f}",
        f"- ATAC counts 中位数：{manifest['median_atac_total_counts']:.1f}",
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
            "dataset_key": "multiome",
            "download_status": "ready",
            "validation_status": "ready",
            "validation_manifest": str(Path(run_manifest["output_dir"]) / "run_manifest.json"),
            "reason": "Multiome public RNA+ATAC feature matrix validation completed.",
        }
    )
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
