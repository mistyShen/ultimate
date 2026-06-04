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


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate genotype demultiplex table outputs.")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--n-cells", type=int, default=220)
    parser.add_argument("--n-snps", type=int, default=40)
    parser.add_argument("--seed", type=int, default=37)
    args = parser.parse_args()
    manifest = run_validation(args.output_dir, n_cells=args.n_cells, n_snps=args.n_snps, seed=args.seed)
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


def run_validation(output_dir: Path, *, n_cells: int, n_snps: int, seed: int) -> dict:
    figures = output_dir / "results" / "figures"
    tables = output_dir / "results" / "tables"
    objects = output_dir / "objects"
    reports = output_dir / "reports"
    for directory in (figures, tables, objects, reports):
        directory.mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(seed)
    donors = np.array(["DONOR_A", "DONOR_B", "DONOR_C"])
    cell_donor = rng.choice(donors, size=n_cells, p=[0.42, 0.34, 0.24])
    variants = [f"rs{100000 + idx}" for idx in range(n_snps)]
    depth = rng.poisson(6, size=(n_cells, n_snps))
    alt_fraction_by_donor = {"DONOR_A": 0.15, "DONOR_B": 0.5, "DONOR_C": 0.8}
    alt = np.zeros_like(depth)
    for donor in donors:
        mask = cell_donor == donor
        alt[mask] = rng.binomial(depth[mask], alt_fraction_by_donor[str(donor)])

    cells = pd.DataFrame({"cell_id": [f"CELL_{idx:04d}" for idx in range(n_cells)], "true_donor": cell_donor})
    cells["total_depth"] = depth.sum(axis=1)
    cells["alt_fraction"] = alt.sum(axis=1) / np.maximum(cells["total_depth"], 1)
    cells["assignment"] = pd.cut(
        cells["alt_fraction"],
        bins=[-0.01, 0.32, 0.65, 1.01],
        labels=["DONOR_A", "DONOR_B", "DONOR_C"],
    ).astype(str)
    cells["assignment_confidence"] = np.maximum.reduce(
        [
            1.0 - np.abs(cells["alt_fraction"].to_numpy() - 0.15),
            1.0 - np.abs(cells["alt_fraction"].to_numpy() - 0.50),
            1.0 - np.abs(cells["alt_fraction"].to_numpy() - 0.80),
        ]
    )
    cells.to_csv(tables / "genotype_demux_assignments.tsv", sep="\t", index=False)

    depth_table = pd.DataFrame(depth, columns=variants)
    depth_table.insert(0, "cell_id", cells["cell_id"])
    depth_table.to_csv(tables / "cellsnp_depth_matrix_tiny.tsv", sep="\t", index=False)

    donor_summary = cells.groupby("assignment", observed=False).agg(n_cells=("cell_id", "size"), median_depth=("total_depth", "median"), mean_confidence=("assignment_confidence", "mean")).reset_index()
    donor_summary.to_csv(tables / "donor_assignment_summary.tsv", sep="\t", index=False)

    concordance = pd.crosstab(cells["true_donor"], cells["assignment"]).reset_index()
    concordance.to_csv(tables / "assignment_concordance.tsv", sep="\t", index=False)

    _plot_donor_summary(donor_summary, figures / "donor_assignment_counts.png")
    _plot_alt_fraction(cells, figures / "cell_alt_fraction_by_assignment.png")
    _plot_concordance(concordance, donors.tolist(), figures / "assignment_concordance.png")

    object_path = objects / "genotype_demux_validation_object.json"
    object_path.write_text(json.dumps({"n_cells": n_cells, "n_snps": n_snps, "donors": donors.tolist()}, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "validation_scope": "synthetic_genotype_demultiplex_assignments",
        "output_dir": str(output_dir),
        "status": "ready",
        "n_cells": int(n_cells),
        "n_features": int(n_snps),
        "n_samples": int(len(donors)),
        "figures": [str(path) for path in sorted(figures.glob("*.png"))],
        "tables": [str(path) for path in sorted(tables.glob("*.tsv"))],
        "objects": {"json": str(object_path)},
    }
    add_validation_guard_fields(
        manifest,
        validation_kind="synthetic",
        validation_scope="Synthetic genotype demultiplex demo validation",
    )
    (output_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_report(manifest, reports / "report.md", reports / "report.html")
    return manifest


def _plot_donor_summary(frame: pd.DataFrame, path: Path) -> None:
    plt.figure(figsize=(6, 4))
    plt.bar(frame["assignment"], frame["n_cells"], color="#8B6FA8")
    plt.ylabel("Cells")
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def _plot_alt_fraction(frame: pd.DataFrame, path: Path) -> None:
    plt.figure(figsize=(6, 4))
    labels = sorted(frame["assignment"].unique())
    values = [frame.loc[frame["assignment"].eq(label), "alt_fraction"] for label in labels]
    plt.boxplot(values, tick_labels=labels)
    plt.ylabel("Alt allele fraction")
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def _plot_concordance(frame: pd.DataFrame, donors: list[str], path: Path) -> None:
    matrix = frame.set_index("true_donor").reindex(donors).fillna(0)
    matrix = matrix.reindex(columns=donors, fill_value=0)
    plt.figure(figsize=(5, 4))
    plt.imshow(matrix, cmap="Blues")
    plt.colorbar(label="Cells")
    plt.xticks(range(len(donors)), donors, rotation=25, ha="right")
    plt.yticks(range(len(donors)), donors)
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def _write_report(manifest: dict, md_path: Path, html_path: Path) -> None:
    md = [
        "# Genotype Demultiplex 验证报告",
        "",
        f"状态：`{manifest['status']}`",
        "",
        "## 摘要",
        f"- 细胞数：{manifest['n_cells']}",
        f"- SNP 数：{manifest['n_features']}",
        f"- donor 数：{manifest['n_samples']}",
        "- 输出：cellsnp-like depth、donor assignment、concordance、QC 图表和对象 manifest。",
    ]
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    html_path.write_text("<html><body>" + "".join(f"<p>{line}</p>" for line in md) + "</body></html>", encoding="utf-8")


if __name__ == "__main__":
    main()
