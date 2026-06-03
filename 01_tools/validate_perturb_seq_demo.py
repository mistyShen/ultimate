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


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Perturb-seq guide assignment and perturbation summary outputs.")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--n-cells", type=int, default=240)
    parser.add_argument("--n-genes", type=int, default=80)
    parser.add_argument("--seed", type=int, default=29)
    args = parser.parse_args()
    manifest = run_validation(args.output_dir, n_cells=args.n_cells, n_genes=args.n_genes, seed=args.seed)
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


def run_validation(output_dir: Path, *, n_cells: int, n_genes: int, seed: int) -> dict:
    figures = output_dir / "results" / "figures"
    tables = output_dir / "results" / "tables"
    objects = output_dir / "objects"
    reports = output_dir / "reports"
    for directory in (figures, tables, objects, reports):
        directory.mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(seed)
    guides = np.array(["NTC", "TP53_g1", "KRAS_g1", "EGFR_g1"])
    cells = pd.DataFrame(
        {
            "cell_id": [f"CELL_{idx:04d}" for idx in range(n_cells)],
            "sample_id": rng.choice(["CTRL_1", "TRT_1"], size=n_cells),
            "guide_id": rng.choice(guides, p=[0.35, 0.25, 0.20, 0.20], size=n_cells),
        }
    )
    cells["condition"] = np.where(cells["guide_id"].eq("NTC"), "control", "perturbed")
    genes = [f"GENE_{idx:03d}" for idx in range(n_genes)]
    expression = rng.negative_binomial(n=8, p=0.35, size=(n_cells, n_genes)).astype(float)
    target_gene = {"TP53_g1": 3, "KRAS_g1": 9, "EGFR_g1": 15}
    for guide, gene_idx in target_gene.items():
        mask = cells["guide_id"].eq(guide).to_numpy()
        expression[mask, gene_idx] += rng.poisson(12, size=int(mask.sum()))

    expr = pd.DataFrame(expression, columns=genes)
    expr.insert(0, "cell_id", cells["cell_id"])
    expr.to_csv(tables / "expression_matrix_tiny.tsv", sep="\t", index=False)
    cells.to_csv(tables / "guide_assignments.tsv", sep="\t", index=False)

    guide_summary = cells.groupby("guide_id", observed=False).size().rename("n_cells").reset_index()
    guide_summary["fraction"] = guide_summary["n_cells"] / guide_summary["n_cells"].sum()
    guide_summary.to_csv(tables / "guide_assignment_summary.tsv", sep="\t", index=False)

    de_rows = []
    ntc_mask = cells["guide_id"].eq("NTC").to_numpy()
    for guide in guides:
        if guide == "NTC":
            continue
        mask = cells["guide_id"].eq(guide).to_numpy()
        for gene_idx, gene in enumerate(genes):
            control_mean = float(expression[ntc_mask, gene_idx].mean())
            guide_mean = float(expression[mask, gene_idx].mean())
            log2fc = np.log2((guide_mean + 1.0) / (control_mean + 1.0))
            de_rows.append({"contrast": f"{guide}_vs_NTC", "gene": gene, "log2fc": log2fc, "mean_guide": guide_mean, "mean_ntc": control_mean})
    de = pd.DataFrame(de_rows)
    de["rank_score"] = de["log2fc"].abs()
    de.sort_values(["contrast", "rank_score"], ascending=[True, False]).to_csv(tables / "perturbation_de_summary.tsv", sep="\t", index=False)

    signature = (
        de.groupby("contrast", observed=False)["log2fc"]
        .apply(lambda values: float(np.mean(np.abs(values.nlargest(10)))))
        .rename("top10_abs_log2fc_mean")
        .reset_index()
    )
    signature.to_csv(tables / "perturbation_signature_scores.tsv", sep="\t", index=False)

    _plot_guide_counts(guide_summary, figures / "guide_assignment_counts.png")
    _plot_de_heatmap(de, figures / "perturbation_top_gene_heatmap.png")
    _plot_signature(signature, figures / "perturbation_signature_scores.png")

    object_path = objects / "perturb_seq_validation_object.json"
    object_path.write_text(
        json.dumps({"n_cells": n_cells, "n_genes": n_genes, "guides": guides.tolist()}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "validation_scope": "synthetic_perturb_seq_guide_assignment_and_de",
        "output_dir": str(output_dir),
        "status": "ready",
        "n_cells": int(n_cells),
        "n_features": int(n_genes),
        "n_guides": int(len(guides)),
        "figures": [str(path) for path in sorted(figures.glob("*.png"))],
        "tables": [str(path) for path in sorted(tables.glob("*.tsv"))],
        "objects": {"json": str(object_path)},
    }
    (output_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_report(manifest, reports / "report.md", reports / "report.html")
    return manifest


def _plot_guide_counts(frame: pd.DataFrame, path: Path) -> None:
    plt.figure(figsize=(6, 4))
    plt.bar(frame["guide_id"], frame["n_cells"], color="#4777A8")
    plt.ylabel("Cells")
    plt.xticks(rotation=20, ha="right")
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def _plot_de_heatmap(de: pd.DataFrame, path: Path) -> None:
    top = de.sort_values("rank_score", ascending=False).head(24)
    matrix = top.pivot_table(index="gene", columns="contrast", values="log2fc", fill_value=0.0)
    plt.figure(figsize=(7, 6))
    plt.imshow(matrix, aspect="auto", cmap="RdBu_r", vmin=-2.5, vmax=2.5)
    plt.colorbar(label="log2FC")
    plt.yticks(range(matrix.shape[0]), matrix.index, fontsize=7)
    plt.xticks(range(matrix.shape[1]), matrix.columns, rotation=35, ha="right")
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def _plot_signature(frame: pd.DataFrame, path: Path) -> None:
    plt.figure(figsize=(6, 4))
    plt.plot(frame["contrast"], frame["top10_abs_log2fc_mean"], marker="o", color="#B04A4A")
    plt.ylabel("Top10 |log2FC| mean")
    plt.xticks(rotation=25, ha="right")
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def _write_report(manifest: dict, md_path: Path, html_path: Path) -> None:
    md = [
        "# Perturb-seq 验证报告",
        "",
        f"状态：`{manifest['status']}`",
        "",
        "## 摘要",
        f"- 细胞数：{manifest['n_cells']}",
        f"- 基因数：{manifest['n_features']}",
        f"- guide 数：{manifest['n_guides']}",
        "- 输出：guide assignment、扰动差异表、signature score、图表和对象 manifest。",
    ]
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    html_path.write_text("<html><body>" + "".join(f"<p>{line}</p>" for line in md) + "</body></html>", encoding="utf-8")


if __name__ == "__main__":
    main()
