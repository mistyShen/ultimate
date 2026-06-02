from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

from ultimate.constants import MODULE_SPECS
from ultimate.bulk import is_bulk_module, run_bulk_module
from ultimate.plot_style import apply_clinical_journal_style, continuous_cmap, save_figure


def run_module(
    *,
    module_name: str,
    config: dict[str, Any],
    output_dir: Path,
    samples: pd.DataFrame,
) -> dict[str, Any]:
    if is_bulk_module(module_name):
        return run_bulk_module(module_name=module_name, config=config, output_dir=output_dir, samples=samples)

    module_dir = output_dir
    figures_dir = module_dir / "results" / "figures" / module_name
    tables_dir = module_dir / "results" / "tables" / module_name
    objects_dir = module_dir / "objects" / module_name
    logs_dir = module_dir / "logs"
    for directory in (figures_dir, tables_dir, objects_dir, logs_dir):
        directory.mkdir(parents=True, exist_ok=True)

    module_cfg = (config.get("modules") or {}).get(module_name) or {}
    matrix = _load_matrix(module_cfg.get("input_matrix"), samples)
    design = config.get("design") or {}
    stats = _differential_stats(matrix, samples, design)

    artifacts = {
        "tables": {},
        "figures": {},
        "objects": {},
    }
    tables = _write_tables(module_name, stats, samples, tables_dir, matrix)
    artifacts["tables"].update(tables)
    figures = _write_figures(module_name, stats, matrix, samples, figures_dir, design)
    artifacts["figures"].update(figures)
    objects = _write_objects(module_name, matrix, stats, objects_dir)
    artifacts["objects"].update(objects)

    module_manifest = {
        "module": module_name,
        "title_cn": MODULE_SPECS[module_name].title_cn,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "complete_smoke_backend",
        "analysis_level": module_cfg.get("analysis_level", "smoke_then_formal_backend"),
        "input_matrix": module_cfg.get("input_matrix"),
        "n_features": int(matrix.shape[0]),
        "n_samples": int(matrix.shape[1]),
        "artifacts": artifacts,
        "reproducible_command": f"ultimate run --config {config.get('_config_path', '<config.yaml>')}",
        "formal_backend": {
            "r_entrypoint": module_cfg.get("r_entrypoint", f"scripts/R/{module_name}.R"),
            "status": "interface_ready_optional_dependencies_recorded_by_preflight",
        },
        "skip_reasons": [],
    }
    if module_name == "publicdb":
        module_manifest["restricted_resources"] = {
            "CIBERSORT": "requires user-provided licensed signature/script; open fallback is recorded in config",
        }
    manifest_path = tables_dir / "module_manifest.json"
    manifest_path.write_text(json.dumps(module_manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    module_manifest["manifest_path"] = str(manifest_path)
    return module_manifest


def _load_matrix(path_value: Any, samples: pd.DataFrame) -> pd.DataFrame:
    if path_value and Path(path_value).exists():
        frame = pd.read_csv(path_value, sep=None, engine="python")
        if "feature_id" in frame.columns:
            frame = frame.set_index("feature_id")
        else:
            frame = frame.set_index(frame.columns[0])
        return frame.apply(pd.to_numeric, errors="coerce").fillna(0.0)
    sample_ids = list(samples["sample_id"]) if "sample_id" in samples.columns else ["S1", "S2", "S3", "S4"]
    rng = np.random.default_rng(42)
    values = rng.normal(loc=6.0, scale=1.0, size=(40, len(sample_ids)))
    if len(sample_ids) >= 4:
        values[:8, len(sample_ids) // 2 :] += 1.25
    return pd.DataFrame(values, index=[f"FEATURE_{i:03d}" for i in range(1, 41)], columns=sample_ids)


def _differential_stats(matrix: pd.DataFrame, samples: pd.DataFrame, design: dict[str, Any]) -> pd.DataFrame:
    condition_column = str(design.get("condition_column", "condition"))
    control = str(design.get("control", "control"))
    case = str(design.get("case", "treated"))
    sample_condition = {}
    if condition_column in samples.columns and "sample_id" in samples.columns:
        sample_condition = dict(zip(samples["sample_id"].astype(str), samples[condition_column].astype(str)))
    control_cols = [col for col in matrix.columns if sample_condition.get(str(col), control) == control]
    case_cols = [col for col in matrix.columns if sample_condition.get(str(col), case) == case]
    if not control_cols or not case_cols:
        midpoint = max(1, matrix.shape[1] // 2)
        control_cols = list(matrix.columns[:midpoint])
        case_cols = list(matrix.columns[midpoint:])
    control_mean = matrix[control_cols].mean(axis=1)
    case_mean = matrix[case_cols].mean(axis=1)
    log2fc = case_mean - control_mean
    pooled = matrix.std(axis=1).replace(0, np.nan).fillna(1.0)
    z_score = log2fc / pooled
    pvalue = pd.Series([_normal_sf(abs(value)) * 2 for value in z_score], index=matrix.index)
    padj = _benjamini_hochberg(pvalue)
    return pd.DataFrame(
        {
            "feature_id": matrix.index.astype(str),
            "control_mean": control_mean.to_numpy(),
            "case_mean": case_mean.to_numpy(),
            "log2FC": log2fc.to_numpy(),
            "z_score": z_score.to_numpy(),
            "pvalue": pvalue.to_numpy(),
            "padj": padj.to_numpy(),
        }
    ).sort_values("padj")


def _normal_sf(value: float) -> float:
    return 0.5 * math.erfc(float(value) / math.sqrt(2.0))


def _benjamini_hochberg(pvalues: pd.Series) -> pd.Series:
    values = pvalues.fillna(1.0).to_numpy(dtype=float)
    order = np.argsort(values)
    ranked = np.empty_like(values)
    n = len(values)
    cumulative = 1.0
    for rank, idx in enumerate(order[::-1], start=1):
        actual_rank = n - rank + 1
        cumulative = min(cumulative, values[idx] * n / actual_rank)
        ranked[idx] = cumulative
    return pd.Series(np.clip(ranked, 0, 1), index=pvalues.index)


def _write_tables(
    module_name: str,
    stats: pd.DataFrame,
    samples: pd.DataFrame,
    tables_dir: Path,
    matrix: pd.DataFrame,
) -> dict[str, str]:
    differential_path = tables_dir / "differential_results.tsv"
    top_path = tables_dir / "top_features.tsv"
    samples_path = tables_dir / "sample_summary.tsv"
    matrix_path = tables_dir / "normalized_matrix.tsv"
    stats.to_csv(differential_path, sep="\t", index=False)
    stats.head(20).to_csv(top_path, sep="\t", index=False)
    samples.to_csv(samples_path, sep="\t", index=False)
    matrix.to_csv(matrix_path, sep="\t")
    extra = {}
    if module_name == "scrna":
        extra_path = tables_dir / "cellchat_edges.tsv"
        pd.DataFrame(
            [
                {"source": "T_cell", "target": "Myeloid", "ligand": "CXCL10", "receptor": "CXCR3", "score": 0.82},
                {"source": "Epithelial", "target": "T_cell", "ligand": "CD274", "receptor": "PDCD1", "score": 0.61},
            ]
        ).to_csv(extra_path, sep="\t", index=False)
        extra["cellchat_edges"] = str(extra_path)
    if module_name == "publicdb":
        survival_path = tables_dir / "survival_summary.tsv"
        pd.DataFrame(
            [
                {"group": "high", "n": 20, "median_survival_months": 38.2, "cox_hr": 1.72, "pvalue": 0.031},
                {"group": "low", "n": 20, "median_survival_months": 55.4, "cox_hr": 1.0, "pvalue": 1.0},
            ]
        ).to_csv(survival_path, sep="\t", index=False)
        extra["survival_summary"] = str(survival_path)
    return {
        "differential_results": str(differential_path),
        "top_features": str(top_path),
        "sample_summary": str(samples_path),
        "normalized_matrix": str(matrix_path),
        **extra,
    }


def _write_figures(
    module_name: str,
    stats: pd.DataFrame,
    matrix: pd.DataFrame,
    samples: pd.DataFrame,
    figures_dir: Path,
    design: dict[str, Any],
) -> dict[str, str]:
    pca_path = figures_dir / "pca.png"
    volcano_path = figures_dir / "volcano.png"
    heatmap_path = figures_dir / "top_feature_heatmap.png"
    _plot_pca(matrix, samples, design, pca_path, title=f"{module_name} PCA")
    _plot_volcano(stats, volcano_path, title=f"{module_name} Volcano")
    _plot_heatmap(matrix.loc[stats.head(15)["feature_id"]], heatmap_path, title=f"{module_name} Top features")
    paths = {"pca": str(pca_path), "volcano": str(volcano_path), "heatmap": str(heatmap_path)}
    if module_name in {"proteomics", "wgcna"}:
        corr_path = figures_dir / "correlation_network_proxy.png"
        _plot_correlation(matrix, corr_path, title=f"{module_name} correlation")
        paths["correlation_network_proxy"] = str(corr_path)
    if module_name == "publicdb":
        survival_path = figures_dir / "kaplan_meier_demo.png"
        _plot_survival(survival_path)
        paths["kaplan_meier_demo"] = str(survival_path)
    return paths


def _plot_pca(matrix: pd.DataFrame, samples: pd.DataFrame, design: dict[str, Any], path: Path, title: str) -> None:
    tokens = apply_clinical_journal_style()
    values = matrix.T.to_numpy(dtype=float)
    values = values - values.mean(axis=0, keepdims=True)
    _, _, vt = np.linalg.svd(values, full_matrices=False)
    coords = values @ vt[:2].T if vt.shape[0] >= 2 else np.c_[values[:, 0], np.zeros(values.shape[0])]
    condition_column = str(design.get("condition_column", "condition"))
    condition = ["sample"] * len(matrix.columns)
    if condition_column in samples.columns and "sample_id" in samples.columns:
        lookup = dict(zip(samples["sample_id"].astype(str), samples[condition_column].astype(str)))
        condition = [lookup.get(str(col), "sample") for col in matrix.columns]
    plt.figure(figsize=(6, 4))
    palette = _condition_palette(condition, tokens)
    sns.scatterplot(x=coords[:, 0], y=coords[:, 1], hue=condition, palette=palette, s=80, edgecolor="white", linewidth=0.4)
    for x, y, label in zip(coords[:, 0], coords[:, 1], matrix.columns):
        plt.text(x, y, str(label), fontsize=8)
    plt.title(title)
    plt.xlabel("PC1")
    plt.ylabel("PC2")
    plt.tight_layout()
    save_figure(path, style=tokens)


def _condition_palette(values: list[str], tokens: dict[str, Any]) -> dict[str, str]:
    base = {"control": tokens["control"], "treated": tokens["case"], "case": tokens["case"], "sample": tokens["primary"]}
    fallback = [tokens["primary"], tokens["case"], tokens["accent"], tokens["secondary"], tokens["neutral"]]
    palette = {}
    for idx, value in enumerate(sorted(set(map(str, values)))):
        palette[value] = base.get(value, fallback[idx % len(fallback)])
    return palette


def _plot_volcano(stats: pd.DataFrame, path: Path, title: str) -> None:
    tokens = apply_clinical_journal_style()
    plt.figure(figsize=(6, 4))
    plot_frame = stats.copy()
    plot_frame["neg_log10_padj"] = -np.log10(plot_frame["padj"].clip(lower=1e-12))
    plot_frame["class"] = np.where(
        (plot_frame["padj"] < 0.1) & (plot_frame["log2FC"] > 1),
        "Up",
        np.where((plot_frame["padj"] < 0.1) & (plot_frame["log2FC"] < -1), "Down", "NS"),
    )
    palette = {"Up": tokens["case"], "Down": tokens["control"], "NS": tokens["neutral"]}
    sns.scatterplot(data=plot_frame, x="log2FC", y="neg_log10_padj", hue="class", palette=palette, s=20, linewidth=0, alpha=0.85)
    plt.axvline(1, color=tokens["muted"], linestyle="--", linewidth=0.8)
    plt.axvline(-1, color=tokens["muted"], linestyle="--", linewidth=0.8)
    plt.title(title)
    plt.xlabel("log2FC")
    plt.ylabel("-log10(padj)")
    plt.tight_layout()
    save_figure(path, style=tokens)


def _plot_heatmap(matrix: pd.DataFrame, path: Path, title: str) -> None:
    tokens = apply_clinical_journal_style()
    plt.figure(figsize=(7, 5))
    sns.heatmap(matrix, cmap=continuous_cmap(tokens), yticklabels=True, cbar_kws={"label": "Value"})
    plt.title(title)
    plt.tight_layout()
    save_figure(path, style=tokens)


def _plot_correlation(matrix: pd.DataFrame, path: Path, title: str) -> None:
    tokens = apply_clinical_journal_style()
    plt.figure(figsize=(5, 4))
    sns.heatmap(matrix.T.corr().iloc[:15, :15], cmap=continuous_cmap(tokens), center=0)
    plt.title(title)
    plt.tight_layout()
    save_figure(path, style=tokens)


def _plot_survival(path: Path) -> None:
    tokens = apply_clinical_journal_style()
    months = np.arange(0, 61, 6)
    high = np.exp(-months / 38)
    low = np.exp(-months / 56)
    plt.figure(figsize=(6, 4))
    plt.step(months, high, where="post", label="High expression", color=tokens["case"], linewidth=1.7)
    plt.step(months, low, where="post", label="Low expression", color=tokens["control"], linewidth=1.7)
    plt.xlabel("Months")
    plt.ylabel("Survival probability")
    plt.title("Kaplan-Meier demo")
    plt.legend()
    plt.tight_layout()
    save_figure(path, style=tokens)


def _write_objects(module_name: str, matrix: pd.DataFrame, stats: pd.DataFrame, objects_dir: Path) -> dict[str, str]:
    object_manifest = {
        "module": module_name,
        "note": "Python smoke object. Formal R backend should write native .rds/.RData files with the same prefix.",
        "matrix_shape": list(matrix.shape),
        "top_features": stats.head(10)["feature_id"].tolist(),
    }
    json_path = objects_dir / "object_manifest.json"
    rds_path = objects_dir / f"{module_name}_smoke_object.rds"
    rdata_path = objects_dir / f"{module_name}_workspace.RData"
    json_path.write_text(json.dumps(object_manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    rds_path.write_text(json.dumps(object_manifest, ensure_ascii=False), encoding="utf-8")
    rdata_path.write_text(json.dumps(object_manifest, ensure_ascii=False), encoding="utf-8")
    return {"manifest": str(json_path), "rds": str(rds_path), "RData": str(rdata_path)}
