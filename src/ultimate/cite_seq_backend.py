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
CITE_WARNING = "ADT 是抗体 panel 限定的标签计数，不是全蛋白组；RNA/protein 不一致不能自动解释为机制。"


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
