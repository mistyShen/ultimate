from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns


CLINICAL_JOURNAL_STYLE: dict[str, Any] = {
    "style_id": "clinical_journal_v1",
    "style_cn": "临床期刊版",
    "font_family": "DejaVu Sans",
    "background": "#FFFFFF",
    "text": "#1F2937",
    "axis": "#334155",
    "grid": "#E5E7EB",
    "muted": "#64748B",
    "primary": "#2F5D8C",
    "secondary": "#6F8FAF",
    "case": "#B42318",
    "control": "#1D4ED8",
    "accent": "#0F766E",
    "neutral": "#94A3B8",
    "heatmap_cmap": "vlag",
    "dpi": 180,
    "figure_format": "png",
}


def apply_clinical_journal_style(style: dict[str, Any] | None = None) -> dict[str, Any]:
    tokens = {**CLINICAL_JOURNAL_STYLE, **(style or {})}
    sns.set_theme(
        context="paper",
        style="whitegrid",
        font=tokens["font_family"],
        rc={
            "figure.facecolor": tokens["background"],
            "axes.facecolor": tokens["background"],
            "axes.edgecolor": tokens["axis"],
            "axes.labelcolor": tokens["text"],
            "axes.titlecolor": tokens["text"],
            "grid.color": tokens["grid"],
            "grid.linewidth": 0.7,
            "text.color": tokens["text"],
            "xtick.color": tokens["axis"],
            "ytick.color": tokens["axis"],
            "legend.frameon": False,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "savefig.facecolor": tokens["background"],
            "savefig.bbox": "tight",
        },
    )
    return tokens


def write_style_manifest(output_dir: Path, style: dict[str, Any] | None = None) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    tokens = apply_clinical_journal_style(style)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "style": tokens,
        "rules": {
            "background": "white",
            "primary_palette": "blue-gray",
            "difference_encoding": "red for case/up, blue for control/down",
            "exports": "png by default; pdf/svg supported by callers",
        },
    }
    path = output_dir / "style_manifest.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def save_figure(path: Path, *, style: dict[str, Any] | None = None, formats: tuple[str, ...] = ("png",)) -> list[str]:
    tokens = apply_clinical_journal_style(style)
    path.parent.mkdir(parents=True, exist_ok=True)
    saved = []
    for fmt in formats:
        target = path.with_suffix(f".{fmt}")
        plt.savefig(target, dpi=int(tokens.get("dpi", 180)))
        saved.append(str(target))
    plt.close()
    return saved


def write_figure_manifest(rows: list[dict[str, Any]], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "figure_manifest.tsv"
    columns = ["figure_id", "module", "kind", "path", "style_id", "title", "status"]
    pd.DataFrame(rows, columns=columns).to_csv(path, sep="\t", index=False)
    return path


def generate_style_review(output_dir: Path, *, style: dict[str, Any] | None = None) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    tokens = apply_clinical_journal_style(style)
    style_manifest = write_style_manifest(output_dir, tokens)
    rows = []

    rng = np.random.default_rng(2026)
    groups = np.array(["Control"] * 20 + ["Tumor"] * 20)
    x = np.r_[rng.normal(0, 0.8, 20), rng.normal(2.4, 0.9, 20)]
    y = np.r_[rng.normal(0, 0.9, 20), rng.normal(1.5, 0.8, 20)]
    _figure_pca(output_dir / "pca_review.png", x, y, groups, tokens)
    rows.append(_row("style_pca", "style_review", "pca", output_dir / "pca_review.png", "PCA 风格样例", tokens))

    _figure_umap(output_dir / "umap_review.png", x, y, groups, tokens)
    rows.append(_row("style_umap", "style_review", "umap", output_dir / "umap_review.png", "UMAP 风格样例", tokens))

    stats = pd.DataFrame(
        {
            "log2FC": rng.normal(0, 1.4, 240),
            "padj": np.clip(rng.beta(0.7, 6, 240), 1e-6, 1),
        }
    )
    _figure_volcano(output_dir / "volcano_review.png", stats, tokens)
    rows.append(_row("style_volcano", "style_review", "volcano", output_dir / "volcano_review.png", "火山图风格样例", tokens))

    matrix = pd.DataFrame(rng.normal(0, 1, (18, 8)), index=[f"Gene{i:02d}" for i in range(18)])
    _figure_heatmap(output_dir / "heatmap_review.png", matrix, tokens)
    rows.append(_row("style_heatmap", "style_review", "heatmap", output_dir / "heatmap_review.png", "热图风格样例", tokens))

    qc = pd.DataFrame({"group": groups, "nFeature": np.r_[rng.normal(2800, 350, 20), rng.normal(3400, 450, 20)]})
    _figure_qc_violin(output_dir / "qc_violin_review.png", qc, tokens)
    rows.append(_row("style_qc_violin", "style_review", "qc_violin", output_dir / "qc_violin_review.png", "QC 小提琴图风格样例", tokens))

    _figure_km(output_dir / "km_review.png", tokens)
    rows.append(_row("style_km", "style_review", "km", output_dir / "km_review.png", "KM 曲线风格样例", tokens))

    _figure_spatial(output_dir / "spatial_review.png", rng, tokens)
    rows.append(_row("style_spatial", "style_review", "spatial", output_dir / "spatial_review.png", "空间散点风格样例", tokens))

    figure_manifest = write_figure_manifest(rows, output_dir)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "ready_for_review",
        "style_manifest": str(style_manifest),
        "figure_manifest": str(figure_manifest),
        "figures": [row["path"] for row in rows],
    }
    manifest_path = output_dir / "style_review_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def _row(figure_id: str, module: str, kind: str, path: Path, title: str, tokens: dict[str, Any]) -> dict[str, str]:
    return {
        "figure_id": figure_id,
        "module": module,
        "kind": kind,
        "path": str(path),
        "style_id": str(tokens["style_id"]),
        "title": title,
        "status": "ready",
    }


def _palette(tokens: dict[str, Any]) -> dict[str, str]:
    return {"Control": tokens["control"], "Tumor": tokens["case"], "control": tokens["control"], "treated": tokens["case"]}


def _figure_pca(path: Path, x: np.ndarray, y: np.ndarray, groups: np.ndarray, tokens: dict[str, Any]) -> None:
    plt.figure(figsize=(5.4, 4.2))
    sns.scatterplot(x=x, y=y, hue=groups, palette=_palette(tokens), s=42, edgecolor="white", linewidth=0.4)
    plt.title("PCA")
    plt.xlabel("PC1 (31.2%)")
    plt.ylabel("PC2 (18.7%)")
    plt.tight_layout()
    save_figure(path, style=tokens)


def _figure_umap(path: Path, x: np.ndarray, y: np.ndarray, groups: np.ndarray, tokens: dict[str, Any]) -> None:
    plt.figure(figsize=(5.4, 4.2))
    sns.scatterplot(x=np.tanh(x) + x / 4, y=np.tanh(y) + y / 4, hue=groups, palette=_palette(tokens), s=30, alpha=0.88, linewidth=0)
    plt.title("UMAP")
    plt.xlabel("UMAP_1")
    plt.ylabel("UMAP_2")
    plt.tight_layout()
    save_figure(path, style=tokens)


def _figure_volcano(path: Path, stats: pd.DataFrame, tokens: dict[str, Any]) -> None:
    frame = stats.copy()
    frame["neg_log10_padj"] = -np.log10(frame["padj"])
    frame["class"] = np.where(frame["log2FC"] > 1, "Up", np.where(frame["log2FC"] < -1, "Down", "NS"))
    palette = {"Up": tokens["case"], "Down": tokens["control"], "NS": tokens["neutral"]}
    plt.figure(figsize=(5.6, 4.4))
    sns.scatterplot(data=frame, x="log2FC", y="neg_log10_padj", hue="class", palette=palette, s=18, linewidth=0, alpha=0.85)
    plt.axvline(1, color=tokens["muted"], linestyle="--", linewidth=0.8)
    plt.axvline(-1, color=tokens["muted"], linestyle="--", linewidth=0.8)
    plt.title("Volcano")
    plt.xlabel("log2FC")
    plt.ylabel("-log10(adj. P)")
    plt.tight_layout()
    save_figure(path, style=tokens)


def _figure_heatmap(path: Path, matrix: pd.DataFrame, tokens: dict[str, Any]) -> None:
    plt.figure(figsize=(6.2, 5.2))
    sns.heatmap(matrix, cmap=tokens["heatmap_cmap"], center=0, yticklabels=True, xticklabels=False, cbar_kws={"label": "Z-score"})
    plt.title("Top markers")
    plt.tight_layout()
    save_figure(path, style=tokens)


def _figure_qc_violin(path: Path, qc: pd.DataFrame, tokens: dict[str, Any]) -> None:
    plt.figure(figsize=(4.8, 4.2))
    sns.violinplot(
        data=qc,
        x="group",
        y="nFeature",
        hue="group",
        palette=_palette(tokens),
        inner="quartile",
        linewidth=0.8,
        legend=False,
    )
    plt.title("QC: detected features")
    plt.xlabel("")
    plt.ylabel("nFeature")
    plt.tight_layout()
    save_figure(path, style=tokens)


def _figure_km(path: Path, tokens: dict[str, Any]) -> None:
    months = np.arange(0, 61, 6)
    high = np.exp(-months / 34)
    low = np.exp(-months / 58)
    plt.figure(figsize=(5.4, 4.2))
    plt.step(months, high, where="post", label="High risk", color=tokens["case"], linewidth=1.7)
    plt.step(months, low, where="post", label="Low risk", color=tokens["control"], linewidth=1.7)
    plt.title("Kaplan-Meier")
    plt.xlabel("Months")
    plt.ylabel("Survival probability")
    plt.ylim(0, 1.02)
    plt.legend()
    plt.tight_layout()
    save_figure(path, style=tokens)


def _figure_spatial(path: Path, rng: np.random.Generator, tokens: dict[str, Any]) -> None:
    coords = rng.uniform(0, 1, (320, 2))
    score = np.sin(coords[:, 0] * 8) + np.cos(coords[:, 1] * 7)
    plt.figure(figsize=(5.2, 4.6))
    scatter = plt.scatter(coords[:, 0], coords[:, 1], c=score, cmap=tokens["heatmap_cmap"], s=18, linewidth=0)
    plt.colorbar(scatter, label="Signature score")
    plt.title("Spatial signature")
    plt.axis("equal")
    plt.axis("off")
    plt.tight_layout()
    save_figure(path, style=tokens)
