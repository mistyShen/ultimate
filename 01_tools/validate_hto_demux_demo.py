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
    parser = argparse.ArgumentParser(description="Validate HTO / Cell Hashing demultiplex outputs.")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--n-cells", type=int, default=260)
    parser.add_argument("--seed", type=int, default=31)
    args = parser.parse_args()
    manifest = run_validation(args.output_dir, n_cells=args.n_cells, seed=args.seed)
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


def run_validation(output_dir: Path, *, n_cells: int, seed: int) -> dict:
    figures = output_dir / "results" / "figures"
    tables = output_dir / "results" / "tables"
    objects = output_dir / "objects"
    reports = output_dir / "reports"
    for directory in (figures, tables, objects, reports):
        directory.mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(seed)
    tags = ["HTO_CTRL_1", "HTO_CTRL_2", "HTO_TRT_1", "HTO_TRT_2"]
    true_tag = rng.choice(tags + ["doublet", "negative"], p=[0.22, 0.22, 0.22, 0.22, 0.08, 0.04], size=n_cells)
    counts = rng.poisson(3, size=(n_cells, len(tags))).astype(float)
    for idx, label in enumerate(true_tag):
        if label in tags:
            counts[idx, tags.index(label)] += rng.poisson(80)
        elif label == "doublet":
            selected = rng.choice(len(tags), size=2, replace=False)
            counts[idx, selected] += rng.poisson(55, size=2)
    count_table = pd.DataFrame(counts, columns=tags)
    count_table.insert(0, "cell_id", [f"CELL_{idx:04d}" for idx in range(n_cells)])
    count_table.to_csv(tables / "hashtag_counts.tsv", sep="\t", index=False)

    calls = _call_hto(count_table, tags)
    calls["true_label"] = true_tag
    calls.to_csv(tables / "hto_demux_assignments.tsv", sep="\t", index=False)

    composition = calls.groupby("assignment", observed=False).size().rename("n_cells").reset_index()
    composition["fraction"] = composition["n_cells"] / composition["n_cells"].sum()
    composition.to_csv(tables / "hto_sample_composition.tsv", sep="\t", index=False)

    tag_summary = count_table[tags].agg(["mean", "median", "max"]).T.reset_index().rename(columns={"index": "hto_tag"})
    tag_summary.to_csv(tables / "hto_tag_qc_summary.tsv", sep="\t", index=False)

    _plot_composition(composition, figures / "hto_sample_composition.png")
    _plot_tag_heatmap(count_table, tags, figures / "hto_count_heatmap.png")
    _plot_margin(calls, figures / "hto_call_margin.png")

    object_path = objects / "hto_demux_validation_object.json"
    object_path.write_text(json.dumps({"n_cells": n_cells, "hto_tags": tags}, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "validation_scope": "synthetic_hto_demultiplex",
        "output_dir": str(output_dir),
        "status": "ready",
        "n_cells": int(n_cells),
        "n_features": int(len(tags)),
        "n_samples": int(composition.shape[0]),
        "figures": [str(path) for path in sorted(figures.glob("*.png"))],
        "tables": [str(path) for path in sorted(tables.glob("*.tsv"))],
        "objects": {"json": str(object_path)},
    }
    add_validation_guard_fields(
        manifest,
        validation_kind="synthetic",
        validation_scope="Synthetic HTO/Cell Hashing demultiplex demo validation",
    )
    (output_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_report(manifest, reports / "report.md", reports / "report.html")
    return manifest


def _call_hto(count_table: pd.DataFrame, tags: list[str]) -> pd.DataFrame:
    values = count_table[tags].to_numpy()
    order = np.argsort(values, axis=1)
    top_idx = order[:, -1]
    second_idx = order[:, -2]
    top = values[np.arange(values.shape[0]), top_idx]
    second = values[np.arange(values.shape[0]), second_idx]
    margin = top - second
    assignment = np.where(top < 20, "negative", np.where(margin < 20, "doublet", np.array(tags, dtype=object)[top_idx]))
    return pd.DataFrame(
        {
            "cell_id": count_table["cell_id"],
            "assignment": assignment,
            "top_tag": np.array(tags, dtype=object)[top_idx],
            "top_count": top,
            "second_count": second,
            "call_margin": margin,
        }
    )


def _plot_composition(frame: pd.DataFrame, path: Path) -> None:
    plt.figure(figsize=(7, 4))
    plt.bar(frame["assignment"], frame["n_cells"], color="#6D8F6B")
    plt.ylabel("Cells")
    plt.xticks(rotation=25, ha="right")
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def _plot_tag_heatmap(frame: pd.DataFrame, tags: list[str], path: Path) -> None:
    sampled = frame.head(80).set_index("cell_id")[tags]
    plt.figure(figsize=(7, 5))
    plt.imshow(np.log1p(sampled), aspect="auto", cmap="viridis")
    plt.colorbar(label="log1p(count)")
    plt.yticks([])
    plt.xticks(range(len(tags)), tags, rotation=25, ha="right")
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def _plot_margin(frame: pd.DataFrame, path: Path) -> None:
    plt.figure(figsize=(6, 4))
    plt.hist(frame["call_margin"], bins=30, color="#6D83B6")
    plt.xlabel("Top - second HTO count")
    plt.ylabel("Cells")
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def _write_report(manifest: dict, md_path: Path, html_path: Path) -> None:
    md = [
        "# HTO / Cell Hashing 验证报告",
        "",
        f"状态：`{manifest['status']}`",
        "",
        "## 摘要",
        f"- 细胞数：{manifest['n_cells']}",
        f"- HTO 标签数：{manifest['n_features']}",
        f"- assignment 类别数：{manifest['n_samples']}",
        "- 输出：hashtag count、demux assignment、样本组成、QC 图表和对象 manifest。",
    ]
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    html_path.write_text("<html><body>" + "".join(f"<p>{line}</p>" for line in md) + "</body></html>", encoding="utf-8")


if __name__ == "__main__":
    main()
