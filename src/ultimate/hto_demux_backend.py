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


HTO_DEMUX_BACKEND_ID = "hto_demux.default.matrix_assignment_mvp"
HTO_WARNING = "HTO 模块只负责 sample assignment；negative 不能强行分样本，doublet 阈值必须记录。"


def has_hto_demux_backend_config(config: dict[str, Any]) -> bool:
    module_cfg = _module_cfg(config)
    raw_cfg = module_cfg.get("raw") if isinstance(module_cfg.get("raw"), dict) else {}
    keys = {
        "input_table",
        "hto_count_matrix",
        "antibody_capture_matrix",
        "sample_hashtag_mapping",
        "input_path",
    }
    return any(module_cfg.get(key) for key in keys) or any(raw_cfg.get(key) for key in keys)


def run_hto_demux_backend(*, config: dict[str, Any], output_dir: Path, samples: pd.DataFrame) -> dict[str, Any]:
    module_name = "hto_demux"
    tables_dir = output_dir / "results" / "tables" / module_name
    figures_dir = output_dir / "results" / "figures" / module_name
    objects_dir = output_dir / "objects" / module_name
    reports_dir = output_dir / "reports" / module_name
    logs_dir = output_dir / "logs"
    for directory in (tables_dir, figures_dir, objects_dir, reports_dir, logs_dir):
        directory.mkdir(parents=True, exist_ok=True)

    module_cfg = _module_cfg(config)
    input_path = _primary_input_ref(config)
    mapping_path = _mapping_ref(config)
    missing_inputs = _missing_input_reasons(config)
    skip_reasons = list(missing_inputs)
    is_stub = bool(missing_inputs)
    status = "partial:hto_demux_inputs_missing" if missing_inputs else "complete_hto_demux_matrix_backend"
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
        status = "partial:hto_demux_analysis_level_invalid"
        skip_reasons.append(f"analysis_level_invalid:{exc}")
        level_fields = classify_analysis_level(requested_level="smoke_backend", is_stub=True).to_manifest_fields()

    artifacts: dict[str, dict[str, str]] = {"tables": {}, "figures": {}, "objects": {}, "reports": {}}
    warnings = [HTO_WARNING]
    n_cells = 0
    n_tags = 0
    if skip_reasons:
        artifacts.update(_write_skip_outputs(tables_dir=tables_dir, figures_dir=figures_dir, objects_dir=objects_dir, analysis_fields=level_fields))
    else:
        try:
            count_table, tags, read_summary = _read_hto_table(
                input_path,
                max_cells=int(module_cfg.get("max_cells", 5000)),
                seed=int(module_cfg.get("seed", 31)),
            )
            mapping = _read_mapping(mapping_path, tags=tags)
        except Exception as exc:
            status = "partial:hto_demux_input_read_failed"
            skip_reasons.append(f"input_read_failed:{type(exc).__name__}:{exc}")
            level_fields = classify_analysis_level(requested_level="smoke_backend", is_stub=True).to_manifest_fields()
            artifacts.update(_write_skip_outputs(tables_dir=tables_dir, figures_dir=figures_dir, objects_dir=objects_dir, analysis_fields=level_fields))
        else:
            min_positive = float(module_cfg.get("min_positive_count", 20))
            min_margin = float(module_cfg.get("min_margin", 20))
            calls = _call_hto(count_table, tags, mapping=mapping, min_positive=min_positive, min_margin=min_margin)
            artifacts["tables"].update(
                _write_hto_tables(
                    tables_dir=tables_dir,
                    count_table=count_table,
                    calls=calls,
                    tags=tags,
                    input_path=str(input_path or ""),
                    source_dataset=_source_dataset(config),
                    analysis_fields=level_fields,
                    read_summary=read_summary,
                    min_positive=min_positive,
                    min_margin=min_margin,
                )
            )
            artifacts["figures"].update(_write_hto_figures(tables_dir=tables_dir, figures_dir=figures_dir))
            artifacts["objects"].update(
                _write_hto_object(
                    objects_dir=objects_dir,
                    count_table=count_table,
                    calls=calls,
                    tags=tags,
                    input_path=str(input_path or ""),
                    read_summary=read_summary,
                )
            )
            n_cells = int(count_table.shape[0])
            n_tags = int(len(tags))

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
        "input_table": str(input_path or ""),
        "sample_hashtag_mapping": str(mapping_path or ""),
        "n_cells": n_cells,
        "n_features": n_tags,
        "artifacts": artifacts,
        "warnings": warnings,
        "limitations": list(known_limitations(module_name)),
        "handoff": handoff_plan(module_name),
        "reproducible_command": f"ultimate run --config {config.get('_config_path', '<config.yaml>')}",
        "backend": {
            "primary": "hto_matrix_thresholding",
            "selected_backend_id": backend_plan["selected_backend_id"],
            "selected_backend_status": backend_plan["selected_backend_status"],
            "backend_role": backend_plan["selected_backend_role"],
            "resource_profile": backend_plan["backend_resource_profile"],
            "assignment_warning": HTO_WARNING,
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
            "python_entrypoint": "ultimate.hto_demux_backend.run_hto_demux_backend",
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
    return ((config.get("modules") or {}).get("hto_demux") or {}) if isinstance(config.get("modules"), dict) else {}


def _module_is_demo(config: dict[str, Any], module_cfg: dict[str, Any]) -> bool | None:
    if "is_demo" in module_cfg:
        return bool(module_cfg.get("is_demo"))
    project = config.get("project") or {}
    if "is_demo" in project:
        return bool(project.get("is_demo"))
    return None


def _source_dataset(config: dict[str, Any]) -> str:
    project = config.get("project") or {}
    return str(project.get("name") or project.get("job_id") or "hto_demux")


def _primary_input_ref(config: dict[str, Any]) -> Path | None:
    module_cfg = _module_cfg(config)
    raw_cfg = module_cfg.get("raw") if isinstance(module_cfg.get("raw"), dict) else {}
    base = Path(str(config.get("_config_path") or ".")).resolve().parent
    value = (
        module_cfg.get("input_table")
        or module_cfg.get("hto_count_matrix")
        or module_cfg.get("antibody_capture_matrix")
        or module_cfg.get("input_path")
        or raw_cfg.get("input_path")
        or raw_cfg.get("input_table")
        or raw_cfg.get("hto_count_matrix")
    )
    return _resolve_path(base, value) if value else None


def _mapping_ref(config: dict[str, Any]) -> Path | None:
    module_cfg = _module_cfg(config)
    raw_cfg = module_cfg.get("raw") if isinstance(module_cfg.get("raw"), dict) else {}
    base = Path(str(config.get("_config_path") or ".")).resolve().parent
    value = module_cfg.get("sample_hashtag_mapping") or raw_cfg.get("sample_hashtag_mapping")
    return _resolve_path(base, value) if value else None


def _missing_input_reasons(config: dict[str, Any]) -> list[str]:
    input_path = _primary_input_ref(config)
    if input_path is None:
        return ["missing_hto_count_matrix"]
    if not input_path.exists():
        return [f"missing_input_path:{input_path}"]
    if input_path.suffix.lower() not in {".tsv", ".txt", ".csv"}:
        return [f"unsupported_input_extension:{input_path.suffix or 'none'}"]
    mapping_path = _mapping_ref(config)
    if mapping_path is not None and not mapping_path.exists():
        return [f"missing_sample_hashtag_mapping:{mapping_path}"]
    return []


def _resolve_path(base: Path, value: Any) -> Path:
    candidate = Path(str(value))
    return candidate if candidate.is_absolute() else (base / candidate).resolve()


def _read_hto_table(path: Path | None, *, max_cells: int, seed: int) -> tuple[pd.DataFrame, list[str], dict[str, Any]]:
    if path is None:
        raise ValueError("input_path_missing")
    sep = "\t" if path.suffix.lower() in {".tsv", ".txt"} else ","
    frame = pd.read_csv(path, sep=sep)
    if frame.empty:
        raise ValueError(f"HTO count matrix is empty: {path}")
    first = frame.columns[0]
    if first != "cell_id":
        frame = frame.rename(columns={first: "cell_id"})
    tags = [column for column in frame.columns if column != "cell_id" and _is_hto_tag_column(column)]
    if not tags:
        raise ValueError(f"No HTO tag columns found in {path}")
    frame[tags] = frame[tags].apply(pd.to_numeric, errors="coerce").fillna(0)
    original_n_cells = int(frame.shape[0])
    if original_n_cells > max_cells:
        frame = frame.sample(n=max_cells, random_state=seed).sort_values("cell_id").reset_index(drop=True)
    return frame, tags, {"original_n_cells": original_n_cells, "max_cells": int(max_cells), "sampling_seed": int(seed)}


def _is_hto_tag_column(column: str) -> bool:
    lowered = str(column).strip().lower()
    summary_columns = {
        "total_reads",
        "total_counts",
        "n_counts",
        "ncount_hto",
        "nfeature_hto",
        "no_match",
        "ambiguous",
        "bad_struct",
        "unmapped",
        "unknown",
    }
    return lowered not in summary_columns and not lowered.startswith(("total_", "n_count", "n_feature"))


def _read_mapping(path: Path | None, *, tags: list[str]) -> dict[str, str]:
    if path is None:
        return {tag: tag for tag in tags}
    sep = "\t" if path.suffix.lower() in {".tsv", ".txt"} else ","
    frame = pd.read_csv(path, sep=sep)
    tag_col = "hashtag_id" if "hashtag_id" in frame.columns else "hto_tag" if "hto_tag" in frame.columns else frame.columns[0]
    sample_col = "sample_id" if "sample_id" in frame.columns else "sample" if "sample" in frame.columns else frame.columns[-1]
    mapping = {str(row[tag_col]): str(row[sample_col]) for _, row in frame.iterrows()}
    return {tag: mapping.get(tag, tag) for tag in tags}


def _call_hto(
    count_table: pd.DataFrame,
    tags: list[str],
    *,
    mapping: dict[str, str],
    min_positive: float,
    min_margin: float,
) -> pd.DataFrame:
    values = count_table[tags].to_numpy(dtype=float)
    order = np.argsort(values, axis=1)
    top_idx = order[:, -1]
    second_idx = order[:, -2] if values.shape[1] > 1 else order[:, -1]
    top = values[np.arange(values.shape[0]), top_idx]
    second = values[np.arange(values.shape[0]), second_idx] if values.shape[1] > 1 else np.zeros(values.shape[0])
    margin = top - second
    top_tags = np.array(tags, dtype=object)[top_idx]
    assignment_class = np.where(top < min_positive, "negative", np.where(margin < min_margin, "doublet", "singlet"))
    assigned_sample = [mapping.get(tag, tag) if cls == "singlet" else cls for tag, cls in zip(top_tags, assignment_class, strict=False)]
    confidence = np.where(assignment_class == "singlet", margin / np.maximum(top, 1), 0.0)
    return pd.DataFrame(
        {
            "cell_id": count_table["cell_id"].astype(str),
            "hashtag_id": top_tags,
            "assigned_sample": assigned_sample,
            "assignment_class": assignment_class,
            "confidence": np.round(confidence, 4),
            "top_count": top,
            "second_count": second,
            "call_margin": margin,
            "threshold_note": f"singlet if top>={min_positive:g} and margin>={min_margin:g}; otherwise doublet/negative",
        }
    )


def _write_hto_tables(
    *,
    tables_dir: Path,
    count_table: pd.DataFrame,
    calls: pd.DataFrame,
    tags: list[str],
    input_path: str,
    source_dataset: str,
    analysis_fields: dict[str, Any],
    read_summary: dict[str, Any],
    min_positive: float,
    min_margin: float,
) -> dict[str, str]:
    paths: dict[str, str] = {}
    base = _base_fields(analysis_fields, input_path, source_dataset)
    counts = count_table.copy()
    counts.to_csv(tables_dir / "hashtag_counts.tsv", sep="\t", index=False)

    positive_counts = (count_table[tags] >= min_positive).sum(axis=1)
    qc = pd.DataFrame(
        {
            **base,
            "cell_id": count_table["cell_id"].astype(str),
            "total_hto_counts": count_table[tags].sum(axis=1),
            "background_status": np.where(count_table[tags].max(axis=1) < min_positive, "negative_or_low_signal", "signal_detected"),
            "positive_hashtag_count": positive_counts,
            "delivery_allowed": analysis_fields.get("delivery_allowed"),
        }
    )
    paths["hto_qc"] = _write_tsv(qc, tables_dir / "hto_qc.tsv")

    assignment = calls[["cell_id", "hashtag_id", "assigned_sample", "assignment_class", "confidence", "threshold_note"]].copy()
    assignment.insert(0, "module", "hto_demux")
    paths["hto_assignment"] = _write_tsv(assignment, tables_dir / "hto_assignment.tsv")

    sample_rows = []
    for sample_id, group in calls.groupby("assigned_sample", observed=False):
        sample_rows.append(
            {
                **base,
                "sample_id": sample_id,
                "singlet_count": int((group["assignment_class"] == "singlet").sum()),
                "doublet_count": int((group["assignment_class"] == "doublet").sum()),
                "negative_count": int((group["assignment_class"] == "negative").sum()),
                "assignment_status": "threshold_assignment",
            }
        )
    paths["sample_assignment_summary"] = _write_tsv(pd.DataFrame(sample_rows), tables_dir / "sample_assignment_summary.tsv")

    doublet_rows = []
    for sample_id, group in calls.groupby("assigned_sample", observed=False):
        total = max(int(group.shape[0]), 1)
        doublets = int((group["assignment_class"] == "doublet").sum())
        doublet_rows.append(
            {
                **base,
                "sample_id": sample_id,
                "hto_doublet_count": doublets,
                "doublet_rate": doublets / total,
                "threshold_note": f"margin < {min_margin:g}",
            }
        )
    paths["doublet_summary"] = _write_tsv(pd.DataFrame(doublet_rows), tables_dir / "doublet_summary.tsv")

    metadata = calls[["cell_id", "assigned_sample", "assignment_class", "confidence"]].copy()
    metadata["metadata_handoff_status"] = "ready_for_scrna_metadata_join"
    metadata.insert(0, "module", "hto_demux")
    paths["cell_metadata_with_sample"] = _write_tsv(metadata, tables_dir / "cell_metadata_with_sample.tsv")

    tag_summary = count_table[tags].agg(["mean", "median", "max"]).T.reset_index().rename(columns={"index": "hashtag_id"})
    tag_summary["detected_cell_fraction"] = (count_table[tags].to_numpy() > 0).mean(axis=0)
    tag_summary["input_original_n_cells"] = read_summary.get("original_n_cells")
    tag_summary.insert(0, "module", "hto_demux")
    paths["hto_tag_qc_summary"] = _write_tsv(tag_summary, tables_dir / "hto_tag_qc_summary.tsv")
    return paths


def _write_hto_figures(*, tables_dir: Path, figures_dir: Path) -> dict[str, str]:
    tokens = apply_clinical_journal_style()
    paths: dict[str, str] = {}
    qc = pd.read_csv(tables_dir / "hto_qc.tsv", sep="\t")
    assignment = pd.read_csv(tables_dir / "hto_assignment.tsv", sep="\t")
    counts = pd.read_csv(tables_dir / "hashtag_counts.tsv", sep="\t")
    tag_cols = [column for column in counts.columns if column != "cell_id"]

    fig, ax = plt.subplots(figsize=(7, 4.2))
    ax.hist(np.log1p(qc["total_hto_counts"]), bins=35, color="#547AA5", edgecolor="white", linewidth=0.4)
    ax.set_xlabel("log1p(total HTO counts)")
    ax.set_ylabel("Cells")
    ax.set_title("HTO count distribution")
    density_path = figures_dir / "hto_density.png"
    save_figure(density_path, style=tokens)
    paths["hto_density"] = str(density_path)

    sampled = counts.head(120).set_index("cell_id")[tag_cols]
    fig, ax = plt.subplots(figsize=(7.5, 5))
    im = ax.imshow(np.log1p(sampled), aspect="auto", cmap="viridis")
    fig.colorbar(im, ax=ax, label="log1p(count)")
    ax.set_yticks([])
    ax.set_xticks(range(len(tag_cols)))
    ax.set_xticklabels(tag_cols, rotation=25, ha="right")
    ax.set_title("HTO count heatmap")
    heatmap_path = figures_dir / "hto_heatmap.png"
    save_figure(heatmap_path, style=tokens)
    paths["hto_heatmap"] = str(heatmap_path)

    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    order = assignment["assignment_class"].value_counts().index.tolist()
    counts_by_class = assignment["assignment_class"].value_counts().reindex(order)
    ax.bar(counts_by_class.index, counts_by_class.values, color=["#547AA5", "#C97064", "#7B8F67"][: len(counts_by_class)])
    ax.set_ylabel("Cells")
    ax.set_title("HTO assignment classes")
    classes_path = figures_dir / "hto_assignment_classes.png"
    save_figure(classes_path, style=tokens)
    paths["hto_assignment_classes"] = str(classes_path)
    return paths


def _write_hto_object(
    *,
    objects_dir: Path,
    count_table: pd.DataFrame,
    calls: pd.DataFrame,
    tags: list[str],
    input_path: str,
    read_summary: dict[str, Any],
) -> dict[str, str]:
    path = objects_dir / "hto_demux_mvp_object.rds"
    payload = {
        "object_type": "json_serialized_hto_demux_mvp",
        "input_path": input_path,
        "n_cells": int(count_table.shape[0]),
        "n_tags": int(len(tags)),
        "tags": tags,
        "assignment_counts": calls["assignment_class"].value_counts().to_dict(),
        **read_summary,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"mvp_object": str(path)}


def _write_skip_outputs(*, tables_dir: Path, figures_dir: Path, objects_dir: Path, analysis_fields: dict[str, Any]) -> dict[str, dict[str, str]]:
    base = {
        "module": "hto_demux",
        "analysis_level": analysis_fields.get("analysis_level"),
        "delivery_allowed": analysis_fields.get("delivery_allowed"),
        "skip_status": "skipped_no_valid_hto_input",
    }
    artifacts = {"tables": {}, "figures": {}, "objects": {}, "reports": {}}
    for name in ("hto_qc", "hto_assignment", "sample_assignment_summary", "doublet_summary", "cell_metadata_with_sample"):
        artifacts["tables"][name] = _write_tsv(pd.DataFrame([base]), tables_dir / f"{name}.tsv")
    fig, ax = plt.subplots(figsize=(5, 3))
    ax.text(0.5, 0.5, "HTO input missing", ha="center", va="center")
    ax.axis("off")
    density_path = figures_dir / "hto_density.png"
    save_figure(density_path, style=apply_clinical_journal_style())
    artifacts["figures"]["hto_density"] = str(density_path)
    fig, ax = plt.subplots(figsize=(5, 3))
    ax.text(0.5, 0.5, "HTO input missing", ha="center", va="center")
    ax.axis("off")
    heatmap_path = figures_dir / "hto_heatmap.png"
    save_figure(heatmap_path, style=apply_clinical_journal_style())
    artifacts["figures"]["hto_heatmap"] = str(heatmap_path)
    object_path = objects_dir / "hto_demux_mvp_object.rds"
    object_path.write_text(json.dumps(base, indent=2, ensure_ascii=False), encoding="utf-8")
    artifacts["objects"]["mvp_object"] = str(object_path)
    return artifacts


def _base_fields(analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str) -> dict[str, Any]:
    return {
        "module": "hto_demux",
        "run_id": source_dataset,
        "sample_id": "all",
        "source_dataset": source_dataset,
        "input_artifact": input_artifact,
        "input_modality": "hto_count_matrix",
        "analysis_level": analysis_fields.get("analysis_level"),
        "result_scope": "hto_demux_matrix_assignment_mvp",
        "method_status": "fully_automatic_validated_entrypoint",
        "delivery_allowed": analysis_fields.get("delivery_allowed"),
    }


def _write_tsv(frame: pd.DataFrame, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = _coerce_mvp_table_schema(
        "hto_demux",
        path.name,
        frame,
        matrix=None,
        samples=None,
        analysis_fields=_analysis_fields_from_frame(frame),
        run_id=_first_frame_value(frame, "run_id"),
        source_dataset=_first_frame_value(frame, "source_dataset"),
        input_artifact=_first_frame_value(frame, "input_artifact"),
        input_modality=_first_frame_value(frame, "input_modality") or "hto_demux",
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
