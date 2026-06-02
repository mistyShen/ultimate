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
    parser = argparse.ArgumentParser(description="Validate 0518 DNA/mtDNA outputs inside Ultimate.")
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

    mt_root = source_root / "analysis_mtDNA" / "singlecell_mgatk_like"
    dna_root = source_root / "analysis_dna"
    source_tables = {
        "cell_mtDNA_depth": mt_root / "counts" / "cell_mtDNA_depth.tsv",
        "high_confidence_variants": mt_root / "variants" / "high_confidence_informative_variants.tsv",
        "variant_vaf_matrix": mt_root / "variants" / "cell_by_variant_vaf_matrix.tsv",
        "mtDNA_variant_stats": mt_root / "variants" / "mtDNA_snv_variant_stats.tsv",
        "dna_flagstat_A_121": dna_root / "bam" / "A_121" / "A_121.flagstat.txt",
    }
    copied = {}
    for key, path in source_tables.items():
        if path.exists():
            target = tables / path.name
            shutil.copy2(path, target)
            copied[key] = str(target)

    _plot_depth(tables / "cell_mtDNA_depth.tsv", figures / "cell_mtDNA_depth_barplot.png")
    _plot_variant_counts(tables / "high_confidence_informative_variants.tsv", figures / "high_confidence_variant_counts.png")
    for src in sorted((mt_root / "plots").glob("*.png")):
        shutil.copy2(src, figures / src.name)
    for src in sorted((dna_root / "plots").glob("*.png")):
        shutil.copy2(src, figures / src.name)

    summary = _build_summary(tables)
    summary_path = tables / "mtdna_validation_summary.tsv"
    pd.DataFrame([summary]).to_csv(summary_path, sep="\t", index=False)
    object_path = objects / "mtdna_validation_object.json"
    object_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_root": str(source_root),
        "output_dir": str(output_dir),
        "status": "ready" if copied else "missing_source_outputs",
        "copied_tables": copied,
        "summary": summary,
        "figures": [str(path) for path in sorted(figures.glob("*.png"))],
        "tables": [str(path) for path in sorted(tables.glob("*"))],
        "objects": {"json": str(object_path)},
    }
    (output_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_report(manifest, reports / "report.md", reports / "report.html")
    return manifest


def _plot_depth(path: Path, out: Path) -> None:
    if not path.exists():
        return
    frame = pd.read_csv(path, sep="\t")
    x = frame.iloc[:, 0].astype(str)
    y = frame.select_dtypes("number").iloc[:, 0]
    plt.figure(figsize=(7, 4))
    plt.bar(x, y)
    plt.ylabel(y.name)
    plt.tight_layout()
    plt.savefig(out, dpi=160)
    plt.close()


def _plot_variant_counts(path: Path, out: Path) -> None:
    if not path.exists():
        return
    frame = pd.read_csv(path, sep="\t")
    sample_col = "cell_id" if "cell_id" in frame.columns else "sample" if "sample" in frame.columns else frame.columns[0]
    counts = frame.groupby(sample_col).size()
    plt.figure(figsize=(7, 4))
    counts.plot(kind="bar")
    plt.ylabel("High-confidence variants")
    plt.tight_layout()
    plt.savefig(out, dpi=160)
    plt.close()


def _build_summary(tables: Path) -> dict:
    summary = {}
    depth = tables / "cell_mtDNA_depth.tsv"
    variants = tables / "high_confidence_informative_variants.tsv"
    if depth.exists():
        frame = pd.read_csv(depth, sep="\t")
        summary["n_cells_with_depth"] = int(frame.shape[0])
    if variants.exists():
        frame = pd.read_csv(variants, sep="\t")
        summary["n_high_confidence_variants"] = int(frame.shape[0])
        for col in ("cell_id", "sample"):
            if col in frame.columns:
                summary["n_cells_with_variants"] = int(frame[col].nunique())
                break
    return summary


def _write_report(manifest: dict, md_path: Path, html_path: Path) -> None:
    md = [
        "# 0518 DNA/mtDNA 生产验证报告",
        "",
        f"源目录：`{manifest['source_root']}`",
        f"状态：`{manifest['status']}`",
        "",
        "## 摘要",
        *[f"- {k}: {v}" for k, v in manifest["summary"].items()],
    ]
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    html_path.write_text("<html><body>" + "".join(f"<p>{line}</p>" for line in md) + "</body></html>", encoding="utf-8")


if __name__ == "__main__":
    main()
