#!/usr/bin/env python3
from __future__ import annotations

import argparse
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
    parser = argparse.ArgumentParser(description="Validate Perturb-seq guide assignment and perturbation summary outputs.")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--input-h5ad", type=Path, default=None, help="Optional public Perturb-seq h5ad with perturbation metadata.")
    parser.add_argument("--source-url", default="", help="Public data source URL recorded in the manifest.")
    parser.add_argument("--max-cells", type=int, default=6000)
    parser.add_argument("--n-cells", type=int, default=240)
    parser.add_argument("--n-genes", type=int, default=80)
    parser.add_argument("--seed", type=int, default=29)
    args = parser.parse_args()
    if args.input_h5ad:
        manifest = run_public_h5ad_validation(
            args.input_h5ad,
            args.output_dir,
            source_url=args.source_url,
            max_cells=args.max_cells,
            seed=args.seed,
        )
    else:
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
    add_validation_guard_fields(
        manifest,
        validation_kind="synthetic",
        validation_scope="Synthetic Perturb-seq guide assignment demo validation",
    )
    (output_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_report(manifest, reports / "report.md", reports / "report.html")
    return manifest


def run_public_h5ad_validation(input_h5ad: Path, output_dir: Path, *, source_url: str = "", max_cells: int = 6000, seed: int = 29) -> dict:
    figures = output_dir / "results" / "figures"
    tables = output_dir / "results" / "tables"
    objects = output_dir / "objects"
    reports = output_dir / "reports"
    for directory in (figures, tables, objects, reports):
        directory.mkdir(parents=True, exist_ok=True)

    cells, n_vars, read_summary = _read_perturb_h5ad_obs(input_h5ad, max_cells=max_cells, seed=seed)
    cells.to_csv(tables / "guide_assignments.tsv", sep="\t", index=False)
    _write_perturb_mvp_table(
        tables,
        "guide_assignment.tsv",
        pd.DataFrame(
            {
                "cell_id": cells["cell_id"],
                "guide_id": cells["guide_id"],
                "target_gene": cells["guide_id"].map(_target_gene_from_guide),
                "assignment_class": np.where(cells["condition"].eq("control_like"), "control", "targeting"),
                "confidence": 1.0,
                "multiplet_strategy": "single_guide_metadata_handoff",
            }
        ),
        input_h5ad=input_h5ad,
        source_dataset="pertpy Adamson 2016 pilot Perturb-seq fixture",
    )
    _write_perturb_mvp_table(
        tables,
        "guide_qc.tsv",
        pd.DataFrame(
            {
                "cell_id": cells["cell_id"],
                "guide_id": cells["guide_id"],
                "guide_count": 1,
                "assignment_status": "assigned_from_public_h5ad_metadata",
                "multiplet_warning": "Public fixture validates metadata import; multi-guide handling remains project-specific.",
            }
        ),
        input_h5ad=input_h5ad,
        source_dataset="pertpy Adamson 2016 pilot Perturb-seq fixture",
    )

    guide_summary = cells.groupby("guide_id", observed=False).size().rename("n_cells").reset_index()
    guide_summary["fraction"] = guide_summary["n_cells"] / guide_summary["n_cells"].sum()
    guide_summary.to_csv(tables / "guide_assignment_summary.tsv", sep="\t", index=False)

    perturb_summary = (
        cells.groupby(["guide_id", "perturbation_type"], observed=False)
        .agg(n_cells=("cell_id", "size"), mean_ncounts=("ncounts", "mean"), mean_ngenes=("ngenes", "mean"))
        .reset_index()
    )
    _write_perturb_mvp_table(
        tables,
        "perturbation_summary.tsv",
        pd.DataFrame(
            {
                "perturbation": perturb_summary["guide_id"],
                "target_gene": perturb_summary["guide_id"].map(_target_gene_from_guide),
                "cell_count": perturb_summary["n_cells"],
                "control_status": np.where(
                    perturb_summary["perturbation_type"].astype(str).str.contains("control|ctrl|ntc", case=False, regex=True),
                    "control_like",
                    "targeting",
                ),
            }
        ),
        input_h5ad=input_h5ad,
        source_dataset="pertpy Adamson 2016 pilot Perturb-seq fixture",
    )

    control_mask = cells["perturbation_type"].astype(str).str.contains("control|ctrl|ntc", case=False, regex=True)
    if not control_mask.any():
        control_mask = cells["guide_id"].astype(str).str.contains("control|ctrl|ntc", case=False, regex=True)
    control_mean_counts = float(cells.loc[control_mask, "ncounts"].mean()) if control_mask.any() else float(cells["ncounts"].mean())
    control_mean_genes = float(cells.loc[control_mask, "ngenes"].mean()) if control_mask.any() else float(cells["ngenes"].mean())
    effect = perturb_summary.copy()
    effect["contrast"] = effect["guide_id"].astype(str) + "_vs_control_like"
    effect["log2fc_ncounts"] = np.log2((effect["mean_ncounts"] + 1.0) / (control_mean_counts + 1.0))
    effect["log2fc_ngenes"] = np.log2((effect["mean_ngenes"] + 1.0) / (control_mean_genes + 1.0))
    effect["effect_status"] = "design_ready_qc_metric_only"
    effect.to_csv(tables / "perturbation_de_summary.tsv", sep="\t", index=False)
    _write_perturb_mvp_table(
        tables,
        "perturbation_expression_effect.tsv",
        pd.DataFrame(
            {
                "perturbation": effect["guide_id"],
                "target_gene": effect["guide_id"].map(_target_gene_from_guide),
                "feature_id": "ncounts",
                "effect_size": effect["log2fc_ncounts"],
                "model_status": effect["effect_status"],
            }
        ),
        input_h5ad=input_h5ad,
        source_dataset="pertpy Adamson 2016 pilot Perturb-seq fixture",
    )
    pseudobulk = effect.rename(columns={"mean_ncounts": "pseudobulk_ncounts_mean", "mean_ngenes": "pseudobulk_ngenes_mean"})
    _write_perturb_mvp_table(
        tables,
        "pseudobulk_by_perturbation.tsv",
        pd.DataFrame(
            {
                "perturbation": pseudobulk["guide_id"],
                "feature_id": "ncounts_mean",
                "count_value": pseudobulk["pseudobulk_ncounts_mean"],
                "design_ready_status": pseudobulk["effect_status"],
            }
        ),
        input_h5ad=input_h5ad,
        source_dataset="pertpy Adamson 2016 pilot Perturb-seq fixture",
    )
    _write_perturb_mvp_table(
        tables,
        "target_response.tsv",
        pd.DataFrame(
            {
                "target_gene": effect["guide_id"].map(_target_gene_from_guide),
                "response_feature": "ncounts",
                "effect_size": effect["log2fc_ncounts"],
                "mechanism_warning": "QC-level public fixture effect; not a mechanistic perturbation model.",
            }
        ),
        input_h5ad=input_h5ad,
        source_dataset="pertpy Adamson 2016 pilot Perturb-seq fixture",
    )

    signature = effect[["contrast", "log2fc_ncounts", "log2fc_ngenes", "n_cells", "effect_status"]].copy()
    signature["top10_abs_log2fc_mean"] = signature[["log2fc_ncounts", "log2fc_ngenes"]].abs().mean(axis=1)
    signature.to_csv(tables / "perturbation_signature_scores.tsv", sep="\t", index=False)
    pd.DataFrame(
        [
            {
                "backend": "pertpy_or_DE_model",
                "input_mode": "h5ad_with_perturbation_metadata",
                "status": "handoff_ready",
                "note": "Public fixture validates perturbation metadata import and design-ready summaries. Formal gene-level perturbation model remains a handoff/backend step.",
            }
        ]
    ).to_csv(tables / "perturbation_model_handoff.tsv", sep="\t", index=False)

    _plot_guide_counts(guide_summary.head(30), figures / "guide_assignment_counts.png")
    _plot_public_effect(effect.head(30), figures / "perturbation_qc_effects.png")
    _plot_signature(signature.head(30), figures / "perturbation_signature_scores.png")

    object_path = objects / "perturb_seq_public_fixture_object.json"
    object_path.write_text(
        json.dumps(
            {
                "input_h5ad": str(input_h5ad),
                "source_url": source_url,
                "n_cells": int(cells.shape[0]),
                "n_genes": int(n_vars),
                "n_perturbations": int(guide_summary.shape[0]),
                **read_summary,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "validation_scope": "public_adamson_perturbseq_metadata_import_and_handoff",
        "dataset": "pertpy Adamson 2016 pilot Perturb-seq fixture",
        "source_url": source_url,
        "input_h5ad": str(input_h5ad),
        "output_dir": str(output_dir),
        "status": "ready",
        "n_cells": int(cells.shape[0]),
        "n_features": int(n_vars),
        "n_guides": int(guide_summary.shape[0]),
        "figures": [str(path) for path in sorted(figures.glob("*.png"))],
        "tables": [str(path) for path in sorted(tables.glob("*.tsv"))],
        "objects": {"json": str(object_path)},
        "limitations": [
            "该 public fixture 验证 Perturb-seq h5ad perturbation metadata 导入和 design-ready 输出，不等于完整 gene-level perturbation DE 模型。",
            "effect 表基于 ncounts/ngenes QC 指标，仅用于接口验证；正式项目需使用原始表达矩阵和合适统计模型。",
        ],
    }
    add_validation_guard_fields(
        manifest,
        validation_kind="public",
        validation_scope="Public Adamson Perturb-seq h5ad fixture validation for perturbation metadata import and handoff.",
    )
    (output_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_report(manifest, reports / "report.md", reports / "report.html")
    return manifest


def _write_perturb_mvp_table(
    tables: Path,
    filename: str,
    frame: pd.DataFrame,
    *,
    input_h5ad: Path,
    source_dataset: str,
) -> None:
    coerced = _coerce_mvp_table_schema(
        "perturb_seq",
        filename,
        frame,
        matrix=None,
        samples=None,
        analysis_fields={"analysis_level": "validated_backend", "delivery_allowed": False},
        run_id=os.environ.get("SLURM_JOB_ID") or "local_public_validation",
        source_dataset=source_dataset,
        input_artifact=str(input_h5ad),
        input_modality="h5ad",
    )
    coerced.to_csv(tables / filename, sep="\t", index=False)


def _target_gene_from_guide(guide: object) -> str:
    text = str(guide)
    if text.lower() in {"control", "ctrl", "ntc", "non-targeting", "non_targeting"}:
        return "non_targeting"
    return text.split("_", 1)[0].split("-", 1)[0] or "unknown"


def _read_perturb_h5ad_obs(input_h5ad: Path, *, max_cells: int, seed: int) -> tuple[pd.DataFrame, int, dict]:
    try:
        import h5py
    except ModuleNotFoundError as exc:
        raise RuntimeError("Reading Perturb-seq h5ad input requires h5py. Use the scrna environment or install the scrna extra.") from exc

    with h5py.File(input_h5ad, "r") as handle:
        obs = handle["obs"]
        var = handle["var"]
        n_vars = _h5_length(var.get("index")) or _h5_length(var.get("_index")) or _h5_length(var.get("gene_symbol")) or _x_feature_count(handle)
        cell_id = _first_present_column(obs, "cell_barcode", "index", "_index")
        perturbation = _read_obs_column(obs, "perturbation")
        perturbation_type = _read_obs_column(obs, "perturbation_type")
        ncounts = _first_present_numeric_column(obs, "ncounts", "UMI count")
        ngenes = _read_numeric_obs_column(obs, "ngenes")
    if perturbation is None:
        raise ValueError(f"h5ad is missing obs['perturbation']: {input_h5ad}")
    n_obs = len(perturbation)
    if cell_id is None:
        cell_id = [f"cell_{idx:05d}" for idx in range(n_obs)]
    if perturbation_type is None:
        perturbation_type = ["unknown"] * n_obs
    if ncounts is None:
        ncounts = np.zeros(n_obs, dtype=float)
    if ngenes is None:
        ngenes = np.zeros(n_obs, dtype=float)
    cells = pd.DataFrame(
        {
            "cell_id": cell_id,
            "guide_id": perturbation,
            "perturbation_type": perturbation_type,
            "condition": np.where(pd.Series(perturbation_type).astype(str).str.contains("control|ctrl|ntc", case=False, regex=True), "control_like", "perturbed"),
            "ncounts": ncounts,
            "ngenes": ngenes,
        }
    )
    original_cells = int(cells.shape[0])
    if original_cells > max_cells:
        cells = cells.sample(n=max_cells, random_state=seed).sort_values("cell_id").reset_index(drop=True)
    return cells, int(n_vars), {"original_n_cells": original_cells, "max_cells": int(max_cells), "sampling_seed": int(seed)}


def _first_present_column(obs, *keys: str) -> list[str] | None:
    for key in keys:
        values = _read_obs_column(obs, key)
        if values is not None:
            return values
    return None


def _first_present_numeric_column(obs, *keys: str) -> np.ndarray | None:
    for key in keys:
        values = _read_numeric_obs_column(obs, key)
        if values is not None:
            return values
    return None


def _read_obs_column(obs, key: str) -> list[str] | None:
    if key not in obs:
        return None
    obj = obs[key]
    if hasattr(obj, "keys") and "categories" in obj and "codes" in obj:
        categories = [_decode(value) for value in obj["categories"][()]]
        codes = obj["codes"][()]
        return [categories[int(code)] if int(code) >= 0 else "" for code in codes]
    return [_decode(value) for value in obj[()]]


def _read_numeric_obs_column(obs, key: str) -> np.ndarray | None:
    if key not in obs:
        return None
    obj = obs[key]
    if hasattr(obj, "keys"):
        return None
    return np.asarray(obj[()], dtype=float)


def _h5_length(obj) -> int:
    if obj is None:
        return 0
    if hasattr(obj, "keys") and "codes" in obj:
        return len(obj["codes"])
    return len(obj)


def _x_feature_count(handle) -> int:
    if "X" not in handle:
        return 0
    shape = handle["X"].attrs.get("shape")
    if shape is None or len(shape) < 2:
        return 0
    return int(shape[1])


def _decode(value) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


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


def _plot_public_effect(frame: pd.DataFrame, path: Path) -> None:
    plt.figure(figsize=(7, 4))
    plt.bar(frame["guide_id"].astype(str), frame["log2fc_ncounts"], color="#4777A8")
    plt.ylabel("log2FC ncounts vs control-like")
    plt.xticks(rotation=45, ha="right", fontsize=7)
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
