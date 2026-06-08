#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
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

from ultimate.modules.common import _coerce_mvp_table_schema


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate genotype demultiplex table outputs.")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--input-dir", type=Path, default=None, help="Optional public cellsnp-lite/vireo matrix directory.")
    parser.add_argument("--source-url", default="", help="Public data source URL recorded in the manifest.")
    parser.add_argument("--n-cells", type=int, default=220)
    parser.add_argument("--n-snps", type=int, default=40)
    parser.add_argument("--seed", type=int, default=37)
    args = parser.parse_args()
    if args.input_dir:
        manifest = run_public_fixture_validation(args.input_dir, args.output_dir, source_url=args.source_url)
    else:
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


def run_public_fixture_validation(input_dir: Path, output_dir: Path, *, source_url: str = "") -> dict:
    figures = output_dir / "results" / "figures"
    tables = output_dir / "results" / "tables"
    objects = output_dir / "objects"
    reports = output_dir / "reports"
    for directory in (figures, tables, objects, reports):
        directory.mkdir(parents=True, exist_ok=True)

    ad_path = input_dir / "cellSNP.tag.AD.mtx"
    dp_path = input_dir / "cellSNP.tag.DP.mtx"
    vcf_path = input_dir / "cellSNP.base.vcf.gz"
    samples_path = input_dir / "cellSNP.samples.tsv"
    required = (ad_path, dp_path, vcf_path, samples_path)
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing genotype demux public fixture files: " + ", ".join(missing))

    ad = _summarize_mtx(ad_path)
    dp = _summarize_mtx(dp_path)
    if ad["shape"] != dp["shape"]:
        raise ValueError(f"AD/DP matrix shape mismatch: {ad['shape']} vs {dp['shape']}")
    n_snps, n_cells = ad["shape"]
    cells = _read_samples(samples_path, n_cells)
    variants = _read_vcf_variants(vcf_path, n_snps)

    cell_dp = dp["col_sums"]
    cell_ad = ad["col_sums"]
    alt_fraction = np.divide(cell_ad, np.maximum(cell_dp, 1), out=np.zeros_like(cell_ad, dtype=float), where=cell_dp > 0)
    assignment = _assignment_ready_bins(alt_fraction, cell_dp)
    assignments = pd.DataFrame(
        {
            "cell_id": cells,
            "total_depth": cell_dp.astype(int),
            "alt_count": cell_ad.astype(int),
            "alt_fraction": alt_fraction,
            "assignment": assignment,
            "assignment_confidence": np.where(cell_dp > 0, np.minimum(1.0, cell_dp / np.nanpercentile(cell_dp[cell_dp > 0], 95)), 0.0),
            "assignment_status": "vireo_input_ready_not_full_demux",
        }
    )
    assignments.to_csv(tables / "genotype_demux_assignments.tsv", sep="\t", index=False)
    assignment_mvp = pd.DataFrame(
        {
            "cell_id": assignments["cell_id"],
            "assigned_genotype": assignments["assignment"],
            "doublet_status": "not_called_handoff",
            "assignment_probability": assignments["assignment_confidence"],
            "snp_count": int(n_snps),
            "reference_vcf_status": "public_fixture_vcf_loaded",
        }
    )
    _write_genotype_mvp_table(
        tables,
        "assignment.tsv",
        assignment_mvp,
        input_dir=input_dir,
        source_dataset="single-cell-genetics/vireo data/cellSNP_mat",
    )
    _write_genotype_mvp_table(
        tables,
        "assignment_confidence.tsv",
        assignment_mvp[["cell_id", "assigned_genotype", "assignment_probability"]].assign(
            confidence_class=np.where(assignment_mvp["assignment_probability"].ge(0.5), "moderate_or_high", "low_confidence")
        ),
        input_dir=input_dir,
        source_dataset="single-cell-genetics/vireo data/cellSNP_mat",
    )
    _write_genotype_mvp_table(
        tables,
        "cell_metadata_with_genotype.tsv",
        assignment_mvp[["cell_id", "assigned_genotype", "doublet_status", "assignment_probability"]].assign(
            metadata_handoff_status="ready_for_scrna_metadata_join"
        ),
        input_dir=input_dir,
        source_dataset="single-cell-genetics/vireo data/cellSNP_mat",
    )

    snp_qc = variants.copy()
    snp_qc["dp_sum"] = dp["row_sums"].astype(int)
    snp_qc["ad_sum"] = ad["row_sums"].astype(int)
    snp_qc["alt_fraction"] = np.divide(snp_qc["ad_sum"], np.maximum(snp_qc["dp_sum"], 1))
    snp_qc["detected_cell_fraction"] = np.divide(dp["row_nnz"], max(n_cells, 1))
    _write_genotype_mvp_table(
        tables,
        "snp_qc.tsv",
        pd.DataFrame(
            {
                "snp_id": snp_qc["variant_id"],
                "chrom": snp_qc["chrom"],
                "pos": snp_qc["pos"],
                "covered_cell_count": dp["row_nnz"].astype(int),
                "reference_vcf_status": "public_fixture_vcf_loaded",
            }
        ),
        input_dir=input_dir,
        source_dataset="single-cell-genetics/vireo data/cellSNP_mat",
    )

    donor_summary = (
        assignments.groupby("assignment", observed=False)
        .agg(n_cells=("cell_id", "size"), median_depth=("total_depth", "median"), mean_confidence=("assignment_confidence", "mean"))
        .reset_index()
    )
    donor_summary.to_csv(tables / "donor_assignment_summary.tsv", sep="\t", index=False)
    composition = donor_summary.rename(columns={"assignment": "assigned_genotype", "n_cells": "cell_count"})
    composition["composition_fraction"] = composition["cell_count"] / max(float(composition["cell_count"].sum()), 1.0)
    composition["assignment_status"] = "assignment_ready_public_fixture"
    _write_genotype_mvp_table(
        tables,
        "sample_composition.tsv",
        composition[["assigned_genotype", "cell_count", "composition_fraction", "assignment_status"]],
        input_dir=input_dir,
        source_dataset="single-cell-genetics/vireo data/cellSNP_mat",
    )
    _write_genotype_mvp_table(
        tables,
        "doublet_summary.tsv",
        composition[["assigned_genotype"]].assign(doublet_count=0, doublet_rate=0.0),
        input_dir=input_dir,
        source_dataset="single-cell-genetics/vireo data/cellSNP_mat",
    )
    pd.DataFrame(
        [
            {"matrix": "AD", "path": str(ad_path), "n_snps": n_snps, "n_cells": n_cells, "nnz": ad["nnz"], "total_counts": int(ad["row_sums"].sum())},
            {"matrix": "DP", "path": str(dp_path), "n_snps": n_snps, "n_cells": n_cells, "nnz": dp["nnz"], "total_counts": int(dp["row_sums"].sum())},
        ]
    ).to_csv(tables / "cellsnp_matrix_qc.tsv", sep="\t", index=False)
    pd.DataFrame(
        [
            {
                "backend": "vireo",
                "input_mode": "cellSNP_mat",
                "status": "handoff_ready",
                "note": "Public fixture validates cellsnp-lite/vireo matrix import. Full donor inference should run vireo on project data.",
            }
        ]
    ).to_csv(tables / "vireo_handoff.tsv", sep="\t", index=False)

    _plot_donor_summary(donor_summary, figures / "donor_assignment_counts.png")
    _plot_alt_fraction(assignments, figures / "cell_alt_fraction_by_assignment.png")
    _plot_snp_depth(snp_qc, figures / "snp_depth_distribution.png")

    object_path = objects / "genotype_demux_public_fixture_object.json"
    object_path.write_text(
        json.dumps(
            {
                "input_dir": str(input_dir),
                "source_url": source_url,
                "n_cells": int(n_cells),
                "n_snps": int(n_snps),
                "ad_matrix": str(ad_path),
                "dp_matrix": str(dp_path),
                "vcf": str(vcf_path),
                "samples": str(samples_path),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "validation_scope": "public_vireo_cellsnp_matrix_import_and_handoff",
        "dataset": "single-cell-genetics/vireo data/cellSNP_mat",
        "source_url": source_url,
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "status": "ready",
        "n_cells": int(n_cells),
        "n_features": int(n_snps),
        "n_samples": int(donor_summary.shape[0]),
        "figures": [str(path) for path in sorted(figures.glob("*.png"))],
        "tables": [str(path) for path in sorted(tables.glob("*.tsv"))],
        "objects": {"json": str(object_path)},
        "limitations": [
            "该 public fixture 验证 cellsnp-lite/vireo 矩阵导入和 handoff，不等于从 BAM/VCF 重跑完整 demultiplex。",
            "assignment 是 assignment-ready 分箱摘要，不是 vireo 概率模型正式 donor call。",
        ],
    }
    add_validation_guard_fields(
        manifest,
        validation_kind="public",
        validation_scope="Public vireo cellSNP matrix fixture validation for genotype demultiplex import and handoff.",
    )
    (output_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_report(manifest, reports / "report.md", reports / "report.html")
    return manifest


def _write_genotype_mvp_table(
    tables: Path,
    filename: str,
    frame: pd.DataFrame,
    *,
    input_dir: Path,
    source_dataset: str,
) -> None:
    coerced = _coerce_mvp_table_schema(
        "genotype_demux",
        filename,
        frame,
        matrix=None,
        samples=None,
        analysis_fields={"analysis_level": "validated_backend", "delivery_allowed": False},
        run_id=os.environ.get("SLURM_JOB_ID") or "local_public_validation",
        source_dataset=source_dataset,
        input_artifact=str(input_dir),
        input_modality="cellsnp_output",
    )
    coerced.to_csv(tables / filename, sep="\t", index=False)


def _summarize_mtx(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        line = handle.readline()
        if not line.startswith("%%MatrixMarket"):
            raise ValueError(f"Not a MatrixMarket file: {path}")
        for line in handle:
            if not line.startswith("%"):
                n_rows, n_cols, nnz = (int(value) for value in line.split()[:3])
                break
        else:
            raise ValueError(f"Missing MatrixMarket dimension line: {path}")
        row_sums = np.zeros(n_rows, dtype=float)
        col_sums = np.zeros(n_cols, dtype=float)
        row_nnz = np.zeros(n_rows, dtype=int)
        for line in handle:
            if not line.strip():
                continue
            row, col, value = line.split()[:3]
            row_idx = int(row) - 1
            col_idx = int(col) - 1
            count = float(value)
            row_sums[row_idx] += count
            col_sums[col_idx] += count
            row_nnz[row_idx] += 1
    return {"shape": (n_rows, n_cols), "nnz": nnz, "row_sums": row_sums, "col_sums": col_sums, "row_nnz": row_nnz}


def _read_samples(path: Path, expected: int) -> list[str]:
    cells = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(cells) != expected:
        raise ValueError(f"Sample count mismatch: {len(cells)} samples vs {expected} matrix cells")
    return cells


def _read_vcf_variants(path: Path, expected: int) -> pd.DataFrame:
    rows = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("#"):
                continue
            chrom, pos, variant_id, ref, alt, *_ = line.rstrip("\n").split("\t")
            rows.append({"variant_id": variant_id if variant_id != "." else f"{chrom}:{pos}:{ref}>{alt}", "chrom": chrom, "pos": int(pos), "ref": ref, "alt": alt})
    if len(rows) != expected:
        raise ValueError(f"Variant count mismatch: {len(rows)} VCF variants vs {expected} matrix rows")
    return pd.DataFrame(rows)


def _assignment_ready_bins(alt_fraction: np.ndarray, depth: np.ndarray) -> np.ndarray:
    labels = np.array(["low_alt_fraction", "mid_alt_fraction", "high_alt_fraction"], dtype=object)
    bins = np.digitize(alt_fraction, bins=[0.32, 0.65], right=False)
    assignment = labels[bins]
    assignment = assignment.astype(object)
    assignment[depth <= 0] = "unassigned_no_depth"
    return assignment


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


def _plot_snp_depth(frame: pd.DataFrame, path: Path) -> None:
    plt.figure(figsize=(6, 4))
    plt.hist(frame["dp_sum"], bins=40, color="#6D83B6")
    plt.xlabel("Depth per SNP")
    plt.ylabel("SNPs")
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
