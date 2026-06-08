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
    _coerce_mvp_table_schema,
)
from ultimate.plot_style import apply_clinical_journal_style, save_figure


PERTURB_SEQ_BACKEND_ID = "perturb_seq.default.guide_assignment_mvp"
PERTURB_WARNING = "guide assignment 错误会污染结论；扰动 effect 不能自动写成直接机制。"


def has_perturb_seq_backend_config(config: dict[str, Any]) -> bool:
    module_cfg = _module_cfg(config)
    raw_cfg = module_cfg.get("raw") if isinstance(module_cfg.get("raw"), dict) else {}
    keys = {
        "input_h5ad",
        "guide_assignment_table",
        "guide_count_matrix",
        "expression_matrix",
        "input_path",
    }
    return any(module_cfg.get(key) for key in keys) or any(raw_cfg.get(key) for key in keys)


def run_perturb_seq_backend(*, config: dict[str, Any], output_dir: Path, samples: pd.DataFrame) -> dict[str, Any]:
    module_name = "perturb_seq"
    tables_dir = output_dir / "results" / "tables" / module_name
    figures_dir = output_dir / "results" / "figures" / module_name
    objects_dir = output_dir / "objects" / module_name
    reports_dir = output_dir / "reports" / module_name
    logs_dir = output_dir / "logs"
    for directory in (tables_dir, figures_dir, objects_dir, reports_dir, logs_dir):
        directory.mkdir(parents=True, exist_ok=True)

    module_cfg = _module_cfg(config)
    input_path = _primary_input_ref(config)
    missing_inputs = _missing_input_reasons(config)
    skip_reasons = list(missing_inputs)
    is_stub = bool(missing_inputs)
    status = "partial:perturb_seq_inputs_missing" if missing_inputs else "complete_perturb_seq_guide_backend"
    try:
        level = classify_analysis_level(
            requested_level=module_cfg.get("analysis_level"),
            input_path=input_path,
            is_demo=_module_is_demo(config, module_cfg),
            is_stub=is_stub,
            public_dataset=bool(module_cfg.get("public_dataset") or module_cfg.get("validation_dataset")) and not is_stub,
        )
        level_fields = level.to_manifest_fields()
    except ValueError as exc:
        status = "partial:perturb_seq_analysis_level_invalid"
        skip_reasons.append(f"analysis_level_invalid:{exc}")
        level_fields = classify_analysis_level(requested_level="smoke_backend", is_stub=True).to_manifest_fields()

    artifacts: dict[str, dict[str, str]] = {"tables": {}, "figures": {}, "objects": {}, "reports": {}}
    warnings = [PERTURB_WARNING]
    n_cells = 0
    n_features = 0
    n_guides = 0
    if skip_reasons:
        artifacts.update(_write_skip_outputs(tables_dir=tables_dir, figures_dir=figures_dir, objects_dir=objects_dir, analysis_fields=level_fields))
    else:
        try:
            cells, n_features, read_summary = _read_input(
                input_path,
                max_cells=int(module_cfg.get("max_cells", 6000)),
                seed=int(module_cfg.get("seed", 29)),
            )
        except Exception as exc:
            status = "partial:perturb_seq_input_read_failed"
            skip_reasons.append(f"input_read_failed:{type(exc).__name__}:{exc}")
            level_fields = classify_analysis_level(requested_level="smoke_backend", is_stub=True).to_manifest_fields()
            artifacts.update(_write_skip_outputs(tables_dir=tables_dir, figures_dir=figures_dir, objects_dir=objects_dir, analysis_fields=level_fields))
        else:
            artifacts["tables"].update(
                _write_perturb_tables(
                    tables_dir=tables_dir,
                    cells=cells,
                    input_path=str(input_path or ""),
                    source_dataset=_source_dataset(config),
                    analysis_fields=level_fields,
                    read_summary=read_summary,
                )
            )
            artifacts["figures"].update(_write_perturb_figures(tables_dir=tables_dir, figures_dir=figures_dir))
            artifacts["objects"].update(
                _write_perturb_object(
                    objects_dir=objects_dir,
                    cells=cells,
                    input_path=str(input_path or ""),
                    n_features=n_features,
                    read_summary=read_summary,
                )
            )
            n_cells = int(cells.shape[0])
            n_guides = int(cells["guide_id"].nunique())

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
        skip_reasons=skip_reasons,
    )

    module_manifest = {
        "module": module_name,
        "title_cn": MODULE_SPECS[module_name].title_cn,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        **level_fields,
        "input_path": str(input_path or ""),
        "n_cells": n_cells,
        "n_features": n_features,
        "n_guides": n_guides,
        "artifacts": artifacts,
        "warnings": warnings,
        "limitations": list(known_limitations(module_name)),
        "handoff": handoff_plan(module_name),
        "reproducible_command": f"ultimate run --config {config.get('_config_path', '<config.yaml>')}",
        "backend": {
            "primary": "perturb_seq_guide_assignment_mvp",
            "selected_backend_id": backend_plan["selected_backend_id"],
            "selected_backend_status": backend_plan["selected_backend_status"],
            "backend_role": backend_plan["selected_backend_role"],
            "resource_profile": backend_plan["backend_resource_profile"],
            "interpretation_warning": PERTURB_WARNING,
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
            "python_entrypoint": "ultimate.perturb_seq_backend.run_perturb_seq_backend",
            "status": "fully_automatic_validated_entrypoint" if not status.startswith("partial") else "partial_inputs_missing",
        },
        "skip_reasons": skip_reasons,
    }
    artifacts["reports"].update(write_module_report_bundle(module_manifest, reports_dir))
    manifest_path = tables_dir / "module_manifest.json"
    module_manifest["manifest_path"] = str(manifest_path)
    manifest_path.write_text(json.dumps(module_manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    write_module_report_bundle(module_manifest, reports_dir)
    return module_manifest


def _module_cfg(config: dict[str, Any]) -> dict[str, Any]:
    return ((config.get("modules") or {}).get("perturb_seq") or {}) if isinstance(config.get("modules"), dict) else {}


def _module_is_demo(config: dict[str, Any], module_cfg: dict[str, Any]) -> bool | None:
    if "is_demo" in module_cfg:
        return bool(module_cfg.get("is_demo"))
    project = config.get("project") or {}
    if "is_demo" in project:
        return bool(project.get("is_demo"))
    return None


def _source_dataset(config: dict[str, Any]) -> str:
    project = config.get("project") or {}
    return str(project.get("name") or project.get("job_id") or "perturb_seq")


def _primary_input_ref(config: dict[str, Any]) -> Path | None:
    module_cfg = _module_cfg(config)
    raw_cfg = module_cfg.get("raw") if isinstance(module_cfg.get("raw"), dict) else {}
    base = Path(str(config.get("_config_path") or ".")).resolve().parent
    value = (
        module_cfg.get("input_h5ad")
        or module_cfg.get("guide_assignment_table")
        or module_cfg.get("input_path")
        or raw_cfg.get("input_h5ad")
        or raw_cfg.get("guide_assignment_table")
        or raw_cfg.get("input_path")
    )
    return _resolve_path(base, value) if value else None


def _missing_input_reasons(config: dict[str, Any]) -> list[str]:
    input_path = _primary_input_ref(config)
    if input_path is None:
        return ["missing_perturb_seq_input"]
    if not input_path.exists():
        return [f"missing_input_path:{input_path}"]
    if input_path.suffix.lower() not in {".h5ad", ".tsv", ".txt", ".csv"}:
        return [f"unsupported_input_extension:{input_path.suffix or 'none'}"]
    return []


def _resolve_path(base: Path, value: Any) -> Path:
    candidate = Path(str(value))
    return candidate if candidate.is_absolute() else (base / candidate).resolve()


def _read_input(path: Path | None, *, max_cells: int, seed: int) -> tuple[pd.DataFrame, int, dict[str, Any]]:
    if path is None:
        raise ValueError("input_path_missing")
    if path.suffix.lower() == ".h5ad":
        return _read_perturb_h5ad_obs(path, max_cells=max_cells, seed=seed)
    sep = "\t" if path.suffix.lower() in {".tsv", ".txt"} else ","
    frame = pd.read_csv(path, sep=sep)
    if frame.empty:
        raise ValueError(f"Perturb-seq guide assignment table is empty: {path}")
    cells = _normalize_assignment_table(frame)
    original_cells = int(cells.shape[0])
    if original_cells > max_cells:
        cells = cells.sample(n=max_cells, random_state=seed).sort_values("cell_id").reset_index(drop=True)
    return cells, 0, {"original_n_cells": original_cells, "max_cells": int(max_cells), "sampling_seed": int(seed), "input_mode": "guide_assignment_table"}


def _normalize_assignment_table(frame: pd.DataFrame) -> pd.DataFrame:
    rename = {}
    if "cell_id" not in frame.columns:
        rename[frame.columns[0]] = "cell_id"
    if "guide_id" not in frame.columns:
        for candidate in ("perturbation", "guide", "gRNA", "target"):
            if candidate in frame.columns:
                rename[candidate] = "guide_id"
                break
    cells = frame.rename(columns=rename).copy()
    if "guide_id" not in cells.columns:
        raise ValueError("guide assignment table must contain guide_id or perturbation column")
    if "perturbation_type" not in cells.columns:
        cells["perturbation_type"] = np.where(cells["guide_id"].astype(str).str.contains("control|ctrl|ntc", case=False, regex=True), "control", "targeting")
    if "condition" not in cells.columns:
        cells["condition"] = np.where(cells["perturbation_type"].astype(str).str.contains("control|ctrl|ntc", case=False, regex=True), "control_like", "perturbed")
    if "ncounts" not in cells.columns:
        cells["ncounts"] = 0.0
    if "ngenes" not in cells.columns:
        cells["ngenes"] = 0.0
    cells["cell_id"] = cells["cell_id"].astype(str)
    cells["guide_id"] = cells["guide_id"].astype(str)
    cells["ncounts"] = pd.to_numeric(cells["ncounts"], errors="coerce").fillna(0.0)
    cells["ngenes"] = pd.to_numeric(cells["ngenes"], errors="coerce").fillna(0.0)
    return cells[["cell_id", "guide_id", "perturbation_type", "condition", "ncounts", "ngenes"]]


def _read_perturb_h5ad_obs(input_h5ad: Path, *, max_cells: int, seed: int) -> tuple[pd.DataFrame, int, dict[str, Any]]:
    try:
        import h5py
    except ModuleNotFoundError as exc:
        raise RuntimeError("Reading Perturb-seq h5ad input requires h5py.") from exc

    with h5py.File(input_h5ad, "r") as handle:
        obs = handle["obs"]
        var = handle["var"]
        n_vars = _h5_length(var.get("index")) or _h5_length(var.get("_index")) or _h5_length(var.get("gene_symbol")) or _x_feature_count(handle)
        cell_id = _first_present_column(obs, "cell_barcode", "index", "_index")
        perturbation = _first_present_column(obs, "perturbation", "guide_id", "target", "gRNA")
        perturbation_type = _first_present_column(obs, "perturbation_type", "guide_type")
        ncounts = _first_present_numeric_column(obs, "ncounts", "UMI count", "total_counts")
        ngenes = _first_present_numeric_column(obs, "ngenes", "n_genes_by_counts")
    if perturbation is None:
        raise ValueError(f"h5ad is missing perturbation/guide metadata: {input_h5ad}")
    n_obs = len(perturbation)
    if cell_id is None:
        cell_id = [f"cell_{idx:05d}" for idx in range(n_obs)]
    if perturbation_type is None:
        perturbation_type = ["unknown"] * n_obs
    if ncounts is None:
        ncounts = np.zeros(n_obs, dtype=float)
    if ngenes is None:
        ngenes = np.zeros(n_obs, dtype=float)
    cells = pd.DataFrame(
        {
            "cell_id": cell_id,
            "guide_id": perturbation,
            "perturbation_type": perturbation_type,
            "condition": np.where(pd.Series(perturbation_type).astype(str).str.contains("control|ctrl|ntc", case=False, regex=True), "control_like", "perturbed"),
            "ncounts": ncounts,
            "ngenes": ngenes,
        }
    )
    original_cells = int(cells.shape[0])
    if original_cells > max_cells:
        cells = cells.sample(n=max_cells, random_state=seed).sort_values("cell_id").reset_index(drop=True)
    return cells, int(n_vars), {"original_n_cells": original_cells, "max_cells": int(max_cells), "sampling_seed": int(seed), "input_mode": "h5ad_obs_metadata"}


def _write_perturb_tables(
    *,
    tables_dir: Path,
    cells: pd.DataFrame,
    input_path: str,
    source_dataset: str,
    analysis_fields: dict[str, Any],
    read_summary: dict[str, Any],
) -> dict[str, str]:
    base = _base_fields(analysis_fields, input_path, source_dataset)
    paths: dict[str, str] = {}
    guide_counts = cells["guide_id"].value_counts().to_dict()

    guide_qc = pd.DataFrame(
        {
            **base,
            "cell_id": cells["cell_id"],
            "guide_id": cells["guide_id"],
            "guide_count": cells["guide_id"].map(guide_counts).astype(int),
            "assignment_status": "assigned_from_metadata",
            "multiplet_warning": "multi-guide cells require explicit guide count matrix; metadata-only input cannot confirm multiplets",
        }
    )
    paths["guide_qc"] = _write_tsv(guide_qc, tables_dir / "guide_qc.tsv")

    assignment = pd.DataFrame(
        {
            "module": "perturb_seq",
            "cell_id": cells["cell_id"],
            "guide_id": cells["guide_id"],
            "target_gene": cells["guide_id"].map(_target_from_guide),
            "assignment_class": np.where(cells["condition"].astype(str).str.contains("control", case=False, regex=True), "control", "targeting"),
            "confidence": 1.0,
            "multiplet_strategy": "metadata_single_assignment; use guide count matrix for multi-guide QC",
        }
    )
    paths["guide_assignment"] = _write_tsv(assignment, tables_dir / "guide_assignment.tsv")

    summary = (
        assignment.groupby(["guide_id", "target_gene", "assignment_class"], observed=False)
        .size()
        .rename("cell_count")
        .reset_index()
        .rename(columns={"guide_id": "perturbation"})
    )
    summary["control_status"] = np.where(summary["assignment_class"].eq("control"), "control_like", "perturbed")
    summary["delivery_allowed"] = analysis_fields.get("delivery_allowed")
    summary.insert(0, "module", "perturb_seq")
    paths["perturbation_summary"] = _write_tsv(summary, tables_dir / "perturbation_summary.tsv")

    control_mask = cells["condition"].astype(str).str.contains("control|ctrl|ntc", case=False, regex=True) | cells["guide_id"].astype(str).str.contains("control|ctrl|ntc", case=False, regex=True)
    control_mean_counts = float(cells.loc[control_mask, "ncounts"].mean()) if control_mask.any() else float(cells["ncounts"].mean())
    control_mean_genes = float(cells.loc[control_mask, "ngenes"].mean()) if control_mask.any() else float(cells["ngenes"].mean())
    effect = (
        cells.groupby("guide_id", observed=False)
        .agg(cell_count=("cell_id", "size"), mean_ncounts=("ncounts", "mean"), mean_ngenes=("ngenes", "mean"))
        .reset_index()
        .rename(columns={"guide_id": "perturbation"})
    )
    effect["target_gene"] = effect["perturbation"].map(_target_from_guide)
    effect["feature_id"] = "qc_metric_ncounts_ngenes"
    effect["effect_size"] = np.log2((effect["mean_ncounts"] + 1.0) / (control_mean_counts + 1.0))
    effect["model_status"] = "design_ready_qc_metric_only"
    effect.insert(0, "module", "perturb_seq")
    paths["perturbation_expression_effect"] = _write_tsv(effect[["module", "perturbation", "target_gene", "feature_id", "effect_size", "model_status"]], tables_dir / "perturbation_expression_effect.tsv")

    pseudobulk = effect[["module", "perturbation", "target_gene", "mean_ncounts", "mean_ngenes", "cell_count"]].copy()
    pseudobulk["sample_id"] = "all"
    pseudobulk["feature_id"] = "qc_metric_ncounts"
    pseudobulk["count_value"] = pseudobulk["mean_ncounts"]
    pseudobulk["design_ready_status"] = "ready_for_expression_matrix_backend"
    paths["pseudobulk_by_perturbation"] = _write_tsv(pseudobulk[["module", "perturbation", "sample_id", "feature_id", "count_value", "design_ready_status"]], tables_dir / "pseudobulk_by_perturbation.tsv")

    target_response = effect[["module", "target_gene", "effect_size"]].copy()
    target_response["response_feature"] = "qc_metric_ncounts"
    target_response["mechanism_warning"] = PERTURB_WARNING
    paths["target_response"] = _write_tsv(target_response[["module", "target_gene", "response_feature", "effect_size", "mechanism_warning"]], tables_dir / "target_response.tsv")

    read_summary_frame = pd.DataFrame([{**base, **read_summary, "n_guides": int(cells["guide_id"].nunique())}])
    paths["input_read_summary"] = _write_tsv(read_summary_frame, tables_dir / "input_read_summary.tsv")
    return paths


def _write_perturb_figures(*, tables_dir: Path, figures_dir: Path) -> dict[str, str]:
    tokens = apply_clinical_journal_style()
    paths: dict[str, str] = {}
    summary = pd.read_csv(tables_dir / "perturbation_summary.tsv", sep="\t")
    effect = pd.read_csv(tables_dir / "perturbation_expression_effect.tsv", sep="\t")

    guide_path = figures_dir / "guide_distribution.png"
    plt.figure(figsize=(7, 4.2))
    order = summary.sort_values("cell_count", ascending=False).head(30)
    plt.bar(order["perturbation"].astype(str), order["cell_count"], color=tokens["primary"])
    plt.xticks(rotation=35, ha="right")
    plt.ylabel("Cells")
    plt.title("Perturbation guide distribution")
    plt.tight_layout()
    save_figure(guide_path, style=tokens)
    paths["guide_distribution"] = str(guide_path)

    umap_path = figures_dir / "perturbation_umap_placeholder.png"
    plt.figure(figsize=(5.8, 4.6))
    x = np.arange(effect.shape[0])
    y = effect["effect_size"].to_numpy(dtype=float)
    plt.scatter(x, y, c=y, cmap="coolwarm", s=28, alpha=0.85)
    plt.axhline(0, color="#8A8F98", linewidth=0.8)
    plt.xlabel("Perturbation index")
    plt.ylabel("QC metric effect size")
    plt.title("Perturbation effect preview")
    plt.tight_layout()
    save_figure(umap_path, style=tokens)
    paths["perturbation_umap_placeholder"] = str(umap_path)
    return paths


def _write_perturb_object(*, objects_dir: Path, cells: pd.DataFrame, input_path: str, n_features: int, read_summary: dict[str, Any]) -> dict[str, str]:
    path = objects_dir / "perturb_seq_mvp_object.rds"
    payload = {
        "object_type": "json_serialized_perturb_seq_mvp",
        "input_path": input_path,
        "n_cells": int(cells.shape[0]),
        "n_features": int(n_features),
        "n_guides": int(cells["guide_id"].nunique()),
        "guide_counts": cells["guide_id"].value_counts().to_dict(),
        **read_summary,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"mvp_object": str(path)}


def _write_skip_outputs(*, tables_dir: Path, figures_dir: Path, objects_dir: Path, analysis_fields: dict[str, Any]) -> dict[str, dict[str, str]]:
    base = {
        "module": "perturb_seq",
        "analysis_level": analysis_fields.get("analysis_level"),
        "delivery_allowed": analysis_fields.get("delivery_allowed"),
        "skip_status": "skipped_no_valid_perturb_seq_input",
    }
    artifacts = {"tables": {}, "figures": {}, "objects": {}, "reports": {}}
    for name in ("guide_qc", "guide_assignment", "perturbation_summary", "perturbation_expression_effect", "pseudobulk_by_perturbation", "target_response"):
        artifacts["tables"][name] = _write_tsv(pd.DataFrame([base]), tables_dir / f"{name}.tsv")
    for figure_name in ("guide_distribution", "perturbation_umap_placeholder"):
        path = figures_dir / f"{figure_name}.png"
        plt.figure(figsize=(5, 3))
        plt.text(0.5, 0.5, "Perturb-seq input missing", ha="center", va="center")
        plt.axis("off")
        save_figure(path, style=apply_clinical_journal_style())
        artifacts["figures"][figure_name] = str(path)
    object_path = objects_dir / "perturb_seq_mvp_object.rds"
    object_path.write_text(json.dumps(base, indent=2, ensure_ascii=False), encoding="utf-8")
    artifacts["objects"]["mvp_object"] = str(object_path)
    return artifacts


def _target_from_guide(guide_id: Any) -> str:
    text = str(guide_id)
    if text.lower() in {"control", "ctrl", "ntc", "non-targeting", "non_targeting"}:
        return "control"
    for sep in ("_", "-", "."):
        if sep in text:
            return text.split(sep)[0]
    return text


def _base_fields(analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str) -> dict[str, Any]:
    return {
        "module": "perturb_seq",
        "run_id": source_dataset,
        "sample_id": "all",
        "source_dataset": source_dataset,
        "input_artifact": input_artifact,
        "input_modality": "perturb_seq_h5ad_or_assignment_table",
        "analysis_level": analysis_fields.get("analysis_level"),
        "result_scope": "perturb_seq_guide_assignment_mvp",
        "method_status": "fully_automatic_validated_entrypoint",
        "delivery_allowed": analysis_fields.get("delivery_allowed"),
    }


def _first_present_column(obs, *keys: str) -> list[str] | None:
    for key in keys:
        values = _read_obs_column(obs, key)
        if values is not None:
            return values
    return None


def _first_present_numeric_column(obs, *keys: str) -> np.ndarray | None:
    for key in keys:
        values = _read_numeric_obs_column(obs, key)
        if values is not None:
            return values
    return None


def _read_obs_column(obs, key: str) -> list[str] | None:
    if key not in obs:
        return None
    obj = obs[key]
    if hasattr(obj, "keys") and "categories" in obj and "codes" in obj:
        categories = [_decode(value) for value in obj["categories"][()]]
        codes = obj["codes"][()]
        return [categories[int(code)] if int(code) >= 0 else "" for code in codes]
    return [_decode(value) for value in obj[()]]


def _read_numeric_obs_column(obs, key: str) -> np.ndarray | None:
    if key not in obs:
        return None
    obj = obs[key]
    if hasattr(obj, "keys"):
        return None
    return np.asarray(obj[()], dtype=float)


def _h5_length(obj) -> int:
    if obj is None:
        return 0
    if hasattr(obj, "keys") and "codes" in obj:
        return len(obj["codes"])
    return len(obj)


def _x_feature_count(handle) -> int:
    if "X" not in handle:
        return 0
    shape = handle["X"].attrs.get("shape")
    if shape is None or len(shape) < 2:
        return 0
    return int(shape[1])


def _decode(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def _write_tsv(frame: pd.DataFrame, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = _coerce_mvp_table_schema(
        "perturb_seq",
        path.name,
        frame,
        matrix=None,
        samples=None,
        analysis_fields=_analysis_fields_from_frame(frame),
        run_id=_first_frame_value(frame, "run_id"),
        source_dataset=_first_frame_value(frame, "source_dataset"),
        input_artifact=_first_frame_value(frame, "input_artifact"),
        input_modality=_first_frame_value(frame, "input_modality") or "perturb_seq",
    )
    frame.to_csv(path, sep="\t", index=False)
    return str(path)


def _analysis_fields_from_frame(frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "analysis_level": _first_frame_value(frame, "analysis_level") or "not_recorded",
        "delivery_allowed": _first_frame_bool(frame, "delivery_allowed"),
        "validation_evidence_allowed": _first_frame_bool(frame, "validation_evidence_allowed"),
    }


def _first_frame_value(frame: pd.DataFrame, column: str) -> str:
    if column not in frame.columns or frame.empty:
        return ""
    value = frame[column].iloc[0]
    return "" if pd.isna(value) else str(value)


def _first_frame_bool(frame: pd.DataFrame, column: str) -> bool:
    value = _first_frame_value(frame, column).strip().lower()
    return value in {"true", "1", "yes"}
