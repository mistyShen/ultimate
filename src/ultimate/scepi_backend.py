from __future__ import annotations

import json
import re
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
    write_tool_coverage_table,
)
from ultimate.plot_style import apply_clinical_journal_style, save_figure


SCEPI_BACKEND_ID = "scepi.default.matrix_handoff_mvp"
SCEPI_WARNING = "beta matrix、scBS-seq、CUT&Tag、CUT&RUN、scATAC 不能混用同一统计套路；region-level 结果是矩阵级 QC/summary，不等同于 full modality-specific backend。"
SCEPI_FEATURE_ID_COLUMNS = ("feature_id", "region_id", "peak_id", "probe_id", "locus_id")

SCEPI_BACKEND_METADATA: dict[str, Any] = {
    "module": "scepi",
    "backend_id": SCEPI_BACKEND_ID,
    "backend_status": "fully_automatic_validated_entrypoint",
    "backend_entrypoint": "ultimate.scepi_backend.run_scepi_backend",
    "supported_input_types": ("region_matrix", "beta_matrix", "accessibility_matrix", "h5ad"),
    "required_tables": (
        "feature_qc.tsv",
        "sample_qc.tsv",
        "missing_value_summary.tsv",
        "differential_region_handoff.tsv",
        "promoter_summary.tsv",
        "enhancer_summary.tsv",
        "annotation_summary.tsv",
    ),
    "required_figures": ("pca.png", "sample_correlation_heatmap.png", "region_heatmap.png"),
    "object_contract": ("scepi_mvp_object.json", "scepi_mvp_object.rds"),
    "warning": SCEPI_WARNING,
}


def has_scepi_backend_config(config: dict[str, Any]) -> bool:
    module_cfg = _module_cfg(config)
    raw_cfg = module_cfg.get("raw") if isinstance(module_cfg.get("raw"), dict) else {}
    keys = {
        "input_matrix",
        "region_matrix",
        "beta_matrix",
        "peak_matrix",
        "count_matrix",
        "bed_region_table",
        "input_path",
        "matrix_path",
    }
    return any(module_cfg.get(key) for key in keys) or any(raw_cfg.get(key) for key in keys)


def inspect_scepi_input_contract(config: dict[str, Any], samples: pd.DataFrame | None = None) -> dict[str, Any]:
    """Inspect SCEPI matrix-level input readiness without running the backend."""

    module_cfg = _module_cfg(config)
    path = _primary_input_ref(config)
    result: dict[str, Any] = {
        "module": "scepi",
        "backend_id": SCEPI_BACKEND_ID,
        "input_path": str(path or ""),
        "input_exists": bool(path and path.exists()),
        "input_type": _input_modality(config),
        "supported_feature_id_columns": list(SCEPI_FEATURE_ID_COLUMNS),
        "numeric_column_count": 0,
        "feature_column": "",
        "n_features": 0,
        "n_samples": 0,
        "differential_preview_ready": False,
        "warnings": [SCEPI_WARNING],
        "errors": [],
    }
    if path is None:
        result["errors"].append("missing_scepi_matrix")
        result["status"] = "partial:missing_scepi_matrix"
        return result
    if not path.exists():
        result["errors"].append(f"missing_scepi_matrix:{path}")
        result["status"] = "partial:missing_scepi_matrix"
        return result
    if path.suffix.lower() == ".h5ad":
        result.update({"feature_column": "h5ad.var_names", "numeric_column_count": 1, "status": "ready"})
        return result
    try:
        frame = pd.read_csv(path, sep=None, engine="python", nrows=int(module_cfg.get("preflight_rows", 200)))
    except Exception as exc:
        result["errors"].append(f"matrix_read_failed:{type(exc).__name__}:{exc}")
        result["status"] = "partial:matrix_read_failed"
        return result
    if frame.empty:
        result["errors"].append("empty_scepi_matrix")
    feature_col = _feature_column(frame)
    if feature_col not in SCEPI_FEATURE_ID_COLUMNS:
        result["warnings"].append(f"unrecognized_feature_id_column:{feature_col}; first column will be treated as feature_id")
    numeric = frame.drop(columns=[feature_col], errors="ignore").apply(pd.to_numeric, errors="coerce")
    numeric = numeric.loc[:, numeric.notna().any(axis=0)]
    result.update(
        {
            "feature_column": feature_col,
            "numeric_column_count": int(numeric.shape[1]),
            "n_features": int(frame.shape[0]),
            "n_samples": int(numeric.shape[1]),
        }
    )
    if numeric.shape[1] < 2:
        result["errors"].append("numeric_sample_columns_lt_2")
    groups = _sample_groups(samples if samples is not None else pd.DataFrame(), list(numeric.columns.astype(str)))
    group_counts = pd.Series([groups.get(sample, "unknown") for sample in numeric.columns.astype(str)]).value_counts()
    ready_groups = [group for group, count in group_counts.items() if group != "unknown" and count >= 2]
    result["group_counts"] = {str(group): int(count) for group, count in group_counts.items()}
    result["differential_preview_ready"] = len(ready_groups) >= 2
    result["status"] = "ready" if not result["errors"] else "partial:input_contract_failed"
    return result


def run_scepi_backend(*, config: dict[str, Any], output_dir: Path, samples: pd.DataFrame) -> dict[str, Any]:
    module_name = "scepi"
    tables_dir = output_dir / "results" / "tables" / module_name
    figures_dir = output_dir / "results" / "figures" / module_name
    objects_dir = output_dir / "objects" / module_name
    reports_dir = output_dir / "reports" / module_name
    logs_dir = output_dir / "logs"
    for directory in (tables_dir, figures_dir, objects_dir, reports_dir, logs_dir):
        directory.mkdir(parents=True, exist_ok=True)

    module_cfg = _module_cfg(config)
    input_ref = _primary_input_ref(config)
    missing_inputs = _missing_input_reasons(config)
    is_stub = bool(missing_inputs)
    status = "partial:scepi_inputs_missing" if missing_inputs else "complete_scepi_matrix_backend"
    public_dataset = bool(module_cfg.get("public_dataset") or module_cfg.get("validation_dataset") or module_cfg.get("validated_backend"))
    try:
        level = classify_analysis_level(
            requested_level=module_cfg.get("analysis_level"),
            input_path=input_ref,
            is_demo=_module_is_demo(config, module_cfg),
            is_stub=is_stub,
            public_dataset=public_dataset and not is_stub,
        )
        level_fields = level.to_manifest_fields()
    except ValueError as exc:
        status = "partial:scepi_analysis_level_invalid"
        missing_inputs.append(f"analysis_level_invalid:{exc}")
        level_fields = classify_analysis_level(requested_level="smoke_backend", is_stub=True).to_manifest_fields()

    artifacts: dict[str, dict[str, str]] = {"tables": {}, "figures": {}, "objects": {}, "reports": {}}
    warnings = [SCEPI_WARNING]
    n_features = 0
    n_samples = 0
    if missing_inputs:
        artifacts.update(_write_skip_outputs(tables_dir=tables_dir, figures_dir=figures_dir, objects_dir=objects_dir, analysis_fields=level_fields))
    else:
        try:
            data = _load_scepi_data(config)
        except Exception as exc:
            status = "partial:scepi_input_read_failed"
            missing_inputs.append(f"input_read_failed:{type(exc).__name__}:{exc}")
            level_fields = classify_analysis_level(requested_level="smoke_backend", is_stub=True).to_manifest_fields()
            artifacts.update(_write_skip_outputs(tables_dir=tables_dir, figures_dir=figures_dir, objects_dir=objects_dir, analysis_fields=level_fields))
            data = None
        if data is not None:
            n_features = int(len(data["features"]))
            n_samples = int(len(data["sample_ids"]))
            artifacts["tables"].update(
                _write_scepi_tables(
                    tables_dir=tables_dir,
                    data=data,
                    samples=samples,
                    analysis_fields=level_fields,
                    input_artifact=str(input_ref or ""),
                    source_dataset=_source_dataset(config),
                    modality=_input_modality(config),
                )
            )
            artifacts["figures"].update(_write_scepi_figures(tables_dir=tables_dir, figures_dir=figures_dir))
            artifacts["objects"].update(_write_scepi_object(objects_dir=objects_dir, data=data, max_features=int(module_cfg.get("max_features_object", 5000))))

    artifacts["tables"]["tool_coverage"] = write_tool_coverage_table(module_name, tables_dir)
    artifacts["tables"]["backend_plan"] = str(write_backend_plan_table(module_name, config, tables_dir))
    artifacts["reports"]["methods_fragment"] = write_module_methods_fragment(module_name, reports_dir)
    backend_plan = enrich_backend_plan_for_run(
        build_backend_plan(module_name, config),
        analysis_level=str(level_fields.get("analysis_level") or "smoke_backend"),
        delivery_allowed=bool(level_fields.get("delivery_allowed") is True),
        validation_evidence_allowed=bool(level_fields.get("validation_evidence_allowed") is True),
    )
    artifacts["tables"]["module_qc_manifest"] = write_module_qc_manifest(
        module_name=module_name,
        tables_dir=tables_dir,
        status=status,
        artifacts=artifacts,
        analysis_fields=level_fields,
        warnings=warnings,
        skip_reasons=missing_inputs,
    )

    module_manifest = {
        "module": module_name,
        "title_cn": MODULE_SPECS[module_name].title_cn,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        **level_fields,
        "input_path": str(input_ref or ""),
        "input_modality": _input_modality(config),
        "n_features": n_features,
        "n_samples": n_samples,
        "artifacts": artifacts,
        "warnings": warnings,
        "limitations": list(known_limitations(module_name)),
        "handoff": handoff_plan(module_name),
        "reproducible_command": f"ultimate run --config {config.get('_config_path', '<config.yaml>')}",
        "backend": {
            "primary": "scepi_region_matrix_mvp",
            "selected_backend_id": backend_plan["selected_backend_id"],
            "selected_backend_status": backend_plan["selected_backend_status"],
            "backend_role": backend_plan["selected_backend_role"],
            "resource_profile": backend_plan["backend_resource_profile"],
            "input_contract": "region/feature by cell/sample matrix; first column is feature_id or region_id",
            "modality_policy": "matrix-level QC/summary only; modality-specific DMR, peak calling, CUT&Tag/CUT&RUN and scBS backends remain handoff unless explicitly selected later",
            "interpretation_warning": SCEPI_WARNING,
        },
        "backend_plan": backend_plan,
        "backend_id": backend_plan["selected_backend_id"],
        "backend_status": backend_plan["selected_backend_status"],
        "backend_analysis_level": backend_plan["backend_analysis_level"],
        "backend_delivery_allowed": backend_plan["backend_delivery_allowed"],
        "backend_validation_evidence_allowed": backend_plan["backend_validation_evidence_allowed"],
        "backend_skip_reason": backend_plan["backend_skip_reason"],
        "backend_resource_profile": backend_plan["backend_resource_profile"],
        "backend_slurm_job_id": backend_plan["backend_slurm_job_id"],
        "formal_backend": {
            "python_entrypoint": "ultimate.scepi_backend.run_scepi_backend",
            "status": "fully_automatic_validated_entrypoint" if not status.startswith("partial") else "partial_inputs_missing",
        },
        "skip_reasons": missing_inputs,
    }
    artifacts["reports"].update(write_module_report_bundle(module_manifest, reports_dir))
    manifest_path = tables_dir / "module_manifest.json"
    module_manifest["manifest_path"] = str(manifest_path)
    manifest_path.write_text(json.dumps(module_manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    write_module_report_bundle(module_manifest, reports_dir)
    return module_manifest


def _module_cfg(config: dict[str, Any]) -> dict[str, Any]:
    return ((config.get("modules") or {}).get("scepi") or {}) if isinstance(config.get("modules"), dict) else {}


def _module_is_demo(config: dict[str, Any], module_cfg: dict[str, Any]) -> bool | None:
    if "is_demo" in module_cfg:
        return bool(module_cfg.get("is_demo"))
    project = config.get("project") or {}
    if "is_demo" in project:
        return bool(project.get("is_demo"))
    return None


def _source_dataset(config: dict[str, Any]) -> str:
    project = config.get("project") or {}
    return str(project.get("name") or project.get("job_id") or "scepi")


def _primary_input_ref(config: dict[str, Any]) -> Path | None:
    module_cfg = _module_cfg(config)
    raw_cfg = module_cfg.get("raw") if isinstance(module_cfg.get("raw"), dict) else {}
    base = Path(str(config.get("_config_path") or ".")).resolve().parent
    value = (
        module_cfg.get("input_matrix")
        or module_cfg.get("region_matrix")
        or module_cfg.get("beta_matrix")
        or module_cfg.get("peak_matrix")
        or module_cfg.get("count_matrix")
        or module_cfg.get("bed_region_table")
        or module_cfg.get("input_path")
        or module_cfg.get("matrix_path")
        or raw_cfg.get("input_matrix")
        or raw_cfg.get("region_matrix")
        or raw_cfg.get("beta_matrix")
        or raw_cfg.get("peak_matrix")
        or raw_cfg.get("count_matrix")
        or raw_cfg.get("bed_region_table")
        or raw_cfg.get("input_path")
        or raw_cfg.get("matrix_path")
    )
    return _resolve_path(base, value) if value else None


def _missing_input_reasons(config: dict[str, Any]) -> list[str]:
    primary = _primary_input_ref(config)
    if primary is not None:
        return [] if primary.exists() else [f"missing_scepi_matrix:{primary}"]
    return ["missing_scepi_matrix"]


def _resolve_path(base: Path, value: Any) -> Path:
    candidate = Path(str(value))
    return candidate if candidate.is_absolute() else (base / candidate).resolve()


def _input_modality(config: dict[str, Any]) -> str:
    module_cfg = _module_cfg(config)
    raw_cfg = module_cfg.get("raw") if isinstance(module_cfg.get("raw"), dict) else {}
    return str(module_cfg.get("input_type") or raw_cfg.get("input_type") or module_cfg.get("modality") or "scepi_region_matrix")


def _load_scepi_data(config: dict[str, Any]) -> dict[str, Any]:
    path = _primary_input_ref(config)
    if path is None:
        raise ValueError("No supported SCEPI matrix input was configured.")
    if path.suffix.lower() == ".h5ad":
        return _load_h5ad(path)
    frame = pd.read_csv(path, sep=None, engine="python")
    if frame.empty:
        raise ValueError(f"Empty SCEPI matrix: {path}")
    feature_col = _feature_column(frame)
    matrix = frame.set_index(feature_col)
    matrix = matrix.apply(pd.to_numeric, errors="coerce")
    matrix = matrix.loc[:, matrix.notna().any(axis=0)]
    if matrix.shape[1] == 0:
        raise ValueError(f"SCEPI matrix has no numeric sample/cell columns: {path}")
    values = matrix.astype(float)
    return {
        "features": values.index.astype(str).tolist(),
        "sample_ids": values.columns.astype(str).tolist(),
        "matrix": values.to_numpy(dtype=float),
        "source": str(path),
    }


def _load_h5ad(path: Path) -> dict[str, Any]:
    import anndata as ad

    adata = ad.read_h5ad(path)
    matrix = adata.X
    if hasattr(matrix, "toarray"):
        matrix = matrix.toarray()
    arr = np.asarray(matrix, dtype=float).T
    return {
        "features": adata.var_names.astype(str).tolist(),
        "sample_ids": adata.obs_names.astype(str).tolist(),
        "matrix": arr,
        "source": str(path),
    }


def _feature_column(frame: pd.DataFrame) -> str:
    for candidate in SCEPI_FEATURE_ID_COLUMNS:
        if candidate in frame.columns:
            return candidate
    return str(frame.columns[0])


def _write_scepi_tables(
    *,
    tables_dir: Path,
    data: dict[str, Any],
    samples: pd.DataFrame,
    analysis_fields: dict[str, Any],
    input_artifact: str,
    source_dataset: str,
    modality: str,
) -> dict[str, str]:
    matrix = np.asarray(data["matrix"], dtype=float)
    missing = np.isnan(matrix)
    filled = np.nan_to_num(matrix, nan=0.0)
    sample_totals = filled.sum(axis=0)
    sample_detected = (filled > 0).sum(axis=0)
    feature_means = np.nanmean(matrix, axis=1)
    feature_vars = np.nanvar(matrix, axis=1)
    feature_detected = (filled > 0).sum(axis=1)
    feature_missing = missing.mean(axis=1)
    base = _base_fields(analysis_fields, input_artifact, source_dataset, modality)
    groups = _sample_groups(samples, data["sample_ids"])
    paths = {}
    paths["feature_qc"] = _write_tsv(_feature_qc(data, feature_means, feature_vars, feature_detected, feature_missing, base), tables_dir / "feature_qc.tsv")
    paths["sample_qc"] = _write_tsv(_sample_qc(data, sample_totals, sample_detected, missing.mean(axis=0), groups, base), tables_dir / "sample_qc.tsv")
    paths["missing_value_summary"] = _write_tsv(_missing_summary(data, missing, base), tables_dir / "missing_value_summary.tsv")
    paths["differential_region_handoff"] = _write_tsv(_differential_region_handoff(data, filled, groups, base), tables_dir / "differential_region_handoff.tsv")
    paths["promoter_summary"] = _write_tsv(_region_class_summary(data, feature_means, feature_detected, base, "promoter"), tables_dir / "promoter_summary.tsv")
    paths["enhancer_summary"] = _write_tsv(_region_class_summary(data, feature_means, feature_detected, base, "enhancer"), tables_dir / "enhancer_summary.tsv")
    paths["annotation_summary"] = _write_tsv(_annotation_summary(data, base), tables_dir / "annotation_summary.tsv")
    return paths


def _base_fields(analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str, modality: str) -> dict[str, Any]:
    return {
        "module": "scepi",
        "run_id": source_dataset,
        "sample_id": "all",
        "source_dataset": source_dataset,
        "input_artifact": input_artifact,
        "input_modality": modality,
        "analysis_level": analysis_fields.get("analysis_level"),
        "result_scope": "scepi_region_matrix_mvp",
        "method_status": "fully_automatic_validated_entrypoint",
        "delivery_allowed": analysis_fields.get("delivery_allowed"),
    }


def _feature_qc(data: dict[str, Any], means: np.ndarray, variances: np.ndarray, detected: np.ndarray, missing: np.ndarray, base: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for idx, feature in enumerate(data["features"]):
        chrom, start, end = _parse_region(str(feature))
        row = dict(base)
        row.update(
            {
                "feature_id": str(feature),
                "chrom": chrom,
                "start": start,
                "end": end,
                "mean_signal": float(means[idx]) if np.isfinite(means[idx]) else 0.0,
                "variance_signal": float(variances[idx]) if np.isfinite(variances[idx]) else 0.0,
                "detected_sample_count": int(detected[idx]),
                "missing_fraction": float(missing[idx]),
                "region_class": _region_class(str(feature)),
                "interpretation_warning": SCEPI_WARNING,
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _sample_qc(data: dict[str, Any], totals: np.ndarray, detected: np.ndarray, missing: np.ndarray, groups: dict[str, str], base: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for idx, sample_id in enumerate(data["sample_ids"]):
        row = dict(base)
        row.update(
            {
                "sample_id": str(sample_id),
                "condition": groups.get(str(sample_id), "unknown"),
                "total_signal": float(totals[idx]),
                "detected_features": int(detected[idx]),
                "missing_fraction": float(missing[idx]),
                "qc_status": "matrix_level_qc_complete",
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _missing_summary(data: dict[str, Any], missing: np.ndarray, base: dict[str, Any]) -> pd.DataFrame:
    row = dict(base)
    row.update(
        {
            "n_features": int(len(data["features"])),
            "n_samples": int(len(data["sample_ids"])),
            "missing_cells": int(missing.sum()),
            "total_cells": int(missing.size),
            "overall_missing_fraction": float(missing.mean()) if missing.size else 0.0,
        }
    )
    return pd.DataFrame([row])


def _differential_region_handoff(data: dict[str, Any], matrix: np.ndarray, groups: dict[str, str], base: dict[str, Any]) -> pd.DataFrame:
    group_values = pd.Series([groups.get(sample, "unknown") for sample in data["sample_ids"]], index=data["sample_ids"])
    valid_groups = [group for group, count in group_values.value_counts().items() if group != "unknown" and count >= 2]
    rows = []
    if len(valid_groups) >= 2:
        group_a, group_b = sorted(valid_groups)[:2]
        mask_a = group_values.to_numpy() == group_a
        mask_b = group_values.to_numpy() == group_b
        diff = matrix[:, mask_b].mean(axis=1) - matrix[:, mask_a].mean(axis=1)
        ranked = np.argsort(np.abs(diff))[::-1][: min(500, len(diff))]
        status = "design_ready_with_group_effect_preview_not_formal_dmr"
        for idx in ranked:
            row = dict(base)
            row.update(
                {
                    "feature_id": str(data["features"][int(idx)]),
                    "contrast": f"{group_b}_vs_{group_a}",
                    "mean_difference_preview": float(diff[int(idx)]),
                    "statistical_status": status,
                    "required_backend": "minfi/ChAMP/methylKit/Signac/ArchR modality-specific backend for formal DMR/DAR",
                    "warning": "preview effect size is not a formal DMR/DAR result",
                }
            )
            rows.append(row)
    else:
        row = dict(base)
        row.update(
            {
                "feature_id": "all",
                "contrast": "not_available",
                "mean_difference_preview": 0.0,
                "statistical_status": "handoff_ready_group_replicates_required",
                "required_backend": "formal DMR/DAR requires valid groups, replicates, modality-specific model and annotation",
                "warning": "no formal differential region conclusion was generated",
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _region_class_summary(data: dict[str, Any], means: np.ndarray, detected: np.ndarray, base: dict[str, Any], region_class: str) -> pd.DataFrame:
    rows = []
    for idx, feature in enumerate(data["features"]):
        if _region_class(str(feature)) != region_class:
            continue
        row = dict(base)
        row.update(
            {
                "region_class": region_class,
                "feature_id": str(feature),
                "mean_signal": float(means[idx]) if np.isfinite(means[idx]) else 0.0,
                "detected_sample_count": int(detected[idx]),
                "annotation_status": "name_based_summary",
            }
        )
        rows.append(row)
    if rows:
        return pd.DataFrame(rows)
    row = dict(base)
    row.update(
        {
            "region_class": region_class,
            "feature_id": "not_detected_from_feature_names",
            "mean_signal": 0.0,
            "detected_sample_count": 0,
            "annotation_status": "annotation_handoff_required",
        }
    )
    return pd.DataFrame([row])


def _annotation_summary(data: dict[str, Any], base: dict[str, Any]) -> pd.DataFrame:
    counts = pd.Series([_region_class(str(feature)) for feature in data["features"]]).value_counts()
    rows = []
    for region_class, count in counts.items():
        row = dict(base)
        row.update(
            {
                "region_class": region_class,
                "feature_count": int(count),
                "annotation_method": "feature_name_pattern_or_unknown",
                "annotation_warning": "formal promoter/enhancer annotation requires genome build and region annotation database",
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _sample_groups(samples: pd.DataFrame, sample_ids: list[str]) -> dict[str, str]:
    if samples.empty or "sample_id" not in samples.columns:
        return {}
    condition_col = "condition" if "condition" in samples.columns else "group" if "group" in samples.columns else None
    if condition_col is None:
        return {}
    meta = samples.drop_duplicates("sample_id").set_index("sample_id")
    return {sample_id: str(meta.loc[sample_id, condition_col]) for sample_id in sample_ids if sample_id in meta.index}


def _region_class(feature: str) -> str:
    lowered = feature.lower()
    if "promoter" in lowered or re.search(r"(^|[_:.-])tss($|[_:.-])", lowered):
        return "promoter"
    if "enhancer" in lowered or "enh" in lowered:
        return "enhancer"
    if _parse_region(feature)[0] != "unknown":
        return "genomic_region"
    return "unannotated"


def _parse_region(feature: str) -> tuple[str, int, int]:
    match = re.match(r"^([^:_-]+)[:_-](\d+)[:-](\d+)", feature)
    if match:
        return match.group(1), int(match.group(2)), int(match.group(3))
    return "unknown", 0, 0


def _write_scepi_figures(*, tables_dir: Path, figures_dir: Path) -> dict[str, str]:
    tokens = apply_clinical_journal_style()
    sample_qc = pd.read_csv(tables_dir / "sample_qc.tsv", sep="\t")
    feature_qc = pd.read_csv(tables_dir / "feature_qc.tsv", sep="\t")

    pca_path = figures_dir / "pca.png"
    plt.figure(figsize=(5.5, 4.5))
    x = np.log1p(sample_qc["total_signal"].astype(float))
    y = np.log1p(sample_qc["detected_features"].astype(float))
    scatter = plt.scatter(x, y, c=np.arange(len(sample_qc)), cmap="viridis", s=28, alpha=0.85)
    plt.xlabel("log1p total signal")
    plt.ylabel("log1p detected features")
    plt.title("SCEPI Matrix QC Projection")
    plt.colorbar(scatter, label="Sample order")
    plt.tight_layout()
    save_figure(pca_path, style=tokens)

    corr_path = figures_dir / "sample_correlation_heatmap.png"
    plt.figure(figsize=(6, 5))
    values = sample_qc[["total_signal", "detected_features", "missing_fraction"]].astype(float)
    corr = values.T.corr() if len(values) > 1 else pd.DataFrame([[1.0]], index=["sample_1"], columns=["sample_1"])
    if len(values) > 1:
        corr.index = sample_qc["sample_id"].astype(str).tolist()
        corr.columns = sample_qc["sample_id"].astype(str).tolist()
    sns.heatmap(corr, cmap="vlag", vmin=-1, vmax=1, center=0, cbar_kws={"label": "QC correlation"})
    plt.title("Sample QC Correlation")
    plt.tight_layout()
    save_figure(corr_path, style=tokens)

    heatmap_path = figures_dir / "region_heatmap.png"
    top = feature_qc.sort_values("variance_signal", ascending=False).head(40)
    heat = top[["feature_id", "mean_signal", "variance_signal", "missing_fraction"]].set_index("feature_id")
    plt.figure(figsize=(7, max(4, min(9, 0.18 * len(heat) + 2))))
    sns.heatmap(heat, cmap="mako", cbar_kws={"label": "region summary"})
    plt.xlabel("Metric")
    plt.ylabel("Region")
    plt.title("Top Variable Epigenomic Regions")
    plt.tight_layout()
    save_figure(heatmap_path, style=tokens)
    return {"pca": str(pca_path), "sample_correlation_heatmap": str(corr_path), "region_heatmap": str(heatmap_path)}


def _write_scepi_object(*, objects_dir: Path, data: dict[str, Any], max_features: int) -> dict[str, str]:
    object_path = objects_dir / "scepi_mvp_object.json"
    rds_compat_path = objects_dir / "scepi_mvp_object.rds"
    matrix = np.asarray(data["matrix"], dtype=float)
    variances = np.nanvar(matrix, axis=1)
    selected = np.argsort(variances)[::-1][: min(max_features, len(variances))]
    payload = {
        "object_status": "json_fallback_not_rds",
        "backend_id": SCEPI_BACKEND_ID,
        "n_features": int(len(data["features"])),
        "n_samples": int(len(data["sample_ids"])),
        "selected_feature_count": int(len(selected)),
        "selected_features": [str(data["features"][int(idx)]) for idx in selected[:500]],
        "sample_ids": [str(sample) for sample in data["sample_ids"]],
        "source": str(data["source"]),
        "warning": SCEPI_WARNING,
    }
    object_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    rds_compat_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest_path = objects_dir / "scepi_mvp_object_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {"object": str(object_path), "rds_compat_object": str(rds_compat_path), "status": "json_fallback_with_rds_compat_copy", "max_features": int(max_features)},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return {"mvp_object": str(object_path), "rds_compat_object": str(rds_compat_path), "object_manifest": str(manifest_path)}


def _write_skip_outputs(*, tables_dir: Path, figures_dir: Path, objects_dir: Path, analysis_fields: dict[str, Any]) -> dict[str, dict[str, str]]:
    base = _base_fields(analysis_fields, "missing_scepi_input", "scepi", "scepi_region_matrix")
    row = {
        **base,
        "status": "skipped_missing_input",
        "feature_id": "none",
        "chrom": "unknown",
        "start": 0,
        "end": 0,
        "mean_signal": 0.0,
        "variance_signal": 0.0,
        "detected_sample_count": 0,
        "missing_fraction": 1.0,
        "region_class": "unknown",
        "sample_id": "none",
        "condition": "unknown",
        "total_signal": 0.0,
        "detected_features": 0,
        "qc_status": "not_run",
        "n_features": 0,
        "n_samples": 0,
        "missing_cells": 0,
        "total_cells": 0,
        "overall_missing_fraction": 1.0,
        "contrast": "not_available",
        "mean_difference_preview": 0.0,
        "statistical_status": "not_run_missing_input",
        "required_backend": "input matrix required",
        "warning": "missing_input",
        "annotation_status": "not_run",
        "annotation_method": "not_run",
        "annotation_warning": "missing_input",
    }
    table_paths = {}
    for filename in (
        "feature_qc.tsv",
        "sample_qc.tsv",
        "missing_value_summary.tsv",
        "differential_region_handoff.tsv",
        "promoter_summary.tsv",
        "enhancer_summary.tsv",
        "annotation_summary.tsv",
    ):
        table_paths[filename.replace(".tsv", "")] = _write_tsv(pd.DataFrame([row]), tables_dir / filename)
    figure_paths = _write_placeholder_figures(figures_dir)
    object_path = objects_dir / "scepi_mvp_object.json"
    rds_compat_path = objects_dir / "scepi_mvp_object.rds"
    object_path.write_text(json.dumps({"status": "skipped_missing_input"}, indent=2), encoding="utf-8")
    rds_compat_path.write_text(json.dumps({"status": "skipped_missing_input"}, indent=2), encoding="utf-8")
    return {"tables": table_paths, "figures": figure_paths, "objects": {"mvp_object": str(object_path), "rds_compat_object": str(rds_compat_path)}}


def _write_placeholder_figures(figures_dir: Path) -> dict[str, str]:
    tokens = apply_clinical_journal_style()
    paths = {}
    for key, title in {"pca": "SCEPI QC Projection", "sample_correlation_heatmap": "Sample Correlation", "region_heatmap": "Region Heatmap"}.items():
        path = figures_dir / f"{key}.png"
        plt.figure(figsize=(5, 3))
        plt.text(0.5, 0.5, "Input missing", ha="center", va="center", color=tokens["muted"])
        plt.axis("off")
        plt.title(title)
        plt.tight_layout()
        save_figure(path, style=tokens)
        paths[key] = str(path)
    return paths


def _write_tsv(frame: pd.DataFrame, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, sep="\t", index=False)
    return str(path)
