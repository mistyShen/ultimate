from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.transforms import Bbox
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
    "morandi_clinical": {
        "style_id": "v36_morandi_clinical",
        "style_cn": "Morandi 高级临床柔彩",
        "font_family": "DejaVu Sans",
        "background": "#FFFFFF",
        "text": "#4A4F59",
        "axis": "#747B86",
        "grid": "#ECEDEA",
        "muted": "#9FA5AE",
        "primary": "#7A8B99",
        "secondary": "#8FB2A6",
        "case": "#B46A6A",
        "control": "#6E8FAF",
        "accent": "#C6A16B",
        "neutral": "#C8C3BC",
        "bar": "#86A99E",
        "bar_light": "#E5EEEA",
        "bar_highlight": "#B46A6A",
        "category_palette": ["#6E8FAF", "#B46A6A", "#8FB2A6", "#C6A16B", "#8D7E9F", "#B8AFA4"],
        "heatmap_cmap": "ultimate_soft_diverging",
        "heatmap_low": "#6E8FAF",
        "heatmap_mid": "#FAFAF8",
        "heatmap_high": "#B46A6A",
        "continuous_cmap": "mako",
        "dpi": 180,
        "figure_format": "png",
    },
    "nord_science": {
        "style_id": "v36_nord_science",
        "style_cn": "Nord Science 冷静科研",
        "font_family": "DejaVu Sans",
        "background": "#FFFFFF",
        "text": "#3B4252",
        "axis": "#667080",
        "grid": "#E9EDF3",
        "muted": "#9AA4B4",
        "primary": "#5E81AC",
        "secondary": "#88C0D0",
        "case": "#BF616A",
        "control": "#5E81AC",
        "accent": "#D08770",
        "neutral": "#C5CAD3",
        "bar": "#81A1C1",
        "bar_light": "#E2EAF3",
        "bar_highlight": "#BF616A",
        "category_palette": ["#5E81AC", "#BF616A", "#A3BE8C", "#D08770", "#B48EAD", "#88C0D0"],
        "heatmap_cmap": "ultimate_soft_diverging",
        "heatmap_low": "#5E81AC",
        "heatmap_mid": "#FBFCFE",
        "heatmap_high": "#BF616A",
        "continuous_cmap": "rocket",
        "dpi": 180,
        "figure_format": "png",
    },
    "carto_safe": {
        "style_id": "v36_carto_safe",
        "style_cn": "CARTO Safe 高分辨分类",
        "font_family": "DejaVu Sans",
        "background": "#FFFFFF",
        "text": "#404854",
        "axis": "#6B7280",
        "grid": "#EEF1F4",
        "muted": "#929BA8",
        "primary": "#88CCEE",
        "secondary": "#44AA99",
        "case": "#CC6677",
        "control": "#4477AA",
        "accent": "#DDCC77",
        "neutral": "#BBBBBB",
        "bar": "#44AA99",
        "bar_light": "#DFF0ED",
        "bar_highlight": "#CC6677",
        "category_palette": ["#4477AA", "#CC6677", "#228833", "#EE6677", "#AA3377", "#BBBBBB"],
        "heatmap_cmap": "ultimate_soft_diverging",
        "heatmap_low": "#4477AA",
        "heatmap_mid": "#FAFAFA",
        "heatmap_high": "#CC6677",
        "continuous_cmap": "viridis",
        "dpi": 180,
        "figure_format": "png",
    },
    "nejm_blue_red_refined": {
        "style_id": "v36_nejm_blue_red_refined",
        "style_cn": "NEJM 蓝红精修",
        "font_family": "DejaVu Sans",
        "background": "#FFFFFF",
        "text": "#3D4149",
        "axis": "#626B76",
        "grid": "#ECEFF1",
        "muted": "#8D96A0",
        "primary": "#2F6F9F",
        "secondary": "#6BA292",
        "case": "#B33A3A",
        "control": "#2F6F9F",
        "accent": "#D49A44",
        "neutral": "#BFC6CE",
        "bar": "#6BA292",
        "bar_light": "#E3EFEC",
        "bar_highlight": "#B33A3A",
        "category_palette": ["#2F6F9F", "#B33A3A", "#6BA292", "#D49A44", "#756D9C", "#A9AEB5"],
        "heatmap_cmap": "ultimate_soft_diverging",
        "heatmap_low": "#2F6F9F",
        "heatmap_mid": "#FCFCFA",
        "heatmap_high": "#B33A3A",
        "continuous_cmap": "cividis",
        "dpi": 180,
        "figure_format": "png",
    },
    "high_contrast_publication": {
        "style_id": "v36_high_contrast_publication",
        "style_cn": "高对比出版图",
        "font_family": "DejaVu Sans",
        "background": "#FFFFFF",
        "text": "#20242A",
        "axis": "#4D5562",
        "grid": "#E6E9EF",
        "muted": "#7C8797",
        "primary": "#2455A4",
        "secondary": "#0B8F7A",
        "case": "#C43D3D",
        "control": "#2455A4",
        "accent": "#E0A11B",
        "neutral": "#AEB6C2",
        "bar": "#0B8F7A",
        "bar_light": "#DBEFEB",
        "bar_highlight": "#C43D3D",
        "category_palette": ["#2455A4", "#C43D3D", "#0B8F7A", "#E0A11B", "#6B55A4", "#64748B"],
        "heatmap_cmap": "ultimate_soft_diverging",
        "heatmap_low": "#2455A4",
        "heatmap_mid": "#FFFFFF",
        "heatmap_high": "#C43D3D",
        "continuous_cmap": "viridis",
        "dpi": 180,
        "figure_format": "png",
    },
}

CLINICAL_JOURNAL_STYLE: dict[str, Any] = STYLE_REGISTRY["soft_color"]
_ACTIVE_STYLE: dict[str, Any] = {}

DEFAULT_FIGURE_OPTIONS: dict[str, Any] = {
    "show_title": True,
    "show_subtitle": True,
    "show_legend": True,
    "legend_position": "outside_right",
    "show_grid": True,
    "show_spines": False,
    "show_threshold_lines": True,
    "show_colorbar": True,
    "show_labels": True,
    "show_panel_label": True,
    "show_caption": True,
    "show_points": True,
    "show_jitter": True,
    "show_errorbar": True,
}

FIGURE_OPTION_PRESETS: dict[str, dict[str, Any]] = {
    "publication": dict(DEFAULT_FIGURE_OPTIONS),
    "minimal": {
        **DEFAULT_FIGURE_OPTIONS,
        "show_subtitle": False,
        "show_legend": False,
        "show_grid": False,
        "show_panel_label": False,
        "show_caption": False,
        "show_threshold_lines": False,
        "show_errorbar": False,
    },
}


def available_styles() -> dict[str, dict[str, Any]]:
    return {name: dict(style) for name, style in STYLE_REGISTRY.items()}


def figure_options(preset: str = "publication", overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    if preset not in FIGURE_OPTION_PRESETS:
        raise ValueError(f"Unsupported figure options preset {preset!r}; expected one of {sorted(FIGURE_OPTION_PRESETS)}")
    return {**FIGURE_OPTION_PRESETS[preset], **(overrides or {})}


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
            "font.size": 11,
            "axes.titlesize": 14,
            "axes.labelsize": 11,
            "xtick.labelsize": 10,
            "ytick.labelsize": 10,
            "legend.fontsize": 10,
            "legend.title_fontsize": 10,
            "text.color": tokens["text"],
            "xtick.color": tokens["axis"],
            "ytick.color": tokens["axis"],
            "legend.frameon": False,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "patch.edgecolor": tokens["grid"],
            "savefig.facecolor": tokens["background"],
            "savefig.bbox": "tight",
            "savefig.pad_inches": 0.18,
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


def save_figure(path: Path, *, style: dict[str, Any] | None = None, formats: tuple[str, ...] = ("png",), close: bool = True) -> list[str]:
    tokens = apply_clinical_journal_style(style)
    path.parent.mkdir(parents=True, exist_ok=True)
    saved = []
    for fmt in formats:
        target = path.with_suffix(f".{fmt}")
        plt.savefig(target, dpi=int(tokens.get("dpi", 180)), bbox_inches="tight", pad_inches=0.18)
        saved.append(str(target))
    if close:
        plt.close()
    return saved


def write_figure_manifest(rows: list[dict[str, Any]], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "figure_manifest.tsv"
    columns = ["figure_id", "module", "kind", "path", "style_id", "title", "status", "layout_status", "layout_warning"]
    pd.DataFrame(rows, columns=columns).to_csv(path, sep="\t", index=False)
    return path


def generate_style_review(
    output_dir: Path,
    *,
    style: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
    options_preset: str = "publication",
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    tokens = apply_clinical_journal_style(style)
    opts = figure_options(options_preset, options)
    style_manifest = write_style_manifest(output_dir, tokens)
    rows = []
    layout_rows = []

    rng = np.random.default_rng(2026)
    groups = np.array(["Control"] * 20 + ["Tumor"] * 20)
    x = np.r_[rng.normal(0, 0.8, 20), rng.normal(2.4, 0.9, 20)]
    y = np.r_[rng.normal(0, 0.9, 20), rng.normal(1.5, 0.8, 20)]
    _add_review_figure(rows, layout_rows, "style_pca", "pca", output_dir / "pca_review.png", "PCA 风格样例", tokens, _figure_pca, x, y, groups, tokens, opts)

    _add_review_figure(rows, layout_rows, "style_umap", "umap", output_dir / "umap_review.png", "UMAP 风格样例", tokens, _figure_umap, x, y, groups, tokens, opts)

    stats = pd.DataFrame(
        {
            "log2FC": rng.normal(0, 1.4, 240),
            "padj": np.clip(rng.beta(0.7, 6, 240), 1e-6, 1),
        }
    )
    _add_review_figure(rows, layout_rows, "style_volcano", "volcano", output_dir / "volcano_review.png", "火山图风格样例", tokens, _figure_volcano, stats, tokens, opts)

    matrix = pd.DataFrame(rng.normal(0, 1, (18, 8)), index=[f"Gene{i:02d}" for i in range(18)])
    _add_review_figure(rows, layout_rows, "style_heatmap", "heatmap", output_dir / "heatmap_review.png", "热图风格样例", tokens, _figure_heatmap, matrix, tokens, opts)

    qc = pd.DataFrame({"group": groups, "nFeature": np.r_[rng.normal(2800, 350, 20), rng.normal(3400, 450, 20)]})
    _add_review_figure(rows, layout_rows, "style_qc_violin", "qc_violin", output_dir / "qc_violin_review.png", "QC 小提琴图风格样例", tokens, _figure_qc_violin, qc, tokens, opts)

    _add_review_figure(rows, layout_rows, "style_qc_bar", "qc_bar", output_dir / "qc_bar_review.png", "QC 条形图风格样例", tokens, _figure_qc_bar, tokens, opts)

    _add_review_figure(rows, layout_rows, "style_composition_bar", "composition_bar", output_dir / "composition_bar_review.png", "细胞组成条形图风格样例", tokens, _figure_composition_bar, tokens, opts)

    _add_review_figure(rows, layout_rows, "style_dotplot", "dotplot", output_dir / "dotplot_review.png", "Dotplot 风格样例", tokens, _figure_dotplot, tokens, opts)

    _add_review_figure(rows, layout_rows, "style_km", "km", output_dir / "km_review.png", "KM 曲线风格样例", tokens, _figure_km, tokens, opts)

    _add_review_figure(rows, layout_rows, "style_spatial", "spatial", output_dir / "spatial_review.png", "空间散点风格样例", tokens, _figure_spatial, rng, tokens, opts)

    figure_manifest = write_figure_manifest(rows, output_dir)
    layout_qc = _write_layout_qc(layout_rows, output_dir)
    contact_sheet = _write_contact_sheet(rows, output_dir, tokens, opts)
    layout_failed = [row for row in layout_rows if row["layout_status"] == "layout_failed"]
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "ready_for_review" if not layout_failed else "layout_review_required",
        "options_preset": options_preset,
        "figure_options": opts,
        "style_manifest": str(style_manifest),
        "figure_manifest": str(figure_manifest),
        "layout_qc": str(layout_qc),
        "contact_sheet": str(contact_sheet),
        "figures": [row["path"] for row in rows],
    }
    manifest_path = output_dir / "style_review_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def _row(figure_id: str, module: str, kind: str, path: Path, title: str, tokens: dict[str, Any], layout: dict[str, str]) -> dict[str, str]:
    return {
        "figure_id": figure_id,
        "module": module,
        "kind": kind,
        "path": str(path),
        "style_id": str(tokens["style_id"]),
        "title": title,
        "status": "ready",
        "layout_status": layout["layout_status"],
        "layout_warning": layout["layout_warning"],
    }


def _palette(tokens: dict[str, Any]) -> dict[str, str]:
    return {"Control": tokens["control"], "Tumor": tokens["case"], "control": tokens["control"], "treated": tokens["case"]}


def _add_review_figure(
    rows: list[dict[str, str]],
    layout_rows: list[dict[str, str]],
    figure_id: str,
    kind: str,
    path: Path,
    title: str,
    tokens: dict[str, Any],
    callback,
    *args,
) -> None:
    callback(path, *args)
    layout = _layout_qc(figure_id, path)
    layout_rows.append(layout)
    rows.append(_row(figure_id, "style_review", kind, path, title, tokens, layout))
    plt.close()


def _new_figure(figsize: tuple[float, float] = (6.4, 4.8)) -> tuple[Any, Any]:
    fig, ax = plt.subplots(figsize=figsize, constrained_layout=True)
    return fig, ax


def _decorate_axes(ax: Any, title: str, xlabel: str, ylabel: str, tokens: dict[str, Any], opts: dict[str, Any], *, panel_label: str | None = None, subtitle: str | None = None) -> None:
    if opts.get("show_title"):
        ax.set_title(title, loc="left", pad=14, fontsize=14, fontweight="semibold")
    else:
        ax.set_title("")
    if opts.get("show_subtitle") and subtitle:
        subtitle_text = ax.text(0, 1.015, subtitle, transform=ax.transAxes, ha="left", va="bottom", fontsize=10, color=tokens["muted"])
        subtitle_text.set_gid("layout_subtitle")
    ax.set_xlabel(xlabel if opts.get("show_labels") else "")
    ax.set_ylabel(ylabel if opts.get("show_labels") else "")
    if opts.get("show_grid"):
        ax.grid(True, color=tokens["grid"], linewidth=0.7)
    else:
        ax.grid(False)
    for spine in ax.spines.values():
        spine.set_visible(bool(opts.get("show_spines")))
    if opts.get("show_panel_label") and panel_label:
        panel_text = ax.text(-0.12, 1.08, panel_label, transform=ax.transAxes, ha="left", va="top", fontsize=14, fontweight="bold", color=tokens["text"])
        panel_text.set_gid("layout_panel_label")


def _place_legend(ax: Any, opts: dict[str, Any]) -> None:
    legend = ax.get_legend()
    if not opts.get("show_legend"):
        if legend is not None:
            legend.remove()
        return
    handles, labels = ax.get_legend_handles_labels()
    if not handles:
        return
    if legend is not None:
        legend.remove()
    if opts.get("legend_position") == "inside":
        ax.legend(handles, labels, loc="upper right", frameon=False, title=None)
    else:
        ax.legend(handles, labels, loc="center left", bbox_to_anchor=(1.02, 0.5), borderaxespad=0, frameon=False, title=None)


def _caption(fig: Any, text: str, tokens: dict[str, Any], opts: dict[str, Any]) -> None:
    if opts.get("show_caption"):
        caption = fig.text(0.01, -0.045, text, ha="left", va="top", fontsize=9.5, color=tokens["muted"])
        caption.set_gid("layout_caption")


def _figure_pca(path: Path, x: np.ndarray, y: np.ndarray, groups: np.ndarray, tokens: dict[str, Any], opts: dict[str, Any]) -> None:
    fig, ax = _new_figure((6.4, 4.8))
    if opts.get("show_points"):
        sns.scatterplot(ax=ax, x=x, y=y, hue=groups, palette=_palette(tokens), s=48, edgecolor="white", linewidth=0.5)
    _decorate_axes(ax, "PCA", "PC1 (31.2%)", "PC2 (18.7%)", tokens, opts, panel_label="A", subtitle="Sample-level separation")
    _place_legend(ax, opts)
    _caption(fig, "Legend outside.", tokens, opts)
    save_figure(path, style=tokens, close=False)


def _figure_umap(path: Path, x: np.ndarray, y: np.ndarray, groups: np.ndarray, tokens: dict[str, Any], opts: dict[str, Any]) -> None:
    fig, ax = _new_figure((6.4, 4.8))
    if opts.get("show_points"):
        sns.scatterplot(ax=ax, x=np.tanh(x) + x / 4, y=np.tanh(y) + y / 4, hue=groups, palette=_palette(tokens), s=32, alpha=0.88, linewidth=0)
    _decorate_axes(ax, "UMAP", "UMAP_1", "UMAP_2", tokens, opts, panel_label="B", subtitle="Cluster/state overview")
    _place_legend(ax, opts)
    _caption(fig, "Clean margins.", tokens, opts)
    save_figure(path, style=tokens, close=False)


def _figure_volcano(path: Path, stats: pd.DataFrame, tokens: dict[str, Any], opts: dict[str, Any]) -> None:
    frame = stats.copy()
    frame["neg_log10_padj"] = -np.log10(frame["padj"])
    frame["class"] = np.where(frame["log2FC"] > 1, "Up", np.where(frame["log2FC"] < -1, "Down", "NS"))
    palette = {"Up": tokens["case"], "Down": tokens["control"], "NS": tokens["neutral"]}
    fig, ax = _new_figure((6.7, 4.9))
    if opts.get("show_points"):
        sns.scatterplot(ax=ax, data=frame, x="log2FC", y="neg_log10_padj", hue="class", palette=palette, s=20, linewidth=0, alpha=0.86)
    if opts.get("show_threshold_lines"):
        ax.axvline(1, color=tokens["muted"], linestyle="--", linewidth=0.8)
        ax.axvline(-1, color=tokens["muted"], linestyle="--", linewidth=0.8)
    _decorate_axes(ax, "Volcano", "log2 fold change", "-log10(adj. P)", tokens, opts, panel_label="C", subtitle="Differential signal")
    _place_legend(ax, opts)
    _caption(fig, "Thresholds optional.", tokens, opts)
    save_figure(path, style=tokens, close=False)


def _figure_heatmap(path: Path, matrix: pd.DataFrame, tokens: dict[str, Any], opts: dict[str, Any]) -> None:
    fig, ax = _new_figure((7.0, 5.8))
    sns.heatmap(
        matrix,
        ax=ax,
        cmap=continuous_cmap(tokens),
        center=0,
        vmin=-2.5,
        vmax=2.5,
        yticklabels=True,
        xticklabels=False,
        cbar=bool(opts.get("show_colorbar")),
        cbar_kws={"label": "Z-score", "shrink": 0.78, "pad": 0.03, "ticks": [-2, 0, 2]},
    )
    _decorate_axes(ax, "Top markers", "", "", tokens, opts, panel_label="D", subtitle="Centered expression")
    _caption(fig, "Reserved colorbar.", tokens, opts)
    save_figure(path, style=tokens, close=False)


def _figure_qc_violin(path: Path, qc: pd.DataFrame, tokens: dict[str, Any], opts: dict[str, Any]) -> None:
    fig, ax = _new_figure((5.8, 4.7))
    sns.violinplot(
        ax=ax,
        data=qc,
        x="group",
        y="nFeature",
        hue="group",
        palette=_palette(tokens),
        inner="quartile",
        linewidth=0.8,
        legend=False,
    )
    _decorate_axes(ax, "QC: detected features", "", "nFeature", tokens, opts, panel_label="E", subtitle="Distribution by group")
    _caption(fig, "Stable QC labels.", tokens, opts)
    save_figure(path, style=tokens, close=False)


def _figure_qc_bar(path: Path, tokens: dict[str, Any], opts: dict[str, Any]) -> None:
    frame = pd.DataFrame(
        {
            "metric": ["Raw", "Filtered", "HQ cells", "Doublets"],
            "count": [9800, 8420, 7910, 310],
            "class": ["normal", "normal", "normal", "highlight"],
        }
    )
    colors = [tokens["bar_highlight"] if value == "highlight" else tokens["bar"] for value in frame["class"]]
    fig, ax = _new_figure((6.8, 4.7))
    sns.barplot(ax=ax, data=frame, x="metric", y="count", hue="metric", palette=dict(zip(frame["metric"], colors)), legend=False)
    _decorate_axes(ax, "QC summary", "", "Cells", tokens, opts, panel_label="F", subtitle="Filtering overview")
    ax.set_ylim(0, 10500)
    ax.set_yticks([0, 2500, 5000, 7500, 10000])
    ax.tick_params(axis="x", rotation=12)
    for label in ax.get_xticklabels():
        label.set_horizontalalignment("right")
    _caption(fig, "Angled labels.", tokens, opts)
    save_figure(path, style=tokens, close=False)


def _figure_composition_bar(path: Path, tokens: dict[str, Any], opts: dict[str, Any]) -> None:
    cell_types = ["T cell", "B cell", "Myeloid", "Epithelial", "Stromal"]
    frame = pd.DataFrame(
        {
            "sample": np.repeat(["S1", "S2", "S3"], len(cell_types)),
            "cell_type": cell_types * 3,
            "fraction": [0.34, 0.14, 0.20, 0.22, 0.10, 0.28, 0.18, 0.27, 0.17, 0.10, 0.18, 0.21, 0.30, 0.20, 0.11],
        }
    )
    palette = tokens.get("category_palette") or [tokens["control"], tokens["case"], tokens["secondary"], tokens["accent"], tokens["primary"]]
    fig, ax = _new_figure((6.8, 4.8))
    bottom = np.zeros(3)
    samples = ["S1", "S2", "S3"]
    for idx, cell_type in enumerate(cell_types):
        values = frame.loc[frame["cell_type"] == cell_type, "fraction"].to_numpy()
        ax.bar(samples, values, bottom=bottom, label=cell_type, color=palette[idx % len(palette)], width=0.62)
        bottom += values
    _decorate_axes(ax, "Cell composition", "", "Fraction", tokens, opts, panel_label="G", subtitle="Stacked sample proportions")
    ax.set_ylim(0, 1.02)
    ax.set_yticks([0, 0.25, 0.50, 0.75, 1.00])
    _place_legend(ax, opts)
    _caption(fig, "Limited palette.", tokens, opts)
    save_figure(path, style=tokens, close=False)


def _figure_dotplot(path: Path, tokens: dict[str, Any], opts: dict[str, Any]) -> None:
    genes = ["CD3D", "MS4A1", "LYZ", "EPCAM", "COL1A1"]
    clusters = ["T cell", "B cell", "Myeloid", "Epithelial", "Stromal"]
    rng = np.random.default_rng(12)
    frame = pd.DataFrame([(g, c, rng.uniform(0.05, 0.9), rng.normal(0, 0.9)) for c in clusters for g in genes], columns=["gene", "cluster", "pct", "score"])
    fig, ax = _new_figure((6.8, 4.8))
    if opts.get("show_points"):
        scatter = ax.scatter(
            frame["gene"],
            frame["cluster"],
            s=frame["pct"] * 280,
            c=frame["score"],
            cmap=continuous_cmap(tokens),
            edgecolor="white",
            linewidth=0.5,
        )
        if opts.get("show_colorbar"):
            fig.colorbar(scatter, ax=ax, shrink=0.74, pad=0.03, label="Scaled expression")
    _decorate_axes(ax, "Marker dotplot", "", "", tokens, opts, panel_label="H", subtitle="Size: percent expressed")
    ax.tick_params(axis="x", rotation=25)
    for label in ax.get_xticklabels():
        label.set_horizontalalignment("right")
    _caption(fig, "Dense marker panel.", tokens, opts)
    save_figure(path, style=tokens, close=False)


def _figure_km(path: Path, tokens: dict[str, Any], opts: dict[str, Any]) -> None:
    months = np.arange(0, 61, 6)
    high = np.exp(-months / 34)
    low = np.exp(-months / 58)
    fig, ax = _new_figure((6.4, 4.8))
    ax.step(months, high, where="post", label="High risk", color=tokens["case"], linewidth=1.8)
    ax.step(months, low, where="post", label="Low risk", color=tokens["control"], linewidth=1.8)
    _decorate_axes(ax, "Kaplan-Meier", "Months", "Survival probability", tokens, opts, panel_label="I", subtitle="Risk-group example")
    ax.set_xlim(0, 60)
    ax.set_xticks([0, 12, 24, 36, 48, 60])
    ax.set_ylim(0, 1.00)
    ax.set_yticks([0, 0.25, 0.50, 0.75, 1.00])
    _place_legend(ax, opts)
    _caption(fig, "Legend outside.", tokens, opts)
    save_figure(path, style=tokens, close=False)


def _figure_spatial(path: Path, rng: np.random.Generator, tokens: dict[str, Any], opts: dict[str, Any]) -> None:
    coords = rng.uniform(0, 1, (320, 2))
    score = np.sin(coords[:, 0] * 8) + np.cos(coords[:, 1] * 7)
    fig, ax = _new_figure((6.2, 5.2))
    if opts.get("show_points"):
        scatter = ax.scatter(coords[:, 0], coords[:, 1], c=score, cmap=continuous_cmap(tokens), s=20, linewidth=0)
        if opts.get("show_colorbar"):
            fig.colorbar(scatter, ax=ax, shrink=0.78, pad=0.03, label="Signature score")
    _decorate_axes(ax, "Spatial signature", "", "", tokens, opts, panel_label="J", subtitle="Coordinate-preserving view")
    ax.axis("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    ax.axis("off")
    _caption(fig, "Reserved colorbar.", tokens, opts)
    save_figure(path, style=tokens, close=False)


def _layout_qc(figure_id: str, path: Path) -> dict[str, str]:
    fig = plt.gcf()
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    boxes: list[tuple[str, Bbox]] = []
    legend_text_ids = {id(text) for ax in fig.axes for legend in [ax.get_legend()] if legend is not None for text in legend.get_texts()}
    for idx, text in enumerate(fig.findobj(match=matplotlib.text.Text)):
        if not text.get_visible() or not text.get_text():
            continue
        if id(text) in legend_text_ids or text.get_gid() in {"layout_caption"}:
            continue
        bbox = text.get_window_extent(renderer=renderer)
        if bbox.width > 1 and bbox.height > 1:
            boxes.append((f"text_{idx}", bbox.expanded(1.04, 1.10)))
    for idx, legend in enumerate(fig.legends + [ax.get_legend() for ax in fig.axes if ax.get_legend() is not None]):
        if legend and legend.get_visible():
            boxes.append((f"legend_{idx}", legend.get_window_extent(renderer=renderer).expanded(1.02, 1.04)))
    warnings: list[str] = []
    for left_idx, (left_name, left_box) in enumerate(boxes):
        for right_name, right_box in boxes[left_idx + 1 :]:
            if left_box.overlaps(right_box):
                if left_name.startswith("text_") and right_name.startswith("text_"):
                    continue
                warnings.append(f"overlap:{left_name}:{right_name}")
    # Match the actual exported canvas. Review figures are saved with
    # bbox_inches="tight", so the layout QA should check against the tight
    # rendered extent instead of the pre-save interactive canvas.
    figure_box = fig.get_tightbbox(renderer).transformed(fig.dpi_scale_trans)
    for name, bbox in boxes:
        if bbox.x0 < figure_box.x0 - 2 or bbox.y0 < figure_box.y0 - 18 or bbox.x1 > figure_box.x1 + 18 or bbox.y1 > figure_box.y1 + 18:
            warnings.append(f"outside_canvas:{name}")
    return {
        "figure_id": figure_id,
        "path": str(path),
        "layout_status": "layout_warning" if warnings else "layout_pass",
        "layout_warning": ";".join(warnings[:6]),
    }


def _write_layout_qc(rows: list[dict[str, str]], output_dir: Path) -> Path:
    path = output_dir / "layout_qc.tsv"
    pd.DataFrame(rows, columns=["figure_id", "path", "layout_status", "layout_warning"]).to_csv(path, sep="\t", index=False)
    return path


def _write_contact_sheet(rows: list[dict[str, str]], output_dir: Path, tokens: dict[str, Any], opts: dict[str, Any]) -> Path:
    images = []
    for row in rows:
        image = plt.imread(row["path"])
        images.append((row["kind"], image))
    ncols = 1
    nrows = int(np.ceil(len(images) / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(11.5, max(6, 5.7 * nrows)), constrained_layout=True)
    axes_array = np.atleast_1d(axes).ravel()
    for ax, (kind, image) in zip(axes_array, images):
        ax.imshow(image)
        ax.set_title(kind.replace("_", " ").title(), loc="left", fontsize=15, color=tokens["text"], pad=10)
        ax.axis("off")
    for ax in axes_array[len(images) :]:
        ax.axis("off")
    if opts.get("show_title"):
        fig.suptitle(str(tokens["style_id"]), fontsize=16, fontweight="semibold", color=tokens["text"])
    path = output_dir / "style_review_contact_sheet.png"
    fig.savefig(path, dpi=int(tokens.get("dpi", 180)), bbox_inches="tight", pad_inches=0.22)
    plt.close(fig)
    return path
