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


METHOD_TOOLS_BACKEND_ID = "method_tools.default.delivery_manifest_mvp"
METHOD_TOOLS_WARNING = "交互式浏览器只是展示，不改变分析结论；公开交付前必须脱敏 metadata。"
SENSITIVE_TOKENS = ("name", "patient", "phone", "email", "address", "id_card", "身份证", "姓名", "电话", "邮箱")


def has_method_tools_backend_config(config: dict[str, Any]) -> bool:
    module_cfg = _module_cfg(config)
    raw_cfg = module_cfg.get("raw") if isinstance(module_cfg.get("raw"), dict) else {}
    keys = {
        "input_h5ad",
        "input_h5mu",
        "input_path",
        "object_path",
        "figures_dir",
        "tables_dir",
        "source_run_dir",
    }
    return any(module_cfg.get(key) for key in keys) or any(raw_cfg.get(key) for key in keys)


def run_method_tools_backend(*, config: dict[str, Any], output_dir: Path, samples: pd.DataFrame) -> dict[str, Any]:
    module_name = "method_tools"
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
    is_stub = bool(missing_inputs)
    status = "partial:method_tools_inputs_missing" if missing_inputs else "complete_method_tools_delivery_backend"
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
        status = "partial:method_tools_analysis_level_invalid"
        missing_inputs.append(f"analysis_level_invalid:{exc}")
        level_fields = classify_analysis_level(requested_level="smoke_backend", is_stub=True).to_manifest_fields()

    artifacts: dict[str, dict[str, str]] = {"tables": {}, "figures": {}, "objects": {}, "reports": {}}
    warnings = [METHOD_TOOLS_WARNING]
    n_obs = 0
    n_vars = 0
    if missing_inputs:
        artifacts.update(_write_skip_outputs(tables_dir=tables_dir, figures_dir=figures_dir, objects_dir=objects_dir, analysis_fields=level_fields))
    else:
        try:
            data = _load_object(input_path, max_cells=int(module_cfg.get("max_cells_object", 3000)))
        except Exception as exc:
            status = "partial:method_tools_input_read_failed"
            missing_inputs.append(f"input_read_failed:{type(exc).__name__}:{exc}")
            level_fields = classify_analysis_level(requested_level="smoke_backend", is_stub=True).to_manifest_fields()
            artifacts.update(_write_skip_outputs(tables_dir=tables_dir, figures_dir=figures_dir, objects_dir=objects_dir, analysis_fields=level_fields))
            data = None
        if data is not None:
            n_obs = int(data["n_obs"])
            n_vars = int(data["n_vars"])
            tables = _write_method_tables(
                tables_dir=tables_dir,
                figures_root=output_dir / "results" / "figures",
                tables_root=output_dir / "results" / "tables",
                obs=data["obs"],
                input_path=str(input_path or ""),
                analysis_fields=level_fields,
                source_dataset=_source_dataset(config),
            )
            artifacts["tables"].update(tables)
            artifacts["figures"].update(_write_method_figures(tables_dir=tables_dir, figures_dir=figures_dir))
            artifacts["objects"].update(_write_cellxgene_ready_object(objects_dir=objects_dir, data=data))

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
        "input_path": str(input_path or ""),
        "n_cells": n_obs,
        "n_features": n_vars,
        "artifacts": artifacts,
        "warnings": warnings,
        "limitations": list(known_limitations(module_name)),
        "handoff": handoff_plan(module_name),
        "reproducible_command": f"ultimate run --config {config.get('_config_path', '<config.yaml>')}",
        "backend": {
            "primary": "method_tools_delivery_mvp",
            "selected_backend_id": backend_plan["selected_backend_id"],
            "selected_backend_status": backend_plan["selected_backend_status"],
            "backend_role": backend_plan["selected_backend_role"],
            "resource_profile": backend_plan["backend_resource_profile"],
            "privacy_warning": METHOD_TOOLS_WARNING,
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
            "python_entrypoint": "ultimate.method_tools_backend.run_method_tools_backend",
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
    return ((config.get("modules") or {}).get("method_tools") or {}) if isinstance(config.get("modules"), dict) else {}


def _module_is_demo(config: dict[str, Any], module_cfg: dict[str, Any]) -> bool | None:
    if "is_demo" in module_cfg:
        return bool(module_cfg.get("is_demo"))
    project = config.get("project") or {}
    if "is_demo" in project:
        return bool(project.get("is_demo"))
    return None


def _source_dataset(config: dict[str, Any]) -> str:
    project = config.get("project") or {}
    return str(project.get("name") or project.get("job_id") or "method_tools")


def _primary_input_ref(config: dict[str, Any]) -> Path | None:
    module_cfg = _module_cfg(config)
    raw_cfg = module_cfg.get("raw") if isinstance(module_cfg.get("raw"), dict) else {}
    base = Path(str(config.get("_config_path") or ".")).resolve().parent
    value = (
        module_cfg.get("input_h5ad")
        or module_cfg.get("input_h5mu")
        or module_cfg.get("object_path")
        or module_cfg.get("input_path")
        or raw_cfg.get("input_path")
    )
    return _resolve_path(base, value) if value else None


def _missing_input_reasons(config: dict[str, Any]) -> list[str]:
    input_path = _primary_input_ref(config)
    if input_path is None:
        return ["missing_input_h5ad_or_object_path"]
    if not input_path.exists():
        return [f"missing_input_path:{input_path}"]
    if input_path.suffix.lower() not in {".h5ad", ".h5mu"}:
        return [f"unsupported_input_extension:{input_path.suffix or 'none'}"]
    return []


def _resolve_path(base: Path, value: Any) -> Path:
    candidate = Path(str(value))
    return candidate if candidate.is_absolute() else (base / candidate).resolve()


def _load_object(path: Path | None, *, max_cells: int) -> dict[str, Any]:
    if path is None:
        raise ValueError("input_path_missing")
    if path.suffix.lower() == ".h5mu":
        import mudata as md

        mdata = md.read_h5mu(path)
        first = next(iter(mdata.mod.keys()))
        adata = mdata.mod[first]
    else:
        import anndata as ad

        adata = ad.read_h5ad(path)
    if adata.n_obs > max_cells:
        rng = np.random.default_rng(11)
        selected = np.sort(rng.choice(adata.n_obs, size=max_cells, replace=False))
        adata = adata[selected].copy()
    else:
        adata = adata.copy()
    adata.var_names_make_unique()
    obs = _obs_with_cell_barcode(adata.obs, adata.obs_names.astype(str))
    return {"adata": adata, "obs": obs, "n_obs": int(adata.n_obs), "n_vars": int(adata.n_vars)}


def _obs_with_cell_barcode(obs: pd.DataFrame, obs_names: pd.Index) -> pd.DataFrame:
    metadata = obs.copy()
    barcode_column = "cell_id"
    if barcode_column in metadata.columns:
        barcode_column = "cell_barcode"
    suffix = 1
    while barcode_column in metadata.columns:
        barcode_column = f"cell_barcode_{suffix}"
        suffix += 1
    metadata.insert(0, barcode_column, obs_names.astype(str))
    return metadata


def _write_method_tables(
    *,
    tables_dir: Path,
    figures_root: Path,
    tables_root: Path,
    obs: pd.DataFrame,
    input_path: str,
    analysis_fields: dict[str, Any],
    source_dataset: str,
) -> dict[str, str]:
    paths: dict[str, str] = {}
    figures = _index_files(figures_root, "*.png")
    tables = _index_files(tables_root, "*.tsv")
    paths["figure_index"] = _write_tsv(_index_frame(figures, "figure", analysis_fields, input_path, source_dataset), tables_dir / "figure_index.tsv")
    paths["table_index"] = _write_tsv(_index_frame(tables, "table", analysis_fields, input_path, source_dataset), tables_dir / "table_index.tsv")
    paths["sensitive_metadata_scan"] = _write_tsv(_sensitive_scan(obs, analysis_fields, input_path, source_dataset), tables_dir / "sensitive_metadata_scan.tsv")
    paths["cellxgene_compatibility"] = _write_tsv(_cellxgene_compatibility(obs, analysis_fields, input_path, source_dataset), tables_dir / "cellxgene_compatibility.tsv")
    delivery_manifest = _delivery_manifest(figures=figures, tables=tables, analysis_fields=analysis_fields, input_path=input_path, source_dataset=source_dataset)
    delivery_manifest_path = tables_dir / "delivery_manifest.json"
    delivery_manifest_path.write_text(json.dumps(delivery_manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    paths["delivery_manifest_json"] = str(delivery_manifest_path)
    paths["delivery_manifest_index"] = _write_tsv(
        pd.DataFrame(
            [
                {
                    **_base_fields(analysis_fields, input_path, source_dataset),
                    "manifest_key": key,
                    "manifest_value": json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value,
                }
                for key, value in delivery_manifest.items()
            ]
        ),
        tables_dir / "delivery_manifest_index.tsv",
    )
    return paths


def _index_files(root: Path, pattern: str) -> list[Path]:
    if not root.exists():
        return []
    return sorted(path for path in root.rglob(pattern) if path.is_file() and path.stat().st_size > 0)


def _base_fields(analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str) -> dict[str, Any]:
    return {
        "module": "method_tools",
        "run_id": source_dataset,
        "sample_id": "all",
        "source_dataset": source_dataset,
        "input_artifact": input_artifact,
        "input_modality": "h5ad_or_h5mu",
        "analysis_level": analysis_fields.get("analysis_level"),
        "result_scope": "method_tools_delivery_mvp",
        "method_status": "fully_automatic_validated_entrypoint",
        "delivery_allowed": analysis_fields.get("delivery_allowed"),
    }


def _index_frame(paths: list[Path], category: str, analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str) -> pd.DataFrame:
    rows = []
    for idx, path in enumerate(paths, 1):
        row = _base_fields(analysis_fields, input_artifact, source_dataset)
        row.update({"artifact_id": f"{category}_{idx:04d}", "category": category, "path": str(path), "size_bytes": int(path.stat().st_size)})
        rows.append(row)
    if not rows:
        row = _base_fields(analysis_fields, input_artifact, source_dataset)
        row.update({"artifact_id": f"{category}_0000", "category": category, "path": "", "size_bytes": 0})
        rows.append(row)
    return pd.DataFrame(rows)


def _sensitive_scan(obs: pd.DataFrame, analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str) -> pd.DataFrame:
    rows = []
    for column in obs.columns:
        text = str(column).lower()
        matched = [token for token in SENSITIVE_TOKENS if token.lower() in text]
        sample_values = obs[column].dropna().astype(str).head(5).tolist()
        row = _base_fields(analysis_fields, input_artifact, source_dataset)
        row.update(
            {
                "metadata_field": column,
                "sensitive_flag": bool(matched),
                "matched_tokens": ",".join(matched),
                "non_null_count": int(obs[column].notna().sum()),
                "example_values_redacted": ";".join("[redacted]" if matched else value[:40] for value in sample_values),
                "privacy_action": "review_or_remove_before_public_delivery" if matched else "ok",
            }
        )
        rows.append(row)
    return pd.DataFrame(rows or [{**_base_fields(analysis_fields, input_artifact, source_dataset), "metadata_field": "", "sensitive_flag": False, "matched_tokens": "", "non_null_count": 0, "example_values_redacted": "", "privacy_action": "ok"}])


def _cellxgene_compatibility(obs: pd.DataFrame, analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str) -> pd.DataFrame:
    row = _base_fields(analysis_fields, input_artifact, source_dataset)
    row.update(
        {
            "object_format": Path(input_artifact).suffix.lower().lstrip(".") or "unknown",
            "obs_column_count": int(obs.shape[1]),
            "cellxgene_ready_status": "ready_h5ad_copy" if input_artifact.endswith(".h5ad") else "partial:converted_modality_preview",
            "metadata_cleanup_required": bool(_sensitive_scan(obs, analysis_fields, input_artifact, source_dataset)["sensitive_flag"].any()),
            "browser_warning": METHOD_TOOLS_WARNING,
        }
    )
    return pd.DataFrame([row])


def _delivery_manifest(*, figures: list[Path], tables: list[Path], analysis_fields: dict[str, Any], input_path: str, source_dataset: str) -> dict[str, Any]:
    return {
        "module": "method_tools",
        "source_dataset": source_dataset,
        "input_path": input_path,
        "analysis_level": analysis_fields.get("analysis_level"),
        "delivery_allowed": analysis_fields.get("delivery_allowed"),
        "figure_count": len(figures),
        "table_count": len(tables),
        "privacy_policy": METHOD_TOOLS_WARNING,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _write_method_figures(*, tables_dir: Path, figures_dir: Path) -> dict[str, str]:
    tokens = apply_clinical_journal_style()
    table_index = pd.read_csv(tables_dir / "table_index.tsv", sep="\t")
    figure_index = pd.read_csv(tables_dir / "figure_index.tsv", sep="\t")
    path = figures_dir / "figure_index_overview.png"
    frame = pd.DataFrame(
        {
            "category": ["figures", "tables"],
            "count": [int((figure_index["path"].astype(str) != "").sum()), int((table_index["path"].astype(str) != "").sum())],
        }
    )
    plt.figure(figsize=(5, 3.8))
    plt.bar(frame["category"], frame["count"], color=[tokens["primary"], tokens["case"]])
    plt.ylabel("Artifact count")
    plt.title("Delivery Artifact Index")
    plt.tight_layout()
    save_figure(path, style=tokens)
    return {"figure_index_overview": str(path)}


def _write_cellxgene_ready_object(*, objects_dir: Path, data: dict[str, Any]) -> dict[str, str]:
    path = objects_dir / "cellxgene_ready.h5ad"
    data["adata"].write_h5ad(path)
    manifest = {
        "module": "method_tools",
        "object_name": "cellxgene_ready.h5ad",
        "status": "cellxgene_ready_reference_object",
        "n_cells": data["n_obs"],
        "n_features": data["n_vars"],
        "warning": METHOD_TOOLS_WARNING,
    }
    manifest_path = objects_dir / "cellxgene_ready_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"cellxgene_ready": str(path), "mvp_object": str(path), "cellxgene_ready_manifest": str(manifest_path)}


def _write_skip_outputs(*, tables_dir: Path, figures_dir: Path, objects_dir: Path, analysis_fields: dict[str, Any]) -> dict[str, dict[str, str]]:
    base = _base_fields(analysis_fields, "", "method_tools")
    tables = {
        "figure_index": tables_dir / "figure_index.tsv",
        "table_index": tables_dir / "table_index.tsv",
        "sensitive_metadata_scan": tables_dir / "sensitive_metadata_scan.tsv",
        "cellxgene_compatibility": tables_dir / "cellxgene_compatibility.tsv",
        "delivery_manifest_index": tables_dir / "delivery_manifest_index.tsv",
    }
    for key, path in tables.items():
        pd.DataFrame([{**base, "artifact": key, "status": "skipped_missing_input", "delivery_allowed": False}]).to_csv(path, sep="\t", index=False)
    (tables_dir / "delivery_manifest.json").write_text(json.dumps({**base, "status": "skipped_missing_input"}, indent=2, ensure_ascii=False), encoding="utf-8")
    figure = figures_dir / "figure_index_overview.png"
    plt.figure(figsize=(5, 3))
    plt.text(0.5, 0.5, "method_tools skipped", ha="center", va="center")
    plt.axis("off")
    plt.tight_layout()
    plt.savefig(figure, dpi=160)
    plt.close()
    obj = objects_dir / "cellxgene_ready.h5ad"
    obj.write_text(json.dumps({**base, "status": "skipped_missing_input"}, ensure_ascii=False), encoding="utf-8")
    return {
        "tables": {key: str(path) for key, path in tables.items()} | {"delivery_manifest_json": str(tables_dir / "delivery_manifest.json")},
        "figures": {"figure_index_overview": str(figure)},
        "objects": {"cellxgene_ready": str(obj), "mvp_object": str(obj)},
    }


def _write_tsv(frame: pd.DataFrame, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = _coerce_mvp_table_schema(
        "method_tools",
        path.name,
        frame,
        matrix=None,
        samples=None,
        analysis_fields=_analysis_fields_from_frame(frame),
        run_id=_first_frame_value(frame, "run_id"),
        source_dataset=_first_frame_value(frame, "source_dataset"),
        input_artifact=_first_frame_value(frame, "input_artifact"),
        input_modality=_first_frame_value(frame, "input_modality") or "method_tools",
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
