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


VDJ_BACKEND_ID = "vdj.default.scirpy_mvp"
VDJ_WARNING = "clonotype 相同不等于抗原相同；抗原特异性和 clone-state association 只作为 handoff，不自动断言。"


def has_vdj_backend_config(config: dict[str, Any]) -> bool:
    module_cfg = _module_cfg(config)
    raw_cfg = module_cfg.get("raw") if isinstance(module_cfg.get("raw"), dict) else {}
    keys = {
        "input_dir",
        "cellranger_vdj_out",
        "contig_annotations",
        "clonotypes",
        "airr_table",
        "mixcr_output",
    }
    if any(module_cfg.get(key) for key in keys):
        return True
    if any(raw_cfg.get(key) for key in keys):
        return True
    return False


def run_vdj_backend(*, config: dict[str, Any], output_dir: Path, samples: pd.DataFrame) -> dict[str, Any]:
    module_name = "vdj"
    module_dir = output_dir
    tables_dir = module_dir / "results" / "tables" / module_name
    figures_dir = module_dir / "results" / "figures" / module_name
    objects_dir = module_dir / "objects" / module_name
    reports_dir = module_dir / "reports" / module_name
    logs_dir = module_dir / "logs"
    for directory in (tables_dir, figures_dir, objects_dir, reports_dir, logs_dir):
        directory.mkdir(parents=True, exist_ok=True)

    module_cfg = _module_cfg(config)
    contig_path, clonotype_path, input_dir = _resolve_vdj_inputs(config)
    missing_inputs = []
    if contig_path is None or not contig_path.exists():
        missing_inputs.append(f"missing_contig_annotations:{contig_path or 'not_configured'}")
    if clonotype_path is None or not clonotype_path.exists():
        missing_inputs.append(f"missing_clonotypes:{clonotype_path or 'not_configured'}")

    artifacts: dict[str, dict[str, str]] = {"tables": {}, "figures": {}, "objects": {}, "reports": {}}
    warnings = [VDJ_WARNING]
    skip_reasons = list(missing_inputs)
    is_stub = bool(missing_inputs)
    status = "partial:vdj_inputs_missing" if missing_inputs else "complete_vdj_10x_backend"
    public_dataset = bool(module_cfg.get("public_dataset") or module_cfg.get("validation_dataset") or module_cfg.get("validated_backend"))
    try:
        level = classify_analysis_level(
            requested_level=module_cfg.get("analysis_level"),
            input_path=contig_path,
            is_demo=_module_is_demo(config, module_cfg),
            is_stub=is_stub,
            public_dataset=public_dataset and not is_stub,
        )
        level_fields = level.to_manifest_fields()
    except ValueError as exc:
        status = "partial:vdj_analysis_level_invalid"
        skip_reasons.append(f"analysis_level_invalid:{exc}")
        level_fields = classify_analysis_level(requested_level="smoke_backend", is_stub=True).to_manifest_fields()

    if missing_inputs:
        artifacts.update(_write_skip_outputs(tables_dir=tables_dir, figures_dir=figures_dir, objects_dir=objects_dir, samples=samples, analysis_fields=level_fields))
        n_cells = 0
        n_clonotypes = 0
    else:
        contigs = pd.read_csv(contig_path)
        clonotypes = pd.read_csv(clonotype_path)
        cells, productive = _filter_productive_cells(contigs)
        cell_meta = _cell_metadata(productive, samples)
        vdj_tables = _write_vdj_tables(
            tables_dir=tables_dir,
            contigs=contigs,
            clonotypes=clonotypes,
            cells=cells,
            productive=productive,
            cell_meta=cell_meta,
            analysis_fields=level_fields,
            input_artifact=str(input_dir or contig_path.parent),
            source_dataset=_source_dataset(config),
        )
        artifacts["tables"].update(vdj_tables)
        artifacts["figures"].update(_write_vdj_figures(tables_dir=tables_dir, figures_dir=figures_dir))
        artifacts["objects"].update(_write_vdj_object(objects_dir=objects_dir, cell_meta=cell_meta, clonotypes=clonotypes))
        n_cells = int(cell_meta["barcode"].nunique()) if "barcode" in cell_meta.columns else 0
        n_clonotypes = int(clonotypes.shape[0])

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
        "input_dir": str(input_dir or ""),
        "contig_annotations": str(contig_path or ""),
        "clonotypes": str(clonotype_path or ""),
        "n_cells": n_cells,
        "n_clonotypes": n_clonotypes,
        "artifacts": artifacts,
        "warnings": warnings,
        "limitations": list(known_limitations(module_name)),
        "handoff": handoff_plan(module_name),
        "reproducible_command": f"ultimate run --config {config.get('_config_path', '<config.yaml>')}",
        "backend": {
            "primary": "vdj_10x_contig_clonotype",
            "selected_backend_id": backend_plan["selected_backend_id"],
            "selected_backend_status": backend_plan["selected_backend_status"],
            "backend_role": backend_plan["selected_backend_role"],
            "resource_profile": backend_plan["backend_resource_profile"],
            "input_contract": "10x filtered_contig_annotations.csv + clonotypes.csv",
            "antigen_specificity_status": "not_inferred",
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
            "python_entrypoint": "ultimate.vdj_backend.run_vdj_backend",
            "status": "fully_automatic_mvp" if not missing_inputs else "partial_inputs_missing",
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
    return ((config.get("modules") or {}).get("vdj") or {}) if isinstance(config.get("modules"), dict) else {}


def _module_is_demo(config: dict[str, Any], module_cfg: dict[str, Any]) -> bool | None:
    if "is_demo" in module_cfg:
        return bool(module_cfg.get("is_demo"))
    project = config.get("project") or {}
    if "is_demo" in project:
        return bool(project.get("is_demo"))
    return None


def _source_dataset(config: dict[str, Any]) -> str:
    project = config.get("project") or {}
    return str(project.get("name") or project.get("job_id") or "vdj")


def _resolve_vdj_inputs(config: dict[str, Any]) -> tuple[Path | None, Path | None, Path | None]:
    module_cfg = _module_cfg(config)
    raw_cfg = module_cfg.get("raw") if isinstance(module_cfg.get("raw"), dict) else {}
    base = Path(str(config.get("_config_path") or ".")).resolve().parent

    input_dir_value = (
        module_cfg.get("input_dir")
        or module_cfg.get("cellranger_vdj_out")
        or raw_cfg.get("input_dir")
        or raw_cfg.get("cellranger_vdj_out")
        or raw_cfg.get("cellranger_out")
    )
    input_dir = _resolve_path(base, input_dir_value) if input_dir_value else None
    contig_value = module_cfg.get("contig_annotations") or raw_cfg.get("contig_annotations")
    clonotype_value = module_cfg.get("clonotypes") or raw_cfg.get("clonotypes")
    contig = _resolve_path(base, contig_value) if contig_value else (input_dir / "filtered_contig_annotations.csv" if input_dir else None)
    clonotypes = _resolve_path(base, clonotype_value) if clonotype_value else (input_dir / "clonotypes.csv" if input_dir else None)
    return contig, clonotypes, input_dir


def _resolve_path(base: Path, value: Any) -> Path:
    candidate = Path(str(value))
    return candidate if candidate.is_absolute() else (base / candidate).resolve()


def _filter_productive_cells(contigs: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    cells = contigs.copy()
    if "is_cell" in cells.columns:
        cells = cells[_as_bool_series(cells["is_cell"])].copy()
    productive = cells.copy()
    if "productive" in productive.columns:
        productive = productive[_as_bool_series(productive["productive"])].copy()
    return cells, productive


def _as_bool_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)
    if pd.api.types.is_numeric_dtype(series):
        return series.fillna(0).astype(int) != 0
    normalized = series.fillna("").astype(str).str.strip().str.lower()
    return normalized.isin({"true", "t", "1", "yes", "y"})


def _cell_metadata(productive: pd.DataFrame, samples: pd.DataFrame) -> pd.DataFrame:
    if productive.empty:
        return pd.DataFrame(columns=["barcode", "sample_id", "condition", "clonotype_id", "n_productive_contigs"])
    clone_col = _first_existing(productive, ("raw_clonotype_id", "clonotype_id"))
    reads_col = _first_existing(productive, ("reads", "read_count"))
    umi_col = _first_existing(productive, ("umis", "umi_count", "umi_counts"))
    agg: dict[str, tuple[str, str] | tuple[str, Any]] = {"n_productive_contigs": ("barcode", "size")}
    if "chain" in productive.columns:
        agg["n_chains"] = ("chain", "nunique")
    if reads_col:
        agg["total_reads"] = (reads_col, "sum")
    if umi_col:
        agg["total_umis"] = (umi_col, "sum")
    if clone_col:
        agg["clonotype_id"] = (clone_col, lambda values: ";".join(sorted(set(map(str, values)))))
    per_cell = productive.groupby("barcode").agg(**agg).reset_index()
    if "clonotype_id" not in per_cell.columns:
        per_cell["clonotype_id"] = "unknown"
    per_cell = _attach_sample_metadata(per_cell, samples)
    return per_cell


def _attach_sample_metadata(per_cell: pd.DataFrame, samples: pd.DataFrame) -> pd.DataFrame:
    frame = per_cell.copy()
    frame["barcode"] = frame["barcode"].astype(str)
    if not samples.empty and "barcode" in samples.columns:
        keep = [col for col in ("barcode", "sample_id", "condition", "cell_type", "state") if col in samples.columns]
        frame = frame.merge(samples[keep].copy(), on="barcode", how="left")
    if "sample_id" not in frame.columns:
        if not samples.empty and "sample_id" in samples.columns and samples["sample_id"].nunique() == 1:
            frame["sample_id"] = str(samples["sample_id"].iloc[0])
        else:
            frame["sample_id"] = frame["barcode"].str.extract(r"^([^_-]+)[_-]", expand=False).fillna("sample_1")
    if "condition" not in frame.columns:
        if not samples.empty and "condition" in samples.columns and samples["condition"].nunique() == 1:
            frame["condition"] = str(samples["condition"].iloc[0])
        else:
            frame["condition"] = "unknown"
    frame["sample_id"] = frame["sample_id"].fillna("sample_1").astype(str)
    frame["condition"] = frame["condition"].fillna("unknown").astype(str)
    return frame


def _first_existing(frame: pd.DataFrame, names: tuple[str, ...]) -> str | None:
    for name in names:
        if name in frame.columns:
            return name
    return None


def _write_vdj_tables(
    *,
    tables_dir: Path,
    contigs: pd.DataFrame,
    clonotypes: pd.DataFrame,
    cells: pd.DataFrame,
    productive: pd.DataFrame,
    cell_meta: pd.DataFrame,
    analysis_fields: dict[str, Any],
    input_artifact: str,
    source_dataset: str,
) -> dict[str, str]:
    paths: dict[str, str] = {}
    qc = _vdj_qc(cell_meta, contigs, cells, productive, analysis_fields, input_artifact, source_dataset)
    paths["vdj_qc"] = _write_tsv(qc, tables_dir / "vdj_qc.tsv")

    clone_summary = _clonotype_summary(clonotypes, cell_meta, analysis_fields, input_artifact, source_dataset)
    paths["clonotype_summary"] = _write_tsv(clone_summary, tables_dir / "clonotype_summary.tsv")

    clone_expansion = _clone_expansion(cell_meta, analysis_fields, input_artifact, source_dataset)
    paths["clone_expansion"] = _write_tsv(clone_expansion, tables_dir / "clone_expansion.tsv")

    clone_sharing = _clone_sharing(cell_meta, analysis_fields, input_artifact, source_dataset)
    paths["clone_sharing"] = _write_tsv(clone_sharing, tables_dir / "clone_sharing.tsv")

    paths["v_gene_usage"] = _write_tsv(_gene_usage(productive, "v_gene", analysis_fields, input_artifact, source_dataset), tables_dir / "v_gene_usage.tsv")
    paths["j_gene_usage"] = _write_tsv(_gene_usage(productive, "j_gene", analysis_fields, input_artifact, source_dataset), tables_dir / "j_gene_usage.tsv")
    paths["cdr3_length"] = _write_tsv(_cdr3_length(productive, cell_meta, analysis_fields, input_artifact, source_dataset), tables_dir / "cdr3_length.tsv")
    paths["clone_condition_summary"] = _write_tsv(
        _clone_condition_summary(cell_meta, analysis_fields, input_artifact, source_dataset),
        tables_dir / "clone_condition_summary.tsv",
    )
    paths["cell_metadata"] = _write_tsv(cell_meta, tables_dir / "vdj_cell_metadata.tsv")
    return paths


def _base_rows(analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str) -> dict[str, Any]:
    return {
        "module": "vdj",
        "run_id": source_dataset,
        "sample_id": "all",
        "source_dataset": source_dataset,
        "input_artifact": input_artifact,
        "input_modality": "vdj",
        "analysis_level": analysis_fields.get("analysis_level"),
        "result_scope": "vdj_10x_contig_clonotype_mvp",
        "method_status": "fully_automatic_mvp",
        "delivery_allowed": analysis_fields.get("delivery_allowed"),
    }


def _vdj_qc(
    cell_meta: pd.DataFrame,
    contigs: pd.DataFrame,
    cells: pd.DataFrame,
    productive: pd.DataFrame,
    analysis_fields: dict[str, Any],
    input_artifact: str,
    source_dataset: str,
) -> pd.DataFrame:
    rows = []
    for sample_id, group in _group_or_all(cell_meta, "sample_id"):
        row = _base_rows(analysis_fields, input_artifact, source_dataset)
        row.update(
            {
                "sample_id": sample_id,
                "n_contigs": int(contigs.shape[0]),
                "n_cell_contigs": int(cells.shape[0]),
                "n_productive_contigs": int(productive.shape[0]),
                "productive_contig_count": int(productive.shape[0]),
                "paired_chain_count": int((group.get("n_chains", pd.Series(dtype=int)).fillna(0).astype(int) >= 2).sum()) if "n_chains" in group.columns else 0,
                "vdj_input_status": "cellranger_vdj_tables_ready",
                "n_cells": int(group["barcode"].nunique()) if "barcode" in group.columns else 0,
                "n_clonotypes": int(group["clonotype_id"].nunique()) if "clonotype_id" in group.columns else 0,
                "paired_chain_status": "summary_only",
                "antigen_specificity_status": "not_inferred",
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _clonotype_summary(
    clonotypes: pd.DataFrame,
    cell_meta: pd.DataFrame,
    analysis_fields: dict[str, Any],
    input_artifact: str,
    source_dataset: str,
) -> pd.DataFrame:
    clone_col = _first_existing(clonotypes, ("clonotype_id", "raw_clonotype_id"))
    freq_col = _first_existing(clonotypes, ("frequency", "cell_count", "count"))
    cdr3_col = _first_existing(clonotypes, ("cdr3s_aa", "cdr3_aa", "cdr3"))
    rows = []
    if clone_col:
        source = clonotypes.copy()
        if freq_col is None and "clonotype_id" in cell_meta.columns:
            counts = cell_meta["clonotype_id"].value_counts().rename_axis(clone_col).reset_index(name="cell_count")
            source = source.merge(counts, on=clone_col, how="left")
            freq_col = "cell_count"
        for _, item in source.iterrows():
            row = _base_rows(analysis_fields, input_artifact, source_dataset)
            clone_id = str(item.get(clone_col, "unknown"))
            row.update(
                {
                    "clonotype_id": clone_id,
                    "chain": _clonotype_chain_label(clone_id, cell_meta),
                    "cell_count": int(float(item.get(freq_col, 0) or 0)) if freq_col else int((cell_meta.get("clonotype_id") == clone_id).sum()),
                    "sample_count": int(cell_meta.loc[cell_meta.get("clonotype_id") == clone_id, "sample_id"].nunique()) if "sample_id" in cell_meta.columns else 0,
                    "cdr3_aa": str(item.get(cdr3_col, "")) if cdr3_col else "",
                    "antigen_specificity_status": "not_inferred",
                    "interpretation_warning": VDJ_WARNING,
                }
            )
            rows.append(row)
    if not rows:
        row = _base_rows(analysis_fields, input_artifact, source_dataset)
        row.update({"clonotype_id": "unknown", "cell_count": 0, "sample_count": 0, "cdr3_aa": "", "antigen_specificity_status": "not_inferred", "interpretation_warning": VDJ_WARNING})
        rows.append(row)
    return pd.DataFrame(rows).sort_values("cell_count", ascending=False)


def _clone_expansion(cell_meta: pd.DataFrame, analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str) -> pd.DataFrame:
    rows = []
    if not cell_meta.empty:
        counts = cell_meta.groupby(["sample_id", "clonotype_id"], dropna=False).size().reset_index(name="clone_size")
        for _, item in counts.iterrows():
            row = _base_rows(analysis_fields, input_artifact, source_dataset)
            size = int(item["clone_size"])
            row.update(
                {
                    "sample_id": str(item["sample_id"]),
                    "clonotype_id": str(item["clonotype_id"]),
                    "clone_size": size,
                    "expansion_class": _expansion_class(size),
                }
            )
            rows.append(row)
    return pd.DataFrame(rows or [_empty_clone_row(analysis_fields, input_artifact, source_dataset)])


def _clone_sharing(cell_meta: pd.DataFrame, analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str) -> pd.DataFrame:
    rows = []
    if not cell_meta.empty:
        samples = sorted(cell_meta["sample_id"].dropna().astype(str).unique())
        clone_sets = {sample: set(cell_meta.loc[cell_meta["sample_id"].astype(str) == sample, "clonotype_id"].dropna().astype(str)) for sample in samples}
        if len(samples) == 1:
            samples = samples * 2
        for left in sorted(set(samples)):
            for right in sorted(set(samples)):
                shared = clone_sets.get(left, set()).intersection(clone_sets.get(right, set()))
                union = clone_sets.get(left, set()).union(clone_sets.get(right, set()))
                row = _base_rows(analysis_fields, input_artifact, source_dataset)
                row.update(
                    {
                        "sample_id": left,
                        "sample_id_a": left,
                        "sample_id_2": right,
                        "sample_id_b": right,
                        "shared_clonotype_count": int(len(shared)),
                        "jaccard_index": float(len(shared) / len(union)) if union else 0.0,
                        "sharing_metric": float(len(shared) / len(union)) if union else 0.0,
                        "interpretation_warning": "clone sharing 不等于抗原特异性相同。",
                    }
                )
                rows.append(row)
    return pd.DataFrame(rows or [_empty_clone_row(analysis_fields, input_artifact, source_dataset)])


def _gene_usage(productive: pd.DataFrame, gene_col: str, analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str) -> pd.DataFrame:
    rows = []
    if gene_col in productive.columns and not productive.empty:
        counts = productive[gene_col].fillna("unknown").astype(str).value_counts().reset_index()
        counts.columns = [gene_col, "productive_chain_count"]
        total = counts["productive_chain_count"].sum()
        for _, item in counts.iterrows():
            row = _base_rows(analysis_fields, input_artifact, source_dataset)
            row.update(
                {
                    gene_col: str(item[gene_col]),
                    "productive_chain_count": int(item["productive_chain_count"]),
                    "usage_fraction": float(item["productive_chain_count"] / total) if total else 0.0,
                }
            )
            rows.append(row)
    if not rows:
        row = _base_rows(analysis_fields, input_artifact, source_dataset)
        row.update({gene_col: "not_available", "productive_chain_count": 0, "usage_fraction": 0.0})
        rows.append(row)
    return pd.DataFrame(rows)


def _cdr3_length(productive: pd.DataFrame, cell_meta: pd.DataFrame, analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str) -> pd.DataFrame:
    cdr3_col = _first_existing(productive, ("cdr3", "cdr3_aa", "cdr3s_aa"))
    clone_col = _first_existing(productive, ("raw_clonotype_id", "clonotype_id"))
    rows = []
    if cdr3_col:
        for _, item in productive.iterrows():
            cdr3 = str(item.get(cdr3_col, "") or "")
            row = _base_rows(analysis_fields, input_artifact, source_dataset)
            row.update(
                {
                    "barcode": str(item.get("barcode", "")),
                    "clonotype_id": str(item.get(clone_col, "")) if clone_col else "",
                    "chain": str(item.get("chain", "")),
                    "cdr3_aa": cdr3,
                    "cdr3_length_aa": int(len(cdr3)),
                    "cell_count": 1,
                }
            )
            rows.append(row)
    return pd.DataFrame(rows or [_empty_clone_row(analysis_fields, input_artifact, source_dataset)])


def _clone_condition_summary(cell_meta: pd.DataFrame, analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str) -> pd.DataFrame:
    rows = []
    if not cell_meta.empty:
        counts = cell_meta.groupby(["condition", "clonotype_id"], dropna=False).size().reset_index(name="clone_size")
        for _, item in counts.iterrows():
            row = _base_rows(analysis_fields, input_artifact, source_dataset)
            row.update(
                {
                    "condition": str(item["condition"]),
                    "clonotype_id": str(item["clonotype_id"]),
                    "clone_size": int(item["clone_size"]),
                    "clone_state_handoff_status": "requires_external_scrna_metadata",
                }
            )
            rows.append(row)
    return pd.DataFrame(rows or [_empty_clone_row(analysis_fields, input_artifact, source_dataset)])


def _group_or_all(frame: pd.DataFrame, column: str) -> list[tuple[str, pd.DataFrame]]:
    if frame.empty or column not in frame.columns:
        return [("all", frame)]
    return [(str(key), group.copy()) for key, group in frame.groupby(column, dropna=False)]


def _expansion_class(size: int) -> str:
    if size <= 1:
        return "singleton"
    if size <= 3:
        return "small"
    if size <= 10:
        return "expanded"
    return "large"


def _clonotype_chain_label(clone_id: str, cell_meta: pd.DataFrame) -> str:
    if cell_meta.empty or "clonotype_id" not in cell_meta.columns or "n_chains" not in cell_meta.columns:
        return "not_recorded"
    subset = cell_meta[cell_meta["clonotype_id"].astype(str) == str(clone_id)]
    if subset.empty:
        return "not_recorded"
    max_chains = int(subset["n_chains"].fillna(0).astype(int).max())
    if max_chains >= 2:
        return "paired_chain_summary"
    if max_chains == 1:
        return "single_chain_summary"
    return "not_recorded"


def _empty_clone_row(analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str) -> dict[str, Any]:
    row = _base_rows(analysis_fields, input_artifact, source_dataset)
    row.update({"clonotype_id": "none", "clone_size": 0, "status": "no_productive_clonotypes"})
    return row


def _write_vdj_figures(*, tables_dir: Path, figures_dir: Path) -> dict[str, str]:
    tokens = apply_clinical_journal_style()
    clone_expansion = pd.read_csv(tables_dir / "clone_expansion.tsv", sep="\t")
    v_usage = pd.read_csv(tables_dir / "v_gene_usage.tsv", sep="\t")
    clone_sharing = pd.read_csv(tables_dir / "clone_sharing.tsv", sep="\t")

    clone_path = figures_dir / "clone_size_distribution.png"
    plt.figure(figsize=(6, 4))
    sizes = clone_expansion.get("clone_size", pd.Series([0])).astype(float)
    sns.histplot(sizes, bins=max(3, min(20, int(sizes.max() if len(sizes) else 3))), color=tokens["primary"])
    plt.xlabel("Clone size")
    plt.ylabel("Clonotype count")
    plt.title("Clone Size Distribution")
    plt.tight_layout()
    save_figure(clone_path, style=tokens)

    v_path = figures_dir / "v_gene_usage.png"
    plt.figure(figsize=(7, 4))
    gene_col = "v_gene" if "v_gene" in v_usage.columns else v_usage.columns[-3]
    top_v = v_usage.sort_values("productive_chain_count", ascending=False).head(15)
    sns.barplot(data=top_v, x=gene_col, y="productive_chain_count", color=tokens["primary"])
    plt.xticks(rotation=65, ha="right")
    plt.xlabel("V gene")
    plt.ylabel("Productive chains")
    plt.title("V Gene Usage")
    plt.tight_layout()
    save_figure(v_path, style=tokens)

    sharing_path = figures_dir / "clone_sharing_heatmap.png"
    plt.figure(figsize=(5, 4))
    if {"sample_id", "sample_id_2", "shared_clonotype_count"}.issubset(clone_sharing.columns):
        matrix = clone_sharing.pivot_table(index="sample_id", columns="sample_id_2", values="shared_clonotype_count", fill_value=0)
    else:
        matrix = pd.DataFrame([[0]], index=["sample_1"], columns=["sample_1"])
    sns.heatmap(matrix, annot=True, fmt=".0f", cmap="Blues", cbar_kws={"label": "Shared clonotypes"})
    plt.title("Clone Sharing")
    plt.tight_layout()
    save_figure(sharing_path, style=tokens)
    return {
        "clone_size_distribution": str(clone_path),
        "v_gene_usage": str(v_path),
        "clone_sharing_heatmap": str(sharing_path),
    }


def _write_vdj_object(*, objects_dir: Path, cell_meta: pd.DataFrame, clonotypes: pd.DataFrame) -> dict[str, str]:
    object_path = objects_dir / "vdj_mvp.h5ad"
    try:
        import anndata as ad
        from scipy import sparse

        obs = cell_meta.set_index("barcode", drop=False).copy() if "barcode" in cell_meta.columns else pd.DataFrame(index=[])
        var = pd.DataFrame(index=sorted(clonotypes.get("clonotype_id", pd.Series(["unknown"])).fillna("unknown").astype(str).unique()))
        if obs.empty or var.empty:
            matrix = sparse.csr_matrix((max(1, obs.shape[0]), max(1, var.shape[0])), dtype=np.float32)
        else:
            var_index = {clone: idx for idx, clone in enumerate(var.index)}
            rows = np.arange(obs.shape[0])
            cols = [var_index.get(str(value), 0) for value in obs.get("clonotype_id", pd.Series(["unknown"] * obs.shape[0])).astype(str)]
            matrix = sparse.csr_matrix((np.ones(obs.shape[0], dtype=np.float32), (rows, cols)), shape=(obs.shape[0], var.shape[0]))
        ad.AnnData(X=matrix, obs=obs, var=var).write_h5ad(object_path)
        status = "h5ad_written"
    except Exception as exc:  # pragma: no cover - exercised only when optional h5ad stack is absent
        object_path.write_text(
            json.dumps({"object_status": "json_fallback_not_h5ad", "reason": f"{type(exc).__name__}:{exc}"}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        status = "json_fallback_not_h5ad"
    manifest_path = objects_dir / "vdj_mvp_object_manifest.json"
    manifest_path.write_text(json.dumps({"object": str(object_path), "status": status}, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"mvp_object": str(object_path), "object_manifest": str(manifest_path)}


def _write_skip_outputs(*, tables_dir: Path, figures_dir: Path, objects_dir: Path, samples: pd.DataFrame, analysis_fields: dict[str, Any]) -> dict[str, dict[str, str]]:
    base = _base_rows(analysis_fields, "missing_vdj_input", "vdj")
    row = {
        **base,
        "status": "skipped_missing_input",
        "clonotype_id": "none",
        "clone_size": 0,
        "productive_contig_count": 0,
        "paired_chain_count": 0,
        "vdj_input_status": "missing_input",
        "chain": "not_recorded",
        "sample_id_a": "none",
        "sample_id_b": "none",
        "sharing_metric": 0.0,
        "cell_count": 0,
        "antigen_specificity_status": "not_inferred",
    }
    table_paths = {}
    for filename in (
        "vdj_qc.tsv",
        "clonotype_summary.tsv",
        "clone_expansion.tsv",
        "clone_sharing.tsv",
        "v_gene_usage.tsv",
        "j_gene_usage.tsv",
        "cdr3_length.tsv",
        "clone_condition_summary.tsv",
    ):
        table_paths[filename.replace(".tsv", "")] = _write_tsv(pd.DataFrame([row]), tables_dir / filename)
    figure_paths = _write_placeholder_figures(figures_dir)
    object_path = objects_dir / "vdj_mvp.h5ad"
    object_path.write_text(json.dumps({"status": "skipped_missing_input", "sample_count": int(samples.shape[0])}, indent=2), encoding="utf-8")
    return {"tables": table_paths, "figures": figure_paths, "objects": {"mvp_object": str(object_path)}}


def _write_placeholder_figures(figures_dir: Path) -> dict[str, str]:
    tokens = apply_clinical_journal_style()
    paths = {}
    for key, title in {
        "clone_size_distribution": "Clone Size Distribution",
        "v_gene_usage": "V Gene Usage",
        "clone_sharing_heatmap": "Clone Sharing",
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
