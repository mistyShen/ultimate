#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate 0518 single-cell DNA/genome QC outputs inside Ultimate.")
    parser.add_argument("--source-root", type=Path, default=Path("/shared/shen/2026/0518"))
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    manifest = run_validation(args.source_root, args.output_dir)
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


def run_validation(source_root: Path, output_dir: Path) -> dict:
    figures = output_dir / "results" / "figures"
    tables = output_dir / "results" / "tables"
    objects = output_dir / "objects"
    reports = output_dir / "reports"
    for directory in (figures, tables, objects, reports):
        directory.mkdir(parents=True, exist_ok=True)

    stats_root = source_root / "analysis_dna" / "stats"
    source_tables = {
        "sample_manifest": source_root / "sample_manifest.tsv",
        "dna_mt_depth_summary": stats_root / "dna_mt_depth_summary.tsv",
        "mapped_unmapped_summary": stats_root / "mapped_unmapped_summary.tsv",
        "nuclear_vs_mt_summary": stats_root / "RCA_nuclear_vs_mt_summary.tsv",
        "method_reference_sanity_check": stats_root / "method_reference_sanity_check.tsv",
    }
    copied = {}
    for key, path in source_tables.items():
        if path.exists():
            target = tables / path.name
            shutil.copy2(path, target)
            copied[key] = str(target)

    top_frames = []
    for path in sorted(stats_root.glob("*_top_chromosomes.tsv")):
        target = tables / path.name
        shutil.copy2(path, target)
        copied[f"top_chromosomes:{path.stem}"] = str(target)
        top_frames.append(pd.read_csv(path, sep="\t"))
    if top_frames:
        top_chromosomes = pd.concat(top_frames, ignore_index=True)
        top_chromosomes.to_csv(tables / "all_samples_top_chromosomes.tsv", sep="\t", index=False)
        copied["all_samples_top_chromosomes"] = str(tables / "all_samples_top_chromosomes.tsv")

    _plot_mapping(tables / "mapped_unmapped_summary.tsv", figures / "mapped_unmapped_fraction.png")
    _plot_depth(tables / "dna_mt_depth_summary.tsv", figures / "dna_mtdna_depth.png")
    _plot_top_chromosomes(tables / "all_samples_top_chromosomes.tsv", figures / "top_chromosome_reads.png")

    summary = _build_summary(tables)
    summary_path = tables / "scdna_validation_summary.tsv"
    pd.DataFrame([summary]).to_csv(summary_path, sep="\t", index=False)
    object_path = objects / "scdna_validation_object.json"
    object_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_root": str(source_root),
        "output_dir": str(output_dir),
        "status": "ready" if {"dna_mt_depth_summary", "mapped_unmapped_summary"} <= set(copied) else "missing_source_outputs",
        "validation_scope": "scDNA baseline: FASTQ/sample manifest handoff, mapping QC, nuclear/mtDNA depth summary, chromosome coverage proxy, and reproducible report artifacts.",
        "copied_tables": copied,
        "summary": summary,
        "figures": [str(path) for path in sorted(figures.glob("*.png"))],
        "tables": [str(path) for path in sorted(tables.glob("*.tsv"))],
        "objects": {"json": str(object_path)},
    }
    (output_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_report(manifest, reports / "report.md", reports / "report.html")
    return manifest


def _plot_mapping(path: Path, out: Path) -> None:
    if not path.exists():
        return
    frame = pd.read_csv(path, sep="\t")
    plt.figure(figsize=(6, 4))
    plt.bar(frame["sample_id"], frame["mapped_fraction"], color="#4EA4F5", label="mapped")
    plt.bar(frame["sample_id"], frame["unmapped_fraction"], bottom=frame["mapped_fraction"], color="#F26F8F", label="unmapped")
    plt.ylabel("Fraction")
    plt.ylim(0, 1.02)
    plt.legend(frameon=False)
    plt.tight_layout()
    plt.savefig(out, dpi=180)
    plt.close()


def _plot_depth(path: Path, out: Path) -> None:
    if not path.exists():
        return
    frame = pd.read_csv(path, sep="\t")
    plt.figure(figsize=(6, 4))
    plt.plot(frame["sample_id"], frame["mtDNA_depth"], marker="o", color="#31B7C5", label="mtDNA depth")
    plt.plot(frame["sample_id"], frame["mean_nuclear_depth"], marker="o", color="#F2B84B", label="mean nuclear depth")
    plt.ylabel("Depth")
    plt.legend(frameon=False)
    plt.tight_layout()
    plt.savefig(out, dpi=180)
    plt.close()


def _plot_top_chromosomes(path: Path, out: Path) -> None:
    if not path.exists():
        return
    frame = pd.read_csv(path, sep="\t")
    top = frame[frame["rank"] <= 5].copy()
    pivot = top.pivot_table(index="chrom", columns="sample_id", values="mapped_reads", aggfunc="sum", fill_value=0)
    pivot = pivot.loc[pivot.sum(axis=1).sort_values(ascending=False).index]
    pivot.plot(kind="bar", figsize=(8, 4), color=["#4EA4F5", "#31B7C5", "#F26F8F", "#F2B84B"][: pivot.shape[1]])
    plt.ylabel("Mapped reads")
    plt.xticks(rotation=30, ha="right")
    plt.tight_layout()
    plt.savefig(out, dpi=180)
    plt.close()


def _build_summary(tables: Path) -> dict:
    summary: dict[str, float | int | str] = {}
    manifest = tables / "sample_manifest.tsv"
    depth = tables / "dna_mt_depth_summary.tsv"
    mapping = tables / "mapped_unmapped_summary.tsv"
    if manifest.exists():
        frame = pd.read_csv(manifest, sep="\t")
        summary["n_samples"] = int(frame["sample_id"].nunique()) if "sample_id" in frame.columns else int(frame.shape[0])
        if "read_pairs" in frame.columns:
            summary["total_read_pairs"] = int(frame["read_pairs"].sum())
    if mapping.exists():
        frame = pd.read_csv(mapping, sep="\t")
        summary["median_mapped_fraction"] = float(frame["mapped_fraction"].median())
    if depth.exists():
        frame = pd.read_csv(depth, sep="\t")
        summary["median_mtdna_depth"] = float(frame["mtDNA_depth"].median())
        summary["median_nuclear_depth"] = float(frame["mean_nuclear_depth"].median())
        summary["median_chrm_fraction_mapped"] = float(frame["chrM_fraction_mapped"].median())
    return summary


def _write_report(manifest: dict, md_path: Path, html_path: Path) -> None:
    md = [
        "# 0518 scDNA/基因组基础验证报告",
        "",
        f"源目录：`{manifest['source_root']}`",
        f"状态：`{manifest['status']}`",
        "",
        "## 摘要",
        *[f"- {k}: {v}" for k, v in manifest["summary"].items()],
        "",
        "## 验证范围",
        f"- {manifest['validation_scope']}",
    ]
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    html_path.write_text("<html><body>" + "".join(f"<p>{line}</p>" for line in md) + "</body></html>", encoding="utf-8")


if __name__ == "__main__":
    main()
