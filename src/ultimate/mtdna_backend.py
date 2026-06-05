from __future__ import annotations

import json
from datetime import datetime, timezone
from itertools import combinations
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


MTDNA_BACKEND_ID = "mtdna.default.lineage_ready_mvp"
MTDNA_WARNING = "NUMTs、homopolymer、低深度和 dropout 必须警示；shared variant 不能自动当作克隆关系。"


def has_mtdna_backend_config(config: dict[str, Any]) -> bool:
    module_cfg = _module_cfg(config)
    raw_cfg = module_cfg.get("raw") if isinstance(module_cfg.get("raw"), dict) else {}
    keys = {
        "source_root",
        "input_dir",
        "input_path",
        "depth_table",
        "variant_table",
        "vaf_matrix",
        "alt_count_matrix",
        "base_count_table",
    }
    return any(module_cfg.get(key) for key in keys) or any(raw_cfg.get(key) for key in keys)


def run_mtdna_backend(*, config: dict[str, Any], output_dir: Path, samples: pd.DataFrame) -> dict[str, Any]:
    module_name = "mtdna"
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
    status = "partial:mtdna_inputs_missing" if missing_inputs else "complete_mtdna_lineage_backend"
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
        status = "partial:mtdna_analysis_level_invalid"
        skip_reasons.append(f"analysis_level_invalid:{exc}")
        level_fields = classify_analysis_level(requested_level="smoke_backend", is_stub=True).to_manifest_fields()

    artifacts: dict[str, dict[str, str]] = {"tables": {}, "figures": {}, "objects": {}, "reports": {}}
    warnings = [MTDNA_WARNING]
    n_cells = 0
    n_variants = 0
    lineage_ready_cells = 0
    if skip_reasons:
        artifacts.update(_write_skip_outputs(tables_dir=tables_dir, figures_dir=figures_dir, objects_dir=objects_dir, analysis_fields=level_fields))
    else:
        try:
            data = _read_mtdna_input(config)
        except Exception as exc:
            status = "partial:mtdna_input_read_failed"
            skip_reasons.append(f"input_read_failed:{type(exc).__name__}:{exc}")
            level_fields = classify_analysis_level(requested_level="smoke_backend", is_stub=True).to_manifest_fields()
            artifacts.update(_write_skip_outputs(tables_dir=tables_dir, figures_dir=figures_dir, objects_dir=objects_dir, analysis_fields=level_fields))
            data = None
        if data is not None:
            artifacts["tables"].update(
                _write_mtdna_tables(
                    tables_dir=tables_dir,
                    data=data,
                    input_ref=str(input_ref or ""),
                    source_dataset=_source_dataset(config),
                    analysis_fields=level_fields,
                )
            )
            artifacts["figures"].update(_write_mtdna_figures(tables_dir=tables_dir, figures_dir=figures_dir))
            artifacts["objects"].update(_write_mtdna_object(objects_dir=objects_dir, data=data, input_ref=str(input_ref or "")))
            n_cells = int(data["depth_by_cell"]["cell_id"].nunique()) if not data["depth_by_cell"].empty else int(data["vaf_long"]["cell_id"].nunique())
            n_variants = int(data["variants"]["variant_id"].nunique()) if not data["variants"].empty else int(data["vaf_long"]["variant_id"].nunique())
            lineage_ready_cells = int(data["lineage_ready_cells"])

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
        "n_features": n_variants,
        "lineage_ready_cells": lineage_ready_cells,
        "artifacts": artifacts,
        "warnings": warnings,
        "limitations": list(known_limitations(module_name)),
        "handoff": handoff_plan(module_name),
        "reproducible_command": f"ultimate run --config {config.get('_config_path', '<config.yaml>')}",
        "backend": {
            "primary": "mtdna_lineage_ready_result_import",
            "selected_backend_id": backend_plan["selected_backend_id"],
            "selected_backend_status": backend_plan["selected_backend_status"],
            "backend_role": backend_plan["selected_backend_role"],
            "resource_profile": backend_plan["backend_resource_profile"],
            "interpretation_warning": MTDNA_WARNING,
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
            "python_entrypoint": "ultimate.mtdna_backend.run_mtdna_backend",
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
    return ((config.get("modules") or {}).get("mtdna") or {}) if isinstance(config.get("modules"), dict) else {}


def _module_is_demo(config: dict[str, Any], module_cfg: dict[str, Any]) -> bool | None:
    if "is_demo" in module_cfg:
        return bool(module_cfg.get("is_demo"))
    project = config.get("project") or {}
    if "is_demo" in project:
        return bool(project.get("is_demo"))
    return None


def _source_dataset(config: dict[str, Any]) -> str:
    project = config.get("project") or {}
    return str(project.get("name") or project.get("job_id") or "mtdna")


def _primary_input_ref(config: dict[str, Any]) -> Path | None:
    module_cfg = _module_cfg(config)
    raw_cfg = module_cfg.get("raw") if isinstance(module_cfg.get("raw"), dict) else {}
    base = Path(str(config.get("_config_path") or ".")).resolve().parent
    value = (
        module_cfg.get("source_root")
        or module_cfg.get("input_dir")
        or module_cfg.get("input_path")
        or module_cfg.get("vaf_matrix")
        or module_cfg.get("variant_table")
        or module_cfg.get("depth_table")
        or raw_cfg.get("source_root")
        or raw_cfg.get("input_dir")
        or raw_cfg.get("input_path")
        or raw_cfg.get("vaf_matrix")
        or raw_cfg.get("variant_table")
        or raw_cfg.get("depth_table")
    )
    return _resolve_path(base, value) if value else None


def _resolve_path(base: Path, value: Any) -> Path:
    candidate = Path(str(value))
    return candidate if candidate.is_absolute() else (base / candidate).resolve()


def _missing_input_reasons(config: dict[str, Any]) -> list[str]:
    input_ref = _primary_input_ref(config)
    if input_ref is None:
        return ["missing_mtdna_input"]
    if not input_ref.exists():
        return [f"missing_input_path:{input_ref}"]
    if input_ref.is_file():
        if input_ref.suffix.lower() not in {".tsv", ".txt", ".csv"}:
            return [f"unsupported_input_extension:{input_ref.suffix or 'none'}"]
        return []
    paths = _resolve_mtdna_paths(config)
    if not paths.get("depth") and not paths.get("variants") and not paths.get("vaf"):
        return [f"missing_mtdna_tables:{input_ref}"]
    return []


def _resolve_mtdna_paths(config: dict[str, Any]) -> dict[str, Path | None]:
    module_cfg = _module_cfg(config)
    raw_cfg = module_cfg.get("raw") if isinstance(module_cfg.get("raw"), dict) else {}
    base = Path(str(config.get("_config_path") or ".")).resolve().parent

    def value_path(*keys: str) -> Path | None:
        for key in keys:
            value = module_cfg.get(key)
            if value:
                return _resolve_path(base, value)
            value = raw_cfg.get(key)
            if value:
                return _resolve_path(base, value)
        return None

    input_ref = _primary_input_ref(config)
    source_root = value_path("source_root", "input_dir", "input_path") or input_ref
    depth = value_path("depth_table", "base_count_table")
    variants = value_path("variant_table")
    vaf = value_path("vaf_matrix")
    alt = value_path("alt_count_matrix")
    position_depth = value_path("position_depth_table")

    if source_root and source_root.is_dir():
        mt_root = source_root / "analysis_mtDNA" / "singlecell_mgatk_like"
        if not mt_root.exists():
            mt_root = source_root
        depth = depth or _first_existing(
            mt_root / "counts" / "cell_mtDNA_depth.tsv",
            mt_root / "cell_mtDNA_depth.tsv",
            mt_root / "mtdna_depth_by_cell.tsv",
        )
        variants = variants or _first_existing(
            mt_root / "variants" / "mtDNA_snv_variant_stats.tsv",
            mt_root / "variants" / "high_confidence_informative_variants.tsv",
            mt_root / "high_confidence_informative_variants.tsv",
            mt_root / "variant_candidates.tsv",
            mt_root / "high_confidence_variants.tsv",
        )
        vaf = vaf or _first_existing(
            mt_root / "variants" / "cell_by_variant_vaf_matrix.tsv",
            mt_root / "cell_by_variant_vaf_matrix.tsv",
            mt_root / "cell_variant_vaf_matrix.tsv",
        )
        alt = alt or _first_existing(
            mt_root / "variants" / "cell_by_variant_alt_count_matrix.tsv",
            mt_root / "cell_by_variant_alt_count_matrix.tsv",
            mt_root / "cell_variant_alt_count_matrix.tsv",
        )
        position_depth = position_depth or _first_existing(
            mt_root / "counts" / "mtdna_depth_by_position.tsv",
            mt_root / "mtdna_depth_by_position.tsv",
        )
    elif input_ref and input_ref.is_file():
        if "vaf" in input_ref.name.lower():
            vaf = vaf or input_ref
        elif "depth" in input_ref.name.lower():
            depth = depth or input_ref
        else:
            variants = variants or input_ref

    return {"depth": depth, "variants": variants, "vaf": vaf, "alt": alt, "position_depth": position_depth}


def _first_existing(*paths: Path) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def _read_mtdna_input(config: dict[str, Any]) -> dict[str, Any]:
    paths = _resolve_mtdna_paths(config)
    depth = _read_depth(paths.get("depth"))
    variants = _read_variants(paths.get("variants"))
    vaf_long, vaf_wide = _read_vaf(paths.get("vaf"))
    alt_long = _read_alt_counts(paths.get("alt"), vaf_long=vaf_long, depth=depth)
    position_depth = _read_position_depth(paths.get("position_depth"), variants=variants)
    if depth.empty and vaf_long.empty and variants.empty:
        raise ValueError("no_mtdna_tables_readable")
    lineage_ready_cells = _lineage_ready_cell_count(vaf_long, depth)
    return {
        "paths": {key: str(value) for key, value in paths.items() if value},
        "depth_by_cell": depth,
        "variants": variants,
        "vaf_long": vaf_long,
        "vaf_wide": vaf_wide,
        "alt_long": alt_long,
        "position_depth": position_depth,
        "shared": _shared_variants(vaf_long),
        "lineage_ready_cells": lineage_ready_cells,
    }


def _read_table(path: Path | None) -> pd.DataFrame:
    if path is None or not path.exists():
        return pd.DataFrame()
    sep = "," if path.suffix.lower() == ".csv" else "\t"
    return pd.read_csv(path, sep=sep)


def _read_depth(path: Path | None) -> pd.DataFrame:
    frame = _read_table(path)
    if frame.empty:
        return pd.DataFrame(columns=["module", "cell_id", "mt_chromosome", "mean_mtdna_depth", "dropout_flag", "lineage_ready"])
    frame = frame.copy()
    cell_col = _pick_col(frame, ("cell_id", "cell", "sample_id", "barcode"), default=frame.columns[0])
    depth_col = _pick_col(frame, ("mean_depth", "mean_mtdna_depth", "mtDNA_depth", "depth", "median_depth"), numeric=True)
    if depth_col is None:
        numeric = frame.select_dtypes(include="number")
        frame["_depth"] = numeric.iloc[:, 0] if not numeric.empty else 0.0
        depth_col = "_depth"
    out = pd.DataFrame(
        {
            "module": "mtdna",
            "cell_id": frame[cell_col].astype(str),
            "mt_chromosome": _series_or_default(frame, "chrom", "chrM"),
            "mean_mtdna_depth": pd.to_numeric(frame[depth_col], errors="coerce").fillna(0.0),
        }
    )
    out["dropout_flag"] = np.where(out["mean_mtdna_depth"] < 10, "low_depth_or_dropout", "pass_depth_proxy")
    out["lineage_ready"] = np.where(out["mean_mtdna_depth"] >= 30, "depth_ready", "depth_limited")
    return out


def _read_variants(path: Path | None) -> pd.DataFrame:
    frame = _read_table(path)
    if frame.empty:
        return pd.DataFrame(columns=["module", "variant_id", "mt_chromosome", "position", "ref", "alt", "heteroplasmy", "filter_status"])
    frame = frame.copy()
    variant_col = _pick_col(frame, ("variant_id", "variant", "id"), default=frame.columns[0])
    chrom_col = _pick_col(frame, ("chrom", "chr", "mt_chromosome"))
    pos_col = _pick_col(frame, ("pos", "position"))
    ref_col = _pick_col(frame, ("ref", "reference"))
    alt_col = _pick_col(frame, ("alt", "alternate"))
    het_col = _pick_col(frame, ("mean_vaf", "heteroplasmy", "max_vaf", "vaf"), numeric=True)
    status_col = _pick_col(frame, ("quality_class", "filter_status", "status"))
    out = pd.DataFrame(
        {
            "module": "mtdna",
            "variant_id": frame[variant_col].astype(str),
            "mt_chromosome": _series_or_default(frame, chrom_col, "chrM"),
            "position": pd.to_numeric(_series_or_default(frame, pos_col, np.nan), errors="coerce"),
            "ref": _series_or_default(frame, ref_col, "N"),
            "alt": _series_or_default(frame, alt_col, "N"),
            "heteroplasmy": pd.to_numeric(_series_or_default(frame, het_col, 0.0), errors="coerce").fillna(0.0),
            "filter_status": _series_or_default(frame, status_col, "candidate"),
        }
    )
    return out


def _read_vaf(path: Path | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = _read_table(path)
    if frame.empty:
        cols = ["module", "cell_id", "variant_id", "vaf", "depth", "lineage_ready"]
        return pd.DataFrame(columns=cols), pd.DataFrame()
    frame = frame.copy()
    cell_col = _pick_col(frame, ("cell_id", "cell", "sample_id", "barcode"), default=frame.columns[0])
    value_cols = [col for col in frame.columns if col != cell_col and pd.api.types.is_numeric_dtype(frame[col])]
    if {"variant_id", "vaf"}.issubset(frame.columns):
        long = frame.rename(columns={cell_col: "cell_id"})[["cell_id", "variant_id", "vaf"]].copy()
    else:
        long = frame[[cell_col, *value_cols]].melt(id_vars=cell_col, var_name="variant_id", value_name="vaf")
        long = long.rename(columns={cell_col: "cell_id"})
    long["vaf"] = pd.to_numeric(long["vaf"], errors="coerce").fillna(0.0).clip(lower=0.0, upper=1.0)
    long["module"] = "mtdna"
    long["depth"] = np.nan
    long["lineage_ready"] = np.where((long["vaf"] >= 0.05) & (long["vaf"] <= 0.95), "lineage_ready_proxy", "homoplasmy_or_low_signal")
    wide = long.pivot_table(index="cell_id", columns="variant_id", values="vaf", aggfunc="max", fill_value=0.0)
    return long[["module", "cell_id", "variant_id", "vaf", "depth", "lineage_ready"]], wide


def _read_alt_counts(path: Path | None, *, vaf_long: pd.DataFrame, depth: pd.DataFrame) -> pd.DataFrame:
    frame = _read_table(path)
    if not frame.empty:
        cell_col = _pick_col(frame, ("cell_id", "cell", "sample_id", "barcode"), default=frame.columns[0])
        if {"variant_id", "alt_count"}.issubset(frame.columns):
            long = frame.rename(columns={cell_col: "cell_id"})[["cell_id", "variant_id", "alt_count"]].copy()
        else:
            value_cols = [col for col in frame.columns if col != cell_col and pd.api.types.is_numeric_dtype(frame[col])]
            long = frame[[cell_col, *value_cols]].melt(id_vars=cell_col, var_name="variant_id", value_name="alt_count")
            long = long.rename(columns={cell_col: "cell_id"})
        long["alt_count"] = pd.to_numeric(long["alt_count"], errors="coerce").fillna(0).round().astype(int)
    elif not vaf_long.empty:
        depth_map = depth.set_index("cell_id")["mean_mtdna_depth"].to_dict() if not depth.empty else {}
        long = vaf_long[["cell_id", "variant_id", "vaf"]].copy()
        long["alt_count"] = [int(round(float(v) * float(depth_map.get(cell, 0)))) for cell, v in zip(long["cell_id"], long["vaf"])]
    else:
        long = pd.DataFrame(columns=["cell_id", "variant_id", "alt_count"])
    long["module"] = "mtdna"
    long["depth"] = [float(depth.set_index("cell_id")["mean_mtdna_depth"].to_dict().get(cell, np.nan)) if not depth.empty else np.nan for cell in long["cell_id"]]
    long["lineage_ready"] = np.where(long["alt_count"] > 0, "alt_count_available", "no_alt_count")
    return long[["module", "cell_id", "variant_id", "alt_count", "depth", "lineage_ready"]]


def _read_position_depth(path: Path | None, *, variants: pd.DataFrame) -> pd.DataFrame:
    frame = _read_table(path)
    if not frame.empty:
        pos_col = _pick_col(frame, ("position", "pos"), default=frame.columns[0])
        depth_col = _pick_col(frame, ("depth", "mean_depth", "median_depth"), numeric=True)
        out = pd.DataFrame(
            {
                "module": "mtdna",
                "mt_chromosome": _series_or_default(frame, _pick_col(frame, ("chrom", "chr", "mt_chromosome")), "chrM"),
                "position": pd.to_numeric(frame[pos_col], errors="coerce"),
                "depth": pd.to_numeric(_series_or_default(frame, depth_col, 0.0), errors="coerce").fillna(0.0),
            }
        )
    elif not variants.empty:
        out = variants[["module", "mt_chromosome", "position"]].copy()
        out["depth"] = np.nan
    else:
        out = pd.DataFrame(columns=["module", "mt_chromosome", "position", "depth"])
    out["homopolymer_warning"] = "not_evaluated_in_mvp"
    return out[["module", "mt_chromosome", "position", "depth", "homopolymer_warning"]]


def _lineage_ready_cell_count(vaf_long: pd.DataFrame, depth: pd.DataFrame) -> int:
    if vaf_long.empty:
        return 0
    ready = vaf_long[(vaf_long["vaf"] >= 0.05) & (vaf_long["vaf"] <= 0.95)]["cell_id"].unique()
    if depth.empty:
        return int(len(ready))
    depth_ready = set(depth.loc[depth["mean_mtdna_depth"] >= 30, "cell_id"].astype(str))
    return int(len([cell for cell in ready if cell in depth_ready]))


def _shared_variants(vaf_long: pd.DataFrame) -> pd.DataFrame:
    columns = ["module", "cell_id", "paired_cell_id", "variant_id", "shared_high_confidence", "interpretation_warning"]
    if vaf_long.empty:
        return pd.DataFrame(columns=columns)
    binary = vaf_long[(vaf_long["vaf"] >= 0.05) & (vaf_long["vaf"] <= 0.95)]
    rows: list[dict[str, Any]] = []
    for variant, group in binary.groupby("variant_id"):
        cells = sorted(group["cell_id"].astype(str).unique())
        for a, b in combinations(cells[:100], 2):
            rows.append(
                {
                    "module": "mtdna",
                    "cell_id": a,
                    "paired_cell_id": b,
                    "variant_id": variant,
                    "shared_high_confidence": True,
                    "interpretation_warning": "shared_variant_is_lineage_hypothesis_not_clone_proof",
                }
            )
            if len(rows) >= 5000:
                return pd.DataFrame(rows, columns=columns)
    return pd.DataFrame(rows, columns=columns)


def _write_mtdna_tables(
    *,
    tables_dir: Path,
    data: dict[str, Any],
    input_ref: str,
    source_dataset: str,
    analysis_fields: dict[str, Any],
) -> dict[str, str]:
    variants = data["variants"].copy()
    if not variants.empty:
        high_conf = variants.copy()
        high_conf["high_confidence_status"] = np.where(
            high_conf["filter_status"].astype(str).str.contains("informative|pass|homoplasmic|heteroplas", case=False, regex=True),
            "high_confidence_or_reported",
            "candidate_requires_review",
        )
    else:
        high_conf = pd.DataFrame(columns=["module", "variant_id", "mt_chromosome", "position", "ref", "alt", "heteroplasmy", "high_confidence_status"])

    lineage = data["vaf_long"].copy()
    if not lineage.empty:
        lineage["binary_state"] = np.where((lineage["vaf"] >= 0.05) & (lineage["vaf"] <= 0.95), 1, 0)
        lineage["lineage_handoff_status"] = np.where(lineage["binary_state"] == 1, "lineage_ready_variant", "not_lineage_informative")
        lineage = lineage[["module", "cell_id", "variant_id", "binary_state", "lineage_handoff_status"]]
    else:
        lineage = pd.DataFrame(columns=["module", "cell_id", "variant_id", "binary_state", "lineage_handoff_status"])

    input_summary = pd.DataFrame(
        [
            {
                "module": "mtdna",
                "source_dataset": source_dataset,
                "input_ref": input_ref,
                "analysis_level": analysis_fields.get("analysis_level"),
                "lineage_ready_cells": data["lineage_ready_cells"],
                "input_tables": json.dumps(data["paths"], ensure_ascii=False),
            }
        ]
    )
    outputs = {
        "mtdna_depth_by_cell": data["depth_by_cell"],
        "mtdna_depth_by_position": data["position_depth"],
        "variant_candidates": variants,
        "high_confidence_variants": high_conf[["module", "variant_id", "mt_chromosome", "position", "ref", "alt", "heteroplasmy", "high_confidence_status"]],
        "cell_variant_vaf_matrix": data["vaf_long"],
        "cell_variant_alt_count_matrix": data["alt_long"],
        "shared_variant_matrix": data["shared"],
        "lineage_input": lineage,
        "input_read_summary": input_summary,
    }
    paths: dict[str, str] = {}
    for key, frame in outputs.items():
        path = tables_dir / f"{key}.tsv"
        frame.to_csv(path, sep="\t", index=False)
        paths[key] = str(path)
    return paths


def _write_mtdna_figures(*, tables_dir: Path, figures_dir: Path) -> dict[str, str]:
    tokens = apply_clinical_journal_style()
    artifacts: dict[str, str] = {}
    depth = _read_table(tables_dir / "mtdna_depth_by_cell.tsv")
    if not depth.empty:
        fig, ax = plt.subplots(figsize=(6.2, 4.0))
        ax.hist(pd.to_numeric(depth["mean_mtdna_depth"], errors="coerce").fillna(0.0), bins=min(20, max(5, depth.shape[0])), color="#31B7C5", edgecolor="white")
        ax.set_xlabel("Mean mtDNA depth")
        ax.set_ylabel("Cells")
        ax.set_title("mtDNA depth distribution")
        path = figures_dir / "depth_distribution.png"
        save_figure(path, style=tokens)
        plt.close(fig)
        artifacts["depth_distribution"] = str(path)

    vaf = _read_table(tables_dir / "cell_variant_vaf_matrix.tsv")
    if not vaf.empty:
        wide = vaf.pivot_table(index="cell_id", columns="variant_id", values="vaf", aggfunc="max", fill_value=0.0)
        fig, ax = plt.subplots(figsize=(7.0, 4.6))
        sns.heatmap(wide.iloc[:80, :80], cmap=continuous_cmap(), vmin=0, vmax=1, ax=ax, cbar_kws={"label": "VAF"})
        ax.set_xlabel("Variant")
        ax.set_ylabel("Cell")
        ax.set_title("mtDNA VAF heatmap")
        path = figures_dir / "vaf_heatmap.png"
        save_figure(path, style=tokens)
        plt.close(fig)
        artifacts["vaf_heatmap"] = str(path)

    shared = _read_table(tables_dir / "shared_variant_matrix.tsv")
    if not shared.empty:
        cells = sorted(set(shared["cell_id"].astype(str)).union(set(shared["paired_cell_id"].astype(str))))[:80]
        matrix = pd.DataFrame(0, index=cells, columns=cells, dtype=float)
        for row in shared.itertuples(index=False):
            if row.cell_id in matrix.index and row.paired_cell_id in matrix.columns:
                matrix.loc[row.cell_id, row.paired_cell_id] += 1
                matrix.loc[row.paired_cell_id, row.cell_id] += 1
        fig, ax = plt.subplots(figsize=(6.4, 5.2))
        sns.heatmap(matrix, cmap="viridis", ax=ax, cbar_kws={"label": "Shared variants"})
        ax.set_title("Shared mtDNA variant matrix")
        path = figures_dir / "shared_variant_heatmap.png"
        save_figure(path, style=tokens)
        plt.close(fig)
        artifacts["shared_variant_heatmap"] = str(path)
    else:
        fig, ax = plt.subplots(figsize=(5.4, 3.4))
        ax.text(0.5, 0.5, "No shared informative variants", ha="center", va="center")
        ax.set_axis_off()
        path = figures_dir / "shared_variant_heatmap.png"
        save_figure(path, style=tokens)
        plt.close(fig)
        artifacts["shared_variant_heatmap"] = str(path)
    return artifacts


def _write_mtdna_object(*, objects_dir: Path, data: dict[str, Any], input_ref: str) -> dict[str, str]:
    path = objects_dir / "mtdna_mvp_object.rds"
    payload = {
        "object_type": "mtdna_lineage_ready_mvp",
        "input_ref": input_ref,
        "n_cells": int(data["depth_by_cell"]["cell_id"].nunique()) if not data["depth_by_cell"].empty else 0,
        "n_variants": int(data["variants"]["variant_id"].nunique()) if not data["variants"].empty else 0,
        "lineage_ready_cells": int(data["lineage_ready_cells"]),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"mvp_object": str(path)}


def _write_skip_outputs(*, tables_dir: Path, figures_dir: Path, objects_dir: Path, analysis_fields: dict[str, Any]) -> dict[str, dict[str, str]]:
    table_specs = {
        "mtdna_depth_by_cell": ["module", "cell_id", "mt_chromosome", "mean_mtdna_depth", "dropout_flag", "lineage_ready"],
        "mtdna_depth_by_position": ["module", "mt_chromosome", "position", "depth", "homopolymer_warning"],
        "variant_candidates": ["module", "variant_id", "mt_chromosome", "position", "ref", "alt", "heteroplasmy", "filter_status"],
        "high_confidence_variants": ["module", "variant_id", "mt_chromosome", "position", "ref", "alt", "heteroplasmy", "high_confidence_status"],
        "cell_variant_vaf_matrix": ["module", "cell_id", "variant_id", "vaf", "depth", "lineage_ready"],
        "cell_variant_alt_count_matrix": ["module", "cell_id", "variant_id", "alt_count", "depth", "lineage_ready"],
        "shared_variant_matrix": ["module", "cell_id", "paired_cell_id", "variant_id", "shared_high_confidence", "interpretation_warning"],
        "lineage_input": ["module", "cell_id", "variant_id", "binary_state", "lineage_handoff_status"],
    }
    tables: dict[str, str] = {}
    for key, columns in table_specs.items():
        path = tables_dir / f"{key}.tsv"
        pd.DataFrame(columns=columns).to_csv(path, sep="\t", index=False)
        tables[key] = str(path)
    object_path = objects_dir / "mtdna_mvp_object.rds"
    object_path.write_text(json.dumps({"status": "skipped", **analysis_fields}, indent=2), encoding="utf-8")
    fig, ax = plt.subplots(figsize=(5.0, 3.2))
    ax.text(0.5, 0.5, "mtDNA backend skipped", ha="center", va="center")
    ax.set_axis_off()
    fig_path = figures_dir / "depth_distribution.png"
    save_figure(fig_path, style=apply_clinical_journal_style())
    plt.close(fig)
    return {"tables": tables, "figures": {"depth_distribution": str(fig_path)}, "objects": {"mvp_object": str(object_path)}, "reports": {}}


def _pick_col(frame: pd.DataFrame, candidates: tuple[str, ...], *, default: str | None = None, numeric: bool = False) -> str | None:
    lower = {str(col).lower(): col for col in frame.columns}
    for candidate in candidates:
        if candidate and candidate.lower() in lower:
            col = lower[candidate.lower()]
            if not numeric or pd.api.types.is_numeric_dtype(frame[col]):
                return str(col)
    if numeric:
        numeric_cols = frame.select_dtypes(include="number").columns
        return str(numeric_cols[0]) if len(numeric_cols) else default
    return default


def _series_or_default(frame: pd.DataFrame, column: str | None, default: Any) -> pd.Series:
    if column and column in frame.columns:
        return frame[column]
    return pd.Series([default] * len(frame), index=frame.index)
