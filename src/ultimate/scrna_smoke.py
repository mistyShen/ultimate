from __future__ import annotations

import gzip
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ultimate.analysis_levels import classify_analysis_level
from ultimate.plot_style import apply_clinical_journal_style, save_figure


SIGNATURES: dict[str, list[str]] = {
    "Proliferation": ["MKI67", "TOP2A", "PCNA", "TYMS", "MCM5"],
    "Inflammation": ["IL6", "CXCL8", "CXCL10", "TNF", "NFKBIA"],
    "Hypoxia": ["HIF1A", "VEGFA", "CA9", "SLC2A1", "LDHA"],
    "EMT": ["VIM", "ZEB1", "ZEB2", "SNAI1", "FN1"],
    "Stemness": ["SOX2", "PROM1", "ALDH1A1", "EPCAM", "KRT19"],
}


@dataclass(frozen=True)
class DemoInputs:
    output_dir: str
    h5ad: str | None
    tenx_h5: str
    tenx_mtx: str
    samplesheet: str
    n_cells: int
    n_genes: int


def create_demo_inputs(output_dir: Path, *, n_cells: int = 120, n_genes: int = 90, seed: int = 17) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    counts, obs, var = _demo_counts(n_cells=n_cells, n_genes=n_genes, seed=seed)

    tenx_mtx = output_dir / "demo_10x_mtx"
    tenx_h5 = output_dir / "demo_filtered_feature_bc_matrix.h5"
    h5ad = output_dir / "demo.h5ad"
    samplesheet = output_dir / "samples.tsv"

    _write_10x_mtx(counts, obs, var, tenx_mtx)
    _write_10x_h5(counts, obs, var, tenx_h5)
    h5ad_path: str | None = None
    try:
        import anndata as ad

        adata = ad.AnnData(X=counts, obs=obs.set_index("barcode"), var=var.set_index("gene_symbol"))
        adata.var_names_make_unique()
        adata.write_h5ad(h5ad)
        h5ad_path = str(h5ad)
    except Exception:
        h5ad_path = None

    obs[["barcode", "sample_id", "condition"]].to_csv(samplesheet, sep="\t", index=False)
    manifest = DemoInputs(
        output_dir=str(output_dir),
        h5ad=h5ad_path,
        tenx_h5=str(tenx_h5),
        tenx_mtx=str(tenx_mtx),
        samplesheet=str(samplesheet),
        n_cells=int(counts.shape[0]),
        n_genes=int(counts.shape[1]),
    )
    manifest_path = output_dir / "demo_manifest.json"
    manifest_path.write_text(json.dumps(asdict(manifest), indent=2, ensure_ascii=False), encoding="utf-8")
    result = asdict(manifest)
    result["manifest_path"] = str(manifest_path)
    return result


def run_scrna_validation(
    *,
    input_path: Path,
    input_type: str,
    output_dir: Path,
    samplesheet: Path | None = None,
    max_cells: int = 3000,
    random_seed: int = 7,
    analysis_level: str | None = None,
    public_dataset: bool = False,
    dataset_label: str | None = None,
    production_approval: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if analysis_level == "production_backend" and production_approval is None:
        raise ValueError("production_backend requires --production-approval with an approved JSON gate file")
    level = classify_analysis_level(
        requested_level=analysis_level,
        input_path=input_path,
        is_stub=False,
        public_dataset=public_dataset,
    )
    sc = _scanpy()
    output_dir.mkdir(parents=True, exist_ok=True)
    figures = output_dir / "results" / "figures"
    tables = output_dir / "results" / "tables"
    objects = output_dir / "objects"
    reports = output_dir / "reports"
    raw_qc = output_dir / "raw_qc"
    logs = output_dir / "logs"
    for directory in (figures, tables, objects, reports, raw_qc, logs):
        directory.mkdir(parents=True, exist_ok=True)

    adata = _read_input(sc, input_path, input_type)
    if input_type == "h5ad":
        adata = _prepare_h5ad_expression_input(adata)
    adata.var_names_make_unique()
    _attach_samplesheet(adata, samplesheet)
    if adata.n_obs > max_cells:
        rng = np.random.default_rng(random_seed)
        selected = rng.choice(adata.n_obs, size=max_cells, replace=False)
        adata = adata[selected].copy()

    if "sample_id" not in adata.obs:
        adata.obs["sample_id"] = "sample_1"
    if "condition" not in adata.obs:
        labels = np.where(np.arange(adata.n_obs) < adata.n_obs / 2, "control", "case")
        adata.obs["condition"] = labels

    _qc(sc, adata, figures, tables, level.analysis_level)
    sc.pp.filter_cells(adata, min_genes=min(5, max(1, adata.n_vars // 10)))
    sc.pp.filter_genes(adata, min_cells=2)
    counts_adata = adata.copy()
    pseudobulk_matrix_source = "raw_counts_or_input_counts"
    if input_type == "h5ad" and _has_log1p_metadata(adata):
        pseudobulk_matrix_source = "input_log_expression_values"
    else:
        sc.pp.normalize_total(adata, target_sum=1e4)
        sc.pp.log1p(adata)
    sc.pp.highly_variable_genes(adata, n_top_genes=min(1000, adata.n_vars), flavor="seurat")
    _score_signatures(sc, adata)
    adata.raw = adata
    if "highly_variable" in adata.var:
        adata = adata[:, adata.var["highly_variable"].astype(bool)].copy()
    sc.pp.scale(adata, max_value=10)
    n_comps = max(2, min(30, adata.n_obs - 1, adata.n_vars - 1))
    sc.tl.pca(adata, n_comps=n_comps, svd_solver="arpack", random_state=random_seed)
    sc.pp.neighbors(adata, n_neighbors=min(15, max(2, adata.n_obs // 4)), n_pcs=n_comps)
    sc.tl.umap(adata, random_state=random_seed)
    try:
        sc.tl.leiden(adata, resolution=0.5, key_added="cluster")
    except Exception:
        from sklearn.cluster import KMeans

        labels = KMeans(n_clusters=min(4, max(2, adata.n_obs // 30)), random_state=random_seed, n_init=10).fit_predict(adata.obsm["X_pca"])
        adata.obs["cluster"] = pd.Categorical([str(label) for label in labels])

    sc.tl.rank_genes_groups(adata, groupby="cluster", method="wilcoxon", pts=True)
    _write_tables(sc, adata, tables, level.analysis_level)
    pseudobulk_paths = _write_pseudobulk(counts_adata, adata.obs, tables, level.analysis_level)
    annotation_warning = _write_annotation_placeholder(adata, tables, level.analysis_level)
    _write_figures(sc, adata, figures)
    h5ad_path = objects / "scrna_mvp.h5ad"
    adata.write_h5ad(h5ad_path)
    figure_manifest = _figure_manifest(figures, tables / "figure_manifest.tsv", level.analysis_level)
    raw_qc_manifest = _write_raw_qc_manifest(
        raw_qc,
        input_path=input_path,
        input_type=input_type,
        tables=tables,
        figures=figures,
        analysis_level=level.analysis_level,
    )
    reproducible_command = _reproducible_command(
        input_path=input_path,
        input_type=input_type,
        output_dir=output_dir,
        samplesheet=samplesheet,
        max_cells=max_cells,
        random_seed=random_seed,
        analysis_level=level.analysis_level,
        public_dataset=public_dataset,
        dataset_label=dataset_label,
        production_approval=production_approval,
    )

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "ready",
        **level.to_manifest_fields(),
        "input_path": str(input_path),
        "input_type": input_type,
        "dataset_label": dataset_label or "",
        "output_dir": str(output_dir),
        "n_cells": int(adata.n_obs),
        "n_genes": int(adata.n_vars),
        "validation_scope": "scRNA MVP: input ingest, QC, filtering, normalization, HVG, PCA, UMAP, clustering, marker, condition DE, composition, signature enrichment, pseudobulk design-ready matrix, h5ad/report/manifest.",
        "pseudobulk_de_status": "design_ready_matrix_only",
        "pseudobulk_matrix_source": pseudobulk_matrix_source,
        "cell_type_annotation_status": "placeholder_not_cell_type",
        "cell_type_annotation_warning": annotation_warning,
        "tables": [str(path) for path in sorted(tables.glob("*.tsv"))],
        "figures": [str(path) for path in sorted(figures.glob("*.png"))],
        "objects": {"h5ad": str(h5ad_path)},
        "figure_manifest": str(figure_manifest),
        "raw_qc_manifest": str(raw_qc_manifest),
        "pseudobulk_outputs": {name: str(path) for name, path in pseudobulk_paths.items()},
        "reproducible_command": reproducible_command,
    }
    if level.analysis_level == "production_backend":
        manifest["production_approval"] = _approval_summary(production_approval or {})
    (output_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_report(manifest, reports / "report.md", reports / "report.html")
    return manifest


def _scanpy():
    try:
        import scanpy as sc
    except ImportError as exc:
        raise RuntimeError("scanpy is required; run in the ultimate-scrna environment") from exc
    return sc


def _read_input(sc, input_path: Path, input_type: str):
    if input_type == "h5ad":
        return sc.read_h5ad(input_path)
    if input_type == "10x_h5":
        return sc.read_10x_h5(input_path, gex_only=True)
    if input_type == "10x_mtx":
        return sc.read_10x_mtx(input_path, var_names="gene_symbols", cache=False)
    raise ValueError(f"Unsupported input_type: {input_type}")


def _prepare_h5ad_expression_input(adata):
    if _has_negative_values(adata.X):
        if adata.raw is not None:
            raw = adata.raw.to_adata()
            raw.obs = adata.obs.copy()
            raw.uns.update(adata.uns)
            return raw
        if "counts" in adata.layers and not _has_negative_values(adata.layers["counts"]):
            adata = adata.copy()
            adata.X = adata.layers["counts"].copy()
            return adata
        raise ValueError(
            "h5ad input appears to contain scaled values with negatives; provide a raw/counts layer or a raw matrix h5ad."
        )
    return adata


def _has_negative_values(matrix) -> bool:
    from scipy import sparse

    if sparse.issparse(matrix):
        return bool(matrix.data.size and np.nanmin(matrix.data) < 0)
    values = np.asarray(matrix)
    return bool(values.size and np.nanmin(values) < 0)


def _has_log1p_metadata(adata) -> bool:
    return "log1p" in getattr(adata, "uns", {})


def _demo_counts(n_cells: int, n_genes: int, seed: int):
    from scipy import sparse

    rng = np.random.default_rng(seed)
    base_genes = sorted({gene for genes in SIGNATURES.values() for gene in genes})
    mt_genes = ["MT-ND1", "MT-CO1", "MT-CYB"]
    filler_count = max(0, n_genes - len(base_genes) - len(mt_genes))
    genes = base_genes + mt_genes + [f"GENE{i:03d}" for i in range(1, filler_count + 1)]
    n_genes = len(genes)
    condition = np.where(np.arange(n_cells) < n_cells / 2, "control", "case")
    sample_id = np.where(np.arange(n_cells) % 4 < 2, "S1", "S2")
    lam = np.full((n_cells, n_genes), 0.25)
    for idx, gene in enumerate(genes):
        if gene in {"MKI67", "TOP2A", "PCNA", "TYMS", "MCM5", "VIM", "VEGFA", "LDHA"}:
            lam[condition == "case", idx] += 2.0
        if gene.startswith("MT-"):
            lam[:, idx] += 0.15
    counts = rng.poisson(lam).astype(np.float32)
    counts[rng.random(counts.shape) < 0.55] = 0
    obs = pd.DataFrame(
        {
            "barcode": [f"CELL{i:03d}-1" for i in range(1, n_cells + 1)],
            "sample_id": sample_id,
            "condition": condition,
        }
    )
    var = pd.DataFrame(
        {
            "gene_id": [f"ENSGDEMO{i:05d}" for i in range(1, n_genes + 1)],
            "gene_symbol": genes,
            "feature_type": "Gene Expression",
            "genome": "GRCh38",
        }
    )
    return sparse.csr_matrix(counts), obs, var


def _write_10x_mtx(counts, obs: pd.DataFrame, var: pd.DataFrame, output_dir: Path) -> None:
    from scipy.io import mmwrite

    output_dir.mkdir(parents=True, exist_ok=True)
    matrix = counts.T.tocoo()
    with gzip.open(output_dir / "matrix.mtx.gz", "wb") as handle:
        mmwrite(handle, matrix)
    with gzip.open(output_dir / "barcodes.tsv.gz", "wt") as handle:
        handle.write("\n".join(obs["barcode"].astype(str)) + "\n")
    with gzip.open(output_dir / "features.tsv.gz", "wt") as handle:
        for row in var.itertuples(index=False):
            handle.write(f"{row.gene_id}\t{row.gene_symbol}\t{row.feature_type}\n")


def _write_10x_h5(counts, obs: pd.DataFrame, var: pd.DataFrame, path: Path) -> None:
    import h5py

    matrix = counts.T.tocsc()
    with h5py.File(path, "w") as h5:
        group = h5.create_group("matrix")
        group.create_dataset("data", data=matrix.data.astype(np.float32), compression="gzip")
        group.create_dataset("indices", data=matrix.indices.astype(np.int64), compression="gzip")
        group.create_dataset("indptr", data=matrix.indptr.astype(np.int64), compression="gzip")
        group.create_dataset("shape", data=np.array(matrix.shape, dtype=np.int64))
        group.create_dataset("barcodes", data=np.asarray(obs["barcode"].astype("S")))
        features = group.create_group("features")
        features.create_dataset("id", data=np.asarray(var["gene_id"].astype("S")))
        features.create_dataset("name", data=np.asarray(var["gene_symbol"].astype("S")))
        features.create_dataset("feature_type", data=np.asarray(var["feature_type"].astype("S")))
        features.create_dataset("genome", data=np.asarray(var["genome"].astype("S")))


def _attach_samplesheet(adata, samplesheet: Path | None) -> None:
    if samplesheet is None or not samplesheet.exists():
        return
    sheet = pd.read_csv(samplesheet, sep=None, engine="python")
    if "barcode" not in sheet.columns:
        return
    sheet = sheet.set_index("barcode")
    for column in sheet.columns:
        mapped = pd.Series(adata.obs_names, index=adata.obs_names).map(sheet[column])
        fallback = adata.obs[column] if column in adata.obs else "unknown"
        adata.obs[column] = mapped.fillna(fallback).to_numpy()


def _qc(sc, adata, figures: Path, tables: Path, analysis_level: str) -> None:
    adata.var["mt"] = pd.Index(adata.var_names.astype(str)).str.upper().str.startswith("MT-")
    sc.pp.calculate_qc_metrics(adata, qc_vars=["mt"], percent_top=None, log1p=False, inplace=True)
    qc_cols = ["total_counts", "n_genes_by_counts", "pct_counts_mt"]
    qc = adata.obs[qc_cols].copy()
    qc["analysis_level"] = analysis_level
    qc.to_csv(tables / "qc_metrics.tsv", sep="\t")
    apply_clinical_journal_style()
    import matplotlib.pyplot as plt
    import seaborn as sns

    melted = adata.obs[qc_cols].melt(var_name="metric", value_name="value")
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    sns.violinplot(data=melted, x="metric", y="value", cut=0, inner="quartile", ax=ax, color="#7EA6C8")
    ax.set_xlabel("")
    ax.set_ylabel("Value")
    fig.tight_layout()
    save_figure(figures / "qc_violin.png")


def _score_signatures(sc, adata) -> None:
    genes = set(adata.var_names.astype(str))
    rows = []
    for name, gene_set in SIGNATURES.items():
        present = [gene for gene in gene_set if gene in genes]
        if len(present) >= 2:
            sc.tl.score_genes(adata, present, score_name=f"{name}_score")
        else:
            adata.obs[f"{name}_score"] = 0.0
        rows.append({"signature": name, "n_input_genes": len(gene_set), "n_present_genes": len(present), "present_genes": ",".join(present)})
    adata.uns["signature_enrichment"] = pd.DataFrame(rows)


def _write_tables(sc, adata, tables: Path, analysis_level: str) -> None:
    markers = sc.get.rank_genes_groups_df(adata, group=None)
    _add_analysis_level(markers, analysis_level).to_csv(tables / "marker_genes.tsv", sep="\t", index=False)
    sc.tl.rank_genes_groups(adata, groupby="condition", method="wilcoxon")
    condition_de = sc.get.rank_genes_groups_df(adata, group=None)
    _add_analysis_level(condition_de, analysis_level).to_csv(tables / "de_condition.tsv", sep="\t", index=False)
    prop = adata.obs.groupby(["sample_id", "cluster"], observed=False).size().rename("n_cells").reset_index()
    prop["fraction"] = prop["n_cells"] / prop.groupby("sample_id")["n_cells"].transform("sum")
    prop["annotation_status"] = "cluster_only_not_cell_type"
    prop["analysis_level"] = analysis_level
    prop.to_csv(tables / "cell_type_composition.tsv", sep="\t", index=False)
    score_cols = [col for col in adata.obs.columns if col.endswith("_score")]
    if score_cols:
        scores = adata.obs.groupby("cluster", observed=False)[score_cols].mean().reset_index()
        scores["analysis_level"] = analysis_level
        scores.to_csv(tables / "signature_scores_by_cluster.tsv", sep="\t", index=False)
    enrichment = adata.uns["signature_enrichment"].copy()
    enrichment["analysis_level"] = analysis_level
    enrichment.to_csv(tables / "basic_enrichment.tsv", sep="\t", index=False)


def _write_figures(sc, adata, figures: Path) -> None:
    import matplotlib.pyplot as plt
    import seaborn as sns

    apply_clinical_journal_style()
    sc.pl.pca(adata, color="condition", show=False)
    save_figure(figures / "pca_condition.png")
    sc.pl.umap(adata, color=["cluster", "condition"], show=False, wspace=0.35)
    save_figure(figures / "umap_cluster_condition.png")

    de = pd.read_csv(figures.parent / "tables" / "de_condition.tsv", sep="\t")
    if {"logfoldchanges", "pvals_adj"}.issubset(de.columns):
        fig, ax = plt.subplots(figsize=(6.2, 4.6))
        y = -np.log10(np.maximum(de["pvals_adj"].fillna(1).to_numpy(), 1e-300))
        ax.scatter(de["logfoldchanges"].fillna(0), y, s=14, alpha=0.72, color="#607D9B")
        ax.axvline(1, color="#B75E5E", lw=1)
        ax.axvline(-1, color="#4D7EA8", lw=1)
        ax.set_xlabel("log2 fold change")
        ax.set_ylabel("-log10 adjusted p")
        fig.tight_layout()
        save_figure(figures / "volcano_condition.png")

    comp = pd.read_csv(figures.parent / "tables" / "cell_type_composition.tsv", sep="\t")
    pivot = comp.pivot_table(index="sample_id", columns="cluster", values="fraction", fill_value=0)
    fig, ax = plt.subplots(figsize=(7, 4.2))
    pivot.plot(kind="bar", stacked=True, ax=ax, colormap="tab20")
    ax.set_ylabel("Fraction")
    ax.set_xlabel("")
    ax.legend(title="Cluster", bbox_to_anchor=(1.02, 1), loc="upper left")
    fig.tight_layout()
    save_figure(figures / "cell_composition.png")

    scores = figures.parent / "tables" / "signature_scores_by_cluster.tsv"
    if scores.exists():
        frame = pd.read_csv(scores, sep="\t").set_index("cluster").select_dtypes(include=[np.number])
        fig, ax = plt.subplots(figsize=(7, max(3.5, 0.35 * len(frame))))
        sns.heatmap(frame, cmap="vlag", center=0, ax=ax)
        fig.tight_layout()
        save_figure(figures / "signature_heatmap.png")


def _add_analysis_level(frame: pd.DataFrame, analysis_level: str) -> pd.DataFrame:
    frame = frame.copy()
    frame["analysis_level"] = analysis_level
    return frame


def _write_annotation_placeholder(adata, tables: Path, analysis_level: str) -> str:
    warning = "cluster labels are computational clusters only; no biological cell type annotation source was provided"
    rows = (
        adata.obs.groupby("cluster", observed=False)
        .size()
        .rename("n_cells")
        .reset_index()
        .assign(
            cell_type_label=lambda frame: "cluster_" + frame["cluster"].astype(str),
            annotation_status="placeholder_not_cell_type",
            warning=warning,
            analysis_level=analysis_level,
        )
    )
    rows[["cluster", "cell_type_label", "annotation_status", "warning", "n_cells", "analysis_level"]].to_csv(
        tables / "cell_type_annotation_placeholder.tsv",
        sep="\t",
        index=False,
    )
    return warning


def _write_pseudobulk(counts_adata, obs: pd.DataFrame, tables: Path, analysis_level: str) -> dict[str, Path]:
    from scipy import sparse

    obs = obs.loc[counts_adata.obs_names].copy()
    if "sample_id" not in obs:
        obs["sample_id"] = "sample_1"
    if "condition" not in obs:
        obs["condition"] = "unknown"
    if "cluster" not in obs:
        obs["cluster"] = "0"
    obs["sample_id"] = obs["sample_id"].astype(str)
    obs["condition"] = obs["condition"].astype(str)
    obs["cluster"] = obs["cluster"].astype(str)
    groups = obs.groupby(["sample_id", "condition", "cluster"], observed=False).indices
    columns: dict[str, np.ndarray] = {}
    design_rows = []
    matrix = counts_adata.X
    for (sample_id, condition, cluster), indices in groups.items():
        pseudobulk_id = _safe_id(f"{sample_id}__{condition}__cluster{cluster}")
        group_matrix = matrix[list(indices), :]
        summed = group_matrix.sum(axis=0)
        vector = np.asarray(summed).reshape(-1) if sparse.issparse(group_matrix) else np.asarray(summed).reshape(-1)
        columns[pseudobulk_id] = vector
        design_rows.append(
            {
                "pseudobulk_id": pseudobulk_id,
                "sample_id": sample_id,
                "condition": condition,
                "cluster": cluster,
                "n_cells": int(len(indices)),
                "analysis_unit": "sample_condition_cluster",
                "analysis_level": analysis_level,
            }
        )
    counts = pd.DataFrame(columns, index=pd.Index(counts_adata.var_names.astype(str), name="feature_id")).reset_index()
    design = pd.DataFrame(design_rows)
    feature_meta = pd.DataFrame(
        {
            "feature_id": counts_adata.var_names.astype(str),
            "gene_symbol": counts_adata.var_names.astype(str),
            "analysis_level": analysis_level,
        }
    )
    count_path = tables / "pseudobulk_counts.tsv"
    design_path = tables / "pseudobulk_design.tsv"
    feature_path = tables / "pseudobulk_feature_metadata.tsv"
    counts.to_csv(count_path, sep="\t", index=False)
    design.to_csv(design_path, sep="\t", index=False)
    feature_meta.to_csv(feature_path, sep="\t", index=False)
    return {
        "pseudobulk_counts": count_path,
        "pseudobulk_design": design_path,
        "pseudobulk_feature_metadata": feature_path,
    }


def _safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in value)


def _write_raw_qc_manifest(
    raw_qc: Path,
    *,
    input_path: Path,
    input_type: str,
    tables: Path,
    figures: Path,
    analysis_level: str,
) -> Path:
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "ready",
        "analysis_level": analysis_level,
        "input_path": str(input_path),
        "input_type": input_type,
        "qc_table": str(tables / "qc_metrics.tsv"),
        "qc_figure": str(figures / "qc_violin.png"),
    }
    path = raw_qc / "raw_qc_manifest.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _reproducible_command(
    *,
    input_path: Path,
    input_type: str,
    output_dir: Path,
    samplesheet: Path | None,
    max_cells: int,
    random_seed: int,
    analysis_level: str,
    public_dataset: bool,
    dataset_label: str | None,
    production_approval: dict[str, Any] | None,
) -> str:
    pieces = [
        "ultimate",
        "validate-scrna",
        "--input-path",
        str(input_path),
        "--input-type",
        input_type,
        "--output-dir",
        str(output_dir),
        "--max-cells",
        str(max_cells),
        "--random-seed",
        str(random_seed),
        "--analysis-level",
        analysis_level,
    ]
    if samplesheet is not None:
        pieces.extend(["--samplesheet", str(samplesheet)])
    if public_dataset:
        pieces.append("--public-dataset")
    if dataset_label:
        pieces.extend(["--dataset-label", str(dataset_label)])
    approval_path = (production_approval or {}).get("_approval_path")
    if approval_path:
        pieces.extend(["--production-approval", str(approval_path)])
    return " ".join(pieces)


def _approval_summary(approval: dict[str, Any]) -> dict[str, Any]:
    return {
        "approved": bool(approval.get("approved")),
        "approved_by": str(approval.get("approved_by", "")),
        "approved_at": str(approval.get("approved_at", "")),
        "project_id": str(approval.get("project_id", "")),
        "input_path": str(approval.get("input_path", "")),
        "output_dir": str(approval.get("output_dir", "")),
        "delivery_scope": str(approval.get("delivery_scope", "")),
        "reason": str(approval.get("reason", "")),
        "approval_path": str(approval.get("_approval_path", "")),
    }


def _figure_manifest(figures: Path, output_path: Path, analysis_level: str) -> Path:
    rows = [
        {
            "figure": path.name,
            "path": str(path),
            "format": path.suffix.lstrip("."),
            "style": "ultimate_active_style",
            "analysis_level": analysis_level,
        }
        for path in sorted(figures.glob("*.png"))
    ]
    pd.DataFrame(rows).to_csv(output_path, sep="\t", index=False)
    return output_path


def _write_report(manifest: dict[str, Any], md_path: Path, html_path: Path) -> None:
    md = [
        "# scRNA-seq MVP 验证报告",
        "",
        f"输入类型：`{manifest['input_type']}`",
        f"输入路径：`{manifest['input_path']}`",
        f"状态：`{manifest['status']}`",
        f"analysis_level：`{manifest['analysis_level']}`",
        f"delivery_allowed：`{manifest['delivery_allowed']}`",
        f"non_delivery_reason：`{manifest['non_delivery_reason'] or 'none'}`",
        "",
        "## 交付边界",
        f"- 当前结果级别：`{manifest['analysis_level']}`",
        f"- 是否允许作为客户正式交付：`{manifest['delivery_allowed']}`",
        f"- 说明：{manifest['non_delivery_reason'] or 'production_backend 可作为正式交付结果。'}",
        f"- 细胞类型注释警示：{manifest['cell_type_annotation_warning']}",
        "",
        "## 数据概览",
        f"- 细胞数：{manifest['n_cells']}",
        f"- 基因数：{manifest['n_genes']}",
        "",
        "## 已验证步骤",
        "- 输入读取、QC、过滤、归一化、高变基因、PCA、UMAP、聚类、marker gene、条件差异、细胞组成、基础 signature 富集、pseudobulk design-ready matrix、h5ad 导出、图表和 manifest。",
        "- cell type annotation 当前是 cluster placeholder，不能当作真实细胞类型结论。",
        "- pseudobulk DE 当前导出 design-ready matrix，尚未自动运行 DESeq2/edgeR。",
        "",
        "## 复现命令",
        f"`{manifest['reproducible_command']}`",
    ]
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    html_path.write_text("<html><body>" + "".join(f"<p>{line}</p>" for line in md) + "</body></html>", encoding="utf-8")
