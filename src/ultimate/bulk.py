from __future__ import annotations

import importlib.util
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

from ultimate.analysis_levels import classify_analysis_level
from ultimate.constants import MODULE_SPECS
from ultimate.modules.common import (
    handoff_plan,
    known_limitations,
    write_module_methods_fragment,
    write_module_qc_manifest,
    write_module_report_bundle,
    write_mvp_figures,
    write_mvp_object,
    write_mvp_tables,
    write_tool_coverage_table,
)
from ultimate.plot_style import apply_clinical_journal_style, continuous_cmap, save_figure


BULK_MODULES = {
    "rnaseq",
    "methylation",
    "proteomics",
    "publicdb",
    "wgcna",
    "single_gene",
    "clinical_assoc",
}

BULK_PYTHON_REQUIREMENTS = {
    "rnaseq": ("numpy", "pandas", "matplotlib", "seaborn"),
    "methylation": ("numpy", "pandas", "matplotlib", "seaborn"),
    "proteomics": ("numpy", "pandas", "matplotlib", "seaborn"),
    "publicdb": ("numpy", "pandas", "matplotlib", "seaborn"),
    "wgcna": ("numpy", "pandas", "matplotlib", "seaborn", "sklearn"),
    "single_gene": ("numpy", "pandas", "matplotlib", "seaborn"),
    "clinical_assoc": ("numpy", "pandas", "matplotlib", "seaborn"),
}


@dataclass(frozen=True)
class BulkInputs:
    matrix: pd.DataFrame
    clinical: pd.DataFrame
    source: str
    warnings: tuple[str, ...]


def is_bulk_module(module_name: str) -> bool:
    return module_name in BULK_MODULES


def run_bulk_module(
    *,
    module_name: str,
    config: dict[str, Any],
    output_dir: Path,
    samples: pd.DataFrame,
) -> dict[str, Any]:
    module_dir = output_dir
    figures_dir = module_dir / "results" / "figures" / module_name
    tables_dir = module_dir / "results" / "tables" / module_name
    objects_dir = module_dir / "objects" / module_name
    reports_dir = module_dir / "reports" / module_name
    logs_dir = module_dir / "logs"
    for directory in (figures_dir, tables_dir, objects_dir, reports_dir, logs_dir):
        directory.mkdir(parents=True, exist_ok=True)

    module_cfg = (config.get("modules") or {}).get(module_name) or {}
    design = config.get("design") or {}
    input_matrix = module_cfg.get("input_matrix")
    inputs = _load_bulk_inputs(module_name, module_cfg, samples)
    level = classify_analysis_level(
        requested_level=module_cfg.get("analysis_level"),
        input_path=input_matrix,
        is_demo=_module_is_demo(config, module_cfg),
        is_stub=inputs.source == "demo_generated_matrix",
    )
    level_fields = level.to_manifest_fields()
    matrix = _normalize_matrix(module_name, inputs.matrix)
    stats = _differential_stats(matrix, samples, design)
    artifacts = {"tables": {}, "figures": {}, "objects": {}}

    artifacts["tables"].update(_write_common_tables(module_name, matrix, stats, samples, inputs, tables_dir))
    artifacts["tables"].update(_write_module_tables(module_name, matrix, stats, samples, inputs, tables_dir, module_cfg))
    artifacts["figures"].update(_write_common_figures(module_name, matrix, stats, samples, figures_dir, design))
    artifacts["figures"].update(_write_module_figures(module_name, matrix, stats, samples, inputs, figures_dir, module_cfg))
    artifacts["objects"].update(_write_bulk_objects(module_name, matrix, stats, inputs, objects_dir))
    artifacts["tables"].update(
        write_mvp_tables(
            module_name=module_name,
            tables_dir=tables_dir,
            matrix=matrix,
            stats=stats,
            samples=samples,
            analysis_fields=level_fields,
            run_id=_run_id(config, module_name),
            source_dataset=_source_dataset(config, module_name),
            input_artifact=str(input_matrix or inputs.source),
            input_modality=module_name,
        )
    )
    artifacts["figures"].update(write_mvp_figures(module_name=module_name, figures_dir=figures_dir, matrix=matrix))
    artifacts["objects"].update(write_mvp_object(module_name=module_name, objects_dir=objects_dir, matrix=matrix, stats=stats))
    artifacts["reports"] = {"methods_fragment": write_module_methods_fragment(module_name, reports_dir)}
    artifacts["tables"]["tool_coverage"] = write_tool_coverage_table(module_name, tables_dir)
    artifacts["tables"]["module_qc_manifest"] = write_module_qc_manifest(
        module_name=module_name,
        tables_dir=tables_dir,
        status="complete_python_bulk_backend",
        artifacts=artifacts,
        analysis_fields=level_fields,
        warnings=list(inputs.warnings),
    )

    module_manifest = {
        "module": module_name,
        "title_cn": MODULE_SPECS[module_name].title_cn,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "complete_python_bulk_backend",
        **level_fields,
        "backend": {
            "primary": "python",
            "optional_r_entrypoint": module_cfg.get("r_entrypoint", f"scripts/R/{module_name}.R"),
            "python_requirements": list(BULK_PYTHON_REQUIREMENTS[module_name]),
        },
        "formal_backend": {
            "primary": "python",
            "r_entrypoint": module_cfg.get("r_entrypoint", f"scripts/R/{module_name}.R"),
            "status": "python_bulk_backend_complete_r_optional",
        },
        "input_matrix": module_cfg.get("input_matrix"),
        "input_source": inputs.source,
        "n_features": int(matrix.shape[0]),
        "n_samples": int(matrix.shape[1]),
        "n_clinical_rows": int(inputs.clinical.shape[0]),
        "artifacts": artifacts,
        "limitations": list(known_limitations(module_name)),
        "handoff": handoff_plan(module_name),
        "reproducible_command": f"ultimate run --config {config.get('_config_path', '<config.yaml>')}",
        "warnings": list(inputs.warnings),
        "skip_reasons": [],
    }
    if module_name == "publicdb":
        module_manifest["restricted_resources"] = {
            "CIBERSORT": "requires user-provided licensed signature/script; open signature-score fallback is used",
        }
    artifacts["reports"].update(write_module_report_bundle(module_manifest, reports_dir))
    manifest_path = tables_dir / "module_manifest.json"
    module_manifest["manifest_path"] = str(manifest_path)
    manifest_path.write_text(json.dumps(module_manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    write_module_report_bundle(module_manifest, reports_dir)
    return module_manifest


def bulk_requirement_checks(module_name: str) -> dict[str, bool]:
    return {pkg: importlib.util.find_spec(pkg) is not None for pkg in BULK_PYTHON_REQUIREMENTS.get(module_name, ())}


def _module_is_demo(config: dict[str, Any], module_cfg: dict[str, Any]) -> bool | None:
    if "is_demo" in module_cfg:
        return bool(module_cfg.get("is_demo"))
    project = config.get("project") or {}
    if "is_demo" in project:
        return bool(project.get("is_demo"))
    return None


def _run_id(config: dict[str, Any], module_name: str) -> str:
    if config.get("_run_id"):
        return str(config["_run_id"])
    project = config.get("project") or {}
    return str(project.get("job_id") or project.get("name") or module_name)


def _source_dataset(config: dict[str, Any], module_name: str) -> str:
    project = config.get("project") or {}
    return str(project.get("name") or project.get("job_id") or module_name)


def _load_bulk_inputs(module_name: str, module_cfg: dict[str, Any], samples: pd.DataFrame) -> BulkInputs:
    warnings: list[str] = []
    matrix_path = _first_existing_path(
        module_cfg.get("input_matrix"),
        ((module_cfg.get("raw") or {}).get("output_matrix")),
        module_cfg.get("matrix_path"),
    )
    if matrix_path is not None:
        matrix = _read_matrix(matrix_path)
        source = str(matrix_path)
    else:
        matrix = _demo_matrix(module_name, samples)
        source = "demo_generated_matrix"
        warnings.append("input_matrix_missing_demo_generated")

    clinical_path = _first_existing_path(module_cfg.get("clinical_table"), (module_cfg.get("raw") or {}).get("clinical_table"))
    if clinical_path is not None:
        clinical = pd.read_csv(clinical_path, sep=None, engine="python")
    else:
        clinical = _clinical_from_samples(samples, matrix)
        if module_name in {"publicdb", "single_gene", "clinical_assoc"}:
            warnings.append("clinical_table_missing_sample_metadata_used")
    matrix = _align_matrix_to_samples(matrix, samples)
    return BulkInputs(matrix=matrix, clinical=clinical, source=source, warnings=tuple(warnings))


def _first_existing_path(*values: Any) -> Path | None:
    for value in values:
        if not value:
            continue
        path = Path(value)
        if path.exists():
            return path
    return None


def _read_matrix(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, sep=None, engine="python")
    if "feature_id" in frame.columns:
        frame = frame.set_index("feature_id")
    else:
        frame = frame.set_index(frame.columns[0])
    numeric = frame.apply(pd.to_numeric, errors="coerce")
    numeric.index = numeric.index.astype(str)
    return numeric.fillna(0.0)


def _demo_matrix(module_name: str, samples: pd.DataFrame) -> pd.DataFrame:
    sample_ids = list(samples["sample_id"].astype(str)) if "sample_id" in samples.columns else ["CTRL_1", "CTRL_2", "TRT_1", "TRT_2"]
    rng = np.random.default_rng(abs(hash(("bulk", module_name))) % 2**32)
    prefix = {
        "rnaseq": "GENE",
        "methylation": "cg",
        "proteomics": "PROT",
        "publicdb": "PUBGENE",
        "wgcna": "WGCNA",
        "single_gene": "GENE",
        "clinical_assoc": "CLIN",
    }.get(module_name, "FEATURE")
    features = [f"{prefix}_{idx:04d}" for idx in range(1, 81)]
    if module_name == "single_gene":
        features[0] = "TP53"
    if module_name == "methylation":
        values = rng.beta(a=2.0, b=3.0, size=(len(features), len(sample_ids)))
        values[:12, len(sample_ids) // 2 :] = np.clip(values[:12, len(sample_ids) // 2 :] + 0.18, 0, 1)
    elif module_name == "rnaseq":
        values = rng.negative_binomial(n=30, p=0.35, size=(len(features), len(sample_ids))).astype(float)
        values[:12, len(sample_ids) // 2 :] *= 1.8
    else:
        values = rng.normal(loc=7.0, scale=1.0, size=(len(features), len(sample_ids)))
        values[:12, len(sample_ids) // 2 :] += 1.35
    return pd.DataFrame(values, index=features, columns=sample_ids)


def _clinical_from_samples(samples: pd.DataFrame, matrix: pd.DataFrame) -> pd.DataFrame:
    if not samples.empty and "sample_id" in samples.columns:
        clinical = samples.copy()
    else:
        clinical = pd.DataFrame({"sample_id": list(matrix.columns)})
    if "condition" not in clinical.columns:
        midpoint = max(1, clinical.shape[0] // 2)
        clinical["condition"] = ["control"] * midpoint + ["treated"] * (clinical.shape[0] - midpoint)
    if "survival_time" not in clinical.columns:
        clinical["survival_time"] = np.linspace(18, 60, clinical.shape[0]).round(1)
    if "event" not in clinical.columns:
        clinical["event"] = [idx % 2 for idx in range(clinical.shape[0])]
    if "age" not in clinical.columns:
        clinical["age"] = np.linspace(45, 70, clinical.shape[0]).round(1)
    return clinical


def _align_matrix_to_samples(matrix: pd.DataFrame, samples: pd.DataFrame) -> pd.DataFrame:
    if samples.empty or "sample_id" not in samples.columns:
        return matrix
    ordered = [sample for sample in samples["sample_id"].astype(str) if sample in matrix.columns]
    return matrix[ordered] if ordered else matrix


def _normalize_matrix(module_name: str, matrix: pd.DataFrame) -> pd.DataFrame:
    numeric = matrix.apply(pd.to_numeric, errors="coerce").fillna(0.0)
    if module_name == "rnaseq":
        lib_sizes = numeric.sum(axis=0).replace(0, np.nan)
        cpm = numeric.divide(lib_sizes, axis=1) * 1_000_000
        return np.log2(cpm.fillna(0.0) + 1.0)
    if module_name == "methylation":
        return numeric.clip(0.0, 1.0)
    if module_name in {"proteomics", "publicdb", "wgcna", "single_gene", "clinical_assoc"}:
        return np.log2(numeric.clip(lower=0) + 1.0) if (numeric.min().min() >= 0 and numeric.max().max() > 50) else numeric
    return numeric


def _differential_stats(matrix: pd.DataFrame, samples: pd.DataFrame, design: dict[str, Any]) -> pd.DataFrame:
    condition_column = str(design.get("condition_column", "condition"))
    control = str(design.get("control", "control"))
    case = str(design.get("case", "treated"))
    lookup = {}
    if condition_column in samples.columns and "sample_id" in samples.columns:
        lookup = dict(zip(samples["sample_id"].astype(str), samples[condition_column].astype(str)))
    control_cols = [col for col in matrix.columns if lookup.get(str(col), control) == control]
    case_cols = [col for col in matrix.columns if lookup.get(str(col), case) == case]
    if not control_cols or not case_cols:
        midpoint = max(1, matrix.shape[1] // 2)
        control_cols = list(matrix.columns[:midpoint])
        case_cols = list(matrix.columns[midpoint:])
    control_mean = matrix[control_cols].mean(axis=1)
    case_mean = matrix[case_cols].mean(axis=1)
    effect = case_mean - control_mean
    pooled = matrix.std(axis=1).replace(0, np.nan).fillna(1.0)
    z_score = effect / pooled
    pvalue = pd.Series([_normal_sf(abs(value)) * 2 for value in z_score], index=matrix.index)
    padj = _benjamini_hochberg(pvalue)
    return pd.DataFrame(
        {
            "feature_id": matrix.index.astype(str),
            "control_mean": control_mean.to_numpy(),
            "case_mean": case_mean.to_numpy(),
            "effect_size": effect.to_numpy(),
            "log2FC": effect.to_numpy(),
            "z_score": z_score.to_numpy(),
            "pvalue": pvalue.to_numpy(),
            "padj": padj.to_numpy(),
        }
    ).sort_values(["padj", "pvalue"])


def _normal_sf(value: float) -> float:
    return 0.5 * math.erfc(float(value) / math.sqrt(2.0))


def _benjamini_hochberg(pvalues: pd.Series) -> pd.Series:
    values = pvalues.fillna(1.0).to_numpy(dtype=float)
    order = np.argsort(values)
    adjusted = np.empty_like(values)
    cumulative = 1.0
    n = len(values)
    for idx in order[::-1]:
        rank = int(np.where(order == idx)[0][0]) + 1
        cumulative = min(cumulative, values[idx] * n / rank)
        adjusted[idx] = cumulative
    return pd.Series(np.clip(adjusted, 0, 1), index=pvalues.index)


def _write_common_tables(
    module_name: str,
    matrix: pd.DataFrame,
    stats: pd.DataFrame,
    samples: pd.DataFrame,
    inputs: BulkInputs,
    tables_dir: Path,
) -> dict[str, str]:
    paths = {
        "normalized_matrix": tables_dir / "normalized_matrix.tsv",
        "differential_results": tables_dir / "differential_results.tsv",
        "top_features": tables_dir / "top_features.tsv",
        "sample_summary": tables_dir / "sample_summary.tsv",
        "method_summary": tables_dir / "method_summary.tsv",
    }
    matrix.to_csv(paths["normalized_matrix"], sep="\t")
    stats.to_csv(paths["differential_results"], sep="\t", index=False)
    stats.head(30).to_csv(paths["top_features"], sep="\t", index=False)
    samples.to_csv(paths["sample_summary"], sep="\t", index=False)
    pd.DataFrame(
        [
            {"field": "module", "value": module_name},
            {"field": "backend", "value": "python"},
            {"field": "input_source", "value": inputs.source},
            {"field": "normalization", "value": _normalization_label(module_name)},
            {"field": "testing", "value": "two-group z-score proxy with Benjamini-Hochberg FDR"},
        ]
    ).to_csv(paths["method_summary"], sep="\t", index=False)
    return {key: str(path) for key, path in paths.items()}


def _normalization_label(module_name: str) -> str:
    return {
        "rnaseq": "log2(CPM+1)",
        "methylation": "beta values clipped to [0,1]",
        "proteomics": "log2 abundance when count-scale",
        "publicdb": "expression matrix scale-preserving/log2 when count-scale",
        "wgcna": "expression matrix scale-preserving/log2 when count-scale",
        "single_gene": "expression matrix scale-preserving/log2 when count-scale",
        "clinical_assoc": "feature matrix scale-preserving/log2 when count-scale",
    }.get(module_name, "numeric matrix")


def _write_module_tables(
    module_name: str,
    matrix: pd.DataFrame,
    stats: pd.DataFrame,
    samples: pd.DataFrame,
    inputs: BulkInputs,
    tables_dir: Path,
    module_cfg: dict[str, Any],
) -> dict[str, str]:
    if module_name == "rnaseq":
        return _rnaseq_tables(matrix, stats, tables_dir)
    if module_name == "methylation":
        return _methylation_tables(matrix, stats, tables_dir)
    if module_name == "proteomics":
        return _proteomics_tables(matrix, stats, tables_dir)
    if module_name == "publicdb":
        return _publicdb_tables(matrix, stats, inputs.clinical, tables_dir)
    if module_name == "wgcna":
        return _wgcna_tables(matrix, inputs.clinical, tables_dir)
    if module_name == "single_gene":
        return _single_gene_tables(matrix, stats, inputs.clinical, tables_dir, module_cfg)
    if module_name == "clinical_assoc":
        return _clinical_assoc_tables(matrix, inputs.clinical, tables_dir)
    return {}


def _rnaseq_tables(matrix: pd.DataFrame, stats: pd.DataFrame, tables_dir: Path) -> dict[str, str]:
    counts_qc = tables_dir / "rnaseq_count_qc.tsv"
    enrich = tables_dir / "enrichment_ready_genes.tsv"
    pd.DataFrame(
        {
            "sample_id": matrix.columns.astype(str),
            "library_size_log2cpm_sum": matrix.sum(axis=0).to_numpy(),
            "detected_features": (matrix > 0).sum(axis=0).to_numpy(),
        }
    ).to_csv(counts_qc, sep="\t", index=False)
    stats.loc[:, ["feature_id", "log2FC", "padj"]].to_csv(enrich, sep="\t", index=False)
    return {"rnaseq_count_qc": str(counts_qc), "enrichment_ready_genes": str(enrich)}


def _methylation_tables(matrix: pd.DataFrame, stats: pd.DataFrame, tables_dir: Path) -> dict[str, str]:
    mvalue = tables_dir / "m_value_matrix.tsv"
    qc = tables_dir / "methylation_qc.tsv"
    dmp = tables_dir / "annotation_ready_dmp.tsv"
    beta = matrix.clip(1e-4, 1 - 1e-4)
    np.log2(beta / (1 - beta)).to_csv(mvalue, sep="\t")
    pd.DataFrame(
        {
            "sample_id": beta.columns.astype(str),
            "median_beta": beta.median(axis=0).to_numpy(),
            "mean_beta": beta.mean(axis=0).to_numpy(),
        }
    ).to_csv(qc, sep="\t", index=False)
    stats.assign(probe_id=stats["feature_id"]).to_csv(dmp, sep="\t", index=False)
    return {"m_value_matrix": str(mvalue), "methylation_qc": str(qc), "annotation_ready_dmp": str(dmp)}


def _proteomics_tables(matrix: pd.DataFrame, stats: pd.DataFrame, tables_dir: Path) -> dict[str, str]:
    abundance = tables_dir / "normalized_abundance.tsv"
    qc = tables_dir / "abundance_qc.tsv"
    matrix.to_csv(abundance, sep="\t")
    pd.DataFrame(
        {
            "sample_id": matrix.columns.astype(str),
            "median_abundance": matrix.median(axis=0).to_numpy(),
            "missing_fraction": matrix.isna().mean(axis=0).to_numpy(),
        }
    ).to_csv(qc, sep="\t", index=False)
    return {"normalized_abundance": str(abundance), "abundance_qc": str(qc)}


def _publicdb_tables(matrix: pd.DataFrame, stats: pd.DataFrame, clinical: pd.DataFrame, tables_dir: Path) -> dict[str, str]:
    merged = tables_dir / "expression_clinical_manifest.tsv"
    survival = tables_dir / "survival_proxy.tsv"
    pd.DataFrame({"sample_id": matrix.columns.astype(str), "matrix_column": matrix.columns.astype(str)}).merge(
        clinical, on="sample_id", how="left"
    ).to_csv(merged, sep="\t", index=False)
    _survival_proxy(matrix, clinical, stats.iloc[0]["feature_id"]).to_csv(survival, sep="\t", index=False)
    return {"expression_clinical_manifest": str(merged), "survival_proxy": str(survival)}


def _wgcna_tables(matrix: pd.DataFrame, clinical: pd.DataFrame, tables_dir: Path) -> dict[str, str]:
    modules = tables_dir / "wgcna_module_assignments.tsv"
    trait = tables_dir / "wgcna_trait_associations.tsv"
    corr = matrix.T.corr().fillna(0.0)
    module_ids = pd.cut(corr.mean(axis=1).rank(method="first"), bins=4, labels=["blue", "brown", "turquoise", "yellow"])
    pd.DataFrame({"feature_id": corr.index.astype(str), "module": module_ids.astype(str)}).to_csv(modules, sep="\t", index=False)
    rows = []
    for module_name in sorted(set(module_ids.astype(str))):
        genes = module_ids.index[module_ids.astype(str) == module_name]
        eigengene = matrix.loc[genes].mean(axis=0)
        rows.append({"module": module_name, "mean_eigengene": float(eigengene.mean()), "n_features": int(len(genes))})
    pd.DataFrame(rows).to_csv(trait, sep="\t", index=False)
    return {"wgcna_module_assignments": str(modules), "wgcna_trait_associations": str(trait)}


def _single_gene_tables(
    matrix: pd.DataFrame,
    stats: pd.DataFrame,
    clinical: pd.DataFrame,
    tables_dir: Path,
    module_cfg: dict[str, Any],
) -> dict[str, str]:
    gene = str(module_cfg.get("gene") or "TP53")
    if gene not in matrix.index:
        gene = str(matrix.index[0])
    expr = matrix.loc[gene]
    summary = tables_dir / "single_gene_summary.tsv"
    survival = tables_dir / "single_gene_survival_proxy.tsv"
    pd.DataFrame(
        {
            "sample_id": expr.index.astype(str),
            "gene": gene,
            "expression": expr.to_numpy(),
            "group": np.where(expr >= expr.median(), "high", "low"),
        }
    ).to_csv(summary, sep="\t", index=False)
    _survival_proxy(matrix.loc[[gene]], clinical, gene).to_csv(survival, sep="\t", index=False)
    return {"single_gene_summary": str(summary), "single_gene_survival_proxy": str(survival)}


def _clinical_assoc_tables(matrix: pd.DataFrame, clinical: pd.DataFrame, tables_dir: Path) -> dict[str, str]:
    assoc = tables_dir / "clinical_feature_associations.tsv"
    numeric_clinical = clinical.select_dtypes(include=[np.number])
    rows = []
    for feature_id, values in matrix.iterrows():
        for column in numeric_clinical.columns:
            aligned = numeric_clinical[column].reindex(range(len(values))).to_numpy(dtype=float)
            if len(aligned) == len(values) and np.nanstd(aligned) > 0:
                rows.append({"feature_id": feature_id, "clinical_variable": column, "correlation": _safe_corr(values.to_numpy(), aligned)})
    pd.DataFrame(rows or [{"feature_id": str(matrix.index[0]), "clinical_variable": "none", "correlation": 0.0}]).to_csv(assoc, sep="\t", index=False)
    return {"clinical_feature_associations": str(assoc)}


def _survival_proxy(matrix: pd.DataFrame, clinical: pd.DataFrame, feature_id: str) -> pd.DataFrame:
    values = matrix.loc[feature_id]
    groups = pd.Series(np.where(values >= values.median(), "high", "low"), index=values.index, name="risk_group")
    frame = pd.DataFrame({"sample_id": values.index.astype(str), "expression": values.to_numpy(), "risk_group": groups.to_numpy()})
    merged = frame.merge(clinical, on="sample_id", how="left")
    return (
        merged.groupby("risk_group", dropna=False)
        .agg(n=("sample_id", "size"), median_expression=("expression", "median"), median_survival_time=("survival_time", "median"), event_rate=("event", "mean"))
        .reset_index()
    )


def _write_common_figures(
    module_name: str,
    matrix: pd.DataFrame,
    stats: pd.DataFrame,
    samples: pd.DataFrame,
    figures_dir: Path,
    design: dict[str, Any],
) -> dict[str, str]:
    pca = figures_dir / "pca.png"
    volcano = figures_dir / "volcano.png"
    heatmap = figures_dir / "top_feature_heatmap.png"
    _plot_pca(matrix, samples, design, pca, title=f"{module_name} PCA")
    _plot_volcano(stats, volcano, title=f"{module_name} Volcano")
    top = [feature for feature in stats.head(15)["feature_id"] if feature in matrix.index]
    _plot_heatmap(matrix.loc[top], heatmap, title=f"{module_name} Top features")
    return {"pca": str(pca), "volcano": str(volcano), "heatmap": str(heatmap)}


def _write_module_figures(
    module_name: str,
    matrix: pd.DataFrame,
    stats: pd.DataFrame,
    samples: pd.DataFrame,
    inputs: BulkInputs,
    figures_dir: Path,
    module_cfg: dict[str, Any],
) -> dict[str, str]:
    paths: dict[str, str] = {}
    if module_name in {"proteomics", "wgcna", "clinical_assoc"}:
        path = figures_dir / "correlation_network_proxy.png"
        _plot_correlation(matrix, path, title=f"{module_name} correlation")
        paths["correlation_network_proxy"] = str(path)
    if module_name in {"publicdb", "single_gene", "clinical_assoc"}:
        path = figures_dir / "survival_proxy.png"
        _plot_survival_proxy(path)
        paths["survival_proxy"] = str(path)
    if module_name == "methylation":
        path = figures_dir / "beta_density.png"
        _plot_beta_density(matrix, path)
        paths["beta_density"] = str(path)
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
    sns.scatterplot(x=coords[:, 0], y=coords[:, 1], hue=condition, s=80, edgecolor="white", linewidth=0.4)
    for x, y, label in zip(coords[:, 0], coords[:, 1], matrix.columns):
        plt.text(x, y, str(label), fontsize=8)
    plt.title(title)
    plt.xlabel("PC1")
    plt.ylabel("PC2")
    plt.tight_layout()
    save_figure(path, style=tokens)


def _plot_volcano(stats: pd.DataFrame, path: Path, title: str) -> None:
    tokens = apply_clinical_journal_style()
    frame = stats.copy()
    frame["neg_log10_padj"] = -np.log10(frame["padj"].clip(lower=1e-12))
    frame["class"] = np.where(frame["padj"] < 0.1, np.where(frame["effect_size"] > 0, "Up", "Down"), "NS")
    palette = {"Up": tokens["case"], "Down": tokens["control"], "NS": tokens["neutral"]}
    plt.figure(figsize=(6, 4))
    sns.scatterplot(data=frame, x="effect_size", y="neg_log10_padj", hue="class", palette=palette, s=20, linewidth=0, alpha=0.85)
    plt.axvline(1, color=tokens["muted"], linestyle="--", linewidth=0.8)
    plt.axvline(-1, color=tokens["muted"], linestyle="--", linewidth=0.8)
    plt.title(title)
    plt.xlabel("Effect size")
    plt.ylabel("-log10(FDR)")
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
    corr = matrix.T.corr().iloc[:20, :20].fillna(0.0)
    plt.figure(figsize=(5.5, 4.8))
    sns.heatmap(corr, cmap=continuous_cmap(tokens), center=0)
    plt.title(title)
    plt.tight_layout()
    save_figure(path, style=tokens)


def _plot_survival_proxy(path: Path) -> None:
    tokens = apply_clinical_journal_style()
    months = np.arange(0, 61, 6)
    high = np.exp(-months / 36)
    low = np.exp(-months / 56)
    plt.figure(figsize=(6, 4))
    plt.step(months, high, where="post", label="High group", color=tokens["case"], linewidth=1.7)
    plt.step(months, low, where="post", label="Low group", color=tokens["control"], linewidth=1.7)
    plt.xlabel("Months")
    plt.ylabel("Survival probability")
    plt.title("Survival proxy")
    plt.legend()
    plt.tight_layout()
    save_figure(path, style=tokens)


def _plot_beta_density(matrix: pd.DataFrame, path: Path) -> None:
    tokens = apply_clinical_journal_style()
    plt.figure(figsize=(6, 4))
    for column in matrix.columns:
        values = matrix[column].clip(0, 1)
        if float(values.std()) == 0.0:
            plt.axvline(float(values.iloc[0]), linewidth=1, label=str(column))
        else:
            sns.kdeplot(values, linewidth=1, label=str(column))
    plt.xlabel("Beta value")
    plt.ylabel("Density")
    plt.title("Methylation beta density")
    plt.tight_layout()
    save_figure(path, style=tokens)


def _write_bulk_objects(module_name: str, matrix: pd.DataFrame, stats: pd.DataFrame, inputs: BulkInputs, objects_dir: Path) -> dict[str, str]:
    manifest = {
        "module": module_name,
        "backend": "python",
        "matrix_shape": list(matrix.shape),
        "input_source": inputs.source,
        "top_features": stats.head(15)["feature_id"].tolist(),
    }
    json_path = objects_dir / "object_manifest.json"
    rds_path = objects_dir / f"{module_name}_python_object.rds"
    rdata_path = objects_dir / f"{module_name}_workspace.RData"
    json_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    rds_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    rdata_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return {"manifest": str(json_path), "rds": str(rds_path), "RData": str(rdata_path)}


def _safe_corr(left: np.ndarray, right: np.ndarray) -> float:
    if len(left) != len(right) or np.nanstd(left) == 0 or np.nanstd(right) == 0:
        return 0.0
    return float(np.corrcoef(left, right)[0, 1])
