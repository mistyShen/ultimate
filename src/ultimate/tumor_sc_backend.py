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


TUMOR_SC_BACKEND_ID = "tumor_sc.default.summary_handoff"
TUMOR_SC_WARNING = "malignant calling 不能只靠 marker；inferCNV/CopyKAT 是 transcriptome-inferred CNV，不是 DNA 金标准。"


def has_tumor_sc_backend_config(config: dict[str, Any]) -> bool:
    module_cfg = _module_cfg(config)
    raw_cfg = module_cfg.get("raw") if isinstance(module_cfg.get("raw"), dict) else {}
    keys = {
        "input_h5ad",
        "input_path",
        "metadata_table",
        "cell_metadata",
        "cnv_result",
        "copykat_result",
        "infercnv_result",
    }
    return any(module_cfg.get(key) for key in keys) or any(raw_cfg.get(key) for key in keys)


def run_tumor_sc_backend(*, config: dict[str, Any], output_dir: Path, samples: pd.DataFrame) -> dict[str, Any]:
    module_name = "tumor_sc"
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
    skip_reasons = list(missing_inputs)
    is_stub = bool(missing_inputs)
    status = "partial:tumor_sc_inputs_missing" if missing_inputs else "complete_tumor_sc_summary_backend"
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
        status = "partial:tumor_sc_analysis_level_invalid"
        skip_reasons.append(f"analysis_level_invalid:{exc}")
        level_fields = classify_analysis_level(requested_level="smoke_backend", is_stub=True).to_manifest_fields()

    artifacts: dict[str, dict[str, str]] = {"tables": {}, "figures": {}, "objects": {}, "reports": {}}
    warnings = [TUMOR_SC_WARNING]
    n_cells = 0
    n_malignant_candidates = 0
    if skip_reasons:
        artifacts.update(_write_skip_outputs(tables_dir=tables_dir, figures_dir=figures_dir, objects_dir=objects_dir, analysis_fields=level_fields))
    else:
        try:
            data = _read_tumor_input(config)
        except Exception as exc:
            status = "partial:tumor_sc_input_read_failed"
            skip_reasons.append(f"input_read_failed:{type(exc).__name__}:{exc}")
            level_fields = classify_analysis_level(requested_level="smoke_backend", is_stub=True).to_manifest_fields()
            artifacts.update(_write_skip_outputs(tables_dir=tables_dir, figures_dir=figures_dir, objects_dir=objects_dir, analysis_fields=level_fields))
            data = None
        if data is not None:
            artifacts["tables"].update(
                _write_tumor_tables(
                    tables_dir=tables_dir,
                    data=data,
                    input_ref=str(input_ref or ""),
                    source_dataset=_source_dataset(config),
                    analysis_fields=level_fields,
                )
            )
            artifacts["figures"].update(_write_tumor_figures(tables_dir=tables_dir, figures_dir=figures_dir))
            artifacts["objects"].update(_write_tumor_object(objects_dir=objects_dir, data=data, input_ref=str(input_ref or "")))
            n_cells = int(data["cells"].shape[0])
            n_malignant_candidates = int(data["malignant"]["malignant_candidate"].sum()) if not data["malignant"].empty else 0

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
        "input_ref": str(input_ref or ""),
        "n_cells": n_cells,
        "n_malignant_candidates": n_malignant_candidates,
        "artifacts": artifacts,
        "warnings": warnings,
        "limitations": list(known_limitations(module_name)),
        "handoff": handoff_plan(module_name),
        "reproducible_command": f"ultimate run --config {config.get('_config_path', '<config.yaml>')}",
        "backend": {
            "primary": "tumor_sc_summary_handoff",
            "selected_backend_id": backend_plan["selected_backend_id"],
            "selected_backend_status": backend_plan["selected_backend_status"],
            "backend_role": backend_plan["selected_backend_role"],
            "resource_profile": backend_plan["backend_resource_profile"],
            "interpretation_warning": TUMOR_SC_WARNING,
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
            "python_entrypoint": "ultimate.tumor_sc_backend.run_tumor_sc_backend",
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
    return ((config.get("modules") or {}).get("tumor_sc") or {}) if isinstance(config.get("modules"), dict) else {}


def _module_is_demo(config: dict[str, Any], module_cfg: dict[str, Any]) -> bool | None:
    if "is_demo" in module_cfg:
        return bool(module_cfg.get("is_demo"))
    project = config.get("project") or {}
    if "is_demo" in project:
        return bool(project.get("is_demo"))
    return None


def _source_dataset(config: dict[str, Any]) -> str:
    project = config.get("project") or {}
    return str(project.get("name") or project.get("job_id") or "tumor_sc")


def _primary_input_ref(config: dict[str, Any]) -> Path | None:
    module_cfg = _module_cfg(config)
    raw_cfg = module_cfg.get("raw") if isinstance(module_cfg.get("raw"), dict) else {}
    base = Path(str(config.get("_config_path") or ".")).resolve().parent
    value = (
        module_cfg.get("input_h5ad")
        or module_cfg.get("input_path")
        or module_cfg.get("metadata_table")
        or module_cfg.get("cell_metadata")
        or raw_cfg.get("input_h5ad")
        or raw_cfg.get("input_path")
        or raw_cfg.get("metadata_table")
    )
    return _resolve_path(base, value) if value else None


def _resolve_path(base: Path, value: Any) -> Path:
    candidate = Path(str(value))
    return candidate if candidate.is_absolute() else (base / candidate).resolve()


def _missing_input_reasons(config: dict[str, Any]) -> list[str]:
    input_ref = _primary_input_ref(config)
    if input_ref is None:
        return ["missing_tumor_sc_input"]
    if not input_ref.exists():
        return [f"missing_input_path:{input_ref}"]
    if input_ref.is_file() and input_ref.suffix.lower() not in {".h5ad", ".tsv", ".csv", ".txt"}:
        return [f"unsupported_input_extension:{input_ref.suffix or 'none'}"]
    return []


def _read_tumor_input(config: dict[str, Any]) -> dict[str, Any]:
    input_ref = _primary_input_ref(config)
    if input_ref is None:
        raise ValueError("input_ref_missing")
    module_cfg = _module_cfg(config)
    max_cells = int(module_cfg.get("max_cells", 6000))
    if input_ref.suffix.lower() == ".h5ad":
        cells, read_summary = _read_h5ad_obs(input_ref, max_cells=max_cells)
    else:
        cells = _read_metadata_table(input_ref, max_cells=max_cells)
        read_summary = {"input_mode": "metadata_table", "original_n_cells": int(cells.shape[0]), "max_cells": max_cells}
    cells = _normalize_cells(cells)
    malignant = _malignant_candidates(cells)
    cells = cells.merge(malignant[["cell_id", "malignant_candidate", "tumor_candidate_score"]], on="cell_id", how="left")
    cnv = _cnv_summary(cells, config)
    return {
        "cells": cells,
        "malignant": malignant,
        "cnv": cnv,
        "read_summary": read_summary,
    }


def _read_metadata_table(path: Path, *, max_cells: int) -> pd.DataFrame:
    sep = "," if path.suffix.lower() == ".csv" else "\t"
    frame = pd.read_csv(path, sep=sep)
    if frame.shape[0] > max_cells:
        frame = frame.sample(n=max_cells, random_state=11).sort_index().reset_index(drop=True)
    return frame


def _read_h5ad_obs(path: Path, *, max_cells: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    try:
        import h5py
    except ModuleNotFoundError as exc:
        raise RuntimeError("Reading tumor_sc h5ad input requires h5py.") from exc

    with h5py.File(path, "r") as handle:
        obs = handle["obs"]
        n_obs = _h5_obs_length(obs)
        columns: dict[str, list[Any]] = {}
        for key in obs.keys():
            values = _read_obs_column(obs, key)
            if values is not None and len(values) == n_obs:
                columns[key] = values
        if "cell_id" not in columns:
            index_values = _first_present_column(obs, "_index", "index", "cell_barcode", "barcode")
            columns["cell_id"] = index_values or [f"cell_{idx:06d}" for idx in range(n_obs)]
    frame = pd.DataFrame(columns)
    if frame.shape[0] > max_cells:
        frame = frame.sample(n=max_cells, random_state=11).sort_values("cell_id").reset_index(drop=True)
    return frame, {"input_mode": "h5ad_obs_metadata", "original_n_cells": int(n_obs), "max_cells": int(max_cells)}


def _h5_obs_length(obs) -> int:
    for key in ("_index", "index", "cell_barcode"):
        if key in obs:
            obj = obs[key]
            if hasattr(obj, "keys") and "codes" in obj:
                return len(obj["codes"])
            return len(obj)
    for key in obs.keys():
        obj = obs[key]
        if hasattr(obj, "keys") and "codes" in obj:
            return len(obj["codes"])
        if not hasattr(obj, "keys"):
            return len(obj)
    return 0


def _first_present_column(obs, *keys: str) -> list[str] | None:
    for key in keys:
        values = _read_obs_column(obs, key)
        if values is not None:
            return values
    return None


def _read_obs_column(obs, key: str) -> list[Any] | None:
    if key not in obs:
        return None
    obj = obs[key]
    if hasattr(obj, "keys") and "categories" in obj and "codes" in obj:
        categories = [_decode(value) for value in obj["categories"][()]]
        return [categories[int(code)] if int(code) >= 0 else "" for code in obj["codes"][()]]
    if hasattr(obj, "keys"):
        return None
    values = obj[()]
    return [_decode(value) for value in values]


def _decode(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return value
    return value


def _normalize_cells(frame: pd.DataFrame) -> pd.DataFrame:
    cells = frame.copy()
    if "cell_id" not in cells.columns:
        first = cells.columns[0] if len(cells.columns) else "cell_id"
        cells = cells.rename(columns={first: "cell_id"})
    rename: dict[str, str] = {}
    for target, candidates in {
        "sample_id": ("sample_id", "sample", "Sample", "Sample_Origin", "sample_origin_harmonized", "dataset_id"),
        "cell_type": ("cell_type", "celltype", "cell_type_level1_harmonized", "Cell_type", "Cell_subtype", "annotation", "leiden"),
        "condition": ("condition", "group", "response", "therapy_response", "treatment", "disease"),
    }.items():
        if target in cells.columns:
            continue
        for candidate in candidates:
            if candidate in cells.columns:
                rename[candidate] = target
                break
    cells = cells.rename(columns=rename)
    if "sample_id" not in cells.columns:
        cells["sample_id"] = "sample"
    if "cell_type" not in cells.columns:
        cells["cell_type"] = "unknown"
    if "condition" not in cells.columns:
        cells["condition"] = "not_recorded"
    cells["cell_id"] = cells["cell_id"].astype(str)
    cells["sample_id"] = cells["sample_id"].astype(str)
    cells["cell_type"] = cells["cell_type"].astype(str)
    cells["condition"] = cells["condition"].astype(str)
    return cells


def _malignant_candidates(cells: pd.DataFrame) -> pd.DataFrame:
    ctype = cells["cell_type"].astype(str)
    tumor_like = ctype.str.contains("tumou?r|malig|epithelial|cancer|carcinoma|AT2|club|basal", case=False, regex=True)
    immune_like = ctype.str.contains("T cell|B cell|NK|myeloid|macrophage|monocyte|dendritic|immune|plasma", case=False, regex=True)
    stromal_like = ctype.str.contains("fibro|CAF|endo|smooth|stromal", case=False, regex=True)
    score = tumor_like.astype(float) + 0.25 * (~immune_like & ~stromal_like).astype(float)
    return pd.DataFrame(
        {
            "cell_id": cells["cell_id"],
            "sample_id": cells["sample_id"],
            "cell_type": cells["cell_type"],
            "tumor_candidate_score": score.clip(0, 1),
            "malignant_candidate": score >= 0.75,
            "candidate_basis": np.where(tumor_like, "tumor_or_epithelial_annotation", "annotation_summary_only"),
            "interpretation_warning": "candidate_not_pathology_confirmed; requires CNV/pathology/manual review",
        }
    )


def _cnv_summary(cells: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    module_cfg = _module_cfg(config)
    cnv_path = module_cfg.get("cnv_result") or module_cfg.get("copykat_result") or module_cfg.get("infercnv_result")
    if cnv_path and Path(str(cnv_path)).exists():
        cnv = _read_metadata_table(Path(str(cnv_path)), max_cells=100000)
        return pd.DataFrame(
            [
                {
                    "module": "tumor_sc",
                    "cnv_backend": "external_cnv_result_import",
                    "input_result": str(cnv_path),
                    "n_rows": int(cnv.shape[0]),
                    "cnv_status": "external_result_imported",
                    "interpretation_warning": "transcriptome-inferred or imported CNV is not DNA-level gold standard",
                }
            ]
        )
    grouped = cells.groupby("cell_type", dropna=False).size().reset_index(name="n_cells")
    grouped["module"] = "tumor_sc"
    grouped["cnv_backend"] = "cnv_handoff_proxy"
    grouped["cnv_status"] = "copykat_infercnv_not_run_in_summary_backend"
    grouped["interpretation_warning"] = "CNV inference requires raw counts and dedicated backend; not DNA-level CNV"
    return grouped[["module", "cnv_backend", "cell_type", "n_cells", "cnv_status", "interpretation_warning"]]


def _write_tumor_tables(
    *,
    tables_dir: Path,
    data: dict[str, Any],
    input_ref: str,
    source_dataset: str,
    analysis_fields: dict[str, Any],
) -> dict[str, str]:
    cells = data["cells"]
    malignant = data["malignant"]
    tme = cells.groupby(["sample_id", "cell_type"], dropna=False).size().reset_index(name="n_cells")
    totals = tme.groupby("sample_id")["n_cells"].transform("sum")
    tme["fraction"] = np.where(totals > 0, tme["n_cells"] / totals, 0.0)
    tme["module"] = "tumor_sc"
    immune = _state_summary(cells, pattern="T cell|CD8|NK|B cell|immune", output_name="immune_state")
    myeloid = _state_summary(cells, pattern="myeloid|macrophage|monocyte|dendritic", output_name="myeloid_state")
    caf = _state_summary(cells, pattern="CAF|fibro|stromal", output_name="caf_state")
    tumor_markers = _tumor_state_markers(cells)
    therapy = cells.groupby(["condition", "cell_type"], dropna=False).size().reset_index(name="n_cells")
    therapy["module"] = "tumor_sc"
    therapy["comparison_status"] = np.where(cells["condition"].nunique() > 1, "group_summary_ready", "single_condition_or_missing_metadata")
    input_summary = pd.DataFrame(
        [
            {
                "module": "tumor_sc",
                "source_dataset": source_dataset,
                "input_ref": input_ref,
                "analysis_level": analysis_fields.get("analysis_level"),
                "read_summary": json.dumps(data["read_summary"], ensure_ascii=False),
            }
        ]
    )
    outputs = {
        "malignant_cell_candidates": malignant,
        "cnv_inference_summary": data["cnv"],
        "tme_composition": tme[["module", "sample_id", "cell_type", "n_cells", "fraction"]],
        "immune_state_scores": immune,
        "myeloid_state_scores": myeloid,
        "caf_subtype_summary": caf,
        "tumor_state_markers": tumor_markers,
        "therapy_response_comparison": therapy,
        "input_read_summary": input_summary,
    }
    paths: dict[str, str] = {}
    for key, frame in outputs.items():
        path = tables_dir / f"{key}.tsv"
        frame.to_csv(path, sep="\t", index=False)
        paths[key] = str(path)
    return paths


def _state_summary(cells: pd.DataFrame, *, pattern: str, output_name: str) -> pd.DataFrame:
    flag = cells["cell_type"].astype(str).str.contains(pattern, case=False, regex=True)
    grouped = cells.assign(state_flag=flag).groupby(["sample_id", "cell_type"], dropna=False).agg(
        n_cells=("cell_id", "size"),
        state_score=("state_flag", "mean"),
    ).reset_index()
    grouped["module"] = "tumor_sc"
    grouped["state_name"] = output_name
    grouped["score_basis"] = "annotation_pattern_summary_not_functional_assay"
    return grouped[["module", "sample_id", "cell_type", "state_name", "n_cells", "state_score", "score_basis"]]


def _tumor_state_markers(cells: pd.DataFrame) -> pd.DataFrame:
    states = [
        ("stemness_score", "PROM1,ALDH1A1,SOX2", "handoff_marker_panel"),
        ("proliferation_score", "MKI67,TOP2A,PCNA", "handoff_marker_panel"),
        ("hypoxia_score", "VEGFA,CA9,LDHA", "handoff_marker_panel"),
        ("emt_score", "VIM,ZEB1,SNAI1", "handoff_marker_panel"),
        ("immune_escape_score", "PD-L1/CD274,HLA genes", "handoff_marker_panel"),
    ]
    tumor_fraction = float(cells.get("malignant_candidate", pd.Series(False, index=cells.index)).mean())
    return pd.DataFrame(
        [
            {
                "module": "tumor_sc",
                "state_name": name,
                "marker_set": markers,
                "score": tumor_fraction if "stemness" not in name else np.nan,
                "score_status": status,
                "interpretation_warning": "state score is marker/signature summary, not functional proof",
            }
            for name, markers, status in states
        ]
    )


def _write_tumor_figures(*, tables_dir: Path, figures_dir: Path) -> dict[str, str]:
    tokens = apply_clinical_journal_style()
    artifacts: dict[str, str] = {}
    tme = _read_table(tables_dir / "tme_composition.tsv")
    if not tme.empty:
        pivot = tme.pivot_table(index="sample_id", columns="cell_type", values="fraction", aggfunc="sum", fill_value=0.0)
        fig, ax = plt.subplots(figsize=(7.0, 4.2))
        pivot.iloc[:, :12].plot(kind="bar", stacked=True, ax=ax, colormap="tab20")
        ax.set_ylabel("Cell fraction")
        ax.set_title("Tumor microenvironment composition")
        ax.legend(frameon=False, bbox_to_anchor=(1.02, 1), loc="upper left", fontsize=7)
        path = figures_dir / "tme_composition.png"
        save_figure(path, style=tokens)
        plt.close(fig)
        artifacts["tme_composition"] = str(path)
    states = _read_table(tables_dir / "tumor_state_markers.tsv")
    if not states.empty:
        fig, ax = plt.subplots(figsize=(6.2, 3.8))
        plot = states.copy()
        plot["score"] = pd.to_numeric(plot["score"], errors="coerce").fillna(0.0)
        ax.bar(plot["state_name"], plot["score"], color="#F26F8F")
        ax.set_ylabel("Summary score")
        ax.set_title("Tumor state marker summary")
        ax.tick_params(axis="x", rotation=30)
        path = figures_dir / "tumor_state_heatmap.png"
        save_figure(path, style=tokens)
        plt.close(fig)
        artifacts["tumor_state_heatmap"] = str(path)
    malignant = _read_table(tables_dir / "malignant_cell_candidates.tsv")
    if not malignant.empty:
        fig, ax = plt.subplots(figsize=(5.8, 3.8))
        counts = malignant["malignant_candidate"].astype(bool).value_counts().rename(index={True: "candidate", False: "other"})
        ax.bar(counts.index.astype(str), counts.values, color=["#F26F8F", "#31B7C5"][: len(counts)])
        ax.set_ylabel("Cells")
        ax.set_title("Malignant candidate calls")
        path = figures_dir / "malignant_candidate_summary.png"
        save_figure(path, style=tokens)
        plt.close(fig)
        artifacts["malignant_candidate_summary"] = str(path)
    cnv = _read_table(tables_dir / "cnv_inference_summary.tsv")
    if not cnv.empty:
        fig, ax = plt.subplots(figsize=(6.2, 3.8))
        if "n_cells" in cnv.columns:
            ax.bar(cnv.get("cell_type", pd.Series(range(cnv.shape[0]))).astype(str), pd.to_numeric(cnv["n_cells"], errors="coerce").fillna(0), color="#8C6FF7")
            ax.tick_params(axis="x", rotation=30)
            ax.set_ylabel("Cells")
        else:
            ax.text(0.5, 0.5, "External CNV result imported", ha="center", va="center")
            ax.set_axis_off()
        ax.set_title("CNV inference handoff summary")
        path = figures_dir / "cnv_proxy_by_chromosome.png"
        save_figure(path, style=tokens)
        plt.close(fig)
        artifacts["cnv_proxy_by_chromosome"] = str(path)
    return artifacts


def _write_tumor_object(*, objects_dir: Path, data: dict[str, Any], input_ref: str) -> dict[str, str]:
    path = objects_dir / "tumor_sc_mvp_object.rds"
    payload = {
        "object_type": "tumor_sc_summary_mvp",
        "input_ref": input_ref,
        "n_cells": int(data["cells"].shape[0]),
        "n_malignant_candidates": int(data["malignant"]["malignant_candidate"].sum()) if not data["malignant"].empty else 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"mvp_object": str(path)}


def _write_skip_outputs(*, tables_dir: Path, figures_dir: Path, objects_dir: Path, analysis_fields: dict[str, Any]) -> dict[str, dict[str, str]]:
    table_specs = {
        "malignant_cell_candidates": ["cell_id", "sample_id", "cell_type", "tumor_candidate_score", "malignant_candidate", "candidate_basis", "interpretation_warning"],
        "cnv_inference_summary": ["module", "cnv_backend", "cnv_status", "interpretation_warning"],
        "tme_composition": ["module", "sample_id", "cell_type", "n_cells", "fraction"],
        "immune_state_scores": ["module", "sample_id", "cell_type", "state_name", "n_cells", "state_score", "score_basis"],
        "myeloid_state_scores": ["module", "sample_id", "cell_type", "state_name", "n_cells", "state_score", "score_basis"],
        "caf_subtype_summary": ["module", "sample_id", "cell_type", "state_name", "n_cells", "state_score", "score_basis"],
        "tumor_state_markers": ["module", "state_name", "marker_set", "score", "score_status", "interpretation_warning"],
        "therapy_response_comparison": ["module", "condition", "cell_type", "n_cells", "comparison_status"],
    }
    tables: dict[str, str] = {}
    for key, columns in table_specs.items():
        path = tables_dir / f"{key}.tsv"
        pd.DataFrame(columns=columns).to_csv(path, sep="\t", index=False)
        tables[key] = str(path)
    object_path = objects_dir / "tumor_sc_mvp_object.rds"
    object_path.write_text(json.dumps({"status": "skipped", **analysis_fields}, indent=2), encoding="utf-8")
    fig, ax = plt.subplots(figsize=(5.0, 3.2))
    ax.text(0.5, 0.5, "tumor_sc backend skipped", ha="center", va="center")
    ax.set_axis_off()
    fig_path = figures_dir / "tme_composition.png"
    save_figure(fig_path, style=apply_clinical_journal_style())
    plt.close(fig)
    return {"tables": tables, "figures": {"tme_composition": str(fig_path)}, "objects": {"mvp_object": str(object_path)}, "reports": {}}


def _read_table(path: Path | None) -> pd.DataFrame:
    if path is None or not path.exists():
        return pd.DataFrame()
    sep = "," if path.suffix.lower() == ".csv" else "\t"
    return pd.read_csv(path, sep=sep)
