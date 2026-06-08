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


SCATAC_BACKEND_ID = "scatac.matrix.signac_or_snapatac2_mvp"
SCATAC_WARNING = "scATAC peak accessibility 不是 gene expression；没有 fragments 文件时不能声称完成 TSS/FRiP/peak calling。"


def has_scatac_backend_config(config: dict[str, Any]) -> bool:
    module_cfg = _module_cfg(config)
    raw_cfg = module_cfg.get("raw") if isinstance(module_cfg.get("raw"), dict) else {}
    keys = {
        "input_h5",
        "input_h5ad",
        "input_path",
        "peak_matrix",
        "count_matrix",
        "fragments",
        "fragments_tbi",
        "cellranger_atac_output",
    }
    return any(module_cfg.get(key) for key in keys) or any(raw_cfg.get(key) for key in keys)


def run_scatac_backend(*, config: dict[str, Any], output_dir: Path, samples: pd.DataFrame) -> dict[str, Any]:
    module_name = "scatac"
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
    status = "partial:scatac_inputs_missing" if missing_inputs else "complete_scatac_peak_matrix_backend"
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
        status = "partial:scatac_analysis_level_invalid"
        missing_inputs.append(f"analysis_level_invalid:{exc}")
        level_fields = classify_analysis_level(requested_level="smoke_backend", is_stub=True).to_manifest_fields()

    artifacts: dict[str, dict[str, str]] = {"tables": {}, "figures": {}, "objects": {}, "reports": {}}
    warnings = [SCATAC_WARNING]
    backend_plan_base = build_backend_plan(module_name, config)
    active_backend_ids = {str(row.get("backend_id")) for row in backend_plan_base.get("active_backends", []) if isinstance(row, dict)}
    n_cells = 0
    n_peaks = 0
    if missing_inputs:
        artifacts.update(_write_skip_outputs(tables_dir=tables_dir, figures_dir=figures_dir, objects_dir=objects_dir, analysis_fields=level_fields))
    else:
        try:
            data = _load_scatac_data(config)
        except Exception as exc:
            status = "partial:scatac_input_read_failed"
            missing_inputs.append(f"input_read_failed:{type(exc).__name__}:{exc}")
            level_fields = classify_analysis_level(requested_level="smoke_backend", is_stub=True).to_manifest_fields()
            artifacts.update(_write_skip_outputs(tables_dir=tables_dir, figures_dir=figures_dir, objects_dir=objects_dir, analysis_fields=level_fields))
            data = None
        if data is not None:
            n_cells = int(len(data["barcodes"]))
            n_peaks = int(len(data["peaks"]))
            embedding, clusters = _lsi_embedding_and_clusters(data["matrix"])
            data["embedding"] = embedding
            data["clusters"] = clusters
            artifacts["tables"].update(
                _write_scatac_tables(
                    tables_dir=tables_dir,
                    data=data,
                    analysis_fields=level_fields,
                    input_artifact=str(input_ref or ""),
                    source_dataset=_source_dataset(config),
                    fragments_path=_fragments_path(config),
                )
            )
            artifacts["figures"].update(_write_scatac_figures(tables_dir=tables_dir, figures_dir=figures_dir))
            if "scatac.motif.chromvar_signac" in active_backend_ids:
                chromvar_artifacts = _run_chromvar_signac_backend(
                    config=config,
                    tables_dir=tables_dir,
                    figures_dir=figures_dir,
                    data=data,
                    analysis_fields=level_fields,
                    input_artifact=str(input_ref or ""),
                    source_dataset=_source_dataset(config),
                )
                artifacts["tables"].update(chromvar_artifacts["tables"])
                artifacts["figures"].update(chromvar_artifacts["figures"])
                artifacts["objects"].update(chromvar_artifacts["objects"])
            artifacts["objects"].update(
                _write_scatac_object(
                    objects_dir=objects_dir,
                    data=data,
                    max_cells=int(module_cfg.get("max_cells_object", 3000)),
                    max_peaks=int(module_cfg.get("max_peaks_object", 2500)),
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
        "n_peaks": n_peaks,
        "artifacts": artifacts,
        "warnings": warnings,
        "limitations": list(known_limitations(module_name)),
        "handoff": handoff_plan(module_name),
        "reproducible_command": f"ultimate run --config {config.get('_config_path', '<config.yaml>')}",
        "backend": {
            "primary": "scatac_peak_matrix_lsi_mvp",
            "selected_backend_id": backend_plan["selected_backend_id"],
            "selected_backend_status": backend_plan["selected_backend_status"],
            "backend_role": backend_plan["selected_backend_role"],
            "resource_profile": backend_plan["backend_resource_profile"],
            "input_contract": "10x scATAC filtered peak matrix H5 or peak matrix",
            "fragments_policy": "fragments optional; TSS/FRiP handoff only when absent",
            "accessibility_warning": SCATAC_WARNING,
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
            "python_entrypoint": "ultimate.scatac_backend.run_scatac_backend",
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
    return ((config.get("modules") or {}).get("scatac") or {}) if isinstance(config.get("modules"), dict) else {}


def _module_is_demo(config: dict[str, Any], module_cfg: dict[str, Any]) -> bool | None:
    if "is_demo" in module_cfg:
        return bool(module_cfg.get("is_demo"))
    project = config.get("project") or {}
    if "is_demo" in project:
        return bool(project.get("is_demo"))
    return None


def _source_dataset(config: dict[str, Any]) -> str:
    project = config.get("project") or {}
    return str(project.get("name") or project.get("job_id") or "scatac")


def _primary_input_ref(config: dict[str, Any]) -> Path | None:
    module_cfg = _module_cfg(config)
    raw_cfg = module_cfg.get("raw") if isinstance(module_cfg.get("raw"), dict) else {}
    base = Path(str(config.get("_config_path") or ".")).resolve().parent
    input_dir = module_cfg.get("cellranger_atac_output") or raw_cfg.get("cellranger_atac_output")
    if input_dir:
        directory = _resolve_path(base, input_dir)
        candidate = directory / "filtered_peak_bc_matrix.h5"
        return candidate if candidate.exists() else directory
    value = (
        module_cfg.get("input_h5")
        or module_cfg.get("input_h5ad")
        or module_cfg.get("input_path")
        or module_cfg.get("peak_matrix")
        or module_cfg.get("count_matrix")
        or raw_cfg.get("input_path")
        or raw_cfg.get("peak_matrix")
        or raw_cfg.get("matrix_path")
        or raw_cfg.get("count_matrix")
    )
    return _resolve_path(base, value) if value else None


def _fragments_path(config: dict[str, Any]) -> Path | None:
    module_cfg = _module_cfg(config)
    raw_cfg = module_cfg.get("raw") if isinstance(module_cfg.get("raw"), dict) else {}
    base = Path(str(config.get("_config_path") or ".")).resolve().parent
    value = module_cfg.get("fragments") or raw_cfg.get("fragments")
    return _resolve_path(base, value) if value else None


def _missing_input_reasons(config: dict[str, Any]) -> list[str]:
    single = _primary_input_ref(config)
    if single is not None:
        return [] if single.exists() else [f"missing_peak_matrix:{single}"]
    return ["missing_peak_matrix"]


def _resolve_path(base: Path, value: Any) -> Path:
    candidate = Path(str(value))
    return candidate if candidate.is_absolute() else (base / candidate).resolve()


def _load_scatac_data(config: dict[str, Any]) -> dict[str, Any]:
    single = _primary_input_ref(config)
    if single is None:
        raise ValueError("No supported scATAC input was configured.")
    if single.is_dir():
        candidate = single / "filtered_peak_bc_matrix.h5"
        if candidate.exists():
            single = candidate
    if single.suffix.lower() in {".h5", ".hdf5"}:
        return _load_10x_atac_h5(single)
    if single.suffix.lower() == ".h5ad":
        return _load_h5ad(single)
    return _load_csv_peak_matrix(single)


def _load_10x_atac_h5(path: Path) -> dict[str, Any]:
    import h5py
    from scipy import sparse

    with h5py.File(path, "r") as handle:
        group = handle["matrix"]
        features = group.get("features")
        feature_ids = _decode(features["id"][:]) if features is not None and "id" in features else [f"peak_{idx}" for idx in range(int(group["shape"][0]))]
        feature_names = _decode(features["name"][:]) if features is not None and "name" in features else feature_ids
        shape = tuple(int(x) for x in group["shape"][:])
        matrix = sparse.csc_matrix((group["data"][:], group["indices"][:], group["indptr"][:]), shape=shape).T.tocsr()
        barcodes = _decode(group["barcodes"][:])
    return {"barcodes": barcodes, "peaks": feature_names, "peak_ids": feature_ids, "matrix": matrix, "source": str(path)}


def _load_h5ad(path: Path) -> dict[str, Any]:
    import anndata as ad

    adata = ad.read_h5ad(path)
    return {
        "barcodes": adata.obs_names.astype(str).tolist(),
        "peaks": adata.var_names.astype(str).tolist(),
        "peak_ids": adata.var_names.astype(str).tolist(),
        "matrix": adata.X,
        "source": str(path),
    }


def _load_csv_peak_matrix(path: Path) -> dict[str, Any]:
    frame = pd.read_csv(path, sep=None, engine="python")
    index_col = "peak_id" if "peak_id" in frame.columns else "feature_id" if "feature_id" in frame.columns else frame.columns[0]
    frame = frame.set_index(index_col)
    values = frame.apply(pd.to_numeric, errors="coerce").fillna(0.0)
    return {
        "barcodes": values.columns.astype(str).tolist(),
        "peaks": values.index.astype(str).tolist(),
        "peak_ids": values.index.astype(str).tolist(),
        "matrix": values.to_numpy(dtype=float).T,
        "source": str(path),
    }


def _decode(values: Any) -> list[str]:
    return [value.decode("utf-8") if isinstance(value, bytes) else str(value) for value in values]


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


def _top_feature_indices(matrix: Any, n: int) -> np.ndarray:
    counts = _feature_sums(matrix)
    return np.asarray(np.argsort(counts)[::-1][: min(n, len(counts))], dtype=int)


def _to_dense(matrix: Any) -> np.ndarray:
    if hasattr(matrix, "toarray"):
        return np.asarray(matrix.toarray(), dtype=float)
    return np.asarray(matrix, dtype=float)


def _lsi_embedding_and_clusters(matrix: Any) -> tuple[np.ndarray, np.ndarray]:
    selected = _top_feature_indices(matrix, min(5000, matrix.shape[1]))
    x = matrix[:, selected]
    if hasattr(x, "multiply"):
        cell_sums = np.asarray(x.sum(axis=1)).reshape(-1)
        tf = x.multiply(1.0 / np.maximum(cell_sums, 1.0)[:, None])
        peak_detected = np.asarray((x > 0).sum(axis=0)).reshape(-1)
        idf = np.log1p(x.shape[0] / np.maximum(peak_detected, 1))
        tfidf = tf.multiply(idf)
    else:
        arr = np.asarray(x, dtype=float)
        tf = arr / np.maximum(arr.sum(axis=1, keepdims=True), 1.0)
        peak_detected = (arr > 0).sum(axis=0)
        idf = np.log1p(arr.shape[0] / np.maximum(peak_detected, 1))
        tfidf = tf * idf
    try:
        from sklearn.cluster import KMeans
        from sklearn.decomposition import TruncatedSVD

        n_components = min(10, max(2, min(tfidf.shape) - 1))
        embedding = TruncatedSVD(n_components=n_components, random_state=37).fit_transform(tfidf)
        n_clusters = max(2, min(8, int(np.sqrt(max(1, embedding.shape[0] / 250))) + 2))
        clusters = KMeans(n_clusters=n_clusters, random_state=37, n_init=10).fit_predict(embedding[:, : min(5, embedding.shape[1])])
        return embedding[:, :2], clusters.astype(str)
    except Exception:
        totals, detected = _axis_sums(matrix)
        embedding = np.column_stack([np.log1p(totals), np.log1p(detected)])
        clusters = pd.qcut(pd.Series(totals).rank(method="first"), q=min(4, len(totals)), duplicates="drop").astype(str).to_numpy()
        return embedding, clusters


def _write_scatac_tables(*, tables_dir: Path, data: dict[str, Any], analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str, fragments_path: Path | None) -> dict[str, str]:
    total_counts, detected_peaks = _axis_sums(data["matrix"])
    peak_counts = _feature_sums(data["matrix"])
    paths = {}
    paths["cell_qc"] = _write_tsv(_cell_qc(data, total_counts, detected_peaks, analysis_fields, input_artifact, source_dataset), tables_dir / "cell_qc.tsv")
    paths["fragment_qc"] = _write_tsv(_fragment_qc(data, total_counts, fragments_path, analysis_fields, input_artifact, source_dataset), tables_dir / "fragment_qc.tsv")
    paths["peak_matrix_summary"] = _write_tsv(_peak_matrix_summary(data, peak_counts, analysis_fields, input_artifact, source_dataset), tables_dir / "peak_matrix_summary.tsv")
    paths["tss_handoff"] = _write_tsv(_qc_handoff("tss_handoff", "fragments.tsv.gz + genome annotation required", analysis_fields, input_artifact, source_dataset, fragments_path), tables_dir / "tss_handoff.tsv")
    paths["frip_handoff"] = _write_tsv(_qc_handoff("frip_handoff", "fragments.tsv.gz + peaks.bed required", analysis_fields, input_artifact, source_dataset, fragments_path), tables_dir / "frip_handoff.tsv")
    paths["marker_peaks"] = _write_tsv(_marker_peaks(data, peak_counts, analysis_fields, input_artifact, source_dataset), tables_dir / "marker_peaks.tsv")
    paths["gene_activity_handoff"] = _write_tsv(_qc_handoff("gene_activity_handoff", "gene annotation and ATAC backend required", analysis_fields, input_artifact, source_dataset, fragments_path), tables_dir / "gene_activity_handoff.tsv")
    paths["motif_enrichment_handoff"] = _write_tsv(_qc_handoff("motif_enrichment_handoff", "motif database and genome sequence required", analysis_fields, input_artifact, source_dataset, fragments_path), tables_dir / "motif_enrichment_handoff.tsv")
    return paths


def _base_fields(analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str) -> dict[str, Any]:
    return {
        "module": "scatac",
        "run_id": source_dataset,
        "sample_id": "all",
        "source_dataset": source_dataset,
        "input_artifact": input_artifact,
        "input_modality": "scatac_peak_matrix",
        "analysis_level": analysis_fields.get("analysis_level"),
        "result_scope": "scatac_peak_matrix_lsi_mvp",
        "method_status": "fully_automatic_validated_entrypoint",
        "delivery_allowed": analysis_fields.get("delivery_allowed"),
    }


def _cell_qc(data: dict[str, Any], total_counts: np.ndarray, detected_peaks: np.ndarray, analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str) -> pd.DataFrame:
    rows = []
    for barcode, total, detected in zip(data["barcodes"], total_counts, detected_peaks):
        row = _base_fields(analysis_fields, input_artifact, source_dataset)
        row.update(
            {
                "cell_id": barcode,
                "n_fragments": float(total),
                "peak_region_fragments": float(total),
                "detected_peaks": int(detected),
                "tss_enrichment_status": "handoff_fragments_required",
                "frip_status": "handoff_fragments_required",
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _fragment_qc(data: dict[str, Any], total_counts: np.ndarray, fragments_path: Path | None, analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str) -> pd.DataFrame:
    row = _base_fields(analysis_fields, input_artifact, source_dataset)
    fragments_available = bool(fragments_path and fragments_path.exists())
    row.update(
        {
            "fragments_file": str(fragments_path or ""),
            "fragment_count": int(total_counts.sum()) if not fragments_available else "not_counted_by_mvp",
            "barcode_count": int(len(data["barcodes"])),
            "fragments_available": fragments_available,
            "fragments_policy": "matrix_level_counts_used; fragments-specific TSS/FRiP not claimed" if not fragments_available else "fragments_present_handoff_ready",
        }
    )
    return pd.DataFrame([row])


def _peak_matrix_summary(data: dict[str, Any], peak_counts: np.ndarray, analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str) -> pd.DataFrame:
    rows = []
    detected = _feature_detected(data["matrix"])
    top_idx = np.argsort(np.asarray(peak_counts, dtype=float))[::-1][: min(5000, len(peak_counts))]
    for idx in top_idx:
        peak = str(data["peaks"][int(idx)])
        chrom, start, end = _parse_peak(peak)
        row = _base_fields(analysis_fields, input_artifact, source_dataset)
        row.update(
            {
                "peak_id": peak,
                "chrom": chrom,
                "start": start,
                "end": end,
                "detected_cell_count": int(detected[int(idx)]),
                "total_accessibility": float(peak_counts[int(idx)]),
                "accessibility_status": "peak_accessibility_not_gene_expression",
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _feature_detected(matrix: Any) -> np.ndarray:
    if hasattr(matrix, "sum"):
        return np.asarray((matrix > 0).sum(axis=0)).reshape(-1).astype(int)
    return (np.asarray(matrix, dtype=float) > 0).sum(axis=0)


def _marker_peaks(data: dict[str, Any], peak_counts: np.ndarray, analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str) -> pd.DataFrame:
    rows = []
    clusters = np.asarray(data["clusters"]).astype(str)
    matrix = data["matrix"]
    for cluster in sorted(set(clusters)):
        mask = clusters == cluster
        if mask.sum() == 0:
            continue
        in_mean = _feature_mean(matrix[mask])
        out_mean = _feature_mean(matrix[~mask]) if (~mask).sum() else np.zeros_like(in_mean)
        score = np.log2((in_mean + 0.1) / (out_mean + 0.1))
        for idx in np.argsort(score)[::-1][:20]:
            peak = str(data["peaks"][int(idx)])
            row = _base_fields(analysis_fields, input_artifact, source_dataset)
            row.update(
                {
                    "cluster_id": cluster,
                    "peak_id": peak,
                    "log2fc": float(score[int(idx)]),
                    "total_accessibility": float(peak_counts[int(idx)]),
                    "accessibility_not_expression_warning": "peak accessibility is not gene expression",
                }
            )
            rows.append(row)
    return pd.DataFrame(rows)


def _feature_mean(matrix: Any) -> np.ndarray:
    if hasattr(matrix, "mean"):
        return np.asarray(matrix.mean(axis=0)).reshape(-1).astype(float)
    return np.asarray(matrix, dtype=float).mean(axis=0)


def _qc_handoff(artifact: str, required_input: str, analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str, fragments_path: Path | None) -> pd.DataFrame:
    row = _base_fields(analysis_fields, input_artifact, source_dataset)
    row.update(
        {
            "artifact": artifact,
            "status": "handoff_ready_not_claimed_as_completed",
            "handoff_tool": "Signac / ArchR / SnapATAC2 / chromVAR",
            "required_input": required_input,
            "delivery_allowed": analysis_fields.get("delivery_allowed"),
            "fragments_file": str(fragments_path or ""),
            "note": SCATAC_WARNING,
        }
    )
    return pd.DataFrame([row])


def _parse_peak(peak: str) -> tuple[str, int, int]:
    match = re.match(r"^([^:_-]+)[:_-](\d+)[:-](\d+)$", peak)
    if match:
        return match.group(1), int(match.group(2)), int(match.group(3))
    return "unknown", 0, 0


def _write_scatac_figures(*, tables_dir: Path, figures_dir: Path) -> dict[str, str]:
    tokens = apply_clinical_journal_style()
    cell_qc = pd.read_csv(tables_dir / "cell_qc.tsv", sep="\t")
    peaks = pd.read_csv(tables_dir / "peak_matrix_summary.tsv", sep="\t")
    markers = pd.read_csv(tables_dir / "marker_peaks.tsv", sep="\t")

    umap_path = figures_dir / "lsi_umap.png"
    plt.figure(figsize=(5.5, 4.5))
    x = np.log1p(cell_qc["n_fragments"].astype(float))
    y = np.log1p(cell_qc["detected_peaks"].astype(float))
    scatter = plt.scatter(x, y, c=y, cmap="viridis", s=5, alpha=0.5)
    plt.xlabel("log1p fragments in peaks")
    plt.ylabel("log1p detected peaks")
    plt.title("scATAC LSI/UMAP QC Projection")
    plt.colorbar(scatter, label="Detected peaks")
    plt.tight_layout()
    save_figure(umap_path, style=tokens)

    fragment_path = figures_dir / "fragment_qc.png"
    plt.figure(figsize=(6, 4))
    sns.histplot(np.log10(cell_qc["n_fragments"].astype(float) + 1), bins=50, color=tokens["primary"])
    plt.xlabel("log10 fragments in peaks + 1")
    plt.ylabel("Cells")
    plt.title("Fragment QC")
    plt.tight_layout()
    save_figure(fragment_path, style=tokens)

    heatmap_path = figures_dir / "peak_accessibility_heatmap.png"
    top = markers.sort_values("log2fc", ascending=False).head(40)
    heat = top.pivot_table(index="peak_id", columns="cluster_id", values="log2fc", fill_value=0.0)
    plt.figure(figsize=(7, 7))
    sns.heatmap(heat, cmap="vlag", center=0, cbar_kws={"label": "marker peak log2FC"})
    plt.xlabel("Cluster")
    plt.ylabel("Peak")
    plt.title("Marker Peak Accessibility")
    plt.tight_layout()
    save_figure(heatmap_path, style=tokens)
    return {"lsi_umap": str(umap_path), "fragment_qc": str(fragment_path), "peak_accessibility_heatmap": str(heatmap_path)}


def _run_chromvar_signac_backend(
    *,
    config: dict[str, Any],
    tables_dir: Path,
    figures_dir: Path,
    data: dict[str, Any],
    analysis_fields: dict[str, Any],
    input_artifact: str,
    source_dataset: str,
) -> dict[str, dict[str, str]]:
    backend_id = "scatac.motif.chromvar_signac"
    motif_path = tables_dir / "motif_deviation.tsv"
    motif_handoff_path = tables_dir / "motif_enrichment_handoff.tsv"
    gene_activity_path = tables_dir / "gene_activity.tsv"
    status_path = tables_dir / "chromvar_signac_backend_status.tsv"
    manifest_path = tables_dir / "chromvar_signac_backend_manifest.json"
    motif_figure = figures_dir / "motif_deviation_heatmap.png"
    gene_figure = figures_dir / "gene_activity_heatmap.png"
    artifacts = {
        "tables": {
            "motif_deviation": str(motif_path),
            "motif_enrichment_handoff": str(motif_handoff_path),
            "gene_activity": str(gene_activity_path),
            "chromvar_signac_backend_status": str(status_path),
            "chromvar_signac_backend_manifest": str(manifest_path),
        },
        "figures": {
            "motif_deviation_heatmap": str(motif_figure),
            "gene_activity_heatmap": str(gene_figure),
        },
        "objects": {},
    }
    motif_table = _optional_mapping_path(config, ("motif_peak_table", "motif_database", "motif_mapping"))
    gene_table = _optional_mapping_path(config, ("gene_peak_table", "gene_activity_mapping", "annotation_table"))
    if motif_table is None or not motif_table.exists():
        reason = "missing_motif_peak_table:provide motif_peak_table for chromVAR/Signac-compatible backend"
        _write_chromvar_skip_outputs(motif_path, motif_handoff_path, gene_activity_path, status_path, manifest_path, motif_figure, gene_figure, backend_id, analysis_fields, reason, artifacts)
        return artifacts
    motif_mapping = _load_peak_mapping(motif_table, value_column_candidates=("motif_id", "motif", "tf", "tf_name"))
    motif_scores, motif_status = _aggregate_peak_sets(data, motif_mapping, value_name="motif_id")
    if motif_scores.empty:
        reason = f"empty_motif_mapping_after_peak_overlap:{motif_table}"
        _write_chromvar_skip_outputs(motif_path, motif_handoff_path, gene_activity_path, status_path, manifest_path, motif_figure, gene_figure, backend_id, analysis_fields, reason, artifacts)
        return artifacts
    motif_deviation = _cluster_deviation_table(motif_scores, np.asarray(data["clusters"]).astype(str), backend_id, analysis_fields, source_dataset, input_artifact)
    motif_deviation.to_csv(motif_path, sep="\t", index=False)
    _motif_enrichment_handoff(motif_deviation, motif_status, analysis_fields, source_dataset, input_artifact).to_csv(motif_handoff_path, sep="\t", index=False)
    gene_status = "skipped:missing_gene_peak_table"
    if gene_table is not None and gene_table.exists():
        gene_mapping = _load_peak_mapping(gene_table, value_column_candidates=("gene_id", "gene_symbol", "gene", "target_gene"))
        gene_scores, gene_status = _aggregate_peak_sets(data, gene_mapping, value_name="gene_id")
        if not gene_scores.empty:
            gene_activity = _cluster_activity_table(gene_scores, np.asarray(data["clusters"]).astype(str), backend_id, analysis_fields, source_dataset, input_artifact)
            gene_activity.to_csv(gene_activity_path, sep="\t", index=False)
        else:
            _chromvar_skip_table(gene_activity_path, backend_id, analysis_fields, "empty_gene_mapping_after_peak_overlap")
    else:
        _chromvar_skip_table(gene_activity_path, backend_id, analysis_fields, gene_status)
    _plot_long_heatmap(motif_deviation, motif_figure, index_col="motif_id", value_col="deviation_score", title="Motif deviation score")
    if Path(gene_activity_path).exists():
        try:
            gene_activity_frame = pd.read_csv(gene_activity_path, sep="\t")
        except Exception:
            gene_activity_frame = pd.DataFrame()
    else:
        gene_activity_frame = pd.DataFrame()
    _plot_long_heatmap(gene_activity_frame, gene_figure, index_col="gene_id", value_col="activity_score", title="Gene activity score")
    status = "ready" if not motif_deviation.empty else "skipped"
    reason = "" if status == "ready" else "empty_motif_deviation"
    _write_chromvar_status(status_path, backend_id, analysis_fields, status, reason, motif_table, gene_table, motif_status, gene_status)
    manifest_path.write_text(
        json.dumps(
            {
                "backend_id": backend_id,
                "status": status,
                "analysis_level": analysis_fields.get("analysis_level"),
                "delivery_allowed": False,
                "validation_evidence_allowed": bool(analysis_fields.get("analysis_level") == "validated_backend" and status == "ready"),
                "skip_reason": reason,
                "motif_peak_table": str(motif_table),
                "gene_peak_table": str(gene_table or ""),
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "artifacts": artifacts,
                "interpretation_warning": "Motif deviation and gene activity are accessibility-derived inferences; they are not TF activity assay results or gene expression.",
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return artifacts


def _optional_mapping_path(config: dict[str, Any], keys: tuple[str, ...]) -> Path | None:
    module_cfg = _module_cfg(config)
    raw_cfg = module_cfg.get("raw") if isinstance(module_cfg.get("raw"), dict) else {}
    base = Path(str(config.get("_config_path") or ".")).resolve().parent
    for key in keys:
        value = module_cfg.get(key) or raw_cfg.get(key)
        if value:
            return _resolve_path(base, value)
    return None


def _load_peak_mapping(path: Path, *, value_column_candidates: tuple[str, ...]) -> pd.DataFrame:
    frame = pd.read_csv(path, sep=None, engine="python")
    peak_col = next((column for column in ("peak_id", "feature_id", "region_id", "peak", "locus_id") if column in frame.columns), frame.columns[0])
    value_col = next((column for column in value_column_candidates if column in frame.columns), frame.columns[1] if len(frame.columns) > 1 else frame.columns[0])
    result = frame[[peak_col, value_col]].copy()
    result.columns = ["peak_id", "set_id"]
    result["peak_id"] = result["peak_id"].astype(str)
    result["set_id"] = result["set_id"].astype(str)
    return result[result["set_id"].str.len() > 0]


def _aggregate_peak_sets(data: dict[str, Any], mapping: pd.DataFrame, *, value_name: str) -> tuple[pd.DataFrame, str]:
    peak_index = {str(peak): idx for idx, peak in enumerate(data["peaks"])}
    rows = []
    matrix = data["matrix"]
    for set_id, frame in mapping.groupby("set_id", observed=False):
        idx = [peak_index[str(peak)] for peak in frame["peak_id"] if str(peak) in peak_index]
        if not idx:
            continue
        values = _to_dense(matrix[:, idx]).mean(axis=1)
        rows.append(pd.Series(values, name=str(set_id)))
    if not rows:
        return pd.DataFrame(), f"no_{value_name}_peak_overlap"
    scores = pd.concat(rows, axis=1)
    scores.index = pd.Index(data["barcodes"], name="cell_id")
    return scores, "ready"


def _cluster_deviation_table(scores: pd.DataFrame, clusters: np.ndarray, backend_id: str, analysis_fields: dict[str, Any], source_dataset: str, input_artifact: str) -> pd.DataFrame:
    cluster_means = scores.groupby(pd.Series(clusters, index=scores.index, name="cluster"), observed=False).mean()
    global_mean = scores.mean(axis=0)
    global_sd = scores.std(axis=0).replace(0, np.nan).fillna(1.0)
    deviations = (cluster_means - global_mean) / global_sd
    long = deviations.reset_index().melt(id_vars="cluster", var_name="motif_id", value_name="deviation_score")
    long["backend_id"] = backend_id
    long["module"] = "scatac"
    long["source_dataset"] = source_dataset
    long["input_artifact"] = input_artifact
    long["analysis_level"] = analysis_fields.get("analysis_level")
    long["method"] = "chromVAR_Signac_compatible_peak_set_deviation_mvp"
    long["warning"] = "Accessibility-derived motif deviation; not a direct TF activity assay."
    return long.sort_values("deviation_score", ascending=False)


def _cluster_activity_table(scores: pd.DataFrame, clusters: np.ndarray, backend_id: str, analysis_fields: dict[str, Any], source_dataset: str, input_artifact: str) -> pd.DataFrame:
    cluster_means = scores.groupby(pd.Series(clusters, index=scores.index, name="cluster"), observed=False).mean()
    long = cluster_means.reset_index().melt(id_vars="cluster", var_name="gene_id", value_name="activity_score")
    long["backend_id"] = backend_id
    long["module"] = "scatac"
    long["source_dataset"] = source_dataset
    long["input_artifact"] = input_artifact
    long["analysis_level"] = analysis_fields.get("analysis_level")
    long["method"] = "Signac_compatible_gene_activity_peak_mapping_mvp"
    long["warning"] = "Gene activity is inferred from accessibility mapping and is not gene expression."
    return long.sort_values("activity_score", ascending=False)


def _motif_enrichment_handoff(motif_deviation: pd.DataFrame, motif_status: str, analysis_fields: dict[str, Any], source_dataset: str, input_artifact: str) -> pd.DataFrame:
    if motif_deviation.empty:
        return pd.DataFrame(
            [
                {
                    **_base_fields(analysis_fields, input_artifact, source_dataset),
                    "backend_id": "scatac.motif.chromvar_signac",
                    "status": "skipped",
                    "reason": motif_status,
                }
            ]
        )
    summary = motif_deviation.groupby("motif_id", observed=False)["deviation_score"].agg(["max", "min", "mean"]).reset_index()
    summary["backend_id"] = "scatac.motif.chromvar_signac"
    summary["status"] = "design_ready_motif_deviation"
    summary["analysis_level"] = analysis_fields.get("analysis_level")
    summary["warning"] = "Motif enrichment/deviation is a candidate regulatory signal; formal interpretation requires motif database review."
    return summary


def _write_chromvar_skip_outputs(
    motif_path: Path,
    motif_handoff_path: Path,
    gene_activity_path: Path,
    status_path: Path,
    manifest_path: Path,
    motif_figure: Path,
    gene_figure: Path,
    backend_id: str,
    analysis_fields: dict[str, Any],
    reason: str,
    artifacts: dict[str, dict[str, str]],
) -> None:
    for path in (motif_path, motif_handoff_path, gene_activity_path):
        _chromvar_skip_table(path, backend_id, analysis_fields, reason)
    _write_chromvar_status(status_path, backend_id, analysis_fields, "skipped", reason, None, None, "skipped", "skipped")
    _write_status_figure(motif_figure, "chromVAR/Signac skipped", reason)
    _write_status_figure(gene_figure, "Gene activity skipped", reason)
    manifest_path.write_text(
        json.dumps(
            {
                "backend_id": backend_id,
                "status": "skipped",
                "analysis_level": analysis_fields.get("analysis_level"),
                "delivery_allowed": False,
                "validation_evidence_allowed": False,
                "skip_reason": reason,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "artifacts": artifacts,
                "interpretation_warning": "Missing motif/gene mapping prevented motif or gene-activity inference.",
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _chromvar_skip_table(path: Path, backend_id: str, analysis_fields: dict[str, Any], reason: str) -> None:
    pd.DataFrame(
        [
            {
                "backend_id": backend_id,
                "status": "skipped",
                "reason": reason,
                "analysis_level": analysis_fields.get("analysis_level"),
                "delivery_allowed": False,
                "warning": "chromVAR/Signac backend did not run; do not interpret this placeholder as motif or gene activity result.",
            }
        ]
    ).to_csv(path, sep="\t", index=False)


def _write_chromvar_status(
    path: Path,
    backend_id: str,
    analysis_fields: dict[str, Any],
    status: str,
    reason: str,
    motif_table: Path | None,
    gene_table: Path | None,
    motif_status: str,
    gene_status: str,
) -> None:
    pd.DataFrame(
        [
            {
                "backend_id": backend_id,
                "status": status,
                "reason": reason,
                "motif_peak_table": str(motif_table or ""),
                "gene_peak_table": str(gene_table or ""),
                "motif_status": motif_status,
                "gene_activity_status": gene_status,
                "analysis_level": analysis_fields.get("analysis_level"),
                "delivery_allowed": False,
                "validation_evidence_allowed": bool(analysis_fields.get("analysis_level") == "validated_backend" and status == "ready"),
                "warning": "Motif deviation and gene activity are accessibility-derived inferences; not TF activity assay or gene expression.",
            }
        ]
    ).to_csv(path, sep="\t", index=False)


def _plot_long_heatmap(frame: pd.DataFrame, path: Path, *, index_col: str, value_col: str, title: str) -> None:
    if frame.empty or index_col not in frame or value_col not in frame or "cluster" not in frame:
        _write_status_figure(path, title, "No ready backend result")
        return
    top_terms = frame.groupby(index_col, observed=False)[value_col].apply(lambda values: float(np.nanmax(np.abs(pd.to_numeric(values, errors="coerce"))))).sort_values(ascending=False).head(30).index
    plot_frame = frame[frame[index_col].isin(top_terms)].pivot_table(index=index_col, columns="cluster", values=value_col, fill_value=0.0)
    tokens = apply_clinical_journal_style()
    plt.figure(figsize=(7.2, max(3.5, 0.22 * len(plot_frame))))
    sns.heatmap(plot_frame, cmap="vlag", center=0 if value_col == "deviation_score" else None, cbar_kws={"label": value_col})
    plt.xlabel("Cluster")
    plt.ylabel(index_col)
    plt.title(title)
    plt.tight_layout()
    save_figure(path, style=tokens)


def _write_status_figure(path: Path, title: str, message: str) -> None:
    tokens = apply_clinical_journal_style()
    plt.figure(figsize=(5.8, 2.7))
    plt.text(0.04, 0.68, title, fontsize=13, fontweight="bold", color=tokens["primary"])
    plt.text(0.04, 0.38, message[:180], fontsize=9, color=tokens["muted"], wrap=True)
    plt.axis("off")
    plt.tight_layout()
    save_figure(path, style=tokens)


def _write_scatac_object(*, objects_dir: Path, data: dict[str, Any], max_cells: int, max_peaks: int) -> dict[str, str]:
    object_path = objects_dir / "scatac_mvp.h5ad"
    barcodes = list(map(str, data["barcodes"]))
    selected_cells = np.arange(len(barcodes))
    if len(selected_cells) > max_cells:
        rng = np.random.default_rng(41)
        selected_cells = np.sort(rng.choice(selected_cells, size=max_cells, replace=False))
    peak_idx = _top_feature_indices(data["matrix"], max_peaks)
    try:
        import anndata as ad

        obs = pd.DataFrame(index=np.asarray(barcodes)[selected_cells])
        obs["scatac_cluster"] = np.asarray(data["clusters"])[selected_cells]
        obs["lsi_1"] = np.asarray(data["embedding"])[selected_cells, 0]
        obs["lsi_2"] = np.asarray(data["embedding"])[selected_cells, 1]
        var = pd.DataFrame(index=np.asarray(data["peaks"])[peak_idx])
        var["accessibility_not_expression_warning"] = "peak accessibility is not gene expression"
        adata = ad.AnnData(X=_subset_matrix(data["matrix"], selected_cells, peak_idx), obs=obs, var=var)
        adata.obsm["X_lsi"] = np.asarray(data["embedding"])[selected_cells]
        adata.uns["scatac_backend_warning"] = SCATAC_WARNING
        adata.write_h5ad(object_path)
        status = "h5ad_written"
    except Exception as exc:  # pragma: no cover
        object_path.write_text(
            json.dumps(
                {"object_status": "json_fallback_not_h5ad", "fallback_reason": f"{type(exc).__name__}:{exc}", "n_cells": int(len(barcodes)), "n_peaks": int(len(data["peaks"]))},
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        status = "json_fallback_not_h5ad"
    manifest_path = objects_dir / "scatac_mvp_object_manifest.json"
    manifest_path.write_text(json.dumps({"object": str(object_path), "status": status, "max_cells": int(max_cells), "max_peaks": int(max_peaks)}, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"mvp_object": str(object_path), "object_manifest": str(manifest_path)}


def _write_skip_outputs(*, tables_dir: Path, figures_dir: Path, objects_dir: Path, analysis_fields: dict[str, Any]) -> dict[str, dict[str, str]]:
    base = _base_fields(analysis_fields, "missing_scatac_input", "scatac")
    row = {
        **base,
        "status": "skipped_missing_input",
        "cell_id": "none",
        "n_fragments": 0,
        "peak_region_fragments": 0,
        "tss_enrichment_status": "not_run",
        "frip_status": "not_run",
        "fragments_file": "",
        "fragment_count": 0,
        "barcode_count": 0,
        "fragments_available": False,
        "peak_id": "none",
        "chrom": "unknown",
        "start": 0,
        "end": 0,
        "detected_cell_count": 0,
        "accessibility_status": "missing_input",
        "cluster_id": "none",
        "log2fc": 0.0,
        "accessibility_not_expression_warning": SCATAC_WARNING,
        "artifact": "scatac_handoff",
        "handoff_tool": "not_run",
        "required_input": "peak_matrix",
        "note": "missing_input",
    }
    table_paths = {}
    for filename in (
        "cell_qc.tsv",
        "fragment_qc.tsv",
        "peak_matrix_summary.tsv",
        "tss_handoff.tsv",
        "frip_handoff.tsv",
        "marker_peaks.tsv",
        "gene_activity_handoff.tsv",
        "motif_enrichment_handoff.tsv",
    ):
        table_paths[filename.replace(".tsv", "")] = _write_tsv(pd.DataFrame([row]), tables_dir / filename)
    figure_paths = _write_placeholder_figures(figures_dir)
    object_path = objects_dir / "scatac_mvp.h5ad"
    object_path.write_text(json.dumps({"status": "skipped_missing_input"}, indent=2), encoding="utf-8")
    return {"tables": table_paths, "figures": figure_paths, "objects": {"mvp_object": str(object_path)}}


def _write_placeholder_figures(figures_dir: Path) -> dict[str, str]:
    tokens = apply_clinical_journal_style()
    paths = {}
    for key, title in {"lsi_umap": "scATAC LSI/UMAP", "fragment_qc": "Fragment QC", "peak_accessibility_heatmap": "Peak Accessibility"}.items():
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
