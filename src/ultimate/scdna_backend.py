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


SCDNA_BACKEND_ID = "scdna.default.matrix_ready_handoff"
SCDNA_WARNING = "allele dropout、低覆盖和 amplicon bias 会影响 scDNA 解释；clone/phylogeny 结果是模型输入或假设，不是唯一真实进化历史。"


def has_scdna_backend_config(config: dict[str, Any]) -> bool:
    module_cfg = _module_cfg(config)
    raw_cfg = module_cfg.get("raw") if isinstance(module_cfg.get("raw"), dict) else {}
    keys = {
        "source_root",
        "input_dir",
        "input_path",
        "coverage_table",
        "variant_table",
        "vaf_matrix",
        "cell_variant_matrix",
        "cnv_matrix",
    }
    return any(module_cfg.get(key) for key in keys) or any(raw_cfg.get(key) for key in keys)


def run_scdna_backend(*, config: dict[str, Any], output_dir: Path, samples: pd.DataFrame) -> dict[str, Any]:
    module_name = "scdna"
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
    status = "partial:scdna_inputs_missing" if missing_inputs else "complete_scdna_matrix_ready_backend"
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
        status = "partial:scdna_analysis_level_invalid"
        skip_reasons.append(f"analysis_level_invalid:{exc}")
        level_fields = classify_analysis_level(requested_level="smoke_backend", is_stub=True).to_manifest_fields()

    artifacts: dict[str, dict[str, str]] = {"tables": {}, "figures": {}, "objects": {}, "reports": {}}
    warnings = [SCDNA_WARNING]
    n_cells = 0
    n_variants = 0
    if skip_reasons:
        artifacts.update(_write_skip_outputs(tables_dir=tables_dir, figures_dir=figures_dir, objects_dir=objects_dir, analysis_fields=level_fields))
    else:
        try:
            data = _read_scdna_input(config)
        except Exception as exc:
            status = "partial:scdna_input_read_failed"
            skip_reasons.append(f"input_read_failed:{type(exc).__name__}:{exc}")
            level_fields = classify_analysis_level(requested_level="smoke_backend", is_stub=True).to_manifest_fields()
            artifacts.update(_write_skip_outputs(tables_dir=tables_dir, figures_dir=figures_dir, objects_dir=objects_dir, analysis_fields=level_fields))
            data = None
        if data is not None:
            artifacts["tables"].update(
                _write_scdna_tables(
                    tables_dir=tables_dir,
                    data=data,
                    input_ref=str(input_ref or ""),
                    source_dataset=_source_dataset(config),
                    analysis_fields=level_fields,
                )
            )
            artifacts["figures"].update(_write_scdna_figures(tables_dir=tables_dir, figures_dir=figures_dir))
            artifacts["objects"].update(_write_scdna_object(objects_dir=objects_dir, data=data, input_ref=str(input_ref or "")))
            n_cells = int(data["coverage_qc"]["cell_id"].nunique()) if not data["coverage_qc"].empty else int(data["cell_vaf"]["cell_id"].nunique())
            n_variants = int(data["variant_qc"]["variant_id"].nunique()) if "variant_id" in data["variant_qc"].columns else 0

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
        "artifacts": artifacts,
        "warnings": warnings,
        "limitations": list(known_limitations(module_name)),
        "handoff": handoff_plan(module_name),
        "reproducible_command": f"ultimate run --config {config.get('_config_path', '<config.yaml>')}",
        "backend": {
            "primary": "scdna_matrix_ready_result_import",
            "selected_backend_id": backend_plan["selected_backend_id"],
            "selected_backend_status": backend_plan["selected_backend_status"],
            "backend_role": backend_plan["selected_backend_role"],
            "resource_profile": backend_plan["backend_resource_profile"],
            "interpretation_warning": SCDNA_WARNING,
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
            "python_entrypoint": "ultimate.scdna_backend.run_scdna_backend",
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
    return ((config.get("modules") or {}).get("scdna") or {}) if isinstance(config.get("modules"), dict) else {}


def _module_is_demo(config: dict[str, Any], module_cfg: dict[str, Any]) -> bool | None:
    if "is_demo" in module_cfg:
        return bool(module_cfg.get("is_demo"))
    project = config.get("project") or {}
    if "is_demo" in project:
        return bool(project.get("is_demo"))
    return None


def _source_dataset(config: dict[str, Any]) -> str:
    project = config.get("project") or {}
    return str(project.get("name") or project.get("job_id") or "scdna")


def _primary_input_ref(config: dict[str, Any]) -> Path | None:
    module_cfg = _module_cfg(config)
    raw_cfg = module_cfg.get("raw") if isinstance(module_cfg.get("raw"), dict) else {}
    base = Path(str(config.get("_config_path") or ".")).resolve().parent
    value = (
        module_cfg.get("source_root")
        or module_cfg.get("input_dir")
        or module_cfg.get("input_path")
        or module_cfg.get("coverage_table")
        or module_cfg.get("variant_table")
        or module_cfg.get("cell_variant_matrix")
        or raw_cfg.get("source_root")
        or raw_cfg.get("input_dir")
        or raw_cfg.get("input_path")
        or raw_cfg.get("coverage_table")
        or raw_cfg.get("variant_table")
        or raw_cfg.get("cell_variant_matrix")
    )
    return _resolve_path(base, value) if value else None


def _resolve_path(base: Path, value: Any) -> Path:
    candidate = Path(str(value))
    return candidate if candidate.is_absolute() else (base / candidate).resolve()


def _missing_input_reasons(config: dict[str, Any]) -> list[str]:
    input_ref = _primary_input_ref(config)
    if input_ref is None:
        return ["missing_scdna_input"]
    if not input_ref.exists():
        return [f"missing_input_path:{input_ref}"]
    if input_ref.is_file():
        if input_ref.suffix.lower() not in {".tsv", ".txt", ".csv", ".vcf"}:
            return [f"unsupported_input_extension:{input_ref.suffix or 'none'}"]
        return []
    paths = _resolve_scdna_paths(config)
    if not paths.get("coverage") and not paths.get("mapping") and not paths.get("variant"):
        return [f"missing_scdna_tables:{input_ref}"]
    return []


def _resolve_scdna_paths(config: dict[str, Any]) -> dict[str, Path | None]:
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
    coverage = value_path("coverage_table")
    mapping = value_path("mapping_table")
    sanity = value_path("sanity_table")
    variant = value_path("variant_table")
    vaf = value_path("vaf_matrix", "cell_vaf_matrix")
    cnv = value_path("cnv_matrix", "cell_cnv_matrix")
    cell_variant = value_path("cell_variant_matrix")
    top_chromosomes = value_path("top_chromosomes_table")

    if source_root and source_root.is_dir():
        stats = source_root / "analysis_dna" / "stats"
        if not stats.exists():
            stats = source_root
        coverage = coverage or _first_existing(stats / "dna_mt_depth_summary.tsv", stats / "coverage_qc.tsv")
        mapping = mapping or _first_existing(stats / "mapped_unmapped_summary.tsv")
        sanity = sanity or _first_existing(stats / "method_reference_sanity_check.tsv")
        top_chromosomes = top_chromosomes or _first_existing(stats / "all_samples_top_chromosomes.tsv")
        if top_chromosomes is None:
            top_candidates = sorted(stats.glob("*_top_chromosomes.tsv"))
            top_chromosomes = top_candidates[0] if top_candidates else None
        variant = variant or _first_existing(source_root / "analysis_dna" / "variants.tsv", source_root / "variants.tsv", stats / "variant_qc.tsv")
        vaf = vaf or _first_existing(source_root / "analysis_dna" / "cell_vaf_matrix.tsv", source_root / "cell_vaf_matrix.tsv")
        cnv = cnv or _first_existing(source_root / "analysis_dna" / "cell_cnv_matrix.tsv", source_root / "cell_cnv_matrix.tsv")
        cell_variant = cell_variant or _first_existing(source_root / "analysis_dna" / "cell_variant_matrix.tsv", source_root / "cell_variant_matrix.tsv")
    elif input_ref and input_ref.is_file():
        lower = input_ref.name.lower()
        if "vaf" in lower:
            vaf = vaf or input_ref
        elif "cnv" in lower:
            cnv = cnv or input_ref
        elif "variant" in lower:
            variant = variant or input_ref
        else:
            coverage = coverage or input_ref

    return {
        "coverage": coverage,
        "mapping": mapping,
        "sanity": sanity,
        "variant": variant,
        "vaf": vaf,
        "cnv": cnv,
        "cell_variant": cell_variant,
        "top_chromosomes": top_chromosomes,
    }


def _first_existing(*paths: Path) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def _read_scdna_input(config: dict[str, Any]) -> dict[str, Any]:
    paths = _resolve_scdna_paths(config)
    coverage = _read_coverage(paths.get("coverage"), mapping_path=paths.get("mapping"), sanity_path=paths.get("sanity"))
    variant_qc = _read_variant_qc(paths.get("variant"), coverage=coverage)
    cell_vaf = _read_cell_vaf(paths.get("vaf"), variant_qc=variant_qc, coverage=coverage)
    cell_variant = _read_cell_variant(paths.get("cell_variant"), cell_vaf=cell_vaf)
    cnv = _read_cnv(paths.get("cnv"), coverage=coverage, top_chromosomes_path=paths.get("top_chromosomes"))
    clone_summary = _clone_summary(cell_variant=cell_variant, cnv=cnv)
    mutation_cooccurrence = _mutation_cooccurrence(cell_variant)
    phylogeny = _phylogeny_input(cell_variant)
    if coverage.empty and variant_qc.empty and cell_vaf.empty and cnv.empty:
        raise ValueError("no_scdna_tables_readable")
    return {
        "paths": {key: str(value) for key, value in paths.items() if value},
        "coverage_qc": coverage,
        "variant_qc": variant_qc,
        "cell_vaf": cell_vaf,
        "cell_variant": cell_variant,
        "cnv": cnv,
        "clone_summary": clone_summary,
        "mutation_cooccurrence": mutation_cooccurrence,
        "phylogeny": phylogeny,
    }


def _read_table(path: Path | None) -> pd.DataFrame:
    if path is None or not path.exists():
        return pd.DataFrame()
    sep = "," if path.suffix.lower() == ".csv" else "\t"
    return pd.read_csv(path, sep=sep)


def _read_coverage(path: Path | None, *, mapping_path: Path | None, sanity_path: Path | None) -> pd.DataFrame:
    frame = _read_table(path)
    if frame.empty:
        return pd.DataFrame(columns=["module", "cell_id", "mean_depth", "covered_loci", "dropout_warning", "delivery_allowed"])
    frame = frame.copy()
    sample_col = _pick_col(frame, ("sample_id", "sample", "cell_id"), default=frame.columns[0])
    nuclear_col = _pick_col(frame, ("mean_nuclear_depth", "nuclear_depth", "mean_depth"), numeric=True)
    mt_col = _pick_col(frame, ("mtDNA_depth", "mtdna_depth", "chrM_depth"), numeric=True)
    out = pd.DataFrame(
        {
            "module": "scdna",
            "cell_id": frame[sample_col].astype(str),
            "mean_depth": pd.to_numeric(_series_or_default(frame, nuclear_col, 0.0), errors="coerce").fillna(0.0),
            "covered_loci": pd.to_numeric(_series_or_default(frame, "nuclear_bases" if "nuclear_bases" in frame.columns else None, 0), errors="coerce").fillna(0).astype(int),
            "mtDNA_depth": pd.to_numeric(_series_or_default(frame, mt_col, 0.0), errors="coerce").fillna(0.0),
        }
    )
    mapping = _read_table(mapping_path)
    if not mapping.empty and {"sample_id", "mapped_fraction"}.issubset(mapping.columns):
        out = out.merge(mapping[["sample_id", "mapped_fraction"]].rename(columns={"sample_id": "cell_id"}), on="cell_id", how="left")
    else:
        out["mapped_fraction"] = np.nan
    sanity = _read_table(sanity_path)
    if not sanity.empty:
        key = _pick_col(sanity, ("sample", "sample_id", "cell_id"), default=sanity.columns[0])
        cols = [col for col in ("bam_quickcheck", "contig_naming_consistent", "final_call") if col in sanity.columns]
        if cols:
            out = out.merge(sanity[[key, *cols]].rename(columns={key: "cell_id"}), on="cell_id", how="left")
    out["dropout_warning"] = np.where(out["mean_depth"] < 1, "low_coverage_or_dropout_risk", "coverage_proxy_available")
    out["delivery_allowed"] = False
    return out


def _read_variant_qc(path: Path | None, *, coverage: pd.DataFrame) -> pd.DataFrame:
    frame = _read_table(path)
    columns = ["module", "variant_id", "chrom", "pos", "ref", "alt", "depth", "vaf", "filter_status"]
    if frame.empty:
        rows = []
        cells = coverage["cell_id"].astype(str).tolist() if not coverage.empty else ["scdna_input"]
        for cell in cells:
            rows.append(
                {
                    "module": "scdna",
                    "variant_id": f"{cell}:variant_calling_handoff",
                    "chrom": "NA",
                    "pos": np.nan,
                    "ref": "NA",
                    "alt": "NA",
                    "depth": float(coverage.loc[coverage["cell_id"] == cell, "mean_depth"].iloc[0]) if not coverage.empty else np.nan,
                    "vaf": np.nan,
                    "filter_status": "variant_calling_not_run; provide VCF or cell_variant_matrix for mutation-level calls",
                }
            )
        return pd.DataFrame(rows, columns=columns)
    frame = frame.copy()
    variant_col = _pick_col(frame, ("variant_id", "variant", "id"), default=frame.columns[0])
    out = pd.DataFrame(
        {
            "module": "scdna",
            "variant_id": frame[variant_col].astype(str),
            "chrom": _series_or_default(frame, _pick_col(frame, ("chrom", "chr")), "NA"),
            "pos": pd.to_numeric(_series_or_default(frame, _pick_col(frame, ("pos", "position")), np.nan), errors="coerce"),
            "ref": _series_or_default(frame, _pick_col(frame, ("ref", "reference")), "NA"),
            "alt": _series_or_default(frame, _pick_col(frame, ("alt", "alternate")), "NA"),
            "depth": pd.to_numeric(_series_or_default(frame, _pick_col(frame, ("depth", "dp"), numeric=True), np.nan), errors="coerce"),
            "vaf": pd.to_numeric(_series_or_default(frame, _pick_col(frame, ("vaf", "af"), numeric=True), np.nan), errors="coerce"),
            "filter_status": _series_or_default(frame, _pick_col(frame, ("filter_status", "filter", "status")), "candidate"),
        }
    )
    return out[columns]


def _read_cell_vaf(path: Path | None, *, variant_qc: pd.DataFrame, coverage: pd.DataFrame) -> pd.DataFrame:
    frame = _read_table(path)
    if not frame.empty:
        cell_col = _pick_col(frame, ("cell_id", "cell", "sample_id", "barcode"), default=frame.columns[0])
        if {"variant_id", "vaf"}.issubset(frame.columns):
            out = frame.rename(columns={cell_col: "cell_id"})[["cell_id", "variant_id", "vaf"]].copy()
        else:
            value_cols = [col for col in frame.columns if col != cell_col and pd.api.types.is_numeric_dtype(frame[col])]
            out = frame[[cell_col, *value_cols]].melt(id_vars=cell_col, var_name="variant_id", value_name="vaf").rename(columns={cell_col: "cell_id"})
        out["module"] = "scdna"
        out["depth"] = np.nan
        out["assay_limitation"] = "variant_matrix_imported"
        return out[["module", "cell_id", "variant_id", "chrom", "pos", "ref", "alt", "vaf", "depth", "assay_limitation"]] if {"chrom", "pos", "ref", "alt"}.issubset(out.columns) else _annotate_vaf(out, variant_qc)
    rows = []
    cells = coverage["cell_id"].astype(str).tolist() if not coverage.empty else ["scdna_input"]
    for _, variant in variant_qc.iterrows():
        for cell in cells:
            rows.append(
                {
                    "module": "scdna",
                    "cell_id": cell,
                    "variant_id": variant["variant_id"],
                    "chrom": variant["chrom"],
                    "pos": variant["pos"],
                    "ref": variant["ref"],
                    "alt": variant["alt"],
                    "vaf": np.nan,
                    "depth": float(coverage.loc[coverage["cell_id"] == cell, "mean_depth"].iloc[0]) if not coverage.empty else np.nan,
                    "assay_limitation": "vaf_matrix_not_available; mutation-level interpretation blocked",
                }
            )
    return pd.DataFrame(rows)


def _annotate_vaf(out: pd.DataFrame, variant_qc: pd.DataFrame) -> pd.DataFrame:
    annot = variant_qc[["variant_id", "chrom", "pos", "ref", "alt"]].drop_duplicates("variant_id") if not variant_qc.empty else pd.DataFrame()
    if not annot.empty:
        out = out.merge(annot, on="variant_id", how="left")
    for col, default in (("chrom", "NA"), ("pos", np.nan), ("ref", "NA"), ("alt", "NA"), ("depth", np.nan), ("assay_limitation", "variant_matrix_imported")):
        if col not in out.columns:
            out[col] = default
    out["vaf"] = pd.to_numeric(out["vaf"], errors="coerce")
    return out[["module", "cell_id", "variant_id", "chrom", "pos", "ref", "alt", "vaf", "depth", "assay_limitation"]]


def _read_cell_variant(path: Path | None, *, cell_vaf: pd.DataFrame) -> pd.DataFrame:
    frame = _read_table(path)
    if not frame.empty:
        return frame
    out = cell_vaf.copy()
    out["genotype_call"] = np.where(pd.to_numeric(out["vaf"], errors="coerce").fillna(0) >= 0.2, "alt_detected", "not_called")
    out["alt_count"] = np.nan
    out["ref_count"] = np.nan
    return out[["module", "cell_id", "variant_id", "genotype_call", "alt_count", "ref_count", "assay_limitation"]]


def _read_cnv(path: Path | None, *, coverage: pd.DataFrame, top_chromosomes_path: Path | None) -> pd.DataFrame:
    frame = _read_table(path)
    if not frame.empty:
        return frame
    rows = []
    for _, row in coverage.iterrows():
        rows.append(
            {
                "module": "scdna",
                "cell_id": row["cell_id"],
                "chrom": "genome_wide",
                "start": 0,
                "end": 0,
                "copy_number_state": "cnv_not_called_depth_proxy_only",
                "confidence": "handoff_required",
            }
        )
    top = _read_table(top_chromosomes_path)
    if not top.empty:
        sample_col = _pick_col(top, ("sample_id", "sample", "cell_id"), default=top.columns[0])
        chrom_col = _pick_col(top, ("chrom", "chr"), default=top.columns[1] if len(top.columns) > 1 else top.columns[0])
        reads_col = _pick_col(top, ("mapped_reads", "reads"), numeric=True)
        for _, row in top.head(100).iterrows():
            rows.append(
                {
                    "module": "scdna",
                    "cell_id": str(row[sample_col]),
                    "chrom": str(row[chrom_col]),
                    "start": 0,
                    "end": 0,
                    "copy_number_state": "chromosome_coverage_proxy",
                    "confidence": float(row[reads_col]) if reads_col else "proxy",
                }
            )
    return pd.DataFrame(rows)


def _clone_summary(*, cell_variant: pd.DataFrame, cnv: pd.DataFrame) -> pd.DataFrame:
    informative = cell_variant[cell_variant["genotype_call"].astype(str).eq("alt_detected")] if "genotype_call" in cell_variant.columns else pd.DataFrame()
    if informative.empty:
        n_cells = int(cnv["cell_id"].nunique()) if not cnv.empty and "cell_id" in cnv.columns else 0
        return pd.DataFrame(
            [
                {
                    "module": "scdna",
                    "clone_id": "clone_model_not_run",
                    "cell_count": n_cells,
                    "marker_variants": "variant_or_cnv_matrix_required",
                    "clone_call_status": "clone_ready_handoff_only",
                    "interpretation_warning": "clone tree is not inferred by this MVP backend",
                }
            ]
        )
    grouped = informative.groupby("variant_id")["cell_id"].nunique().reset_index(name="cell_count")
    grouped["module"] = "scdna"
    grouped["clone_id"] = grouped["variant_id"].map(lambda value: f"candidate_clone_{value}")
    grouped["marker_variants"] = grouped["variant_id"]
    grouped["clone_call_status"] = "candidate_from_variant_matrix"
    grouped["interpretation_warning"] = "clone assignment requires dedicated model and review"
    return grouped[["module", "clone_id", "cell_count", "marker_variants", "clone_call_status", "interpretation_warning"]]


def _mutation_cooccurrence(cell_variant: pd.DataFrame) -> pd.DataFrame:
    columns = ["module", "variant_id_a", "variant_id_b", "cooccurrence_count", "cooccurrence_status"]
    if cell_variant.empty or "genotype_call" not in cell_variant.columns:
        return pd.DataFrame(columns=columns)
    informative = cell_variant[cell_variant["genotype_call"].astype(str).eq("alt_detected")]
    rows = []
    by_cell = informative.groupby("cell_id")["variant_id"].apply(lambda values: sorted(set(map(str, values))))
    for variants in by_cell:
        for a, b in combinations(variants[:50], 2):
            rows.append((a, b))
    if not rows:
        return pd.DataFrame([{"module": "scdna", "variant_id_a": "not_available", "variant_id_b": "not_available", "cooccurrence_count": 0, "cooccurrence_status": "variant_matrix_required"}])
    counts = pd.Series(rows).value_counts()
    return pd.DataFrame(
        [
            {"module": "scdna", "variant_id_a": a, "variant_id_b": b, "cooccurrence_count": int(count), "cooccurrence_status": "candidate_cooccurrence"}
            for (a, b), count in counts.items()
        ],
        columns=columns,
    )


def _phylogeny_input(cell_variant: pd.DataFrame) -> pd.DataFrame:
    if cell_variant.empty:
        return pd.DataFrame(columns=["module", "cell_id", "variant_id", "binary_state", "phylogeny_handoff_status"])
    out = cell_variant[["module", "cell_id", "variant_id"]].copy()
    out["binary_state"] = np.where(cell_variant.get("genotype_call", pd.Series(index=cell_variant.index)).astype(str).eq("alt_detected"), 1, 0)
    out["phylogeny_handoff_status"] = np.where(out["binary_state"] == 1, "phylogeny_ready_binary_variant", "not_informative_or_not_called")
    return out


def _write_scdna_tables(
    *,
    tables_dir: Path,
    data: dict[str, Any],
    input_ref: str,
    source_dataset: str,
    analysis_fields: dict[str, Any],
) -> dict[str, str]:
    input_summary = pd.DataFrame(
        [
            {
                "module": "scdna",
                "source_dataset": source_dataset,
                "input_ref": input_ref,
                "analysis_level": analysis_fields.get("analysis_level"),
                "input_tables": json.dumps(data["paths"], ensure_ascii=False),
                "variant_level_status": "variant_matrix_available" if not data["cell_variant"].empty and data["cell_variant"]["genotype_call"].astype(str).eq("alt_detected").any() else "handoff_or_no_variant_matrix",
            }
        ]
    )
    outputs = {
        "coverage_qc": data["coverage_qc"],
        "variant_qc": data["variant_qc"],
        "cell_variant_matrix": data["cell_variant"],
        "cell_vaf_matrix": data["cell_vaf"],
        "cell_cnv_matrix": data["cnv"],
        "clone_summary": data["clone_summary"],
        "mutation_cooccurrence": data["mutation_cooccurrence"],
        "phylogeny_input": data["phylogeny"],
        "input_read_summary": input_summary,
    }
    paths: dict[str, str] = {}
    for key, frame in outputs.items():
        path = tables_dir / f"{key}.tsv"
        frame.to_csv(path, sep="\t", index=False)
        paths[key] = str(path)
    return paths


def _write_scdna_figures(*, tables_dir: Path, figures_dir: Path) -> dict[str, str]:
    tokens = apply_clinical_journal_style()
    artifacts: dict[str, str] = {}
    coverage = _read_table(tables_dir / "coverage_qc.tsv")
    if not coverage.empty:
        fig, ax = plt.subplots(figsize=(6.2, 4.0))
        ax.hist(pd.to_numeric(coverage["mean_depth"], errors="coerce").fillna(0.0), bins=min(20, max(5, coverage.shape[0])), color="#4EA4F5", edgecolor="white")
        ax.set_xlabel("Mean nuclear depth")
        ax.set_ylabel("Cells / samples")
        ax.set_title("scDNA coverage distribution")
        path = figures_dir / "coverage_distribution.png"
        save_figure(path, style=tokens)
        plt.close(fig)
        artifacts["coverage_distribution"] = str(path)
    vaf = _read_table(tables_dir / "cell_vaf_matrix.tsv")
    if not vaf.empty:
        fig, ax = plt.subplots(figsize=(7.0, 4.6))
        numeric = pd.to_numeric(vaf["vaf"], errors="coerce") if "vaf" in vaf.columns else pd.Series(dtype=float)
        if numeric.notna().any():
            vaf = vaf.copy()
            vaf["vaf"] = numeric.fillna(0.0)
            wide = vaf.pivot_table(index="cell_id", columns="variant_id", values="vaf", aggfunc="max", fill_value=0.0)
            sns.heatmap(wide.iloc[:80, :80], cmap=continuous_cmap(), vmin=0, vmax=1, ax=ax, cbar_kws={"label": "VAF"})
            ax.set_xlabel("Variant")
            ax.set_ylabel("Cell")
            ax.set_title("scDNA VAF matrix")
        else:
            ax.text(0.5, 0.5, "VAF matrix not available\nhandoff table generated", ha="center", va="center")
            ax.set_axis_off()
        path = figures_dir / "vaf_heatmap.png"
        save_figure(path, style=tokens)
        plt.close(fig)
        artifacts["vaf_heatmap"] = str(path)
    clones = _read_table(tables_dir / "clone_summary.tsv")
    if not clones.empty:
        fig, ax = plt.subplots(figsize=(6.0, 3.8))
        ax.bar(clones["clone_id"].astype(str), pd.to_numeric(clones["cell_count"], errors="coerce").fillna(0.0), color="#31B7C5")
        ax.set_ylabel("Cell count")
        ax.set_title("Clone-ready summary")
        ax.tick_params(axis="x", rotation=30)
        path = figures_dir / "clone_summary.png"
        save_figure(path, style=tokens)
        plt.close(fig)
        artifacts["clone_summary"] = str(path)
    return artifacts


def _write_scdna_object(*, objects_dir: Path, data: dict[str, Any], input_ref: str) -> dict[str, str]:
    path = objects_dir / "scdna_mvp_object.rds"
    payload = {
        "object_type": "scdna_matrix_ready_mvp",
        "input_ref": input_ref,
        "n_cells": int(data["coverage_qc"]["cell_id"].nunique()) if not data["coverage_qc"].empty else 0,
        "n_variant_rows": int(data["variant_qc"].shape[0]),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"mvp_object": str(path)}


def _write_skip_outputs(*, tables_dir: Path, figures_dir: Path, objects_dir: Path, analysis_fields: dict[str, Any]) -> dict[str, dict[str, str]]:
    table_specs = {
        "coverage_qc": ["module", "cell_id", "mean_depth", "covered_loci", "dropout_warning", "delivery_allowed"],
        "variant_qc": ["module", "variant_id", "chrom", "pos", "ref", "alt", "depth", "vaf", "filter_status"],
        "cell_variant_matrix": ["module", "cell_id", "variant_id", "genotype_call", "alt_count", "ref_count", "assay_limitation"],
        "cell_vaf_matrix": ["module", "cell_id", "variant_id", "chrom", "pos", "ref", "alt", "vaf", "depth", "assay_limitation"],
        "cell_cnv_matrix": ["module", "cell_id", "chrom", "start", "end", "copy_number_state", "confidence"],
        "clone_summary": ["module", "clone_id", "cell_count", "marker_variants", "clone_call_status", "interpretation_warning"],
        "mutation_cooccurrence": ["module", "variant_id_a", "variant_id_b", "cooccurrence_count", "cooccurrence_status"],
        "phylogeny_input": ["module", "cell_id", "variant_id", "binary_state", "phylogeny_handoff_status"],
    }
    tables: dict[str, str] = {}
    for key, columns in table_specs.items():
        path = tables_dir / f"{key}.tsv"
        pd.DataFrame(columns=columns).to_csv(path, sep="\t", index=False)
        tables[key] = str(path)
    object_path = objects_dir / "scdna_mvp_object.rds"
    object_path.write_text(json.dumps({"status": "skipped", **analysis_fields}, indent=2), encoding="utf-8")
    fig, ax = plt.subplots(figsize=(5.0, 3.2))
    ax.text(0.5, 0.5, "scDNA backend skipped", ha="center", va="center")
    ax.set_axis_off()
    fig_path = figures_dir / "coverage_distribution.png"
    save_figure(fig_path, style=apply_clinical_journal_style())
    plt.close(fig)
    return {"tables": tables, "figures": {"coverage_distribution": str(fig_path)}, "objects": {"mvp_object": str(object_path)}, "reports": {}}


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
