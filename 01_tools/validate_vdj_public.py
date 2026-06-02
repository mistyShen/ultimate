#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate public 10x VDJ contig and clonotype tables.")
    parser.add_argument("--input-dir", type=Path, default=Path("/shared/shen/2026/ultimate/public_data/vdj"))
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    manifest = run_validation(args.input_dir, args.output_dir)
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


def run_validation(input_dir: Path, output_dir: Path) -> dict:
    contig_path = input_dir / "filtered_contig_annotations.csv"
    clonotype_path = input_dir / "clonotypes.csv"
    missing_inputs = [str(path) for path in (contig_path, clonotype_path) if not path.exists()]
    if missing_inputs:
        raise FileNotFoundError(f"Missing required VDJ input files: {', '.join(missing_inputs)}")

    figures = output_dir / "results" / "figures"
    tables = output_dir / "results" / "tables"
    objects = output_dir / "objects"
    reports = output_dir / "reports"
    for directory in (figures, tables, objects, reports):
        directory.mkdir(parents=True, exist_ok=True)

    contigs = pd.read_csv(contig_path)
    clonotypes = pd.read_csv(clonotype_path)
    cells = contigs[_as_bool_series(contigs["is_cell"])].copy()
    productive = cells[_as_bool_series(cells["productive"])].copy()

    chain_counts = productive["chain"].value_counts().rename_axis("chain").reset_index(name="n_contigs")
    chain_counts.to_csv(tables / "productive_chain_counts.tsv", sep="\t", index=False)
    top_clonotypes = clonotypes.sort_values("frequency", ascending=False).head(30).copy()
    top_clonotypes.to_csv(tables / "top_clonotypes.tsv", sep="\t", index=False)

    per_cell = (
        productive.groupby("barcode")
        .agg(
            n_productive_contigs=("contig_id", "size"),
            n_chains=("chain", "nunique"),
            total_reads=("reads", "sum"),
            total_umis=("umis", "sum"),
            clonotype_id=("raw_clonotype_id", lambda x: ";".join(sorted(set(map(str, x))))),
        )
        .reset_index()
    )
    per_cell.to_csv(tables / "vdj_per_cell_summary.tsv", sep="\t", index=False)

    diversity = _diversity(clonotypes)
    diversity_path = tables / "vdj_diversity_summary.tsv"
    pd.DataFrame([diversity]).to_csv(diversity_path, sep="\t", index=False)

    _plot_chain_counts(chain_counts, figures / "productive_chain_counts.png")
    _plot_top_clonotypes(top_clonotypes, figures / "top_clonotype_frequency.png")
    _plot_reads_umis(per_cell, figures / "vdj_reads_vs_umis.png")

    object_path = objects / "vdj_validation_object.json"
    object_path.write_text(json.dumps(diversity, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "status": "ready",
        "n_contigs": int(contigs.shape[0]),
        "n_cell_contigs": int(cells.shape[0]),
        "n_productive_contigs": int(productive.shape[0]),
        "n_cells": int(per_cell.shape[0]),
        "n_clonotypes": int(clonotypes.shape[0]),
        "summary": diversity,
        "figures": [str(path) for path in sorted(figures.glob("*.png"))],
        "tables": [str(path) for path in sorted(tables.glob("*.tsv"))],
        "objects": {"json": str(object_path)},
    }
    (output_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_report(manifest, reports / "report.md", reports / "report.html")
    return manifest


def _diversity(clonotypes: pd.DataFrame) -> dict:
    freq = clonotypes["frequency"].astype(float)
    proportions = freq / freq.sum()
    inverse_simpson = 1.0 / float((proportions**2).sum())
    return {
        "total_clonotypes": int(clonotypes.shape[0]),
        "total_clonotype_cells": int(freq.sum()),
        "top1_frequency": int(freq.max()),
        "top1_fraction": float(proportions.max()),
        "inverse_simpson": inverse_simpson,
    }


def _as_bool_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)
    if pd.api.types.is_numeric_dtype(series):
        return series.fillna(0).astype(int) != 0
    normalized = series.fillna("").astype(str).str.strip().str.lower()
    return normalized.isin({"true", "t", "1", "yes", "y"})


def _plot_chain_counts(frame: pd.DataFrame, path: Path) -> None:
    plt.figure(figsize=(6, 4))
    plt.bar(frame["chain"].astype(str), frame["n_contigs"])
    plt.ylabel("Productive contigs")
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def _plot_top_clonotypes(frame: pd.DataFrame, path: Path) -> None:
    plt.figure(figsize=(10, 4))
    plt.bar(frame["clonotype_id"].astype(str), frame["frequency"])
    plt.xticks(rotation=90)
    plt.ylabel("Frequency")
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def _plot_reads_umis(frame: pd.DataFrame, path: Path) -> None:
    plt.figure(figsize=(5, 4))
    plt.scatter(frame["total_reads"], frame["total_umis"], s=10, alpha=0.6)
    plt.xlabel("Reads per cell")
    plt.ylabel("UMIs per cell")
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def _write_report(manifest: dict, md_path: Path, html_path: Path) -> None:
    md = [
        "# 10x VDJ 公开数据验证报告",
        "",
        f"输入目录：`{manifest['input_dir']}`",
        f"状态：`{manifest['status']}`",
        "",
        "## 摘要",
        f"- contig 数：{manifest['n_contigs']}",
        f"- productive contig 数：{manifest['n_productive_contigs']}",
        f"- 细胞数：{manifest['n_cells']}",
        f"- clonotype 数：{manifest['n_clonotypes']}",
        f"- Inverse Simpson diversity：{manifest['summary']['inverse_simpson']:.3f}",
    ]
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    html_path.write_text("<html><body>" + "".join(f"<p>{line}</p>" for line in md) + "</body></html>", encoding="utf-8")


if __name__ == "__main__":
    main()
