from __future__ import annotations

import importlib.metadata
import importlib.util
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


VELOCITY_BACKEND_ID = "scrna.velocity.scvelo"
VELOCITY_WARNING = "RNA velocity 是基于 spliced/unspliced 的动态趋势推断，不等同于实验证明的细胞命运。"
REQUIRED_LAYERS = ("spliced", "unspliced")


def has_scrna_velocity_backend_config(config: dict[str, Any]) -> bool:
    module_cfg = _module_cfg(config)
    velocity_cfg = _velocity_cfg(module_cfg)
    if bool(velocity_cfg.get("enabled")):
        return True
    requested_backend = str(velocity_cfg.get("backend") or module_cfg.get("backend") or module_cfg.get("backend_id") or "")
    if requested_backend in {VELOCITY_BACKEND_ID, "scvelo", "velocity"}:
        return True
    if str(module_cfg.get("preset") or "").lower() == "trajectory" and _primary_input_ref(config) is not None:
        return True
    if any(velocity_cfg.get(key) for key in ("input_h5ad", "input_loom", "input_path", "velocity_input_path", "loom")):
        return True
    return any(module_cfg.get(key) for key in ("input_loom", "velocity_input_path", "loom"))


def run_scrna_velocity_backend(*, config: dict[str, Any], output_dir: Path, samples: pd.DataFrame) -> dict[str, Any]:
    module_name = "scrna"
    module_dir = output_dir
    tables_dir = module_dir / "results" / "tables" / module_name
    figures_dir = module_dir / "results" / "figures" / module_name
    objects_dir = module_dir / "objects" / module_name
    reports_dir = module_dir / "reports" / module_name
    logs_dir = module_dir / "logs"
    for directory in (tables_dir, figures_dir, objects_dir, reports_dir, logs_dir):
        directory.mkdir(parents=True, exist_ok=True)

    module_cfg = _module_cfg(config)
    velocity_cfg = _velocity_cfg(module_cfg)
    input_ref = _primary_input_ref(config)
    public_dataset = bool(velocity_cfg.get("public_dataset") or module_cfg.get("public_dataset") or velocity_cfg.get("validation_dataset"))
    missing_inputs = _missing_input_reasons(config)
    dependency_reasons = _dependency_reasons()
    skip_reasons = [*missing_inputs, *dependency_reasons]
    is_stub = bool(skip_reasons)
    status = "partial:scrna_velocity_skipped" if skip_reasons else "complete_scrna_velocity_scvelo_backend"
    try:
        level = classify_analysis_level(
            requested_level=module_cfg.get("analysis_level") or velocity_cfg.get("analysis_level"),
            input_path=input_ref,
            is_demo=_module_is_demo(config, module_cfg),
            is_stub=is_stub,
            public_dataset=public_dataset and not is_stub,
        )
        level_fields = level.to_manifest_fields()
    except ValueError as exc:
        status = "partial:scrna_velocity_analysis_level_invalid"
        skip_reasons.append(f"analysis_level_invalid:{exc}")
        level_fields = classify_analysis_level(requested_level="smoke_backend", is_stub=True).to_manifest_fields()

    artifacts: dict[str, dict[str, str]] = {"tables": {}, "figures": {}, "objects": {}, "reports": {}}
    warnings = [VELOCITY_WARNING, "没有 spliced/unspliced 层时必须跳过，不能从普通表达矩阵伪造 velocity。"]
    n_cells = 0
    n_genes = 0
    layer_summary: list[dict[str, Any]] = []
    if skip_reasons:
        artifacts.update(
            _write_skip_outputs(
                tables_dir=tables_dir,
                figures_dir=figures_dir,
                objects_dir=objects_dir,
                analysis_fields=level_fields,
                reason=";".join(skip_reasons),
            )
        )
    else:
        try:
            result = _run_scvelo(
                input_path=input_ref,
                input_type=_input_type(config),
                tables_dir=tables_dir,
                figures_dir=figures_dir,
                objects_dir=objects_dir,
                analysis_level=str(level_fields.get("analysis_level") or "smoke_backend"),
                max_cells=int(velocity_cfg.get("max_cells") or module_cfg.get("max_cells") or 1200),
                max_genes=int(velocity_cfg.get("max_genes") or module_cfg.get("max_genes") or 2000),
                random_seed=int(velocity_cfg.get("random_seed") or module_cfg.get("random_seed") or 7),
            )
            n_cells = int(result["n_cells"])
            n_genes = int(result["n_genes"])
            layer_summary = list(result["layer_summary"])
            artifacts["tables"].update(result["tables"])
            artifacts["figures"].update(result["figures"])
            artifacts["objects"].update(result["objects"])
        except Exception as exc:
            status = "partial:scrna_velocity_backend_failed"
            reason = f"scvelo_failed:{type(exc).__name__}:{exc}"
            skip_reasons.append(reason)
            level_fields = classify_analysis_level(requested_level="smoke_backend", is_stub=True).to_manifest_fields()
            artifacts.update(
                _write_skip_outputs(
                    tables_dir=tables_dir,
                    figures_dir=figures_dir,
                    objects_dir=objects_dir,
                    analysis_fields=level_fields,
                    reason=reason,
                )
            )

    artifacts["tables"]["tool_coverage"] = write_tool_coverage_table(module_name, tables_dir)
    artifacts["tables"]["backend_plan"] = str(write_backend_plan_table(module_name, config, tables_dir))
    artifacts["tables"]["backend_versions"] = str(_write_versions(tables_dir))
    artifacts["reports"]["methods_fragment"] = write_module_methods_fragment(module_name, reports_dir)
    artifacts["reports"]["velocity_report_fragment"] = str(_write_velocity_report_fragment(reports_dir, status, skip_reasons))
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
        skip_reasons=skip_reasons,
    )

    module_manifest = {
        "module": module_name,
        "title_cn": MODULE_SPECS[module_name].title_cn,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        **level_fields,
        "input_path": str(input_ref or ""),
        "input_type": _input_type(config),
        "n_cells": n_cells,
        "n_genes": n_genes,
        "layer_summary": layer_summary,
        "artifacts": artifacts,
        "warnings": warnings,
        "limitations": list(known_limitations(module_name)) + [VELOCITY_WARNING],
        "handoff": handoff_plan(module_name),
        "reproducible_command": f"ultimate run --config {config.get('_config_path', '<config.yaml>')}",
        "slurm_job_id": os.environ.get("SLURM_JOB_ID", ""),
        "slurm_job_name": os.environ.get("SLURM_JOB_NAME", ""),
        "backend": {
            "primary": "scrna_velocity_scvelo",
            "selected_backend_id": VELOCITY_BACKEND_ID,
            "selected_backend_status": "fully_automatic_validated_entrypoint" if not status.startswith("partial") else "partial",
            "backend_role": "optional_backend",
            "resource_profile": "large_scrna",
            "interpretation_warning": VELOCITY_WARNING,
        },
        "backend_plan": backend_plan,
        "backend_id": VELOCITY_BACKEND_ID,
        "backend_status": "fully_automatic_validated_entrypoint" if not status.startswith("partial") else "planned_fully_automatic",
        "backend_analysis_level": level_fields.get("analysis_level"),
        "backend_delivery_allowed": level_fields.get("delivery_allowed"),
        "backend_validation_evidence_allowed": level_fields.get("validation_evidence_allowed"),
        "backend_skip_reason": ";".join(skip_reasons),
        "backend_resource_profile": "large_scrna",
        "backend_slurm_job_id": os.environ.get("SLURM_JOB_ID", ""),
        "formal_backend": {
            "python_entrypoint": "ultimate.scrna_velocity_backend.run_scrna_velocity_backend",
            "status": "fully_automatic_validated_entrypoint" if not status.startswith("partial") else "partial_or_skipped",
        },
        "skip_reasons": skip_reasons,
    }
    artifacts["reports"].update(write_module_report_bundle(module_manifest, reports_dir))
    manifest_path = tables_dir / "velocity_backend_manifest.json"
    module_manifest["manifest_path"] = str(manifest_path)
    manifest_path.write_text(json.dumps(module_manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    write_module_report_bundle(module_manifest, reports_dir)
    return module_manifest


def _module_cfg(config: dict[str, Any]) -> dict[str, Any]:
    return ((config.get("modules") or {}).get("scrna") or {}) if isinstance(config.get("modules"), dict) else {}


def _velocity_cfg(module_cfg: dict[str, Any]) -> dict[str, Any]:
    value = module_cfg.get("velocity")
    return value if isinstance(value, dict) else {}


def _module_is_demo(config: dict[str, Any], module_cfg: dict[str, Any]) -> bool | None:
    if "is_demo" in module_cfg:
        return bool(module_cfg.get("is_demo"))
    project = config.get("project") or {}
    if "is_demo" in project:
        return bool(project.get("is_demo"))
    return None


def _primary_input_ref(config: dict[str, Any]) -> Path | None:
    module_cfg = _module_cfg(config)
    velocity_cfg = _velocity_cfg(module_cfg)
    raw_cfg = module_cfg.get("raw") if isinstance(module_cfg.get("raw"), dict) else {}
    base = Path(str(config.get("_config_path") or ".")).resolve().parent
    use_module_expression_input = str(module_cfg.get("preset") or "").lower() == "trajectory"
    value = (
        velocity_cfg.get("input_h5ad")
        or velocity_cfg.get("input_loom")
        or velocity_cfg.get("input_path")
        or module_cfg.get("velocity_input_path")
        or module_cfg.get("input_loom")
        or (module_cfg.get("input_h5ad") if use_module_expression_input else None)
        or (module_cfg.get("input_path") if use_module_expression_input else None)
        or raw_cfg.get("velocity_input_path")
    )
    return _resolve_path(base, value) if value else None


def _input_type(config: dict[str, Any]) -> str:
    module_cfg = _module_cfg(config)
    velocity_cfg = _velocity_cfg(module_cfg)
    explicit = str(velocity_cfg.get("input_type") or module_cfg.get("velocity_input_type") or "").lower()
    if explicit in {"h5ad", "loom"}:
        return explicit
    path = _primary_input_ref(config)
    if path and path.suffix.lower() == ".loom":
        return "loom"
    return "h5ad"


def _missing_input_reasons(config: dict[str, Any]) -> list[str]:
    input_ref = _primary_input_ref(config)
    if input_ref is None:
        return ["missing_velocity_input_path"]
    if not input_ref.exists():
        return [f"missing_velocity_input_path:{input_ref}"]
    return []


def _dependency_reasons() -> list[str]:
    reasons = []
    for package in ("anndata", "scanpy", "scvelo"):
        if importlib.util.find_spec(package) is None:
            reasons.append(f"dependency_missing:{package}")
    return reasons


def _resolve_path(base: Path, value: Any) -> Path:
    candidate = Path(str(value))
    return candidate if candidate.is_absolute() else (base / candidate).resolve()


def _run_scvelo(
    *,
    input_path: Path | None,
    input_type: str,
    tables_dir: Path,
    figures_dir: Path,
    objects_dir: Path,
    analysis_level: str,
    max_cells: int,
    max_genes: int,
    random_seed: int,
) -> dict[str, Any]:
    if input_path is None:
        raise ValueError("missing velocity input path")
    import anndata as ad
    import scanpy as sc
    import scvelo as scv
    from scipy import sparse

    if input_type == "loom":
        adata = scv.read(str(input_path), cache=False)
    elif input_type == "h5ad":
        adata = ad.read_h5ad(input_path)
    else:
        raise ValueError(f"unsupported velocity input_type:{input_type}")
    missing_layers = [layer for layer in REQUIRED_LAYERS if layer not in adata.layers]
    if missing_layers:
        raise ValueError(f"missing_velocity_layers:{','.join(missing_layers)}")
    adata.var_names_make_unique()
    if adata.n_obs > max_cells:
        rng = np.random.default_rng(random_seed)
        selected = rng.choice(adata.n_obs, size=max_cells, replace=False)
        adata = adata[selected].copy()
    if adata.n_vars > max_genes:
        totals = _layer_sum(adata.layers["spliced"]) + _layer_sum(adata.layers["unspliced"])
        keep = np.argsort(np.asarray(totals).ravel())[-max_genes:]
        adata = adata[:, keep].copy()

    layer_summary = _write_layer_summary(adata, tables_dir, analysis_level)
    scv.pp.filter_and_normalize(
        adata,
        min_shared_counts=5,
    )
    if "X_pca" not in adata.obsm:
        sc.tl.pca(adata, n_comps=max(2, min(30, adata.n_obs - 1, adata.n_vars - 1)), svd_solver="arpack")
    scv.pp.moments(adata, n_pcs=max(2, min(30, adata.obsm["X_pca"].shape[1])), n_neighbors=min(20, max(3, adata.n_obs // 8)))
    scv.tl.velocity(adata, mode="stochastic")
    scv.tl.velocity_graph(adata)
    if "X_umap" not in adata.obsm:
        sc.tl.umap(adata, random_state=random_seed)
    scv.tl.velocity_embedding(adata, basis="umap")
    try:
        scv.tl.velocity_confidence(adata)
    except Exception:
        adata.obs["velocity_confidence"] = np.nan
    try:
        scv.tl.velocity_pseudotime(adata)
    except Exception:
        adata.obs["velocity_pseudotime"] = np.nan

    tables = {
        "velocity_layer_summary": str(tables_dir / "velocity_layer_summary.tsv"),
        "velocity_graph": str(_write_velocity_graph_summary(adata, tables_dir, analysis_level)),
        "velocity_embedding": str(_write_velocity_embedding(adata, tables_dir, analysis_level)),
        "velocity_summary": str(_write_velocity_summary(adata, tables_dir, analysis_level)),
    }
    figures = {"velocity_embedding": str(_write_velocity_figure(adata, figures_dir))}
    object_path = objects_dir / "scrna_velocity.h5ad"
    adata.write_h5ad(object_path)
    return {
        "n_cells": int(adata.n_obs),
        "n_genes": int(adata.n_vars),
        "layer_summary": layer_summary,
        "tables": tables,
        "figures": figures,
        "objects": {"velocity_h5ad": str(object_path)},
    }


def _layer_sum(matrix: Any) -> np.ndarray:
    from scipy import sparse

    if sparse.issparse(matrix):
        return np.asarray(matrix.sum(axis=0)).ravel()
    return np.asarray(matrix).sum(axis=0)


def _write_layer_summary(adata: Any, tables_dir: Path, analysis_level: str) -> list[dict[str, Any]]:
    from scipy import sparse

    rows = []
    for layer in REQUIRED_LAYERS:
        values = adata.layers[layer]
        if sparse.issparse(values):
            total = float(values.sum())
            nnz = int(values.nnz)
        else:
            arr = np.asarray(values)
            total = float(arr.sum())
            nnz = int(np.count_nonzero(arr))
        rows.append(
            {
                "layer": layer,
                "n_cells": int(adata.n_obs),
                "n_genes": int(adata.n_vars),
                "total_counts": total,
                "nonzero_entries": nnz,
                "analysis_level": analysis_level,
            }
        )
    pd.DataFrame(rows).to_csv(tables_dir / "velocity_layer_summary.tsv", sep="\t", index=False)
    return rows


def _write_velocity_graph_summary(adata: Any, tables_dir: Path, analysis_level: str) -> Path:
    graph = adata.uns.get("velocity_graph")
    n_edges = int(graph.nnz) if hasattr(graph, "nnz") else 0
    rows = [
        {
            "backend_id": VELOCITY_BACKEND_ID,
            "n_cells": int(adata.n_obs),
            "n_genes": int(adata.n_vars),
            "velocity_graph_edges": n_edges,
            "mean_velocity_confidence": _safe_mean(adata.obs.get("velocity_confidence")),
            "analysis_level": analysis_level,
            "interpretation_warning": VELOCITY_WARNING,
        }
    ]
    path = tables_dir / "velocity_graph.tsv"
    pd.DataFrame(rows).to_csv(path, sep="\t", index=False)
    return path


def _write_velocity_embedding(adata: Any, tables_dir: Path, analysis_level: str) -> Path:
    coords = np.asarray(adata.obsm.get("X_umap"))
    velocity = np.asarray(adata.obsm.get("velocity_umap", np.zeros_like(coords)))
    rows = pd.DataFrame(
        {
            "barcode": adata.obs_names.astype(str),
            "umap_1": coords[:, 0],
            "umap_2": coords[:, 1],
            "velocity_umap_1": velocity[:, 0],
            "velocity_umap_2": velocity[:, 1],
            "velocity_confidence": np.asarray(adata.obs.get("velocity_confidence", np.full(adata.n_obs, np.nan))),
            "velocity_pseudotime": np.asarray(adata.obs.get("velocity_pseudotime", np.full(adata.n_obs, np.nan))),
            "analysis_level": analysis_level,
        }
    )
    path = tables_dir / "velocity_embedding.tsv"
    rows.to_csv(path, sep="\t", index=False)
    return path


def _write_velocity_summary(adata: Any, tables_dir: Path, analysis_level: str) -> Path:
    rows = [
        {
            "backend_id": VELOCITY_BACKEND_ID,
            "status": "ready",
            "n_cells": int(adata.n_obs),
            "n_genes": int(adata.n_vars),
            "mean_velocity_pseudotime": _safe_mean(adata.obs.get("velocity_pseudotime")),
            "mean_velocity_confidence": _safe_mean(adata.obs.get("velocity_confidence")),
            "analysis_level": analysis_level,
            "interpretation_warning": VELOCITY_WARNING,
        }
    ]
    path = tables_dir / "velocity_summary.tsv"
    pd.DataFrame(rows).to_csv(path, sep="\t", index=False)
    return path


def _write_velocity_figure(adata: Any, figures_dir: Path) -> Path:
    apply_clinical_journal_style()
    coords = np.asarray(adata.obsm.get("X_umap"))
    velocity = np.asarray(adata.obsm.get("velocity_umap", np.zeros_like(coords)))
    color = np.asarray(adata.obs.get("velocity_confidence", np.zeros(adata.n_obs)), dtype=float)
    path = figures_dir / "velocity_embedding.png"
    fig, ax = plt.subplots(figsize=(6.2, 5.2))
    scatter = ax.scatter(coords[:, 0], coords[:, 1], c=color, cmap="viridis", s=16, linewidths=0, alpha=0.82)
    step = max(1, coords.shape[0] // 350)
    ax.quiver(
        coords[::step, 0],
        coords[::step, 1],
        velocity[::step, 0],
        velocity[::step, 1],
        angles="xy",
        scale_units="xy",
        scale=None,
        width=0.002,
        color="#345995",
        alpha=0.55,
    )
    ax.set_xlabel("UMAP 1")
    ax.set_ylabel("UMAP 2")
    ax.set_title("scVelo RNA velocity embedding")
    fig.colorbar(scatter, ax=ax, label="Velocity confidence")
    fig.tight_layout()
    save_figure(path)
    return path


def _safe_mean(values: Any) -> float:
    if values is None:
        return float("nan")
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        return float("nan")
    return float(np.nanmean(arr))


def _write_versions(tables_dir: Path) -> Path:
    rows = []
    for package in ("anndata", "scanpy", "scvelo", "numpy", "pandas"):
        try:
            version = importlib.metadata.version(package)
            status = "present"
        except importlib.metadata.PackageNotFoundError:
            version = ""
            status = "missing"
        rows.append({"package": package, "version": version, "status": status})
    path = tables_dir / "velocity_backend_versions.tsv"
    pd.DataFrame(rows).to_csv(path, sep="\t", index=False)
    return path


def _write_velocity_report_fragment(reports_dir: Path, status: str, skip_reasons: list[str]) -> Path:
    path = reports_dir / "velocity_report_fragment.md"
    lines = [
        "# scRNA RNA velocity backend",
        "",
        f"- backend_id: `{VELOCITY_BACKEND_ID}`",
        f"- status: `{status}`",
        f"- warning: {VELOCITY_WARNING}",
        "- required layers: `spliced`, `unspliced`",
        "",
    ]
    if skip_reasons:
        lines.extend(["## Skip reasons", "", *[f"- `{reason}`" for reason in skip_reasons], ""])
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _write_skip_outputs(
    *,
    tables_dir: Path,
    figures_dir: Path,
    objects_dir: Path,
    analysis_fields: dict[str, Any],
    reason: str,
) -> dict[str, dict[str, str]]:
    tables_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)
    objects_dir.mkdir(parents=True, exist_ok=True)
    table_rows = [
        {
            "backend_id": VELOCITY_BACKEND_ID,
            "status": "skipped",
            "skip_reason": reason,
            "analysis_level": analysis_fields.get("analysis_level"),
            "delivery_allowed": analysis_fields.get("delivery_allowed"),
            "validation_evidence_allowed": analysis_fields.get("validation_evidence_allowed"),
            "interpretation_warning": VELOCITY_WARNING,
        }
    ]
    table_paths = {}
    for filename in ("velocity_graph.tsv", "velocity_embedding.tsv", "velocity_summary.tsv", "velocity_layer_summary.tsv"):
        path = tables_dir / filename
        pd.DataFrame(table_rows).to_csv(path, sep="\t", index=False)
        table_paths[Path(filename).stem] = str(path)
    object_path = objects_dir / "scrna_velocity_skipped.json"
    object_path.write_text(json.dumps({"status": "skipped", "reason": reason}, indent=2), encoding="utf-8")
    fig_path = figures_dir / "velocity_embedding.png"
    _write_skip_figure(fig_path, reason)
    return {"tables": table_paths, "figures": {"velocity_embedding": str(fig_path)}, "objects": {"velocity_skip_object": str(object_path)}}


def _write_skip_figure(path: Path, reason: str) -> None:
    apply_clinical_journal_style()
    fig, ax = plt.subplots(figsize=(6.0, 3.6))
    ax.axis("off")
    ax.text(
        0.5,
        0.55,
        "RNA velocity skipped",
        ha="center",
        va="center",
        fontsize=14,
        fontweight="bold",
        color="#345995",
    )
    ax.text(0.5, 0.35, reason[:120], ha="center", va="center", fontsize=9, color="#6B7280", wrap=True)
    fig.tight_layout()
    save_figure(path)
