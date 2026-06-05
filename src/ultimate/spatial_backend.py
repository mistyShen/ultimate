from __future__ import annotations

import json
import os
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


SPATIAL_BACKEND_ID = "spatial.visium.squidpy_mvp"
SPATIAL_WARNING = "Visium spot 不是单细胞；空间 domain、邻域和通讯/解卷积结果均为统计推断，不能写成实验证明。"


def has_spatial_backend_config(config: dict[str, Any]) -> bool:
    module_cfg = _module_cfg(config)
    raw_cfg = module_cfg.get("raw") if isinstance(module_cfg.get("raw"), dict) else {}
    keys = {
        "input_h5ad",
        "input_path",
        "spaceranger_output",
        "visium_dir",
        "coordinates",
        "coordinate_table",
        "expression_matrix",
        "count_matrix",
        "public_dataset",
        "validation_dataset",
    }
    return any(module_cfg.get(key) for key in keys) or any(raw_cfg.get(key) for key in keys)


def run_spatial_backend(*, config: dict[str, Any], output_dir: Path, samples: pd.DataFrame) -> dict[str, Any]:
    module_name = "spatial"
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
    status = "partial:spatial_inputs_missing" if missing_inputs else "complete_spatial_visium_backend"
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
        status = "partial:spatial_analysis_level_invalid"
        missing_inputs.append(f"analysis_level_invalid:{exc}")
        level_fields = classify_analysis_level(requested_level="smoke_backend", is_stub=True).to_manifest_fields()

    artifacts: dict[str, dict[str, str]] = {"tables": {}, "figures": {}, "objects": {}, "reports": {}}
    warnings = [SPATIAL_WARNING]
    n_spots = 0
    n_genes = 0
    n_domains = 0
    if missing_inputs:
        artifacts.update(_write_skip_outputs(tables_dir=tables_dir, figures_dir=figures_dir, objects_dir=objects_dir, analysis_fields=level_fields))
    else:
        try:
            data = _load_spatial_data(config)
        except Exception as exc:
            status = "partial:spatial_input_read_failed"
            missing_inputs.append(f"input_read_failed:{type(exc).__name__}:{exc}")
            level_fields = classify_analysis_level(requested_level="smoke_backend", is_stub=True).to_manifest_fields()
            artifacts.update(_write_skip_outputs(tables_dir=tables_dir, figures_dir=figures_dir, objects_dir=objects_dir, analysis_fields=level_fields))
            data = None
        if data is not None:
            n_spots = int(len(data["spots"]))
            n_genes = int(len(data["features"]))
            data["domains"] = _domain_labels(data)
            n_domains = int(pd.Series(data["domains"]).nunique())
            artifacts["tables"].update(
                _write_spatial_tables(
                    tables_dir=tables_dir,
                    data=data,
                    analysis_fields=level_fields,
                    input_artifact=str(input_ref or data.get("source", "")),
                    source_dataset=_source_dataset(config),
                )
            )
            artifacts["figures"].update(_write_spatial_figures(tables_dir=tables_dir, figures_dir=figures_dir))
            artifacts["objects"].update(_write_spatial_object(objects_dir=objects_dir, data=data, max_spots=int(module_cfg.get("max_spots_object", 3000))))

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
        "n_spots": n_spots,
        "n_genes": n_genes,
        "n_domains": n_domains,
        "artifacts": artifacts,
        "warnings": warnings,
        "limitations": list(known_limitations(module_name)),
        "handoff": handoff_plan(module_name),
        "reproducible_command": f"ultimate run --config {config.get('_config_path', '<config.yaml>')}",
        "backend": {
            "primary": "spatial_visium_squidpy_mvp",
            "selected_backend_id": backend_plan["selected_backend_id"],
            "selected_backend_status": backend_plan["selected_backend_status"],
            "backend_role": backend_plan["selected_backend_role"],
            "resource_profile": backend_plan["backend_resource_profile"],
            "input_contract": "Visium h5ad / coordinate+matrix / Squidpy public Visium dataset",
            "spatial_interpretation_warning": SPATIAL_WARNING,
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
            "python_entrypoint": "ultimate.spatial_backend.run_spatial_backend",
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
    return ((config.get("modules") or {}).get("spatial") or {}) if isinstance(config.get("modules"), dict) else {}


def _module_is_demo(config: dict[str, Any], module_cfg: dict[str, Any]) -> bool | None:
    if "is_demo" in module_cfg:
        return bool(module_cfg.get("is_demo"))
    project = config.get("project") or {}
    if "is_demo" in project:
        return bool(project.get("is_demo"))
    return None


def _source_dataset(config: dict[str, Any]) -> str:
    project = config.get("project") or {}
    return str(project.get("name") or project.get("job_id") or "spatial")


def _primary_input_ref(config: dict[str, Any]) -> Path | None:
    module_cfg = _module_cfg(config)
    raw_cfg = module_cfg.get("raw") if isinstance(module_cfg.get("raw"), dict) else {}
    base = Path(str(config.get("_config_path") or ".")).resolve().parent
    value = (
        module_cfg.get("input_h5ad")
        or module_cfg.get("input_path")
        or module_cfg.get("spaceranger_output")
        or module_cfg.get("visium_dir")
        or module_cfg.get("expression_matrix")
        or module_cfg.get("count_matrix")
        or raw_cfg.get("input_path")
        or raw_cfg.get("matrix_path")
        or raw_cfg.get("count_matrix")
    )
    return _resolve_path(base, value) if value else None


def _missing_input_reasons(config: dict[str, Any]) -> list[str]:
    module_cfg = _module_cfg(config)
    raw_cfg = module_cfg.get("raw") if isinstance(module_cfg.get("raw"), dict) else {}
    if module_cfg.get("public_dataset") or module_cfg.get("validation_dataset"):
        return []
    base = Path(str(config.get("_config_path") or ".")).resolve().parent
    single = _primary_input_ref(config)
    coordinates = module_cfg.get("coordinates") or module_cfg.get("coordinate_table") or raw_cfg.get("coordinates")
    matrix = module_cfg.get("expression_matrix") or module_cfg.get("count_matrix") or raw_cfg.get("count_matrix")
    if single is not None and single.suffix.lower() == ".h5ad":
        return [] if single.exists() else [f"missing_input_h5ad:{single}"]
    if coordinates or matrix:
        reasons = []
        if not coordinates:
            reasons.append("missing_coordinate_table")
        elif not _resolve_path(base, coordinates).exists():
            reasons.append(f"missing_coordinate_table:{_resolve_path(base, coordinates)}")
        if not matrix:
            reasons.append("missing_expression_matrix")
        elif not _resolve_path(base, matrix).exists():
            reasons.append(f"missing_expression_matrix:{_resolve_path(base, matrix)}")
        return reasons
    return ["missing_spatial_input"]


def _resolve_path(base: Path, value: Any) -> Path:
    candidate = Path(str(value))
    return candidate if candidate.is_absolute() else (base / candidate).resolve()


def _load_spatial_data(config: dict[str, Any]) -> dict[str, Any]:
    module_cfg = _module_cfg(config)
    raw_cfg = module_cfg.get("raw") if isinstance(module_cfg.get("raw"), dict) else {}
    base = Path(str(config.get("_config_path") or ".")).resolve().parent
    if module_cfg.get("public_dataset") or module_cfg.get("validation_dataset"):
        return _load_public_visium(config)
    single = _primary_input_ref(config)
    if single is not None and single.suffix.lower() == ".h5ad":
        return _load_h5ad(single)
    coordinates = module_cfg.get("coordinates") or module_cfg.get("coordinate_table") or raw_cfg.get("coordinates")
    matrix = module_cfg.get("expression_matrix") or module_cfg.get("count_matrix") or raw_cfg.get("count_matrix")
    if coordinates and matrix:
        return _load_matrix_and_coordinates(_resolve_path(base, matrix), _resolve_path(base, coordinates))
    raise ValueError("No supported spatial input was configured.")


def _load_public_visium(config: dict[str, Any]) -> dict[str, Any]:
    module_cfg = _module_cfg(config)
    public_dir = Path(str(module_cfg.get("public_data_dir") or "/shared/shen/2026/ultimate/public_data/spatial"))
    cache_dir = public_dir / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("XDG_CACHE_HOME", str(cache_dir / "xdg"))
    os.environ.setdefault("POOCH_HOME", str(cache_dir / "pooch"))
    import squidpy as sq

    adata_path = cache_dir / "anndata" / "visium_hne_adata.h5ad"
    adata = sq.datasets.visium_hne_adata(path=adata_path)
    adata.var_names_make_unique()
    data = _data_from_anndata(adata, source="squidpy.datasets.visium_hne_adata")
    data["adata"] = adata
    return data


def _load_h5ad(path: Path) -> dict[str, Any]:
    import anndata as ad

    adata = ad.read_h5ad(path)
    data = _data_from_anndata(adata, source=str(path))
    data["adata"] = adata
    return data


def _data_from_anndata(adata, *, source: str) -> dict[str, Any]:
    if "spatial" not in adata.obsm:
        raise ValueError("Input AnnData does not contain obsm['spatial'].")
    matrix = _to_dense(adata.X)
    coords = np.asarray(adata.obsm["spatial"], dtype=float)
    if matrix.ndim != 2:
        raise ValueError("Spatial expression matrix must be two-dimensional.")
    obs = adata.obs.copy()
    if "total_counts" not in obs.columns:
        obs["total_counts"] = np.asarray(matrix.sum(axis=1)).reshape(-1)
    if "n_genes_by_counts" not in obs.columns:
        obs["n_genes_by_counts"] = np.asarray((matrix > 0).sum(axis=1)).reshape(-1)
    if "in_tissue" not in obs.columns:
        obs["in_tissue"] = 1
    return {
        "spots": adata.obs_names.astype(str).tolist(),
        "features": adata.var_names.astype(str).tolist(),
        "matrix": np.asarray(matrix, dtype=float),
        "coords": coords,
        "obs": obs,
        "source": source,
        "image_status": "spatial_image_available" if isinstance(adata.uns.get("spatial"), dict) and adata.uns.get("spatial") else "image_not_required_for_mvp_or_not_provided",
    }


def _load_matrix_and_coordinates(matrix_path: Path, coordinates_path: Path) -> dict[str, Any]:
    matrix = _read_feature_matrix(matrix_path)
    coords = pd.read_csv(coordinates_path, sep=None, engine="python")
    spot_col = _first_existing(coords, ("spot_id", "barcode", "cell_id", coords.columns[0]))
    x_col = _first_existing(coords, ("pxl_col", "x", "imagecol", "array_col", "col"))
    y_col = _first_existing(coords, ("pxl_row", "y", "imagerow", "array_row", "row"))
    if not spot_col or not x_col or not y_col:
        raise ValueError("Coordinate table must include spot_id/barcode and x/y or pxl_col/pxl_row columns.")
    coords = coords.set_index(spot_col)
    shared = [spot for spot in matrix.columns.astype(str) if spot in set(coords.index.astype(str))]
    if not shared:
        raise ValueError("Expression matrix and coordinates have no shared spot barcodes.")
    selected_coords = coords.loc[shared]
    values = matrix[shared].to_numpy(dtype=float).T
    obs = pd.DataFrame(index=shared)
    obs["total_counts"] = values.sum(axis=1)
    obs["n_genes_by_counts"] = (values > 0).sum(axis=1)
    obs["in_tissue"] = selected_coords.get("in_tissue", pd.Series(1, index=selected_coords.index)).to_numpy()
    for column in ("array_row", "array_col", "pxl_row", "pxl_col", "cluster", "domain", "region"):
        if column in selected_coords.columns:
            obs[column] = selected_coords[column].to_numpy()
    return {
        "spots": shared,
        "features": matrix.index.astype(str).tolist(),
        "matrix": values,
        "coords": selected_coords[[x_col, y_col]].to_numpy(dtype=float),
        "obs": obs,
        "source": f"{matrix_path}|{coordinates_path}",
        "image_status": "image_not_required_for_mvp_or_not_provided",
    }


def _read_feature_matrix(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, sep=None, engine="python")
    index_col = "feature_id" if "feature_id" in frame.columns else frame.columns[0]
    frame = frame.set_index(index_col)
    return frame.apply(pd.to_numeric, errors="coerce").fillna(0.0)


def _to_dense(matrix: Any) -> np.ndarray:
    if hasattr(matrix, "toarray"):
        return np.asarray(matrix.toarray(), dtype=float)
    return np.asarray(matrix, dtype=float)


def _first_existing(frame: pd.DataFrame, columns: tuple[Any, ...]) -> str | None:
    for column in columns:
        if column in frame.columns:
            return str(column)
    return None


def _domain_labels(data: dict[str, Any]) -> np.ndarray:
    obs = data["obs"]
    for column in ("cluster", "clusters", "leiden", "domain", "region", "annotation"):
        if column in obs.columns:
            return obs[column].astype(str).to_numpy()
    coords = np.asarray(data["coords"], dtype=float)
    n_domains = max(2, min(8, int(np.sqrt(max(1, coords.shape[0] / 200))) + 2))
    if coords.shape[0] < n_domains:
        return np.array(["domain_0"] * coords.shape[0])
    try:
        from sklearn.cluster import KMeans

        labels = KMeans(n_clusters=n_domains, random_state=23, n_init=10).fit_predict(coords)
        return np.array([f"domain_{label}" for label in labels])
    except Exception:
        x_group = coords[:, 0] > np.median(coords[:, 0])
        y_group = coords[:, 1] > np.median(coords[:, 1])
        labels = x_group.astype(int) * 2 + y_group.astype(int)
        return np.array([f"domain_{label}" for label in labels])


def _write_spatial_tables(*, tables_dir: Path, data: dict[str, Any], analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str) -> dict[str, str]:
    paths = {}
    paths["spatial_qc"] = _write_tsv(_spatial_qc(data, analysis_fields, input_artifact, source_dataset), tables_dir / "spatial_qc.tsv")
    paths["spot_metadata"] = _write_tsv(_spot_metadata(data, analysis_fields, input_artifact, source_dataset), tables_dir / "spot_metadata.tsv")
    paths["coordinate_check"] = _write_tsv(_coordinate_check(data, analysis_fields, input_artifact, source_dataset), tables_dir / "coordinate_check.tsv")
    paths["domain_summary"] = _write_tsv(_domain_summary(data, analysis_fields, input_artifact, source_dataset), tables_dir / "domain_summary.tsv")
    paths["spatial_neighbors"] = _write_tsv(_spatial_neighbors(data, analysis_fields, input_artifact, source_dataset), tables_dir / "spatial_neighbors.tsv")
    paths["spatial_marker_handoff"] = _write_tsv(_handoff_table("spatial_marker_handoff", "reference_annotation_or_domain_marker_backend", analysis_fields, input_artifact, source_dataset), tables_dir / "spatial_marker_handoff.tsv")
    paths["deconvolution_handoff"] = _write_tsv(_handoff_table("deconvolution_handoff", "matched_scRNA_reference_required", analysis_fields, input_artifact, source_dataset), tables_dir / "deconvolution_handoff.tsv")
    return paths


def _base_fields(analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str) -> dict[str, Any]:
    return {
        "module": "spatial",
        "run_id": source_dataset,
        "sample_id": "all",
        "source_dataset": source_dataset,
        "input_artifact": input_artifact,
        "input_modality": "visium_spatial_expression",
        "analysis_level": analysis_fields.get("analysis_level"),
        "result_scope": "spatial_visium_squidpy_mvp",
        "method_status": "fully_automatic_validated_entrypoint",
        "delivery_allowed": analysis_fields.get("delivery_allowed"),
    }


def _spatial_qc(data: dict[str, Any], analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str) -> pd.DataFrame:
    rows = []
    obs = data["obs"]
    for spot in data["spots"]:
        row = _base_fields(analysis_fields, input_artifact, source_dataset)
        row.update(
            {
                "spot_id": spot,
                "total_counts": float(obs.loc[spot, "total_counts"]) if spot in obs.index else 0.0,
                "detected_genes": int(obs.loc[spot, "n_genes_by_counts"]) if spot in obs.index else 0,
                "in_tissue": int(float(obs.loc[spot, "in_tissue"])) if spot in obs.index else 1,
                "platform_note": "Visium spot is not a single cell",
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _spot_metadata(data: dict[str, Any], analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str) -> pd.DataFrame:
    rows = []
    obs = data["obs"]
    coords = np.asarray(data["coords"], dtype=float)
    for idx, spot in enumerate(data["spots"]):
        row = _base_fields(analysis_fields, input_artifact, source_dataset)
        row.update(
            {
                "spot_id": spot,
                "array_row": _obs_value(obs, spot, "array_row", idx),
                "array_col": _obs_value(obs, spot, "array_col", idx),
                "pxl_row": float(_obs_value(obs, spot, "pxl_row", coords[idx, 1])),
                "pxl_col": float(_obs_value(obs, spot, "pxl_col", coords[idx, 0])),
                "in_tissue": int(float(_obs_value(obs, spot, "in_tissue", 1))),
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _coordinate_check(data: dict[str, Any], analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str) -> pd.DataFrame:
    rows = []
    coords = np.asarray(data["coords"], dtype=float)
    finite = np.isfinite(coords).all(axis=1)
    for spot, ok in zip(data["spots"], finite):
        row = _base_fields(analysis_fields, input_artifact, source_dataset)
        row.update(
            {
                "spot_id": spot,
                "coordinate_status": "ready" if bool(ok) else "invalid_coordinate",
                "image_status": data.get("image_status", "image_not_required_for_mvp_or_not_provided"),
                "coordinate_system": "spatial_obsm_or_coordinate_table",
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _domain_summary(data: dict[str, Any], analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str) -> pd.DataFrame:
    rows = []
    counts = pd.Series(data["domains"]).astype(str).value_counts().sort_index()
    for domain, count in counts.items():
        row = _base_fields(analysis_fields, input_artifact, source_dataset)
        row.update(
            {
                "domain_id": domain,
                "spot_count": int(count),
                "domain_method_status": "existing_annotation_or_coordinate_clustering",
                "visium_spot_warning": "Visium spot is not a single cell",
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _spatial_neighbors(data: dict[str, Any], analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str) -> pd.DataFrame:
    spots = list(map(str, data["spots"]))
    coords = np.asarray(data["coords"], dtype=float)
    rows = []
    if len(spots) <= 1:
        row = _base_fields(analysis_fields, input_artifact, source_dataset)
        row.update({"spot_id": spots[0] if spots else "none", "neighbor_spot_id": "none", "distance": 0.0, "graph_status": "insufficient_spots"})
        return pd.DataFrame([row])
    pairs: list[tuple[int, int, float]] = []
    try:
        from sklearn.neighbors import NearestNeighbors

        n_neighbors = min(4, len(spots))
        distances, indices = NearestNeighbors(n_neighbors=n_neighbors).fit(coords).kneighbors(coords)
        for i in range(len(spots)):
            for dist, j in zip(distances[i][1:], indices[i][1:]):
                pairs.append((i, int(j), float(dist)))
    except Exception:
        order = np.argsort(coords[:, 0])
        for left, right in zip(order[:-1], order[1:]):
            pairs.append((int(left), int(right), float(np.linalg.norm(coords[left] - coords[right]))))
    for i, j, distance in pairs:
        row = _base_fields(analysis_fields, input_artifact, source_dataset)
        row.update({"spot_id": spots[i], "neighbor_spot_id": spots[j], "distance": distance, "graph_status": "nearest_neighbor_graph"})
        rows.append(row)
    return pd.DataFrame(rows)


def _handoff_table(artifact: str, required_input: str, analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str) -> pd.DataFrame:
    row = _base_fields(analysis_fields, input_artifact, source_dataset)
    row.update(
        {
            "artifact": artifact,
            "status": "handoff_ready_not_claimed_as_completed",
            "handoff_tool": "squidpy/Seurat/stLearn/reference-dependent backend",
            "required_input": required_input,
            "note": SPATIAL_WARNING,
        }
    )
    return pd.DataFrame([row])


def _obs_value(obs: pd.DataFrame, spot: str, column: str, default: Any) -> Any:
    if spot in obs.index and column in obs.columns:
        return obs.loc[spot, column]
    return default


def _write_spatial_figures(*, tables_dir: Path, figures_dir: Path) -> dict[str, str]:
    tokens = apply_clinical_journal_style()
    qc = pd.read_csv(tables_dir / "spatial_qc.tsv", sep="\t")
    meta = pd.read_csv(tables_dir / "spot_metadata.tsv", sep="\t")
    domains = pd.read_csv(tables_dir / "domain_summary.tsv", sep="\t")
    merged = meta.merge(qc[["spot_id", "total_counts"]], on="spot_id", how="left")

    qc_path = figures_dir / "spatial_qc_plot.png"
    plt.figure(figsize=(6, 5))
    scatter = plt.scatter(merged["pxl_col"], merged["pxl_row"], c=np.log10(merged["total_counts"].astype(float) + 1), s=8, cmap="viridis")
    plt.gca().invert_yaxis()
    plt.axis("equal")
    plt.axis("off")
    plt.colorbar(scatter, label="log10(total counts + 1)")
    plt.title("Spatial QC")
    plt.tight_layout()
    save_figure(qc_path, style=tokens)

    cluster_path = figures_dir / "spatial_cluster.png"
    # Reconstruct a stable visual grouping from coordinates when per-spot domains are not explicitly written.
    codes = pd.qcut(merged["pxl_col"].rank(method="first"), q=min(8, max(2, len(merged) // 100 + 1)), duplicates="drop").cat.codes
    plt.figure(figsize=(6, 5))
    plt.scatter(merged["pxl_col"], merged["pxl_row"], c=codes, s=8, cmap="tab20")
    plt.gca().invert_yaxis()
    plt.axis("equal")
    plt.axis("off")
    plt.title("Spatial Domains")
    plt.tight_layout()
    save_figure(cluster_path, style=tokens)

    domain_path = figures_dir / "domain_map.png"
    plt.figure(figsize=(6, 4))
    sns.barplot(data=domains, x="domain_id", y="spot_count", color=tokens["primary"])
    plt.xticks(rotation=45, ha="right")
    plt.xlabel("Domain")
    plt.ylabel("Spots")
    plt.title("Domain Summary")
    plt.tight_layout()
    save_figure(domain_path, style=tokens)
    return {"spatial_qc_plot": str(qc_path), "spatial_cluster": str(cluster_path), "domain_map": str(domain_path)}


def _write_spatial_object(*, objects_dir: Path, data: dict[str, Any], max_spots: int) -> dict[str, str]:
    object_path = objects_dir / "spatial_mvp.h5ad"
    spots = list(map(str, data["spots"]))
    selected = np.arange(len(spots))
    if len(selected) > max_spots:
        rng = np.random.default_rng(29)
        selected = np.sort(rng.choice(selected, size=max_spots, replace=False))
    try:
        import anndata as ad

        obs = data["obs"].copy()
        obs["spatial_domain"] = np.asarray(data["domains"], dtype=str)
        obs = obs.iloc[selected].copy()
        adata = ad.AnnData(
            X=np.asarray(data["matrix"], dtype=float)[selected],
            obs=obs,
            var=pd.DataFrame(index=list(map(str, data["features"]))),
        )
        adata.obsm["spatial"] = np.asarray(data["coords"], dtype=float)[selected]
        adata.uns["spatial_backend_warning"] = SPATIAL_WARNING
        adata.write_h5ad(object_path)
        status = "h5ad_written"
    except Exception as exc:  # pragma: no cover - depends on optional anndata stack
        object_path.write_text(
            json.dumps(
                {
                    "object_status": "json_fallback_not_h5ad",
                    "fallback_reason": f"{type(exc).__name__}:{exc}",
                    "n_spots": int(len(spots)),
                    "n_features": int(len(data["features"])),
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        status = "json_fallback_not_h5ad"
    manifest_path = objects_dir / "spatial_mvp_object_manifest.json"
    manifest_path.write_text(json.dumps({"object": str(object_path), "status": status, "max_spots": int(max_spots)}, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"mvp_object": str(object_path), "object_manifest": str(manifest_path)}


def _write_skip_outputs(*, tables_dir: Path, figures_dir: Path, objects_dir: Path, analysis_fields: dict[str, Any]) -> dict[str, dict[str, str]]:
    base = _base_fields(analysis_fields, "missing_spatial_input", "spatial")
    row = {
        **base,
        "status": "skipped_missing_input",
        "spot_id": "none",
        "total_counts": 0.0,
        "detected_genes": 0,
        "in_tissue": 0,
        "platform_note": "missing_input",
        "array_row": 0,
        "array_col": 0,
        "pxl_row": 0.0,
        "pxl_col": 0.0,
        "coordinate_status": "missing_input",
        "image_status": "missing_input",
        "coordinate_system": "missing_input",
        "domain_id": "none",
        "spot_count": 0,
        "domain_method_status": "not_run",
        "visium_spot_warning": SPATIAL_WARNING,
        "neighbor_spot_id": "none",
        "distance": 0.0,
        "graph_status": "not_run",
        "artifact": "spatial_handoff",
        "handoff_tool": "not_run",
        "required_input": "spatial_input",
        "note": "missing_input",
    }
    table_paths = {}
    for filename in (
        "spatial_qc.tsv",
        "spot_metadata.tsv",
        "coordinate_check.tsv",
        "domain_summary.tsv",
        "spatial_neighbors.tsv",
        "spatial_marker_handoff.tsv",
        "deconvolution_handoff.tsv",
    ):
        table_paths[filename.replace(".tsv", "")] = _write_tsv(pd.DataFrame([row]), tables_dir / filename)
    figure_paths = _write_placeholder_figures(figures_dir)
    object_path = objects_dir / "spatial_mvp.h5ad"
    object_path.write_text(json.dumps({"status": "skipped_missing_input"}, indent=2), encoding="utf-8")
    return {"tables": table_paths, "figures": figure_paths, "objects": {"mvp_object": str(object_path)}}


def _write_placeholder_figures(figures_dir: Path) -> dict[str, str]:
    tokens = apply_clinical_journal_style()
    paths = {}
    for key, title in {"spatial_qc_plot": "Spatial QC", "spatial_cluster": "Spatial Domains", "domain_map": "Domain Summary"}.items():
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
