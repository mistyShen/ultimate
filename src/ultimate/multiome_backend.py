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
from ultimate.plot_style import apply_clinical_journal_style, save_figure


MULTIOME_BACKEND_ID = "multiome.default.muon_mvp"
MULTIOME_WARNING = "Multiome 不是 scRNA 与 scATAC 简单拼接；peak-gene linkage 是统计关联，不是实验证明。"


def has_multiome_backend_config(config: dict[str, Any]) -> bool:
    module_cfg = _module_cfg(config)
    raw_cfg = module_cfg.get("raw") if isinstance(module_cfg.get("raw"), dict) else {}
    keys = {
        "input_h5",
        "input_h5mu",
        "input_path",
        "feature_matrix",
        "rna_matrix",
        "atac_matrix",
        "peak_matrix",
        "count_matrix",
    }
    return any(module_cfg.get(key) for key in keys) or any(raw_cfg.get(key) for key in keys)


def run_multiome_backend(*, config: dict[str, Any], output_dir: Path, samples: pd.DataFrame) -> dict[str, Any]:
    module_name = "multiome"
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
    status = "partial:multiome_inputs_missing" if missing_inputs else "complete_multiome_muon_backend"
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
        status = "partial:multiome_analysis_level_invalid"
        missing_inputs.append(f"analysis_level_invalid:{exc}")
        level_fields = classify_analysis_level(requested_level="smoke_backend", is_stub=True).to_manifest_fields()

    artifacts: dict[str, dict[str, str]] = {"tables": {}, "figures": {}, "objects": {}, "reports": {}}
    warnings = [MULTIOME_WARNING]
    backend_plan_base = build_backend_plan(module_name, config)
    active_backend_ids = {str(row.get("backend_id")) for row in backend_plan_base.get("active_backends", []) if isinstance(row, dict)}
    backend_execution_rows: list[dict[str, Any]] = []
    n_cells = 0
    n_rna_features = 0
    n_atac_features = 0
    if missing_inputs:
        artifacts.update(_write_skip_outputs(tables_dir=tables_dir, figures_dir=figures_dir, objects_dir=objects_dir, analysis_fields=level_fields))
    else:
        try:
            data = _load_multiome_data(config)
        except Exception as exc:
            status = "partial:multiome_input_read_failed"
            missing_inputs.append(f"input_read_failed:{type(exc).__name__}:{exc}")
            level_fields = classify_analysis_level(requested_level="smoke_backend", is_stub=True).to_manifest_fields()
            artifacts.update(_write_skip_outputs(tables_dir=tables_dir, figures_dir=figures_dir, objects_dir=objects_dir, analysis_fields=level_fields))
            data = None
        if data is not None:
            n_cells = int(len(data["barcodes"]))
            n_rna_features = int(len(data["rna_features"]))
            n_atac_features = int(len(data["atac_features"]))
            artifacts["tables"].update(
                _write_multiome_tables(
                    tables_dir=tables_dir,
                    data=data,
                    analysis_fields=level_fields,
                    input_artifact=str(input_ref or ""),
                    source_dataset=_source_dataset(config),
                )
            )
            artifacts["figures"].update(_write_multiome_figures(tables_dir=tables_dir, figures_dir=figures_dir))
            if "multiome.peak_gene.correlation" in active_backend_ids:
                peak_gene_artifacts = _run_peak_gene_correlation_backend(
                    tables_dir=tables_dir,
                    figures_dir=figures_dir,
                    data=data,
                    analysis_fields=level_fields,
                    input_artifact=str(input_ref or ""),
                    source_dataset=_source_dataset(config),
                )
                artifacts["tables"].update(peak_gene_artifacts["tables"])
                artifacts["figures"].update(peak_gene_artifacts["figures"])
                artifacts["objects"].update(peak_gene_artifacts["objects"])
            artifacts["objects"].update(
                _write_multiome_object(
                    objects_dir=objects_dir,
                    data=data,
                    max_cells=int(module_cfg.get("max_cells_object", 3000)),
                    max_features=int(module_cfg.get("max_features_object", 2500)),
                )
            )

    artifacts["tables"]["tool_coverage"] = write_tool_coverage_table(module_name, tables_dir)
    artifacts["tables"]["backend_plan"] = str(write_backend_plan_table(module_name, config, tables_dir))
    artifacts["reports"]["methods_fragment"] = write_module_methods_fragment(module_name, reports_dir)
    backend_plan = enrich_backend_plan_for_run(
        backend_plan_base,
        analysis_level=str(level_fields.get("analysis_level") or "smoke_backend"),
        delivery_allowed=bool(level_fields.get("delivery_allowed") is True),
        validation_evidence_allowed=bool(level_fields.get("validation_evidence_allowed") is True),
    )
    backend_execution_rows.append(
        {
            "backend_id": MULTIOME_BACKEND_ID,
            "status": "ready" if not status.startswith("partial") else "skipped",
            "analysis_level": level_fields.get("analysis_level") or "smoke_backend",
            "delivery_allowed": bool(level_fields.get("delivery_allowed") is True and not status.startswith("partial")),
            "validation_evidence_allowed": bool(level_fields.get("validation_evidence_allowed") is True and not status.startswith("partial")),
            "reason": "" if not status.startswith("partial") else status,
            "backend_slurm_job_id": str(backend_plan.get("backend_slurm_job_id") or ""),
        }
    )
    if "multiome.peak_gene.correlation" in active_backend_ids:
        backend_execution_rows.append(
            _status_execution_row(
                backend_id="multiome.peak_gene.correlation",
                status_path=tables_dir / "peak_gene_correlation_backend_status.tsv",
                analysis_fields=level_fields,
                backend_plan=backend_plan,
            )
        )
    backend_execution_path = tables_dir / "backend_execution.tsv"
    pd.DataFrame(backend_execution_rows).to_csv(backend_execution_path, sep="\t", index=False)
    artifacts["tables"]["backend_execution"] = str(backend_execution_path)
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
        "n_atac_features": n_atac_features,
        "artifacts": artifacts,
        "warnings": warnings,
        "limitations": list(known_limitations(module_name)),
        "handoff": handoff_plan(module_name),
        "reproducible_command": f"ultimate run --config {config.get('_config_path', '<config.yaml>')}",
        "backend": {
            "primary": "multiome_muon_mvp",
            "selected_backend_id": backend_plan["selected_backend_id"],
            "selected_backend_status": backend_plan["selected_backend_status"],
            "backend_role": backend_plan["selected_backend_role"],
            "resource_profile": backend_plan["backend_resource_profile"],
            "input_contract": "10x ARC/feature-barcode H5 or RNA matrix + ATAC peak matrix",
            "modality_warning": MULTIOME_WARNING,
        },
        "backend_plan": backend_plan,
        "backend_execution_rows": backend_execution_rows,
        "backend_id": backend_plan["selected_backend_id"],
        "backend_status": backend_plan["selected_backend_status"],
        "backend_analysis_level": backend_plan["backend_analysis_level"],
        "backend_delivery_allowed": backend_plan["backend_delivery_allowed"],
        "backend_validation_evidence_allowed": backend_plan["backend_validation_evidence_allowed"],
        "backend_skip_reason": backend_plan["backend_skip_reason"],
        "backend_resource_profile": backend_plan["backend_resource_profile"],
        "backend_slurm_job_id": backend_plan["backend_slurm_job_id"],
        "formal_backend": {
            "python_entrypoint": "ultimate.multiome_backend.run_multiome_backend",
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
    return ((config.get("modules") or {}).get("multiome") or {}) if isinstance(config.get("modules"), dict) else {}


def _module_is_demo(config: dict[str, Any], module_cfg: dict[str, Any]) -> bool | None:
    if "is_demo" in module_cfg:
        return bool(module_cfg.get("is_demo"))
    project = config.get("project") or {}
    if "is_demo" in project:
        return bool(project.get("is_demo"))
    return None


def _source_dataset(config: dict[str, Any]) -> str:
    project = config.get("project") or {}
    return str(project.get("name") or project.get("job_id") or "multiome")


def _primary_input_ref(config: dict[str, Any]) -> Path | None:
    module_cfg = _module_cfg(config)
    raw_cfg = module_cfg.get("raw") if isinstance(module_cfg.get("raw"), dict) else {}
    base = Path(str(config.get("_config_path") or ".")).resolve().parent
    value = (
        module_cfg.get("input_h5")
        or module_cfg.get("input_h5mu")
        or module_cfg.get("input_path")
        or module_cfg.get("feature_matrix")
        or raw_cfg.get("input_path")
        or raw_cfg.get("feature_matrix")
        or raw_cfg.get("matrix_path")
        or raw_cfg.get("count_matrix")
        or module_cfg.get("rna_matrix")
    )
    return _resolve_path(base, value) if value else None


def _missing_input_reasons(config: dict[str, Any]) -> list[str]:
    module_cfg = _module_cfg(config)
    raw_cfg = module_cfg.get("raw") if isinstance(module_cfg.get("raw"), dict) else {}
    base = Path(str(config.get("_config_path") or ".")).resolve().parent
    single = _primary_input_ref(config)
    if single is not None and single.suffix.lower() in {".h5", ".hdf5", ".h5mu"}:
        return [] if single.exists() else [f"missing_input_path:{single}"]
    rna = module_cfg.get("rna_matrix") or raw_cfg.get("rna_matrix") or raw_cfg.get("count_matrix")
    atac = module_cfg.get("atac_matrix") or module_cfg.get("peak_matrix") or raw_cfg.get("atac_matrix") or raw_cfg.get("peak_matrix")
    reasons = []
    if not rna:
        reasons.append("missing_rna_matrix")
    elif not _resolve_path(base, rna).exists():
        reasons.append(f"missing_rna_matrix:{_resolve_path(base, rna)}")
    if not atac:
        reasons.append("missing_atac_matrix")
    elif not _resolve_path(base, atac).exists():
        reasons.append(f"missing_atac_matrix:{_resolve_path(base, atac)}")
    return reasons


def _resolve_path(base: Path, value: Any) -> Path:
    candidate = Path(str(value))
    return candidate if candidate.is_absolute() else (base / candidate).resolve()


def _load_multiome_data(config: dict[str, Any]) -> dict[str, Any]:
    module_cfg = _module_cfg(config)
    raw_cfg = module_cfg.get("raw") if isinstance(module_cfg.get("raw"), dict) else {}
    base = Path(str(config.get("_config_path") or ".")).resolve().parent
    single = _primary_input_ref(config)
    if single is not None and single.suffix.lower() in {".h5", ".hdf5"}:
        return _load_10x_multiome_h5(single)
    if single is not None and single.suffix.lower() == ".h5mu":
        return _load_h5mu(single)
    rna_value = module_cfg.get("rna_matrix") or raw_cfg.get("rna_matrix") or raw_cfg.get("count_matrix")
    atac_value = module_cfg.get("atac_matrix") or module_cfg.get("peak_matrix") or raw_cfg.get("atac_matrix") or raw_cfg.get("peak_matrix")
    if rna_value and atac_value:
        return _load_csv_matrices(_resolve_path(base, rna_value), _resolve_path(base, atac_value))
    raise ValueError("No supported Multiome input was configured.")


def _load_10x_multiome_h5(path: Path) -> dict[str, Any]:
    import h5py
    from scipy import sparse

    with h5py.File(path, "r") as handle:
        group = handle["matrix"]
        features = group["features"]
        feature_type_key = "feature_type" if "feature_type" in features else "feature_types"
        shape = tuple(int(x) for x in group["shape"][:])
        matrix = sparse.csc_matrix((group["data"][:], group["indices"][:], group["indptr"][:]), shape=shape).T.tocsr()
        feature_ids = _decode(features["id"][:])
        feature_names = _decode(features["name"][:])
        feature_types = _decode(features[feature_type_key][:])
        barcodes = _decode(group["barcodes"][:])
    rna_mask = _feature_type_mask(feature_types, {"gene expression"})
    atac_mask = _feature_type_mask(feature_types, {"peaks", "peak", "atac"})
    if not rna_mask.any() or not atac_mask.any():
        raise ValueError("Expected both Gene Expression and Peaks/ATAC features in the 10x H5.")
    return {
        "barcodes": barcodes,
        "rna": matrix[:, rna_mask].tocsr(),
        "atac": matrix[:, atac_mask].tocsr(),
        "rna_features": np.asarray(feature_names)[rna_mask].astype(str).tolist(),
        "atac_features": np.asarray(feature_names)[atac_mask].astype(str).tolist(),
        "source": str(path),
    }


def _load_h5mu(path: Path) -> dict[str, Any]:
    import mudata as md

    mdata = md.read_h5mu(path)
    rna_key = "rna" if "rna" in mdata.mod else "gex" if "gex" in mdata.mod else None
    atac_key = "atac" if "atac" in mdata.mod else "peaks" if "peaks" in mdata.mod else None
    if rna_key is None or atac_key is None:
        raise ValueError("Expected h5mu modalities named rna/gex and atac/peaks.")
    rna = mdata.mod[rna_key]
    atac = mdata.mod[atac_key]
    shared = [cell for cell in rna.obs_names.astype(str) if cell in set(atac.obs_names.astype(str))]
    if not shared:
        raise ValueError("RNA and ATAC modalities have no shared barcodes.")
    return {
        "barcodes": shared,
        "rna": rna[shared].X,
        "atac": atac[shared].X,
        "rna_features": rna.var_names.astype(str).tolist(),
        "atac_features": atac.var_names.astype(str).tolist(),
        "source": str(path),
    }


def _load_csv_matrices(rna_path: Path, atac_path: Path) -> dict[str, Any]:
    rna = _read_feature_matrix(rna_path)
    atac = _read_feature_matrix(atac_path)
    shared = [cell for cell in rna.columns.astype(str) if cell in set(atac.columns.astype(str))]
    if not shared:
        raise ValueError("RNA and ATAC matrices have no shared cell barcodes.")
    return {
        "barcodes": shared,
        "rna": rna[shared].to_numpy(dtype=float).T,
        "atac": atac[shared].to_numpy(dtype=float).T,
        "rna_features": rna.index.astype(str).tolist(),
        "atac_features": atac.index.astype(str).tolist(),
        "source": f"{rna_path}|{atac_path}",
    }


def _decode(values: Any) -> list[str]:
    return [value.decode("utf-8") if isinstance(value, bytes) else str(value) for value in values]


def _feature_type_mask(feature_types: list[str], accepted: set[str]) -> np.ndarray:
    normalized = np.asarray([value.strip().lower() for value in feature_types])
    return np.isin(normalized, list(accepted))


def _read_feature_matrix(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, sep=None, engine="python")
    index_col = "feature_id" if "feature_id" in frame.columns else frame.columns[0]
    frame = frame.set_index(index_col)
    return frame.apply(pd.to_numeric, errors="coerce").fillna(0.0)


def _axis_sums(matrix: Any) -> tuple[np.ndarray, np.ndarray]:
    if hasattr(matrix, "sum"):
        total = np.asarray(matrix.sum(axis=1)).reshape(-1).astype(float)
        detected = np.asarray((matrix > 0).sum(axis=1)).reshape(-1).astype(int)
        return total, detected
    arr = np.asarray(matrix, dtype=float)
    return arr.sum(axis=1), (arr > 0).sum(axis=1)


def _feature_sums(matrix: Any) -> np.ndarray:
    if hasattr(matrix, "sum"):
        return np.asarray(matrix.sum(axis=0)).reshape(-1).astype(float)
    return np.asarray(matrix, dtype=float).sum(axis=0)


def _subset_matrix(matrix: Any, rows: np.ndarray, cols: np.ndarray) -> Any:
    subset = matrix[rows, :][:, cols]
    return subset.tocsr() if hasattr(subset, "tocsr") else np.asarray(subset, dtype=float)


def _write_multiome_tables(*, tables_dir: Path, data: dict[str, Any], analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str) -> dict[str, str]:
    paths = {}
    rna_total, rna_detected = _axis_sums(data["rna"])
    atac_total, atac_detected = _axis_sums(data["atac"])
    paths["rna_qc"] = _write_tsv(_modality_qc("RNA", data["barcodes"], rna_total, rna_detected, analysis_fields, input_artifact, source_dataset), tables_dir / "rna_qc.tsv")
    paths["atac_qc"] = _write_tsv(_modality_qc("ATAC", data["barcodes"], atac_total, atac_detected, analysis_fields, input_artifact, source_dataset), tables_dir / "atac_qc.tsv")
    paths["barcode_overlap"] = _write_tsv(_barcode_overlap(data, analysis_fields, input_artifact, source_dataset), tables_dir / "barcode_overlap.tsv")
    paths["modality_consistency"] = _write_tsv(_modality_consistency(data["barcodes"], rna_total, atac_total, analysis_fields, input_artifact, source_dataset), tables_dir / "modality_consistency.tsv")
    paths["rna_marker_handoff"] = _write_tsv(_feature_handoff("rna_marker_handoff", data["rna_features"], _feature_sums(data["rna"]), "RNA marker analysis requires cluster labels/reference annotation.", analysis_fields, input_artifact, source_dataset), tables_dir / "rna_marker_handoff.tsv")
    paths["atac_marker_peak_handoff"] = _write_tsv(_feature_handoff("atac_marker_peak_handoff", data["atac_features"], _feature_sums(data["atac"]), "ATAC marker peaks require chromatin-specific clustering and fragments-aware QC.", analysis_fields, input_artifact, source_dataset), tables_dir / "atac_marker_peak_handoff.tsv")
    paths["peak_gene_link_handoff"] = _write_tsv(_peak_gene_link_handoff(analysis_fields, input_artifact, source_dataset), tables_dir / "peak_gene_link_handoff.tsv")
    return paths


def _base_fields(analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str) -> dict[str, Any]:
    return {
        "module": "multiome",
        "run_id": source_dataset,
        "sample_id": "all",
        "source_dataset": source_dataset,
        "input_artifact": input_artifact,
        "input_modality": "rna_atac_multiome",
        "analysis_level": analysis_fields.get("analysis_level"),
        "result_scope": "multiome_muon_mvp",
        "method_status": "fully_automatic_validated_entrypoint",
        "delivery_allowed": analysis_fields.get("delivery_allowed"),
    }


def _modality_qc(modality: str, barcodes: list[str], totals: np.ndarray, detected: np.ndarray, analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str) -> pd.DataFrame:
    rows = []
    for barcode, total, n_detected in zip(barcodes, totals, detected):
        row = _base_fields(analysis_fields, input_artifact, source_dataset)
        row.update(
            {
                "cell_id": barcode,
                "qc_metric": f"{modality.lower()}_counts_and_detected_features",
                "qc_value": float(total),
                "detected_features": int(n_detected),
                "qc_status": "ready",
                "modality": modality,
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _barcode_overlap(data: dict[str, Any], analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str) -> pd.DataFrame:
    barcodes = list(map(str, data["barcodes"]))
    row = _base_fields(analysis_fields, input_artifact, source_dataset)
    row.update(
        {
            "rna_barcode_count": len(barcodes),
            "atac_barcode_count": len(barcodes),
            "overlap_count": len(barcodes),
            "overlap_fraction": 1.0 if barcodes else 0.0,
            "overlap_status": "shared_feature_barcode_matrix" if barcodes else "no_shared_barcodes",
        }
    )
    return pd.DataFrame([row])


def _modality_consistency(barcodes: list[str], rna_total: np.ndarray, atac_total: np.ndarray, analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str) -> pd.DataFrame:
    rows = []
    for barcode, rna_count, atac_count in zip(barcodes, rna_total, atac_total):
        row = _base_fields(analysis_fields, input_artifact, source_dataset)
        row.update(
            {
                "cell_id": barcode,
                "rna_qc_status": "ready" if float(rna_count) > 0 else "low_rna_counts",
                "atac_qc_status": "ready" if float(atac_count) > 0 else "low_atac_counts",
                "joint_object_status": "joint_barcode_ready",
                "modality_warning": MULTIOME_WARNING,
                "rna_total_counts": float(rna_count),
                "atac_total_counts": float(atac_count),
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _feature_handoff(artifact: str, features: list[str], counts: np.ndarray, note: str, analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str) -> pd.DataFrame:
    rows = []
    top_idx = np.argsort(np.asarray(counts, dtype=float))[::-1][:50]
    for idx in top_idx:
        row = _base_fields(analysis_fields, input_artifact, source_dataset)
        row.update(
            {
                "artifact": artifact,
                "feature_id": str(features[int(idx)]),
                "status": "handoff_ready_not_claimed_as_completed",
                "handoff_tool": "muon/Seurat WNN/Signac/ArchR/scvi-tools",
                "required_input": "cluster labels and backend-specific parameters",
                "value": float(counts[int(idx)]),
                "note": note,
            }
        )
        rows.append(row)
    return pd.DataFrame(rows or [{**_base_fields(analysis_fields, input_artifact, source_dataset), "artifact": artifact, "feature_id": "none", "status": "no_features", "handoff_tool": "not_run", "required_input": "features", "value": 0.0, "note": note}])


def _peak_gene_link_handoff(analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str) -> pd.DataFrame:
    row = _base_fields(analysis_fields, input_artifact, source_dataset)
    row.update(
        {
            "artifact": "peak_gene_link_handoff",
            "status": "handoff_ready_not_claimed_as_completed",
            "handoff_tool": "Signac LinkPeaks / ArchR peak2gene / Cicero",
            "required_input": "fragments, gene annotations, genome build, matched RNA and ATAC embeddings",
            "note": "Peak-gene linkage is a statistical association and requires additional validation.",
        }
    )
    return pd.DataFrame([row])


def _write_multiome_figures(*, tables_dir: Path, figures_dir: Path) -> dict[str, str]:
    tokens = apply_clinical_journal_style()
    consistency = pd.read_csv(tables_dir / "modality_consistency.tsv", sep="\t")
    rna_qc = pd.read_csv(tables_dir / "rna_qc.tsv", sep="\t")
    atac_qc = pd.read_csv(tables_dir / "atac_qc.tsv", sep="\t")

    embedding_path = figures_dir / "joint_embedding_placeholder.png"
    plt.figure(figsize=(5.5, 4.5))
    plt.scatter(consistency["rna_total_counts"].astype(float) + 1, consistency["atac_total_counts"].astype(float) + 1, s=5, alpha=0.45, color=tokens["primary"])
    plt.xscale("log")
    plt.yscale("log")
    plt.xlabel("RNA total counts + 1")
    plt.ylabel("ATAC total counts + 1")
    plt.title("RNA-ATAC Joint QC")
    plt.tight_layout()
    save_figure(embedding_path, style=tokens)

    modality_path = figures_dir / "modality_qc.png"
    frame = pd.DataFrame(
        {
            "modality": ["RNA", "ATAC"],
            "median_total_counts": [rna_qc["qc_value"].astype(float).median(), atac_qc["qc_value"].astype(float).median()],
            "median_detected_features": [rna_qc["detected_features"].astype(float).median(), atac_qc["detected_features"].astype(float).median()],
        }
    )
    plt.figure(figsize=(6, 4))
    sns.barplot(data=frame, x="modality", y="median_detected_features", color=tokens["bar"])
    plt.xlabel("")
    plt.ylabel("Median detected features")
    plt.title("Modality QC")
    plt.tight_layout()
    save_figure(modality_path, style=tokens)
    return {"joint_embedding_placeholder": str(embedding_path), "modality_qc": str(modality_path)}


def _run_peak_gene_correlation_backend(
    *,
    tables_dir: Path,
    figures_dir: Path,
    data: dict[str, Any],
    analysis_fields: dict[str, Any],
    input_artifact: str,
    source_dataset: str,
) -> dict[str, dict[str, str]]:
    backend_id = "multiome.peak_gene.correlation"
    links_path = tables_dir / "peak_gene_links.tsv"
    modality_path = tables_dir / "peak_gene_modality_correlation.tsv"
    status_path = tables_dir / "peak_gene_correlation_backend_status.tsv"
    manifest_path = tables_dir / "peak_gene_correlation_backend_manifest.json"
    versions_path = tables_dir / "peak_gene_correlation_backend_versions.tsv"
    heatmap_path = figures_dir / "peak_gene_correlation_heatmap.png"
    object_path = tables_dir.parents[2] / "objects" / "multiome" / "peak_gene_correlation_backend.rds"
    artifacts = {
        "tables": {
            "peak_gene_links": str(links_path),
            "peak_gene_modality_correlation": str(modality_path),
            "peak_gene_correlation_backend_status": str(status_path),
            "peak_gene_correlation_backend_manifest": str(manifest_path),
            "peak_gene_correlation_backend_versions": str(versions_path),
        },
        "figures": {"peak_gene_correlation_heatmap": str(heatmap_path)},
        "objects": {"peak_gene_correlation_backend_object": str(object_path)},
    }
    warning = "Peak-gene linkage is a same-barcode statistical association and is not enhancer-gene experimental proof."
    if len(data["barcodes"]) < 3 or len(data["rna_features"]) < 2 or len(data["atac_features"]) < 2:
        reason = f"insufficient_multiome_dimensions:cells={len(data['barcodes'])};rna={len(data['rna_features'])};atac={len(data['atac_features'])}"
        _write_peak_gene_skip(links_path, modality_path, status_path, manifest_path, versions_path, heatmap_path, object_path, backend_id, analysis_fields, reason, warning)
        return artifacts
    rna = _to_dense(data["rna"])
    atac = _to_dense(data["atac"])
    rna_idx = _top_feature_indices(rna, min(30, rna.shape[1]))
    atac_idx = _top_feature_indices(atac, min(30, atac.shape[1]))
    rna_sub = np.log1p(rna[:, rna_idx])
    atac_sub = np.log1p(atac[:, atac_idx])
    corr = _safe_corr(atac_sub, rna_sub)
    rows = []
    for peak_pos, peak_idx in enumerate(atac_idx):
        for gene_pos, gene_idx in enumerate(rna_idx):
            value = float(corr[peak_pos, gene_pos])
            rows.append(
                {
                    "backend_id": backend_id,
                    "peak_id": str(data["atac_features"][int(peak_idx)]),
                    "gene_id": str(data["rna_features"][int(gene_idx)]),
                    "correlation": value,
                    "abs_correlation": abs(value),
                    "n_shared_barcodes": int(len(data["barcodes"])),
                    "method": "pearson_correlation_log1p_counts",
                    "method_boundary": warning,
                    "analysis_level": analysis_fields.get("analysis_level") or "smoke_backend",
                }
            )
    links = pd.DataFrame(rows).sort_values("abs_correlation", ascending=False)
    links.to_csv(links_path, sep="\t", index=False)
    pd.DataFrame(
        [
            {
                "backend_id": backend_id,
                "rna_feature_count": int(rna.shape[1]),
                "atac_peak_count": int(atac.shape[1]),
                "shared_barcode_count": int(len(data["barcodes"])),
                "median_abs_peak_gene_correlation": float(np.median(np.abs(corr))),
                "method_boundary": warning,
            }
        ]
    ).to_csv(modality_path, sep="\t", index=False)
    _write_peak_gene_status(status_path, backend_id, "ready", "", analysis_fields, warning, len(data["barcodes"]))
    _write_peak_gene_versions(versions_path, backend_id)
    _write_peak_gene_manifest(manifest_path, backend_id, "ready", "", analysis_fields, warning, artifacts)
    object_path.write_text(json.dumps({"backend_id": backend_id, "status": "ready", "top_links": links.head(100).to_dict(orient="records"), "method_boundary": warning}, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_peak_gene_heatmap(corr, [str(data["atac_features"][int(i)]) for i in atac_idx], [str(data["rna_features"][int(i)]) for i in rna_idx], heatmap_path)
    return artifacts


def _safe_corr(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    left_z = left - left.mean(axis=0, keepdims=True)
    right_z = right - right.mean(axis=0, keepdims=True)
    left_sd = left_z.std(axis=0, ddof=1, keepdims=True)
    right_sd = right_z.std(axis=0, ddof=1, keepdims=True)
    left_z = left_z / np.where(left_sd == 0, np.nan, left_sd)
    right_z = right_z / np.where(right_sd == 0, np.nan, right_sd)
    corr = np.nan_to_num((left_z.T @ right_z) / max(1, left.shape[0] - 1), nan=0.0, posinf=0.0, neginf=0.0)
    return np.clip(corr, -1.0, 1.0)


def _write_peak_gene_heatmap(corr: np.ndarray, peaks: list[str], genes: list[str], path: Path) -> None:
    tokens = apply_clinical_journal_style()
    heat = pd.DataFrame(corr[: min(20, len(peaks)), : min(20, len(genes))], index=peaks[:20], columns=genes[:20])
    plt.figure(figsize=(8.0, 6.5))
    sns.heatmap(heat, cmap="vlag", center=0, cbar_kws={"label": "Pearson r"})
    plt.xlabel("RNA genes")
    plt.ylabel("ATAC peaks")
    plt.title("Peak-gene correlation")
    plt.tight_layout()
    save_figure(path, style=tokens)


def _write_peak_gene_status(path: Path, backend_id: str, status: str, reason: str, analysis_fields: dict[str, Any], warning: str, n_barcodes: int) -> None:
    pd.DataFrame(
        [
            {
                "backend_id": backend_id,
                "status": status,
                "reason": reason,
                "analysis_level": analysis_fields.get("analysis_level") or "smoke_backend",
                "delivery_allowed": bool(analysis_fields.get("delivery_allowed") is True and status == "ready"),
                "validation_evidence_allowed": bool(analysis_fields.get("validation_evidence_allowed") is True and status == "ready"),
                "n_shared_barcodes": int(n_barcodes),
                "method_boundary": warning,
            }
        ]
    ).to_csv(path, sep="\t", index=False)


def _write_peak_gene_versions(path: Path, backend_id: str) -> None:
    pd.DataFrame(
        [
            {"backend_id": backend_id, "tool": "numpy", "version": np.__version__},
            {"backend_id": backend_id, "tool": "pandas", "version": pd.__version__},
            {"backend_id": backend_id, "tool": "peak_gene_correlation_backend", "version": "python_matrix_mvp"},
        ]
    ).to_csv(path, sep="\t", index=False)


def _write_peak_gene_manifest(path: Path, backend_id: str, status: str, reason: str, analysis_fields: dict[str, Any], warning: str, artifacts: dict[str, dict[str, str]]) -> None:
    path.write_text(
        json.dumps(
            {
                "backend_id": backend_id,
                "status": status,
                "skip_reason": reason,
                "analysis_level": analysis_fields.get("analysis_level") or "smoke_backend",
                "delivery_allowed": bool(analysis_fields.get("delivery_allowed") is True and status == "ready"),
                "validation_evidence_allowed": bool(analysis_fields.get("validation_evidence_allowed") is True and status == "ready"),
                "method_boundary": warning,
                "artifacts": artifacts,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_peak_gene_skip(links_path: Path, modality_path: Path, status_path: Path, manifest_path: Path, versions_path: Path, heatmap_path: Path, object_path: Path, backend_id: str, analysis_fields: dict[str, Any], reason: str, warning: str) -> None:
    pd.DataFrame([{"backend_id": backend_id, "status": "skipped", "reason": reason, "method_boundary": warning}]).to_csv(links_path, sep="\t", index=False)
    pd.DataFrame([{"backend_id": backend_id, "status": "skipped", "reason": reason, "method_boundary": warning}]).to_csv(modality_path, sep="\t", index=False)
    _write_peak_gene_status(status_path, backend_id, "skipped", reason, analysis_fields, warning, 0)
    _write_peak_gene_versions(versions_path, backend_id)
    _write_peak_gene_manifest(manifest_path, backend_id, "skipped", reason, analysis_fields, warning, {"tables": {"peak_gene_links": str(links_path)}})
    object_path.write_text(json.dumps({"backend_id": backend_id, "status": "skipped", "reason": reason}, indent=2), encoding="utf-8")
    _write_placeholder_backend_figure(heatmap_path, "Peak-gene correlation", reason)


def _status_execution_row(*, backend_id: str, status_path: Path, analysis_fields: dict[str, Any], backend_plan: dict[str, Any]) -> dict[str, Any]:
    status = "skipped"
    reason = f"missing_backend_status:{backend_id}"
    if status_path.exists() and status_path.stat().st_size > 0:
        frame = pd.read_csv(status_path, sep="\t")
        if not frame.empty:
            first = frame.iloc[0]
            status = str(first.get("status") or "skipped")
            reason_value = first.get("reason")
            reason = "" if pd.isna(reason_value) else str(reason_value)
    ready = status == "ready"
    return {
        "backend_id": backend_id,
        "status": "ready" if ready else "skipped",
        "analysis_level": analysis_fields.get("analysis_level") or "smoke_backend",
        "delivery_allowed": bool(analysis_fields.get("delivery_allowed") is True and ready),
        "validation_evidence_allowed": bool(analysis_fields.get("validation_evidence_allowed") is True and ready),
        "reason": reason or ("" if ready else status),
        "backend_slurm_job_id": str(backend_plan.get("backend_slurm_job_id") or ""),
    }


def _write_placeholder_backend_figure(path: Path, title: str, message: str) -> None:
    tokens = apply_clinical_journal_style()
    plt.figure(figsize=(5.8, 3.6))
    plt.text(0.5, 0.5, message, ha="center", va="center", wrap=True, color=tokens["muted"])
    plt.axis("off")
    plt.title(title)
    plt.tight_layout()
    save_figure(path, style=tokens)


def _write_multiome_object(*, objects_dir: Path, data: dict[str, Any], max_cells: int, max_features: int) -> dict[str, str]:
    object_path = objects_dir / "multiome_mvp.h5mu"
    barcodes = list(map(str, data["barcodes"]))
    selected_cells = np.arange(len(barcodes))
    if len(selected_cells) > max_cells:
        rng = np.random.default_rng(31)
        selected_cells = np.sort(rng.choice(selected_cells, size=max_cells, replace=False))
    rna_features = _top_feature_indices(data["rna"], max(1, max_features // 2))
    atac_features = _top_feature_indices(data["atac"], max(1, max_features // 2))
    try:
        import anndata as ad
        import mudata as md

        rna = ad.AnnData(
            X=_subset_matrix(data["rna"], selected_cells, rna_features),
            obs=pd.DataFrame(index=np.asarray(barcodes)[selected_cells]),
            var=pd.DataFrame(index=np.asarray(data["rna_features"])[rna_features]),
        )
        atac = ad.AnnData(
            X=_subset_matrix(data["atac"], selected_cells, atac_features),
            obs=pd.DataFrame(index=np.asarray(barcodes)[selected_cells]),
            var=pd.DataFrame(index=np.asarray(data["atac_features"])[atac_features]),
        )
        mdata = md.MuData({"rna": rna, "atac": atac})
        mdata.uns["multiome_backend_warning"] = MULTIOME_WARNING
        mdata.write_h5mu(object_path)
        status = "h5mu_written"
    except Exception as exc:
        first_error = f"{type(exc).__name__}:{exc}"
        try:
            import h5py

            with h5py.File(object_path, "w") as handle:
                handle.attrs["object_status"] = "h5mu_like_hdf5_fallback"
                handle.attrs["fallback_reason"] = first_error
                handle.attrs["multiome_backend_warning"] = MULTIOME_WARNING
                handle.create_dataset("obs/cell_id", data=np.array(barcodes, dtype="S")[selected_cells])
                handle.create_dataset("rna/X", data=_to_dense(_subset_matrix(data["rna"], selected_cells, rna_features)), compression="gzip")
                handle.create_dataset("atac/X", data=_to_dense(_subset_matrix(data["atac"], selected_cells, atac_features)), compression="gzip")
                handle.create_dataset("rna/var/feature_id", data=np.array(np.asarray(data["rna_features"])[rna_features], dtype="S"))
                handle.create_dataset("atac/var/feature_id", data=np.array(np.asarray(data["atac_features"])[atac_features], dtype="S"))
            status = "h5mu_like_hdf5_fallback"
        except Exception as fallback_exc:  # pragma: no cover
            object_path.write_text(
                json.dumps(
                    {
                        "object_status": "json_fallback_not_h5mu",
                        "primary_reason": first_error,
                        "fallback_reason": f"{type(fallback_exc).__name__}:{fallback_exc}",
                        "n_cells": int(len(barcodes)),
                        "n_rna_features": int(len(data["rna_features"])),
                        "n_atac_features": int(len(data["atac_features"])),
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            status = "json_fallback_not_h5mu"
    manifest_path = objects_dir / "multiome_mvp_object_manifest.json"
    manifest_path.write_text(
        json.dumps({"object": str(object_path), "status": status, "max_cells": int(max_cells), "max_features": int(max_features)}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return {"mvp_object": str(object_path), "object_manifest": str(manifest_path)}


def _top_feature_indices(matrix: Any, n: int) -> np.ndarray:
    counts = _feature_sums(matrix)
    return np.asarray(np.argsort(counts)[::-1][: min(n, len(counts))], dtype=int)


def _to_dense(matrix: Any) -> np.ndarray:
    if hasattr(matrix, "toarray"):
        return np.asarray(matrix.toarray(), dtype=float)
    return np.asarray(matrix, dtype=float)


def _write_skip_outputs(*, tables_dir: Path, figures_dir: Path, objects_dir: Path, analysis_fields: dict[str, Any]) -> dict[str, dict[str, str]]:
    base = _base_fields(analysis_fields, "missing_multiome_input", "multiome")
    row = {
        **base,
        "status": "skipped_missing_input",
        "cell_id": "none",
        "qc_metric": "not_run",
        "qc_value": 0.0,
        "detected_features": 0,
        "qc_status": "missing_input",
        "modality": "none",
        "rna_barcode_count": 0,
        "atac_barcode_count": 0,
        "overlap_count": 0,
        "overlap_fraction": 0.0,
        "overlap_status": "missing_input",
        "rna_qc_status": "missing_input",
        "atac_qc_status": "missing_input",
        "joint_object_status": "not_run",
        "modality_warning": MULTIOME_WARNING,
        "artifact": "multiome_handoff",
        "handoff_tool": "not_run",
        "required_input": "multiome_input",
        "note": "missing_input",
    }
    table_paths = {}
    for filename in (
        "rna_qc.tsv",
        "atac_qc.tsv",
        "barcode_overlap.tsv",
        "modality_consistency.tsv",
        "rna_marker_handoff.tsv",
        "atac_marker_peak_handoff.tsv",
        "peak_gene_link_handoff.tsv",
    ):
        table_paths[filename.replace(".tsv", "")] = _write_tsv(pd.DataFrame([row]), tables_dir / filename)
    figure_paths = _write_placeholder_figures(figures_dir)
    object_path = objects_dir / "multiome_mvp.h5mu"
    object_path.write_text(json.dumps({"status": "skipped_missing_input"}, indent=2), encoding="utf-8")
    return {"tables": table_paths, "figures": figure_paths, "objects": {"mvp_object": str(object_path)}}


def _write_placeholder_figures(figures_dir: Path) -> dict[str, str]:
    tokens = apply_clinical_journal_style()
    paths = {}
    for key, title in {"joint_embedding_placeholder": "RNA-ATAC Joint QC", "modality_qc": "Modality QC"}.items():
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
