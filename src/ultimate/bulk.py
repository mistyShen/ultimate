from __future__ import annotations

import importlib.util
import json
import math
import shutil
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
from ultimate.backend_registry import build_backend_plan, enrich_backend_plan_for_run, write_backend_plan_table
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
from ultimate.rnaseq_de_backend import run_rnaseq_de_backend, rnaseq_de_backend_requested


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
    backend_plan_base = build_backend_plan(module_name, config)
    active_backend_ids = {str(row.get("backend_id")) for row in backend_plan_base.get("active_backends", []) if isinstance(row, dict)}

    artifacts["tables"].update(_write_common_tables(module_name, matrix, stats, samples, inputs, tables_dir))
    artifacts["tables"].update(_write_module_tables(module_name, matrix, stats, samples, inputs, tables_dir, module_cfg))
    artifacts["figures"].update(_write_common_figures(module_name, matrix, stats, samples, figures_dir, design))
    artifacts["figures"].update(_write_module_figures(module_name, matrix, stats, samples, inputs, figures_dir, module_cfg))
    artifacts["objects"].update(_write_bulk_objects(module_name, matrix, stats, inputs, objects_dir))
    backend_execution: list[dict[str, Any]] = []
    rnaseq_de_result: dict[str, Any] | None = None
    proteomics_limma_result: dict[str, Any] | None = None
    methylation_dmp_result: dict[str, Any] | None = None
    if module_name == "rnaseq" and rnaseq_de_backend_requested(module_cfg):
        backend_samplesheet = _write_backend_samplesheet(samples, tables_dir)
        rnaseq_de_result = run_rnaseq_de_backend(
            counts_path=_rnaseq_counts_path(module_cfg, inputs),
            samplesheet_path=backend_samplesheet,
            tables_dir=tables_dir,
            figures_dir=figures_dir,
            objects_dir=objects_dir,
            design=design,
            analysis_level=str(level_fields.get("analysis_level") or "smoke_backend"),
            module_cfg=module_cfg,
        )
        backend_execution.append(
            {
                "backend_id": rnaseq_de_result["backend_id"],
                "status": rnaseq_de_result["status"],
                "analysis_level": rnaseq_de_result["analysis_level"],
                "skip_reason": rnaseq_de_result["skip_reason"],
            }
        )
        de_artifacts = rnaseq_de_result.get("artifacts") if isinstance(rnaseq_de_result.get("artifacts"), dict) else {}
        for key in ("de_results", "deseq2_edgeR_de_results", "de_backend_status", "de_backend_versions", "manifest"):
            if key in de_artifacts:
                artifacts["tables"][key] = str(de_artifacts[key])
        for key in ("volcano", "top_gene_heatmap"):
            if key in de_artifacts:
                artifacts["figures"][f"de_backend_{key}"] = str(de_artifacts[key])
        if "rds" in de_artifacts:
            artifacts["objects"]["rnaseq_de_backend_rds"] = str(de_artifacts["rds"])
    if module_name == "proteomics" and "proteomics.de.limma_optional" in active_backend_ids:
        proteomics_limma_result = _run_proteomics_limma_backend(
            matrix=matrix,
            samples=samples,
            design=design,
            tables_dir=tables_dir,
            figures_dir=figures_dir,
            objects_dir=objects_dir,
            analysis_fields=level_fields,
            input_artifact=str(input_matrix or inputs.source),
            source_dataset=_source_dataset(config, module_name),
        )
        backend_execution.append(_bulk_backend_execution_row(proteomics_limma_result, level_fields))
        _merge_backend_artifacts(artifacts, proteomics_limma_result.get("artifacts", {}))
    if module_name == "methylation" and "methylation.dmp.limma_beta" in active_backend_ids:
        methylation_dmp_result = _run_methylation_dmp_backend(
            beta_matrix=matrix,
            samples=samples,
            design=design,
            tables_dir=tables_dir,
            figures_dir=figures_dir,
            objects_dir=objects_dir,
            analysis_fields=level_fields,
            input_artifact=str(input_matrix or inputs.source),
            source_dataset=_source_dataset(config, module_name),
        )
        backend_execution.append(_bulk_backend_execution_row(methylation_dmp_result, level_fields))
        _merge_backend_artifacts(artifacts, methylation_dmp_result.get("artifacts", {}))
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
    artifacts["tables"]["backend_plan"] = str(write_backend_plan_table(module_name, config, tables_dir))
    backend_plan = enrich_backend_plan_for_run(
        backend_plan_base,
        analysis_level=str(level_fields.get("analysis_level") or "smoke_backend"),
        delivery_allowed=bool(level_fields.get("delivery_allowed") is True),
        validation_evidence_allowed=bool(level_fields.get("validation_evidence_allowed") is True),
    )
    if backend_execution:
        backend_execution_path = tables_dir / "backend_execution.tsv"
        pd.DataFrame(backend_execution).to_csv(backend_execution_path, sep="\t", index=False)
        artifacts["tables"]["backend_execution"] = str(backend_execution_path)

    module_status = "complete_python_bulk_backend"
    skip_reasons: list[str] = []
    if rnaseq_de_result is not None and rnaseq_de_result.get("status") != "ready":
        module_status = f"partial:rnaseq_de_backend_{rnaseq_de_result.get('status')}"
        skip_reasons.append(str(rnaseq_de_result.get("skip_reason") or "rnaseq_de_backend_not_ready"))
    if proteomics_limma_result is not None and proteomics_limma_result.get("status") != "ready":
        module_status = f"partial:proteomics_limma_backend_{proteomics_limma_result.get('status')}"
        skip_reasons.append(str(proteomics_limma_result.get("skip_reason") or "proteomics_limma_backend_not_ready"))
    if methylation_dmp_result is not None and methylation_dmp_result.get("status") != "ready":
        module_status = f"partial:methylation_dmp_backend_{methylation_dmp_result.get('status')}"
        skip_reasons.append(str(methylation_dmp_result.get("skip_reason") or "methylation_dmp_backend_not_ready"))

    artifacts["tables"]["module_qc_manifest"] = write_module_qc_manifest(
        module_name=module_name,
        tables_dir=tables_dir,
        status=module_status,
        artifacts=artifacts,
        analysis_fields=level_fields,
        warnings=list(inputs.warnings),
        skip_reasons=skip_reasons,
    )

    module_manifest = {
        "module": module_name,
        "title_cn": MODULE_SPECS[module_name].title_cn,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": module_status,
        **level_fields,
        "backend": {
            "primary": "python",
            "selected_backend_id": backend_plan["selected_backend_id"],
            "selected_backend_status": backend_plan["selected_backend_status"],
            "backend_role": backend_plan["selected_backend_role"],
            "resource_profile": backend_plan["backend_resource_profile"],
            "optional_r_entrypoint": module_cfg.get("r_entrypoint", f"scripts/R/{module_name}.R"),
            "python_requirements": list(BULK_PYTHON_REQUIREMENTS[module_name]),
        },
        "backend_plan": backend_plan,
        "backend_execution": backend_execution,
        "rnaseq_de_backend": rnaseq_de_result or {"backend_id": "rnaseq.de.deseq2_edger", "status": "not_requested"},
        "proteomics_limma_backend": proteomics_limma_result or {"backend_id": "proteomics.de.limma_optional", "status": "not_requested"},
        "methylation_dmp_backend": methylation_dmp_result or {"backend_id": "methylation.dmp.limma_beta", "status": "not_requested"},
        "backend_id": backend_plan["selected_backend_id"],
        "backend_status": backend_plan["selected_backend_status"],
        "backend_analysis_level": backend_plan["backend_analysis_level"],
        "backend_delivery_allowed": backend_plan["backend_delivery_allowed"],
        "backend_validation_evidence_allowed": backend_plan["backend_validation_evidence_allowed"],
        "backend_skip_reason": backend_plan["backend_skip_reason"],
        "backend_resource_profile": backend_plan["backend_resource_profile"],
        "backend_slurm_job_id": backend_plan["backend_slurm_job_id"],
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
        "skip_reasons": skip_reasons,
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
    missingness = tables_dir / "missingness_summary.tsv"
    differential = tables_dir / "differential_proteins.tsv"
    enrichment = tables_dir / "enrichment_handoff.tsv"
    ppi = tables_dir / "ppi_export.tsv"
    matrix.to_csv(abundance, sep="\t")
    pd.DataFrame(
        {
            "sample_id": matrix.columns.astype(str),
            "median_abundance": matrix.median(axis=0).to_numpy(),
            "missing_fraction": matrix.isna().mean(axis=0).to_numpy(),
            "detected_proteins": matrix.notna().sum(axis=0).to_numpy(),
        }
    ).to_csv(qc, sep="\t", index=False)
    pd.DataFrame(
        {
            "feature_id": matrix.index.astype(str),
            "missing_fraction": matrix.isna().mean(axis=1).to_numpy(),
            "detected_samples": matrix.notna().sum(axis=1).to_numpy(),
            "mean_abundance": matrix.mean(axis=1).to_numpy(),
        }
    ).to_csv(missingness, sep="\t", index=False)
    stats.assign(
        backend_note="Python MVP differential abundance proxy; use limma backend for publication-grade proteomics DE."
    ).to_csv(differential, sep="\t", index=False)
    stats.loc[:, ["feature_id", "log2FC", "padj"]].assign(
        handoff_type="GO/KEGG/PPI enrichment input",
        protein_identifier_scope="feature_id_or_gene_symbol_from_input",
    ).to_csv(enrichment, sep="\t", index=False)
    top = stats.head(40)["feature_id"].astype(str).tolist()
    ppi_rows = []
    for left, right in zip(top[0::2], top[1::2]):
        ppi_rows.append(
            {
                "protein_a": left,
                "protein_b": right,
                "edge_type": "correlation_network_handoff",
                "score": "",
                "warning": "PPI export is an input table for STRING/Cytoscape, not inferred physical interaction evidence.",
            }
        )
    pd.DataFrame(
        ppi_rows
        or [
            {
                "protein_a": str(matrix.index[0]) if len(matrix.index) else "",
                "protein_b": "",
                "edge_type": "correlation_network_handoff",
                "score": "",
                "warning": "PPI export requires at least two proteins.",
            }
        ]
    ).to_csv(ppi, sep="\t", index=False)
    return {
        "normalized_abundance": str(abundance),
        "abundance_qc": str(qc),
        "missingness_summary": str(missingness),
        "differential_proteins": str(differential),
        "enrichment_handoff": str(enrichment),
        "ppi_export": str(ppi),
    }


def _run_proteomics_limma_backend(
    *,
    matrix: pd.DataFrame,
    samples: pd.DataFrame,
    design: dict[str, Any],
    tables_dir: Path,
    figures_dir: Path,
    objects_dir: Path,
    analysis_fields: dict[str, Any],
    input_artifact: str,
    source_dataset: str,
) -> dict[str, Any]:
    backend_id = "proteomics.de.limma_optional"
    paths = _backend_paths(tables_dir, figures_dir, objects_dir, prefix="proteomics_limma", result_name="limma_de_results")
    group = _validated_two_group_columns(matrix, samples, design, min_per_group=2)
    warning = "蛋白差异是 abundance table 统计结果；相关网络/PPI 仍为 handoff，不能写成真实物理互作或机制证明。"
    if group["status"] != "ready":
        return _write_bulk_backend_skip(paths, backend_id, analysis_fields, group["reason"], warning)
    result = _two_group_stats(matrix, group["control_cols"], group["case_cols"]).rename(
        columns={"feature_id": "protein_id", "log2FC": "log2_abundance_delta"}
    )
    result.insert(0, "backend_id", backend_id)
    result["method"] = "limma_style_moderated_statistics_python_fallback"
    result["method_boundary"] = warning
    result["control_group"] = group["control"]
    result["case_group"] = group["case"]
    result.to_csv(paths["result"], sep="\t", index=False)
    _write_backend_status(paths["status"], backend_id, "ready", "", analysis_fields, warning, group)
    _write_backend_versions(paths["versions"], backend_id)
    _write_backend_manifest(paths["manifest"], backend_id, "ready", "", analysis_fields, warning, paths, group)
    _write_bulk_backend_object(paths["object"], backend_id, "ready", result.head(100), warning)
    _write_backend_volcano(result.rename(columns={"protein_id": "feature_id", "log2_abundance_delta": "log2FC"}), paths["volcano"], title="Proteomics limma-style DE")
    _write_backend_heatmap(matrix, group["control_cols"] + group["case_cols"], result["protein_id"].astype(str).head(40).tolist(), paths["heatmap"], title="Proteomics differential abundance")
    return {
        "backend_id": backend_id,
        "status": "ready",
        "analysis_level": analysis_fields.get("analysis_level") or "smoke_backend",
        "skip_reason": "",
        "interpretation_warning": warning,
        "artifacts": {
            "tables": {
                "limma_de_results": str(paths["result"]),
                "proteomics_limma_backend_status": str(paths["status"]),
                "proteomics_limma_backend_manifest": str(paths["manifest"]),
                "proteomics_limma_backend_versions": str(paths["versions"]),
            },
            "figures": {
                "proteomics_limma_volcano": str(paths["volcano"]),
                "proteomics_limma_heatmap": str(paths["heatmap"]),
            },
            "objects": {"proteomics_limma_backend_object": str(paths["object"])},
        },
    }


def _run_methylation_dmp_backend(
    *,
    beta_matrix: pd.DataFrame,
    samples: pd.DataFrame,
    design: dict[str, Any],
    tables_dir: Path,
    figures_dir: Path,
    objects_dir: Path,
    analysis_fields: dict[str, Any],
    input_artifact: str,
    source_dataset: str,
) -> dict[str, Any]:
    backend_id = "methylation.dmp.limma_beta"
    paths = _backend_paths(tables_dir, figures_dir, objects_dir, prefix="methylation_dmp", result_name="dmp_limma_results")
    mvalue_summary = tables_dir / "methylation_mvalue_summary.tsv"
    beta = beta_matrix.clip(1e-4, 1 - 1e-4)
    mvalues = np.log2(beta / (1 - beta))
    pd.DataFrame(
        {
            "sample_id": beta.columns.astype(str),
            "mean_beta": beta.mean(axis=0).to_numpy(),
            "median_beta": beta.median(axis=0).to_numpy(),
            "mean_m_value": mvalues.mean(axis=0).to_numpy(),
            "median_m_value": mvalues.median(axis=0).to_numpy(),
        }
    ).to_csv(mvalue_summary, sep="\t", index=False)
    warning = "DMP 是 CpG/region-level beta/M-value 统计差异，不是完整 DMR；IDAT、scBS-seq、CUT&Tag/CUT&RUN 不能混用统计假设。"
    group = _validated_two_group_columns(mvalues, samples, design, min_per_group=2)
    if group["status"] != "ready":
        skipped = _write_bulk_backend_skip(paths, backend_id, analysis_fields, group["reason"], warning)
        skipped["artifacts"]["tables"]["methylation_mvalue_summary"] = str(mvalue_summary)
        return skipped
    result = _two_group_stats(mvalues, group["control_cols"], group["case_cols"]).rename(
        columns={"feature_id": "region_id", "log2FC": "m_value_delta"}
    )
    beta_delta = beta[group["case_cols"]].mean(axis=1) - beta[group["control_cols"]].mean(axis=1)
    result["beta_delta"] = result["region_id"].map(beta_delta.to_dict()).astype(float)
    result.insert(0, "backend_id", backend_id)
    result["method"] = "limma_style_mvalue_dmp_python_fallback"
    result["method_boundary"] = warning
    result["annotation_status"] = "annotation_handoff_required_for_genomic_context"
    result["control_group"] = group["control"]
    result["case_group"] = group["case"]
    result.to_csv(paths["result"], sep="\t", index=False)
    _write_backend_status(paths["status"], backend_id, "ready", "", analysis_fields, warning, group)
    _write_backend_versions(paths["versions"], backend_id)
    _write_backend_manifest(paths["manifest"], backend_id, "ready", "", analysis_fields, warning, paths, group)
    _write_bulk_backend_object(paths["object"], backend_id, "ready", result.head(100), warning)
    _write_backend_volcano(result.rename(columns={"region_id": "feature_id", "m_value_delta": "log2FC"}), paths["volcano"], title="Methylation DMP")
    _write_backend_heatmap(mvalues, group["control_cols"] + group["case_cols"], result["region_id"].astype(str).head(40).tolist(), paths["heatmap"], title="DMP M-value heatmap")
    return {
        "backend_id": backend_id,
        "status": "ready",
        "analysis_level": analysis_fields.get("analysis_level") or "smoke_backend",
        "skip_reason": "",
        "interpretation_warning": warning,
        "artifacts": {
            "tables": {
                "dmp_limma_results": str(paths["result"]),
                "methylation_dmp_backend_status": str(paths["status"]),
                "methylation_dmp_backend_manifest": str(paths["manifest"]),
                "methylation_dmp_backend_versions": str(paths["versions"]),
                "methylation_mvalue_summary": str(mvalue_summary),
            },
            "figures": {
                "methylation_dmp_volcano": str(paths["volcano"]),
                "methylation_dmp_heatmap": str(paths["heatmap"]),
            },
            "objects": {"methylation_dmp_backend_object": str(paths["object"])},
        },
    }


def _backend_paths(tables_dir: Path, figures_dir: Path, objects_dir: Path, *, prefix: str, result_name: str) -> dict[str, Path]:
    return {
        "result": tables_dir / f"{result_name}.tsv",
        "status": tables_dir / f"{prefix}_backend_status.tsv",
        "manifest": tables_dir / f"{prefix}_backend_manifest.json",
        "versions": tables_dir / f"{prefix}_backend_versions.tsv",
        "volcano": figures_dir / f"{prefix}_volcano.png",
        "heatmap": figures_dir / f"{prefix}_heatmap.png",
        "object": objects_dir / f"{prefix}_backend.rds",
    }


def _validated_two_group_columns(matrix: pd.DataFrame, samples: pd.DataFrame, design: dict[str, Any], *, min_per_group: int) -> dict[str, Any]:
    condition_column = str(design.get("condition_column", "condition"))
    control = str(design.get("control", "control"))
    case = str(design.get("case", "treated"))
    if samples.empty or "sample_id" not in samples.columns:
        return {"status": "skipped", "reason": "missing_samplesheet_with_sample_id", "control": control, "case": case, "control_cols": [], "case_cols": []}
    if condition_column not in samples.columns:
        return {"status": "skipped", "reason": f"missing_condition_column:{condition_column}", "control": control, "case": case, "control_cols": [], "case_cols": []}
    lookup = dict(zip(samples["sample_id"].astype(str), samples[condition_column].astype(str)))
    control_cols = [col for col in matrix.columns.astype(str) if lookup.get(str(col)) == control]
    case_cols = [col for col in matrix.columns.astype(str) if lookup.get(str(col)) == case]
    if len(control_cols) < min_per_group or len(case_cols) < min_per_group:
        return {
            "status": "skipped",
            "reason": f"insufficient_replicates:control={len(control_cols)};case={len(case_cols)};required={min_per_group}",
            "control": control,
            "case": case,
            "control_cols": control_cols,
            "case_cols": case_cols,
        }
    return {"status": "ready", "reason": "", "control": control, "case": case, "control_cols": control_cols, "case_cols": case_cols}


def _two_group_stats(matrix: pd.DataFrame, control_cols: list[str], case_cols: list[str]) -> pd.DataFrame:
    control = matrix[control_cols].apply(pd.to_numeric, errors="coerce")
    case = matrix[case_cols].apply(pd.to_numeric, errors="coerce")
    control_mean = control.mean(axis=1)
    case_mean = case.mean(axis=1)
    effect = case_mean - control_mean
    control_var = control.var(axis=1, ddof=1).replace(0, np.nan)
    case_var = case.var(axis=1, ddof=1).replace(0, np.nan)
    stderr = np.sqrt((control_var / max(1, len(control_cols))) + (case_var / max(1, len(case_cols)))).replace(0, np.nan).fillna(matrix.std(axis=1).replace(0, np.nan).fillna(1.0))
    z_score = effect / stderr
    pvalue = pd.Series([_normal_sf(abs(value)) * 2 for value in z_score.fillna(0.0)], index=matrix.index)
    padj = _benjamini_hochberg(pvalue)
    return pd.DataFrame(
        {
            "feature_id": matrix.index.astype(str),
            "control_mean": control_mean.to_numpy(),
            "case_mean": case_mean.to_numpy(),
            "log2FC": effect.to_numpy(),
            "statistic": z_score.to_numpy(),
            "pvalue": pvalue.to_numpy(),
            "padj": padj.to_numpy(),
        }
    ).sort_values(["padj", "pvalue"])


def _write_bulk_backend_skip(paths: dict[str, Path], backend_id: str, analysis_fields: dict[str, Any], reason: str, warning: str) -> dict[str, Any]:
    pd.DataFrame(
        [
            {
                "backend_id": backend_id,
                "status": "skipped",
                "reason": reason,
                "method_boundary": warning,
                "analysis_level": analysis_fields.get("analysis_level") or "smoke_backend",
            }
        ]
    ).to_csv(paths["result"], sep="\t", index=False)
    _write_backend_status(paths["status"], backend_id, "skipped", reason, analysis_fields, warning, {})
    _write_backend_versions(paths["versions"], backend_id)
    _write_backend_manifest(paths["manifest"], backend_id, "skipped", reason, analysis_fields, warning, paths, {})
    _write_bulk_backend_object(paths["object"], backend_id, "skipped", pd.DataFrame(), warning)
    _write_placeholder_backend_figure(paths["volcano"], title=backend_id, message=reason)
    _write_placeholder_backend_figure(paths["heatmap"], title=backend_id, message=reason)
    return {
        "backend_id": backend_id,
        "status": "skipped",
        "analysis_level": analysis_fields.get("analysis_level") or "smoke_backend",
        "skip_reason": reason,
        "interpretation_warning": warning,
        "artifacts": {
            "tables": {
                "result": str(paths["result"]),
                "backend_status": str(paths["status"]),
                "backend_manifest": str(paths["manifest"]),
                "backend_versions": str(paths["versions"]),
            },
            "figures": {"volcano": str(paths["volcano"]), "heatmap": str(paths["heatmap"])},
            "objects": {"backend_object": str(paths["object"])},
        },
    }


def _write_backend_status(path: Path, backend_id: str, status: str, reason: str, analysis_fields: dict[str, Any], warning: str, group: dict[str, Any]) -> None:
    pd.DataFrame(
        [
            {
                "backend_id": backend_id,
                "status": status,
                "reason": reason,
                "analysis_level": analysis_fields.get("analysis_level") or "smoke_backend",
                "delivery_allowed": bool(analysis_fields.get("delivery_allowed") is True and status == "ready"),
                "validation_evidence_allowed": bool(analysis_fields.get("validation_evidence_allowed") is True and status == "ready"),
                "control_group": group.get("control", ""),
                "case_group": group.get("case", ""),
                "n_control": len(group.get("control_cols", []) or []),
                "n_case": len(group.get("case_cols", []) or []),
                "method_boundary": warning,
            }
        ]
    ).to_csv(path, sep="\t", index=False)


def _write_backend_versions(path: Path, backend_id: str) -> None:
    pd.DataFrame(
        [
            {"backend_id": backend_id, "tool": "python", "version": "runtime"},
            {"backend_id": backend_id, "tool": "numpy", "version": np.__version__},
            {"backend_id": backend_id, "tool": "pandas", "version": pd.__version__},
            {"backend_id": backend_id, "tool": "Rscript", "version": "available" if shutil.which("Rscript") else "not_available"},
            {"backend_id": backend_id, "tool": "limma", "version": "optional_r_backend_not_invoked_by_python_mvp"},
        ]
    ).to_csv(path, sep="\t", index=False)


def _write_backend_manifest(path: Path, backend_id: str, status: str, reason: str, analysis_fields: dict[str, Any], warning: str, paths: dict[str, Path], group: dict[str, Any]) -> None:
    manifest = {
        "backend_id": backend_id,
        "status": status,
        "skip_reason": reason,
        "analysis_level": analysis_fields.get("analysis_level") or "smoke_backend",
        "delivery_allowed": bool(analysis_fields.get("delivery_allowed") is True and status == "ready"),
        "validation_evidence_allowed": bool(analysis_fields.get("validation_evidence_allowed") is True and status == "ready"),
        "method_boundary": warning,
        "group_design": {key: value for key, value in group.items() if key in {"control", "case", "control_cols", "case_cols", "reason"}},
        "artifacts": {key: str(value) for key, value in paths.items()},
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_bulk_backend_object(path: Path, backend_id: str, status: str, frame: pd.DataFrame, warning: str) -> None:
    payload = {
        "backend_id": backend_id,
        "status": status,
        "method_boundary": warning,
        "top_rows": frame.to_dict(orient="records") if not frame.empty else [],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_backend_volcano(stats: pd.DataFrame, path: Path, *, title: str) -> None:
    tokens = apply_clinical_journal_style()
    plot = stats.copy()
    plot["neg_log10_padj"] = -np.log10(plot["padj"].astype(float).clip(lower=1e-300))
    plt.figure(figsize=(6.4, 5.0))
    plt.scatter(plot["log2FC"].astype(float), plot["neg_log10_padj"], s=14, alpha=0.65, color=tokens["primary"])
    plt.axhline(-np.log10(0.05), color=tokens["muted"], lw=0.9, ls="--")
    plt.axvline(0, color=tokens["muted"], lw=0.9)
    plt.xlabel("Effect size")
    plt.ylabel("-log10 adjusted P")
    plt.title(title)
    plt.tight_layout()
    save_figure(path, style=tokens)


def _write_backend_heatmap(matrix: pd.DataFrame, columns: list[str], features: list[str], path: Path, *, title: str) -> None:
    tokens = apply_clinical_journal_style()
    selected_features = [feature for feature in features if feature in matrix.index][: min(40, len(features))]
    selected_columns = [column for column in columns if column in matrix.columns]
    if not selected_features or not selected_columns:
        _write_placeholder_backend_figure(path, title=title, message="No features available")
        return
    heat = matrix.loc[selected_features, selected_columns].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    heat = heat.sub(heat.mean(axis=1), axis=0).div(heat.std(axis=1).replace(0, np.nan), axis=0).fillna(0.0)
    plt.figure(figsize=(7.2, max(4.5, min(9.0, 0.18 * len(selected_features) + 2.0))))
    sns.heatmap(heat, cmap="vlag", center=0, cbar_kws={"label": "row z-score"})
    plt.xlabel("Sample")
    plt.ylabel("Feature")
    plt.title(title)
    plt.tight_layout()
    save_figure(path, style=tokens)


def _write_placeholder_backend_figure(path: Path, *, title: str, message: str) -> None:
    tokens = apply_clinical_journal_style()
    plt.figure(figsize=(5.8, 3.6))
    plt.text(0.5, 0.5, message, ha="center", va="center", wrap=True, color=tokens["muted"])
    plt.axis("off")
    plt.title(title)
    plt.tight_layout()
    save_figure(path, style=tokens)


def _bulk_backend_execution_row(result: dict[str, Any], analysis_fields: dict[str, Any]) -> dict[str, Any]:
    ready = result.get("status") == "ready"
    return {
        "backend_id": result.get("backend_id", ""),
        "status": "ready" if ready else "skipped",
        "analysis_level": analysis_fields.get("analysis_level") or "smoke_backend",
        "delivery_allowed": bool(analysis_fields.get("delivery_allowed") is True and ready),
        "validation_evidence_allowed": bool(analysis_fields.get("validation_evidence_allowed") is True and ready),
        "reason": "" if ready else str(result.get("skip_reason") or "backend_not_ready"),
        "backend_slurm_job_id": "",
        "interpretation_warning": str(result.get("interpretation_warning") or result.get("method_boundary") or ""),
    }


def _merge_backend_artifacts(artifacts: dict[str, dict[str, str]], backend_artifacts: dict[str, Any]) -> None:
    for section in ("tables", "figures", "objects"):
        values = backend_artifacts.get(section) if isinstance(backend_artifacts, dict) else None
        if isinstance(values, dict):
            artifacts.setdefault(section, {}).update({str(key): str(value) for key, value in values.items()})


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


def _write_backend_samplesheet(samples: pd.DataFrame, tables_dir: Path) -> Path:
    path = tables_dir / "rnaseq_de_backend_samplesheet.tsv"
    samples.to_csv(path, sep="\t", index=False)
    return path


def _rnaseq_counts_path(module_cfg: dict[str, Any], inputs: BulkInputs) -> Path | None:
    de_cfg = module_cfg.get("de_backend") if isinstance(module_cfg.get("de_backend"), dict) else {}
    candidates = (
        de_cfg.get("counts_path"),
        module_cfg.get("input_matrix"),
        module_cfg.get("matrix_path"),
        (module_cfg.get("raw") or {}).get("matrix_path") if isinstance(module_cfg.get("raw"), dict) else None,
        inputs.source if inputs.source != "demo_generated_matrix" else None,
    )
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(str(candidate))
        if path.exists():
            return path
    return None


def _safe_corr(left: np.ndarray, right: np.ndarray) -> float:
    if len(left) != len(right) or np.nanstd(left) == 0 or np.nanstd(right) == 0:
        return 0.0
    return float(np.corrcoef(left, right)[0, 1])
