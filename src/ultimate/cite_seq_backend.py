from __future__ import annotations

import json
import shutil
import subprocess
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
from ultimate.plot_style import apply_clinical_journal_style, continuous_cmap, save_figure


CITE_BACKEND_ID = "cite_seq.default.clr_mvp"
DSB_BACKEND_ID = "cite_seq.optional.dsb"
CITE_WARNING = "ADT 是抗体 panel 限定的标签计数，不是全蛋白组；RNA/protein 不一致不能自动解释为机制。"
DSB_WARNING = "DSB normalization 依赖 empty/background droplets 和可选 isotype controls；没有背景信息时不能伪装完成 DSB。"


def has_cite_seq_backend_config(config: dict[str, Any]) -> bool:
    module_cfg = _module_cfg(config)
    raw_cfg = module_cfg.get("raw") if isinstance(module_cfg.get("raw"), dict) else {}
    keys = {
        "input_h5",
        "input_h5ad",
        "input_path",
        "feature_matrix",
        "rna_matrix",
        "adt_matrix",
        "h5mu",
        "adt_counts",
        "count_matrix",
    }
    return any(module_cfg.get(key) for key in keys) or any(raw_cfg.get(key) for key in keys)


def run_cite_seq_backend(*, config: dict[str, Any], output_dir: Path, samples: pd.DataFrame) -> dict[str, Any]:
    module_name = "cite_seq"
    module_dir = output_dir
    tables_dir = module_dir / "results" / "tables" / module_name
    figures_dir = module_dir / "results" / "figures" / module_name
    objects_dir = module_dir / "objects" / module_name
    reports_dir = module_dir / "reports" / module_name
    logs_dir = module_dir / "logs"
    for directory in (tables_dir, figures_dir, objects_dir, reports_dir, logs_dir):
        directory.mkdir(parents=True, exist_ok=True)

    module_cfg = _module_cfg(config)
    input_ref = _primary_input_ref(config)
    missing_inputs = _missing_input_reasons(config)
    is_stub = bool(missing_inputs)
    status = "partial:cite_seq_inputs_missing" if missing_inputs else "complete_cite_seq_clr_backend"
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
        status = "partial:cite_seq_analysis_level_invalid"
        missing_inputs.append(f"analysis_level_invalid:{exc}")
        level_fields = classify_analysis_level(requested_level="smoke_backend", is_stub=True).to_manifest_fields()

    artifacts: dict[str, dict[str, str]] = {"tables": {}, "figures": {}, "objects": {}, "reports": {}}
    warnings = [CITE_WARNING]
    n_cells = 0
    n_rna_features = 0
    n_adt_features = 0
    if missing_inputs:
        artifacts.update(_write_skip_outputs(tables_dir=tables_dir, figures_dir=figures_dir, objects_dir=objects_dir, analysis_fields=level_fields))
    else:
        try:
            data = _load_cite_data(config)
        except Exception as exc:
            status = "partial:cite_seq_input_read_failed"
            missing_inputs.append(f"input_read_failed:{type(exc).__name__}:{exc}")
            level_fields = classify_analysis_level(requested_level="smoke_backend", is_stub=True).to_manifest_fields()
            artifacts.update(_write_skip_outputs(tables_dir=tables_dir, figures_dir=figures_dir, objects_dir=objects_dir, analysis_fields=level_fields))
            data = None
        if data is not None:
            n_cells = int(len(data["cells"]))
            n_rna_features = int(len(data["rna_features"]))
            n_adt_features = int(len(data["adt_features"]))
            tables = _write_cite_tables(
                tables_dir=tables_dir,
                data=data,
                analysis_fields=level_fields,
                input_artifact=str(input_ref or ""),
                source_dataset=_source_dataset(config),
            )
            artifacts["tables"].update(tables)
            artifacts["figures"].update(_write_cite_figures(tables_dir=tables_dir, figures_dir=figures_dir))
            artifacts["objects"].update(_write_cite_object(objects_dir=objects_dir, data=data, max_cells=int(module_cfg.get("max_cells_object", 3000))))
            dsb_status, dsb_artifacts = _run_dsb_backend(
                config=config,
                data=data,
                tables_dir=tables_dir,
                figures_dir=figures_dir,
                objects_dir=objects_dir,
                analysis_fields=level_fields,
                input_artifact=str(input_ref or ""),
                source_dataset=_source_dataset(config),
            )
            if dsb_status["requested"]:
                warnings.append(DSB_WARNING)
                artifacts["tables"].update(dsb_artifacts.get("tables", {}))
                artifacts["figures"].update(dsb_artifacts.get("figures", {}))
                artifacts["objects"].update(dsb_artifacts.get("objects", {}))
                if dsb_status["status"] == "ready":
                    status = "complete_cite_seq_clr_dsb_backend"

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
        "n_cells": n_cells,
        "n_rna_features": n_rna_features,
        "n_adt_features": n_adt_features,
        "artifacts": artifacts,
        "warnings": warnings,
        "limitations": list(known_limitations(module_name)),
        "handoff": handoff_plan(module_name),
        "reproducible_command": f"ultimate run --config {config.get('_config_path', '<config.yaml>')}",
        "backend": {
            "primary": "cite_seq_clr_mvp",
            "selected_backend_id": backend_plan["selected_backend_id"],
            "selected_backend_status": backend_plan["selected_backend_status"],
            "backend_role": backend_plan["selected_backend_role"],
            "resource_profile": backend_plan["backend_resource_profile"],
            "normalization_method": "CLR(log1p per cell centered across ADT panel)",
            "panel_scope_warning": CITE_WARNING,
        },
        "backend_plan": backend_plan,
        "optional_backend_status": {
            "cite_seq.optional.dsb": artifacts["tables"].get("dsb_backend_status", "not_requested"),
        },
        "backend_id": backend_plan["selected_backend_id"],
        "backend_status": backend_plan["selected_backend_status"],
        "backend_analysis_level": backend_plan["backend_analysis_level"],
        "backend_delivery_allowed": backend_plan["backend_delivery_allowed"],
        "backend_validation_evidence_allowed": backend_plan["backend_validation_evidence_allowed"],
        "backend_skip_reason": backend_plan["backend_skip_reason"],
        "backend_resource_profile": backend_plan["backend_resource_profile"],
        "backend_slurm_job_id": backend_plan["backend_slurm_job_id"],
        "formal_backend": {
            "python_entrypoint": "ultimate.cite_seq_backend.run_cite_seq_backend",
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
    return ((config.get("modules") or {}).get("cite_seq") or {}) if isinstance(config.get("modules"), dict) else {}


def _module_is_demo(config: dict[str, Any], module_cfg: dict[str, Any]) -> bool | None:
    if "is_demo" in module_cfg:
        return bool(module_cfg.get("is_demo"))
    project = config.get("project") or {}
    if "is_demo" in project:
        return bool(project.get("is_demo"))
    return None


def _source_dataset(config: dict[str, Any]) -> str:
    project = config.get("project") or {}
    return str(project.get("name") or project.get("job_id") or "cite_seq")


def _primary_input_ref(config: dict[str, Any]) -> Path | None:
    module_cfg = _module_cfg(config)
    raw_cfg = module_cfg.get("raw") if isinstance(module_cfg.get("raw"), dict) else {}
    base = Path(str(config.get("_config_path") or ".")).resolve().parent
    value = (
        module_cfg.get("input_h5")
        or module_cfg.get("input_h5ad")
        or module_cfg.get("input_path")
        or module_cfg.get("feature_matrix")
        or raw_cfg.get("feature_matrix")
        or raw_cfg.get("input_path")
        or raw_cfg.get("matrix_path")
        or raw_cfg.get("adt_counts")
        or module_cfg.get("adt_matrix")
    )
    return _resolve_path(base, value) if value else None


def _missing_input_reasons(config: dict[str, Any]) -> list[str]:
    module_cfg = _module_cfg(config)
    raw_cfg = module_cfg.get("raw") if isinstance(module_cfg.get("raw"), dict) else {}
    base = Path(str(config.get("_config_path") or ".")).resolve().parent
    single = _primary_input_ref(config)
    if single is not None:
        return [] if single.exists() else [f"missing_input_path:{single}"]
    rna = module_cfg.get("rna_matrix") or raw_cfg.get("count_matrix")
    adt = module_cfg.get("adt_matrix") or module_cfg.get("adt_counts") or raw_cfg.get("adt_counts")
    reasons = []
    if not rna:
        reasons.append("missing_rna_matrix")
    elif not _resolve_path(base, rna).exists():
        reasons.append(f"missing_rna_matrix:{_resolve_path(base, rna)}")
    if not adt:
        reasons.append("missing_adt_matrix")
    elif not _resolve_path(base, adt).exists():
        reasons.append(f"missing_adt_matrix:{_resolve_path(base, adt)}")
    return reasons


def _resolve_path(base: Path, value: Any) -> Path:
    candidate = Path(str(value))
    return candidate if candidate.is_absolute() else (base / candidate).resolve()


def _load_cite_data(config: dict[str, Any]) -> dict[str, Any]:
    module_cfg = _module_cfg(config)
    raw_cfg = module_cfg.get("raw") if isinstance(module_cfg.get("raw"), dict) else {}
    base = Path(str(config.get("_config_path") or ".")).resolve().parent
    single = _primary_input_ref(config)
    if single is not None and single.suffix.lower() == ".h5ad":
        return _load_h5ad(single)
    if single is not None and single.suffix.lower() in {".h5", ".hdf5"}:
        return _load_10x_h5(single)
    rna_value = module_cfg.get("rna_matrix") or raw_cfg.get("count_matrix")
    adt_value = module_cfg.get("adt_matrix") or module_cfg.get("adt_counts") or raw_cfg.get("adt_counts")
    if rna_value and adt_value:
        return _load_csv_matrices(_resolve_path(base, rna_value), _resolve_path(base, adt_value))
    raise ValueError("No supported CITE-seq input was configured.")


def _load_10x_h5(path: Path) -> dict[str, Any]:
    import scanpy as sc

    adata = sc.read_10x_h5(path, gex_only=False)
    adata.var_names_make_unique()
    return _data_from_anndata(adata)


def _load_h5ad(path: Path) -> dict[str, Any]:
    import anndata as ad

    adata = ad.read_h5ad(path)
    return _data_from_anndata(adata)


def _data_from_anndata(adata) -> dict[str, Any]:
    feature_col = _feature_type_column(adata.var)
    feature_types = adata.var[feature_col].astype(str)
    rna_mask = feature_types.str.lower().eq("gene expression").to_numpy()
    adt_mask = feature_types.str.lower().isin({"antibody capture", "antibody", "adt"}).to_numpy()
    if not rna_mask.any() or not adt_mask.any():
        raise ValueError("Expected both Gene Expression and Antibody Capture/ADT features.")
    rna = _to_dense(adata[:, rna_mask].X)
    adt = _to_dense(adata[:, adt_mask].X)
    rna_features = adata.var_names[rna_mask].astype(str).tolist()
    adt_features = adata.var_names[adt_mask].astype(str).tolist()
    cells = adata.obs_names.astype(str).tolist()
    return {"cells": cells, "rna": rna, "adt": adt, "rna_features": rna_features, "adt_features": adt_features}


def _load_csv_matrices(rna_path: Path, adt_path: Path) -> dict[str, Any]:
    rna = _read_feature_matrix(rna_path)
    adt = _read_feature_matrix(adt_path)
    shared = [cell for cell in rna.columns.astype(str) if cell in set(adt.columns.astype(str))]
    if not shared:
        raise ValueError("RNA and ADT matrices have no shared cell barcodes.")
    return {
        "cells": shared,
        "rna": rna[shared].to_numpy(dtype=float).T,
        "adt": adt[shared].to_numpy(dtype=float).T,
        "rna_features": rna.index.astype(str).tolist(),
        "adt_features": adt.index.astype(str).tolist(),
    }


def _read_feature_matrix(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, sep=None, engine="python")
    index_col = "feature_id" if "feature_id" in frame.columns else frame.columns[0]
    frame = frame.set_index(index_col)
    return frame.apply(pd.to_numeric, errors="coerce").fillna(0.0)


def _feature_type_column(var: pd.DataFrame) -> str:
    for column in ("feature_types", "feature_type", "type"):
        if column in var.columns:
            return column
    raise ValueError("Input object did not contain a feature type column.")


def _to_dense(matrix: Any) -> np.ndarray:
    if hasattr(matrix, "toarray"):
        return np.asarray(matrix.toarray(), dtype=float)
    return np.asarray(matrix, dtype=float)


def _write_cite_tables(*, tables_dir: Path, data: dict[str, Any], analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str) -> dict[str, str]:
    rna = np.asarray(data["rna"], dtype=float)
    adt = np.asarray(data["adt"], dtype=float)
    clr = _clr_normalize(adt)
    cells = list(map(str, data["cells"]))
    adt_features = list(map(str, data["adt_features"]))
    rna_features = list(map(str, data["rna_features"]))
    rna_total = rna.sum(axis=1)
    adt_total = adt.sum(axis=1)
    paths = {}
    paths["adt_qc"] = _write_tsv(
        _adt_qc(cells, rna_total, adt_total, adt, analysis_fields, input_artifact, source_dataset),
        tables_dir / "adt_qc.tsv",
    )
    paths["antibody_panel"] = _write_tsv(
        _antibody_panel(adt_features, analysis_fields, input_artifact, source_dataset),
        tables_dir / "antibody_panel.tsv",
    )
    paths["adt_normalized_matrix"] = _write_tsv(
        _adt_normalized_long(cells, adt_features, clr, analysis_fields, input_artifact, source_dataset),
        tables_dir / "adt_normalized_matrix.tsv",
    )
    paths["adt_marker_summary"] = _write_tsv(
        _adt_marker_summary(adt_features, clr, analysis_fields, input_artifact, source_dataset),
        tables_dir / "adt_marker_summary.tsv",
    )
    paths["rna_protein_consistency"] = _write_tsv(
        _rna_protein_consistency(rna_features, adt_features, rna, clr, analysis_fields, input_artifact, source_dataset),
        tables_dir / "rna_protein_consistency.tsv",
    )
    return paths


def _base_fields(analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str) -> dict[str, Any]:
    return {
        "module": "cite_seq",
        "run_id": source_dataset,
        "sample_id": "all",
        "source_dataset": source_dataset,
        "input_artifact": input_artifact,
        "input_modality": "rna_adt_matrix",
        "analysis_level": analysis_fields.get("analysis_level"),
        "result_scope": "cite_seq_clr_mvp",
        "method_status": "fully_automatic_validated_entrypoint",
        "delivery_allowed": analysis_fields.get("delivery_allowed"),
    }


def _adt_qc(cells: list[str], rna_total: np.ndarray, adt_total: np.ndarray, adt: np.ndarray, analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str) -> pd.DataFrame:
    rows = []
    detected = (adt > 0).sum(axis=1)
    for cell, rna_count, adt_count, n_adt in zip(cells, rna_total, adt_total, detected):
        row = _base_fields(analysis_fields, input_artifact, source_dataset)
        row.update(
            {
                "cell_id": cell,
                "rna_total_counts": float(rna_count),
                "adt_total_counts": float(adt_count),
                "detected_adt_features": int(n_adt),
                "background_status": "isotype_or_empty_droplet_not_provided",
                "isotype_control_status": "not_provided",
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _antibody_panel(adt_features: list[str], analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str) -> pd.DataFrame:
    rows = []
    for feature in adt_features:
        row = _base_fields(analysis_fields, input_artifact, source_dataset)
        row.update(
            {
                "antibody_id": feature,
                "target_protein": _target_from_antibody(feature),
                "isotype_control": "unknown",
                "panel_scope_note": "interpretation_limited_to_measured_antibody_panel",
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _adt_normalized_long(cells: list[str], adt_features: list[str], clr: np.ndarray, analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str) -> pd.DataFrame:
    rows = []
    for i, cell in enumerate(cells):
        for j, antibody in enumerate(adt_features):
            row = _base_fields(analysis_fields, input_artifact, source_dataset)
            row.update({"cell_id": cell, "antibody_id": antibody, "normalized_adt": float(clr[i, j]), "normalization_method": "CLR_log1p_centered_per_cell"})
            rows.append(row)
    return pd.DataFrame(rows)


def _adt_marker_summary(adt_features: list[str], clr: np.ndarray, analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str) -> pd.DataFrame:
    rows = []
    mean_scores = clr.mean(axis=0)
    for antibody, score in sorted(zip(adt_features, mean_scores), key=lambda item: item[1], reverse=True):
        row = _base_fields(analysis_fields, input_artifact, source_dataset)
        row.update({"cluster_id": "all_cells", "antibody_id": antibody, "target_protein": _target_from_antibody(antibody), "marker_score": float(score), "panel_scope_note": "marker_summary_without_celltype_claim"})
        rows.append(row)
    return pd.DataFrame(rows)


def _rna_protein_consistency(rna_features: list[str], adt_features: list[str], rna: np.ndarray, clr: np.ndarray, analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str) -> pd.DataFrame:
    rows = []
    rna_total = rna.sum(axis=1)
    for j, antibody in enumerate(adt_features):
        corr = _safe_corr(rna_total, clr[:, j])
        row = _base_fields(analysis_fields, input_artifact, source_dataset)
        row.update(
            {
                "cell_id": "all_cells",
                "gene_symbol": _target_from_antibody(antibody),
                "antibody_id": antibody,
                "correlation_proxy": corr,
                "mechanism_warning": "RNA_total_vs_ADT_proxy_not_mechanism",
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _clr_normalize(adt: np.ndarray) -> np.ndarray:
    log_values = np.log1p(np.asarray(adt, dtype=float))
    return log_values - log_values.mean(axis=1, keepdims=True)


def _dsb_requested(config: dict[str, Any]) -> bool:
    module_cfg = _module_cfg(config)
    dsb_cfg = module_cfg.get("dsb") if isinstance(module_cfg.get("dsb"), dict) else {}
    if bool(dsb_cfg.get("enabled") or module_cfg.get("dsb_enabled")):
        return True
    requested = module_cfg.get("backends") if isinstance(module_cfg.get("backends"), dict) else {}
    values = {str(key) for key, value in requested.items() if value not in {None, False, ""}}
    values.update(str(value) for value in requested.values() if value not in {None, False, ""})
    return bool({DSB_BACKEND_ID, "dsb", "optional.dsb"} & values)


def _dsb_cfg(config: dict[str, Any]) -> dict[str, Any]:
    module_cfg = _module_cfg(config)
    return module_cfg.get("dsb") if isinstance(module_cfg.get("dsb"), dict) else {}


def _dsb_empty_matrix(config: dict[str, Any]) -> Path | None:
    module_cfg = _module_cfg(config)
    raw_cfg = module_cfg.get("raw") if isinstance(module_cfg.get("raw"), dict) else {}
    dsb_cfg = _dsb_cfg(config)
    base = Path(str(config.get("_config_path") or ".")).resolve().parent
    value = (
        dsb_cfg.get("empty_adt_matrix")
        or dsb_cfg.get("background_adt_matrix")
        or module_cfg.get("empty_adt_matrix")
        or raw_cfg.get("empty_adt_matrix")
    )
    return _resolve_path(base, value) if value else None


def _run_dsb_backend(
    *,
    config: dict[str, Any],
    data: dict[str, Any],
    tables_dir: Path,
    figures_dir: Path,
    objects_dir: Path,
    analysis_fields: dict[str, Any],
    input_artifact: str,
    source_dataset: str,
) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    if not _dsb_requested(config):
        return {"backend_id": DSB_BACKEND_ID, "requested": False, "status": "not_requested", "reason": ""}, {}

    status_path = tables_dir / "dsb_backend_status.tsv"
    manifest_path = tables_dir / "dsb_backend_manifest.json"
    versions_path = tables_dir / "dsb_backend_versions.tsv"
    normalized_path = tables_dir / "dsb_normalized_matrix.tsv"
    background_path = tables_dir / "background_summary.tsv"
    input_matrix_path = tables_dir / "dsb_cell_adt_input.tsv"
    log_path = tables_dir / "dsb_backend.log"
    figure_path = figures_dir / "dsb_heatmap.png"
    object_path = objects_dir / "cite_seq_dsb_backend.rds"
    artifacts = {
        "tables": {
            "dsb_backend_status": str(status_path),
            "dsb_backend_manifest": str(manifest_path),
            "dsb_backend_versions": str(versions_path),
            "dsb_normalized_matrix": str(normalized_path),
            "background_summary": str(background_path),
            "dsb_backend_log": str(log_path),
        },
        "figures": {"dsb_heatmap": str(figure_path)},
        "objects": {"dsb_rds": str(object_path)},
    }

    reason = ""
    empty_matrix = _dsb_empty_matrix(config)
    if empty_matrix is None:
        reason = "missing_empty_adt_matrix"
    elif not empty_matrix.exists():
        reason = f"missing_empty_adt_matrix:{empty_matrix}"
    rscript = shutil.which("Rscript")
    if not reason and not rscript:
        reason = "dependency_missing:Rscript"
    if not reason and not _r_package_available(rscript, "dsb"):
        reason = "dependency_missing:dsb"

    if reason:
        _write_dsb_skip_outputs(
            status_path=status_path,
            manifest_path=manifest_path,
            versions_path=versions_path,
            normalized_path=normalized_path,
            background_path=background_path,
            log_path=log_path,
            figure_path=figure_path,
            object_path=object_path,
            analysis_fields=analysis_fields,
            reason=reason,
            input_artifact=input_artifact,
            source_dataset=source_dataset,
        )
        return {"backend_id": DSB_BACKEND_ID, "requested": True, "status": "skipped", "reason": reason}, artifacts

    _write_feature_matrix(
        path=input_matrix_path,
        features=list(map(str, data["adt_features"])),
        cells=list(map(str, data["cells"])),
        matrix=np.asarray(data["adt"], dtype=float).T,
    )
    dsb_cfg = _dsb_cfg(config)
    controls = dsb_cfg.get("isotype_controls") or dsb_cfg.get("isotype_control_name_vec") or []
    if isinstance(controls, str):
        controls_value = controls
    else:
        controls_value = ",".join(map(str, controls))
    script = Path(__file__).resolve().parents[2] / "scripts" / "R" / "cite_seq_dsb_backend.R"
    command = [
        rscript,
        str(script),
        "--cell-adt",
        str(input_matrix_path),
        "--empty-adt",
        str(empty_matrix),
        "--tables-dir",
        str(tables_dir),
        "--figures-dir",
        str(figures_dir),
        "--objects-dir",
        str(objects_dir),
        "--analysis-level",
        str(analysis_fields.get("analysis_level") or "smoke_backend"),
        "--source-dataset",
        source_dataset,
        "--input-artifact",
        input_artifact,
        "--isotype-controls",
        controls_value,
    ]
    try:
        completed = subprocess.run(command, check=True, text=True, capture_output=True, timeout=240)
        log_path.write_text(
            "COMMAND\t" + " ".join(command) + "\n\nSTDOUT\n" + completed.stdout + "\n\nSTDERR\n" + completed.stderr,
            encoding="utf-8",
        )
        return {"backend_id": DSB_BACKEND_ID, "requested": True, "status": "ready", "reason": ""}, artifacts
    except subprocess.CalledProcessError as exc:
        reason = f"backend_failed:Rscript_exit_{exc.returncode}"
        log_path.write_text(
            "COMMAND\t" + " ".join(command) + "\n\nSTDOUT\n" + (exc.stdout or "") + "\n\nSTDERR\n" + (exc.stderr or ""),
            encoding="utf-8",
        )
    except subprocess.TimeoutExpired as exc:
        reason = "backend_failed:Rscript_timeout"
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        log_path.write_text("COMMAND\t" + " ".join(command) + "\n\nSTDOUT\n" + stdout + "\n\nSTDERR\n" + stderr, encoding="utf-8")
    _write_dsb_skip_outputs(
        status_path=status_path,
        manifest_path=manifest_path,
        versions_path=versions_path,
        normalized_path=normalized_path,
        background_path=background_path,
        log_path=log_path,
        figure_path=figure_path,
        object_path=object_path,
        analysis_fields=analysis_fields,
        reason=reason,
        input_artifact=input_artifact,
        source_dataset=source_dataset,
        status="failed",
    )
    return {"backend_id": DSB_BACKEND_ID, "requested": True, "status": "failed", "reason": reason}, artifacts


def _r_package_available(rscript: str | None, package: str) -> bool:
    if not rscript:
        return False
    code = f"quit(status=ifelse(requireNamespace('{package}', quietly=TRUE), 0, 1))"
    return subprocess.run([rscript, "-e", code], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def _write_feature_matrix(*, path: Path, features: list[str], cells: list[str], matrix: np.ndarray) -> None:
    frame = pd.DataFrame(np.asarray(matrix, dtype=float), columns=cells)
    frame.insert(0, "feature_id", features)
    frame.to_csv(path, sep="\t", index=False)


def _write_dsb_skip_outputs(
    *,
    status_path: Path,
    manifest_path: Path,
    versions_path: Path,
    normalized_path: Path,
    background_path: Path,
    log_path: Path,
    figure_path: Path,
    object_path: Path,
    analysis_fields: dict[str, Any],
    reason: str,
    input_artifact: str,
    source_dataset: str,
    status: str = "skipped",
) -> None:
    base = _base_fields(analysis_fields, input_artifact, source_dataset)
    row = {
        **base,
        "backend_id": DSB_BACKEND_ID,
        "status": status,
        "skip_reason": reason,
        "normalization_method": "DSB_not_run",
        "interpretation_warning": DSB_WARNING,
    }
    pd.DataFrame([row]).to_csv(status_path, sep="\t", index=False)
    pd.DataFrame([{**row, "cell_id": "none", "antibody_id": "none", "dsb_normalized_adt": 0.0}]).to_csv(normalized_path, sep="\t", index=False)
    pd.DataFrame([{**row, "antibody_id": "none", "empty_mean": 0.0, "empty_sd": 0.0}]).to_csv(background_path, sep="\t", index=False)
    pd.DataFrame([{"package": "dsb", "version": "", "status": "not_run", "reason": reason}]).to_csv(versions_path, sep="\t", index=False)
    manifest = {
        "backend_id": DSB_BACKEND_ID,
        "status": status,
        "analysis_level": analysis_fields.get("analysis_level"),
        "delivery_allowed": analysis_fields.get("delivery_allowed"),
        "validation_evidence_allowed": analysis_fields.get("validation_evidence_allowed"),
        "skip_reason": reason,
        "interpretation_warning": DSB_WARNING,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    if not log_path.exists():
        log_path.write_text(f"DSB backend {status}: {reason}\n", encoding="utf-8")
    object_path.write_text(json.dumps({"status": status, "reason": reason}, indent=2), encoding="utf-8")
    _write_dsb_skip_figure(figure_path, reason)


def _write_dsb_skip_figure(path: Path, reason: str) -> None:
    tokens = apply_clinical_journal_style()
    plt.figure(figsize=(5.5, 3.2))
    plt.text(0.5, 0.58, "DSB skipped", ha="center", va="center", color=tokens["primary"], fontsize=13, fontweight="bold")
    plt.text(0.5, 0.38, reason[:100], ha="center", va="center", color=tokens["muted"], fontsize=9, wrap=True)
    plt.axis("off")
    plt.tight_layout()
    save_figure(path, style=tokens)


def _target_from_antibody(value: str) -> str:
    text = str(value)
    for sep in ("_", "-", " "):
        if sep in text:
            return text.split(sep)[0]
    return text


def _safe_corr(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 2 or np.std(a) == 0 or np.std(b) == 0:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def _write_cite_figures(*, tables_dir: Path, figures_dir: Path) -> dict[str, str]:
    tokens = apply_clinical_journal_style()
    qc = pd.read_csv(tables_dir / "adt_qc.tsv", sep="\t")
    normalized = pd.read_csv(tables_dir / "adt_normalized_matrix.tsv", sep="\t")
    consistency = pd.read_csv(tables_dir / "rna_protein_consistency.tsv", sep="\t")

    dist_path = figures_dir / "adt_count_distribution.png"
    plt.figure(figsize=(6, 4))
    sns.histplot(qc["adt_total_counts"].astype(float), bins=30, color=tokens["primary"])
    plt.xlabel("ADT total counts")
    plt.ylabel("Cells")
    plt.title("ADT Count Distribution")
    plt.tight_layout()
    save_figure(dist_path, style=tokens)

    heatmap_path = figures_dir / "adt_heatmap.png"
    top_antibodies = (
        normalized.groupby("antibody_id")["normalized_adt"].mean().sort_values(ascending=False).head(20).index.tolist()
    )
    top_cells = normalized["cell_id"].drop_duplicates().head(80).tolist()
    heatmap = normalized[normalized["antibody_id"].isin(top_antibodies) & normalized["cell_id"].isin(top_cells)]
    matrix = heatmap.pivot_table(index="antibody_id", columns="cell_id", values="normalized_adt", fill_value=0.0)
    plt.figure(figsize=(8, 5))
    sns.heatmap(matrix, cmap=continuous_cmap(tokens), cbar_kws={"label": "CLR ADT"})
    plt.xlabel("Cells")
    plt.ylabel("Antibodies")
    plt.title("ADT CLR Heatmap")
    plt.tight_layout()
    save_figure(heatmap_path, style=tokens)

    consistency_path = figures_dir / "rna_protein_consistency.png"
    plt.figure(figsize=(7, 4))
    top = consistency.sort_values("correlation_proxy", ascending=False).head(20)
    sns.barplot(data=top, x="antibody_id", y="correlation_proxy", color=tokens["primary"])
    plt.xticks(rotation=65, ha="right")
    plt.ylabel("RNA total vs ADT proxy correlation")
    plt.title("RNA-Protein Consistency Proxy")
    plt.tight_layout()
    save_figure(consistency_path, style=tokens)
    return {
        "adt_count_distribution": str(dist_path),
        "adt_heatmap": str(heatmap_path),
        "rna_protein_consistency": str(consistency_path),
    }


def _write_cite_object(*, objects_dir: Path, data: dict[str, Any], max_cells: int) -> dict[str, str]:
    object_path = objects_dir / "cite_mvp.h5mu"
    cells = list(map(str, data["cells"]))
    selected = np.arange(len(cells))
    if len(selected) > max_cells:
        rng = np.random.default_rng(11)
        selected = np.sort(rng.choice(selected, size=max_cells, replace=False))
    try:
        import anndata as ad
        import mudata as md

        rna = ad.AnnData(X=np.asarray(data["rna"], dtype=float)[selected], obs=pd.DataFrame(index=np.array(cells)[selected]), var=pd.DataFrame(index=data["rna_features"]))
        adt = ad.AnnData(X=np.asarray(data["adt"], dtype=float)[selected], obs=pd.DataFrame(index=np.array(cells)[selected]), var=pd.DataFrame(index=data["adt_features"]))
        md.MuData({"rna": rna, "adt": adt}).write_h5mu(object_path)
        status = "h5mu_written"
    except Exception as exc:
        first_error = f"{type(exc).__name__}:{exc}"
        try:
            import h5py

            with h5py.File(object_path, "w") as handle:
                handle.attrs["object_status"] = "h5mu_like_hdf5_fallback"
                handle.attrs["fallback_reason"] = first_error
                handle.create_dataset("obs/cell_id", data=np.array(cells, dtype="S")[selected])
                handle.create_dataset("rna/X", data=np.asarray(data["rna"], dtype=float)[selected], compression="gzip")
                handle.create_dataset("adt/X", data=np.asarray(data["adt"], dtype=float)[selected], compression="gzip")
                handle.create_dataset("rna/var/feature_id", data=np.array(data["rna_features"], dtype="S"))
                handle.create_dataset("adt/var/antibody_id", data=np.array(data["adt_features"], dtype="S"))
            status = "h5mu_like_hdf5_fallback"
        except Exception as fallback_exc:  # pragma: no cover - only when optional HDF5 stack is absent
            object_path.write_text(
                json.dumps(
                    {
                        "object_status": "json_fallback_not_h5mu",
                        "primary_reason": first_error,
                        "fallback_reason": f"{type(fallback_exc).__name__}:{fallback_exc}",
                        "n_cells": int(len(cells)),
                        "n_rna_features": int(len(data["rna_features"])),
                        "n_adt_features": int(len(data["adt_features"])),
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            status = "json_fallback_not_h5mu"
    manifest_path = objects_dir / "cite_mvp_object_manifest.json"
    manifest_path.write_text(json.dumps({"object": str(object_path), "status": status, "max_cells": int(max_cells)}, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"mvp_object": str(object_path), "object_manifest": str(manifest_path)}


def _write_skip_outputs(*, tables_dir: Path, figures_dir: Path, objects_dir: Path, analysis_fields: dict[str, Any]) -> dict[str, dict[str, str]]:
    base = _base_fields(analysis_fields, "missing_cite_seq_input", "cite_seq")
    row = {
        **base,
        "status": "skipped_missing_input",
        "cell_id": "none",
        "adt_total_counts": 0,
        "background_status": "missing_input",
        "isotype_control_status": "not_available",
        "antibody_id": "none",
        "target_protein": "none",
        "isotype_control": "unknown",
        "panel_scope_note": "missing_input",
        "normalized_adt": 0.0,
        "normalization_method": "not_run",
        "cluster_id": "none",
        "marker_score": 0.0,
        "gene_symbol": "none",
        "correlation_proxy": 0.0,
        "mechanism_warning": CITE_WARNING,
    }
    table_paths = {}
    for filename in ("adt_qc.tsv", "antibody_panel.tsv", "adt_normalized_matrix.tsv", "adt_marker_summary.tsv", "rna_protein_consistency.tsv"):
        table_paths[filename.replace(".tsv", "")] = _write_tsv(pd.DataFrame([row]), tables_dir / filename)
    figure_paths = _write_placeholder_figures(figures_dir)
    object_path = objects_dir / "cite_mvp.h5mu"
    object_path.write_text(json.dumps({"status": "skipped_missing_input"}, indent=2), encoding="utf-8")
    return {"tables": table_paths, "figures": figure_paths, "objects": {"mvp_object": str(object_path)}}


def _write_placeholder_figures(figures_dir: Path) -> dict[str, str]:
    tokens = apply_clinical_journal_style()
    paths = {}
    for key, title in {
        "adt_count_distribution": "ADT Count Distribution",
        "adt_heatmap": "ADT Heatmap",
        "rna_protein_consistency": "RNA-Protein Consistency",
    }.items():
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
