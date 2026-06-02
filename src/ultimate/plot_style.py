from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
import numpy as np
import pandas as pd
import seaborn as sns


STYLE_REGISTRY: dict[str, dict[str, Any]] = {
    "soft_color": {
        "style_id": "clinical_journal_v5_aurora_color",
        "style_cn": "临床期刊版-极光柔彩",
        "font_family": "DejaVu Sans",
        "background": "#FFFFFF",
        "text": "#4B5368",
        "axis": "#7B8498",
        "grid": "#EEF2F7",
        "muted": "#A0A8BA",
        "primary": "#8C6FF7",
        "secondary": "#31C5B7",
        "case": "#F26F8F",
        "control": "#4EA4F5",
        "accent": "#F2B84B",
        "neutral": "#C9D1DE",
        "bar": "#31B7C5",
        "bar_light": "#DDF4F3",
        "bar_highlight": "#F26F8F",
        "heatmap_cmap": "ultimate_soft_diverging",
        "heatmap_low": "#43A5F5",
        "heatmap_mid": "#FBFCFF",
        "heatmap_high": "#F06A8F",
        "dpi": 180,
        "figure_format": "png",
    },
    "okabe_ito": {
        "style_id": "scientific_okabe_ito",
        "style_cn": "Okabe-Ito 色盲友好",
        "font_family": "DejaVu Sans",
        "background": "#FFFFFF",
        "text": "#3E4654",
        "axis": "#667085",
        "grid": "#ECEFF3",
        "muted": "#8B95A5",
        "primary": "#009E73",
        "secondary": "#56B4E9",
        "case": "#D55E00",
        "control": "#0072B2",
        "accent": "#E69F00",
        "neutral": "#B7C0CC",
        "bar": "#56B4E9",
        "bar_light": "#D9EEF7",
        "bar_highlight": "#D55E00",
        "heatmap_cmap": "ultimate_soft_diverging",
        "heatmap_low": "#0072B2",
        "heatmap_mid": "#FAFAFA",
        "heatmap_high": "#D55E00",
        "dpi": 180,
        "figure_format": "png",
    },
    "colorbrewer_set2": {
        "style_id": "colorbrewer_set2_soft",
        "style_cn": "ColorBrewer Set2 柔和分类",
        "font_family": "DejaVu Sans",
        "background": "#FFFFFF",
        "text": "#3F4652",
        "axis": "#667085",
        "grid": "#EEF1F4",
        "muted": "#8F99A8",
        "primary": "#66C2A5",
        "secondary": "#8DA0CB",
        "case": "#FC8D62",
        "control": "#8DA0CB",
        "accent": "#E78AC3",
        "neutral": "#B3B3B3",
        "bar": "#66C2A5",
        "bar_light": "#DDEFEA",
        "bar_highlight": "#FC8D62",
        "heatmap_cmap": "ultimate_soft_diverging",
        "heatmap_low": "#8DA0CB",
        "heatmap_mid": "#FBFBFB",
        "heatmap_high": "#FC8D62",
        "dpi": 180,
        "figure_format": "png",
    },
    "nature_modern": {
        "style_id": "journal_nature_modern",
        "style_cn": "Nature 风格现代科研",
        "font_family": "DejaVu Sans",
        "background": "#FFFFFF",
        "text": "#3D4552",
        "axis": "#697386",
        "grid": "#ECEFF3",
        "muted": "#8A94A3",
        "primary": "#3C5488",
        "secondary": "#00A087",
        "case": "#E64B35",
        "control": "#4DBBD5",
        "accent": "#F39B7F",
        "neutral": "#B9C1CD",
        "bar": "#4DBBD5",
        "bar_light": "#D8EEF4",
        "bar_highlight": "#E64B35",
        "heatmap_cmap": "ultimate_soft_diverging",
        "heatmap_low": "#4DBBD5",
        "heatmap_mid": "#F8FAFC",
        "heatmap_high": "#E64B35",
        "dpi": 180,
        "figure_format": "png",
    },
    "lancet_clinical": {
        "style_id": "journal_lancet_clinical",
        "style_cn": "Lancet 风格临床强化",
        "font_family": "DejaVu Sans",
        "background": "#FFFFFF",
        "text": "#3F4652",
        "axis": "#667085",
        "grid": "#ECEFF3",
        "muted": "#8B95A5",
        "primary": "#00468B",
        "secondary": "#0099B4",
        "case": "#AD002A",
        "control": "#00468B",
        "accent": "#42B540",
        "neutral": "#ADB6B6",
        "bar": "#0099B4",
        "bar_light": "#D8EEF2",
        "bar_highlight": "#AD002A",
        "heatmap_cmap": "ultimate_soft_diverging",
        "heatmap_low": "#00468B",
        "heatmap_mid": "#FAFAFA",
        "heatmap_high": "#AD002A",
        "dpi": 180,
        "figure_format": "png",
    },
    "jama_clean": {
        "style_id": "journal_jama_clean",
        "style_cn": "JAMA 风格清爽克制",
        "font_family": "DejaVu Sans",
        "background": "#FFFFFF",
        "text": "#444B55",
        "axis": "#6B7280",
        "grid": "#EEF0F3",
        "muted": "#929AA6",
        "primary": "#374E55",
        "secondary": "#00A1D5",
        "case": "#B24745",
        "control": "#00A1D5",
        "accent": "#DF8F44",
        "neutral": "#C4C7CE",
        "bar": "#79AF97",
        "bar_light": "#E2EFE9",
        "bar_highlight": "#B24745",
        "heatmap_cmap": "ultimate_soft_diverging",
        "heatmap_low": "#00A1D5",
        "heatmap_mid": "#FBFBFB",
        "heatmap_high": "#B24745",
        "dpi": 180,
        "figure_format": "png",
    },
    "nejm_warm": {
        "style_id": "journal_nejm_warm",
        "style_cn": "NEJM 风格暖色临床",
        "font_family": "DejaVu Sans",
        "background": "#FFFFFF",
        "text": "#444B55",
        "axis": "#6B7280",
        "grid": "#EFEDE9",
        "muted": "#9A95A1",
        "primary": "#0072B5",
        "secondary": "#20854E",
        "case": "#BC3C29",
        "control": "#0072B5",
        "accent": "#E18727",
        "neutral": "#C8C1B8",
        "bar": "#6F99AD",
        "bar_light": "#DDE9EE",
        "bar_highlight": "#BC3C29",
        "heatmap_cmap": "ultimate_soft_diverging",
        "heatmap_low": "#0072B5",
        "heatmap_mid": "#FAFAF7",
        "heatmap_high": "#BC3C29",
        "dpi": 180,
        "figure_format": "png",
    },
    "viridis_teal": {
        "style_id": "scientific_viridis_teal",
        "style_cn": "Viridis 连续值友好",
        "font_family": "DejaVu Sans",
        "background": "#FFFFFF",
        "text": "#3F4652",
        "axis": "#667085",
        "grid": "#EEF1F4",
        "muted": "#8F99A8",
        "primary": "#31688E",
        "secondary": "#35B779",
        "case": "#FDE725",
        "control": "#31688E",
        "accent": "#35B779",
        "neutral": "#B8C2CC",
        "bar": "#35B779",
        "bar_light": "#E2F0E8",
        "bar_highlight": "#FDE725",
        "heatmap_cmap": "viridis",
        "dpi": 180,
        "figure_format": "png",
    },
    "cividis_gold": {
        "style_id": "scientific_cividis_gold",
        "style_cn": "Cividis 蓝金连续值",
        "font_family": "DejaVu Sans",
        "background": "#FFFFFF",
        "text": "#3F4652",
        "axis": "#667085",
        "grid": "#EEF1F4",
        "muted": "#8F99A8",
        "primary": "#365C8D",
        "secondary": "#708090",
        "case": "#D9B64C",
        "control": "#365C8D",
        "accent": "#BFA04A",
        "neutral": "#B8C2CC",
        "bar": "#6F8DAA",
        "bar_light": "#DDE7EF",
        "bar_highlight": "#D9B64C",
        "heatmap_cmap": "cividis",
        "dpi": 180,
        "figure_format": "png",
    },
    "clean_clinical": {
        "style_id": "clinical_journal_v1_clean",
        "style_cn": "临床期刊版-清爽蓝灰",
        "font_family": "DejaVu Sans",
        "background": "#FFFFFF",
        "text": "#344054",
        "axis": "#667085",
        "grid": "#E7ECF3",
        "muted": "#98A2B3",
        "primary": "#4E7FA6",
        "secondary": "#84A9C9",
        "case": "#D15A55",
        "control": "#4D88C7",
        "accent": "#4BAA93",
        "neutral": "#B9C3CF",
        "bar": "#6EA7BC",
        "bar_light": "#D9E9EF",
        "bar_highlight": "#D15A55",
        "heatmap_cmap": "vlag",
        "dpi": 180,
        "figure_format": "png",
    },
    "warm_academic": {
        "style_id": "clinical_journal_v4_warm_academic",
        "style_cn": "临床期刊版-暖彩学术",
        "font_family": "DejaVu Sans",
        "background": "#FFFFFF",
        "text": "#4A4A55",
        "axis": "#73707D",
        "grid": "#EFECE8",
        "muted": "#9B96A5",
        "primary": "#7E6BC4",
        "secondary": "#70B7A8",
        "case": "#DD7A68",
        "control": "#5E9CCF",
        "accent": "#D6A45F",
        "neutral": "#C6C0CD",
        "bar": "#78B8AE",
        "bar_light": "#E0EFEA",
        "bar_highlight": "#DD7A68",
        "heatmap_cmap": "ultimate_soft_diverging",
        "heatmap_low": "#5E9CCF",
        "heatmap_mid": "#FAFAF8",
        "heatmap_high": "#DD7A68",
        "dpi": 180,
        "figure_format": "png",
    },
}

CLINICAL_JOURNAL_STYLE: dict[str, Any] = STYLE_REGISTRY["soft_color"]
_ACTIVE_STYLE: dict[str, Any] = {}


def available_styles() -> dict[str, dict[str, Any]]:
    return {name: dict(style) for name, style in STYLE_REGISTRY.items()}


def get_style(style_id: str | None = None, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    key = str(style_id or "soft_color")
    base = STYLE_REGISTRY.get(key) or next((style for style in STYLE_REGISTRY.values() if style["style_id"] == key), None)
    if base is None:
        raise ValueError(f"Unsupported figure style {key!r}; expected one of {sorted(STYLE_REGISTRY)}")
    return {**base, **(overrides or {})}


def set_active_style(style_id: str | None = None, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    global _ACTIVE_STYLE
    _ACTIVE_STYLE = get_style(style_id, overrides)
    return dict(_ACTIVE_STYLE)


def set_active_style_from_config(config: dict[str, Any]) -> dict[str, Any]:
    report = config.get("report") or {}
    style_cfg = report.get("style") or report.get("figure_style") or "soft_color"
    overrides = report.get("style_overrides") if isinstance(report.get("style_overrides"), dict) else None
    return set_active_style(str(style_cfg), overrides)


def apply_clinical_journal_style(style: dict[str, Any] | None = None) -> dict[str, Any]:
    tokens = {**CLINICAL_JOURNAL_STYLE, **_ACTIVE_STYLE, **(style or {})}
    sns.set_theme(
        context="paper",
        style="whitegrid",
        font=tokens["font_family"],
        rc={
            "figure.facecolor": tokens["background"],
            "axes.facecolor": tokens["background"],
            "axes.edgecolor": tokens["axis"],
            "axes.linewidth": 0.8,
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
            "patch.edgecolor": tokens["grid"],
            "savefig.facecolor": tokens["background"],
            "savefig.bbox": "tight",
        },
    )
    return tokens


def continuous_cmap(style: dict[str, Any] | None = None) -> LinearSegmentedColormap | str:
    tokens = {**CLINICAL_JOURNAL_STYLE, **_ACTIVE_STYLE, **(style or {})}
    if tokens.get("heatmap_cmap") == "ultimate_soft_diverging":
        return LinearSegmentedColormap.from_list(
            "ultimate_soft_diverging",
            [tokens["heatmap_low"], tokens["heatmap_mid"], tokens["heatmap_high"]],
            N=256,
        )
    return str(tokens["heatmap_cmap"])


def write_style_manifest(output_dir: Path, style: dict[str, Any] | None = None) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    tokens = apply_clinical_journal_style(style)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "style": tokens,
        "rules": {
            "background": "white",
            "primary_palette": "aurora pastel: violet, teal, sky blue, rose, amber",
            "difference_encoding": "rose for case/up, sky blue for control/down",
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

    _figure_qc_bar(output_dir / "qc_bar_review.png", tokens)
    rows.append(_row("style_qc_bar", "style_review", "qc_bar", output_dir / "qc_bar_review.png", "QC 条形图风格样例", tokens))

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
    sns.heatmap(matrix, cmap=continuous_cmap(tokens), center=0, yticklabels=True, xticklabels=False, cbar_kws={"label": "Z-score"})
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


def _figure_qc_bar(path: Path, tokens: dict[str, Any]) -> None:
    frame = pd.DataFrame(
        {
            "metric": ["Raw cells", "Filtered cells", "High-quality cells", "Doublets"],
            "count": [9800, 8420, 7910, 310],
            "class": ["normal", "normal", "normal", "highlight"],
        }
    )
    colors = [tokens["bar_highlight"] if value == "highlight" else tokens["bar"] for value in frame["class"]]
    plt.figure(figsize=(5.4, 4.0))
    sns.barplot(data=frame, x="metric", y="count", hue="metric", palette=dict(zip(frame["metric"], colors)), legend=False)
    plt.title("QC summary")
    plt.xlabel("")
    plt.ylabel("Cells")
    plt.xticks(rotation=18, ha="right")
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
    scatter = plt.scatter(coords[:, 0], coords[:, 1], c=score, cmap=continuous_cmap(tokens), s=18, linewidth=0)
    plt.colorbar(scatter, label="Signature score")
    plt.title("Spatial signature")
    plt.axis("equal")
    plt.axis("off")
    plt.tight_layout()
    save_figure(path, style=tokens)
