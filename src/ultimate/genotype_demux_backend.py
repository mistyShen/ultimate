from __future__ import annotations

import gzip
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


GENOTYPE_DEMUX_BACKEND_ID = "genotype_demux.default.result_import_mvp"
GENOTYPE_WARNING = "SNP 覆盖不足时不能强行 assignment；reference VCF 错配必须警示。"


def has_genotype_demux_backend_config(config: dict[str, Any]) -> bool:
    module_cfg = _module_cfg(config)
    raw_cfg = module_cfg.get("raw") if isinstance(module_cfg.get("raw"), dict) else {}
    keys = {
        "input_dir",
        "cellsnp_output",
        "vireo_output",
        "souporcell_output",
        "assignment_table",
        "input_path",
    }
    return any(module_cfg.get(key) for key in keys) or any(raw_cfg.get(key) for key in keys)


def run_genotype_demux_backend(*, config: dict[str, Any], output_dir: Path, samples: pd.DataFrame) -> dict[str, Any]:
    module_name = "genotype_demux"
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
    status = "partial:genotype_demux_inputs_missing" if missing_inputs else "complete_genotype_demux_import_backend"
    try:
        level = classify_analysis_level(
            requested_level=module_cfg.get("analysis_level"),
            input_path=input_ref,
            is_demo=_module_is_demo(config, module_cfg),
            is_stub=is_stub,
            public_dataset=bool(module_cfg.get("public_dataset") or module_cfg.get("validation_dataset")) and not is_stub,
        )
        level_fields = level.to_manifest_fields()
    except ValueError as exc:
        status = "partial:genotype_demux_analysis_level_invalid"
        skip_reasons.append(f"analysis_level_invalid:{exc}")
        level_fields = classify_analysis_level(requested_level="smoke_backend", is_stub=True).to_manifest_fields()

    artifacts: dict[str, dict[str, str]] = {"tables": {}, "figures": {}, "objects": {}, "reports": {}}
    warnings = [GENOTYPE_WARNING]
    n_cells = 0
    n_snps = 0
    n_samples = 0
    if skip_reasons:
        artifacts.update(_write_skip_outputs(tables_dir=tables_dir, figures_dir=figures_dir, objects_dir=objects_dir, analysis_fields=level_fields))
    else:
        try:
            data = _read_input(input_ref)
        except Exception as exc:
            status = "partial:genotype_demux_input_read_failed"
            skip_reasons.append(f"input_read_failed:{type(exc).__name__}:{exc}")
            level_fields = classify_analysis_level(requested_level="smoke_backend", is_stub=True).to_manifest_fields()
            artifacts.update(_write_skip_outputs(tables_dir=tables_dir, figures_dir=figures_dir, objects_dir=objects_dir, analysis_fields=level_fields))
        else:
            artifacts["tables"].update(
                _write_genotype_tables(
                    tables_dir=tables_dir,
                    data=data,
                    input_ref=str(input_ref or ""),
                    source_dataset=_source_dataset(config),
                    analysis_fields=level_fields,
                )
            )
            artifacts["figures"].update(_write_genotype_figures(tables_dir=tables_dir, figures_dir=figures_dir))
            artifacts["objects"].update(_write_genotype_object(objects_dir=objects_dir, data=data, input_ref=str(input_ref or "")))
            n_cells = int(data["n_cells"])
            n_snps = int(data["n_snps"])
            n_samples = int(data["assignments"]["assigned_genotype"].nunique())

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
        "n_features": n_snps,
        "n_samples": n_samples,
        "artifacts": artifacts,
        "warnings": warnings,
        "limitations": list(known_limitations(module_name)),
        "handoff": handoff_plan(module_name),
        "reproducible_command": f"ultimate run --config {config.get('_config_path', '<config.yaml>')}",
        "backend": {
            "primary": "genotype_demux_cellsnp_result_import",
            "selected_backend_id": backend_plan["selected_backend_id"],
            "selected_backend_status": backend_plan["selected_backend_status"],
            "backend_role": backend_plan["selected_backend_role"],
            "resource_profile": backend_plan["backend_resource_profile"],
            "interpretation_warning": GENOTYPE_WARNING,
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
            "python_entrypoint": "ultimate.genotype_demux_backend.run_genotype_demux_backend",
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
    return ((config.get("modules") or {}).get("genotype_demux") or {}) if isinstance(config.get("modules"), dict) else {}


def _module_is_demo(config: dict[str, Any], module_cfg: dict[str, Any]) -> bool | None:
    if "is_demo" in module_cfg:
        return bool(module_cfg.get("is_demo"))
    project = config.get("project") or {}
    if "is_demo" in project:
        return bool(project.get("is_demo"))
    return None


def _source_dataset(config: dict[str, Any]) -> str:
    project = config.get("project") or {}
    return str(project.get("name") or project.get("job_id") or "genotype_demux")


def _primary_input_ref(config: dict[str, Any]) -> Path | None:
    module_cfg = _module_cfg(config)
    raw_cfg = module_cfg.get("raw") if isinstance(module_cfg.get("raw"), dict) else {}
    base = Path(str(config.get("_config_path") or ".")).resolve().parent
    value = (
        module_cfg.get("input_dir")
        or module_cfg.get("cellsnp_output")
        or module_cfg.get("vireo_output")
        or module_cfg.get("souporcell_output")
        or module_cfg.get("assignment_table")
        or module_cfg.get("input_path")
        or raw_cfg.get("input_dir")
        or raw_cfg.get("cellsnp_output")
        or raw_cfg.get("assignment_table")
        or raw_cfg.get("input_path")
    )
    return _resolve_path(base, value) if value else None


def _missing_input_reasons(config: dict[str, Any]) -> list[str]:
    input_ref = _primary_input_ref(config)
    if input_ref is None:
        return ["missing_genotype_demux_input"]
    if not input_ref.exists():
        return [f"missing_input_path:{input_ref}"]
    if input_ref.is_dir():
        required = ("cellSNP.tag.AD.mtx", "cellSNP.tag.DP.mtx", "cellSNP.base.vcf.gz", "cellSNP.samples.tsv")
        missing = [name for name in required if not (input_ref / name).exists()]
        if missing:
            return [f"missing_cellsnp_files:{','.join(missing)}"]
        return []
    if input_ref.suffix.lower() not in {".tsv", ".txt", ".csv"}:
        return [f"unsupported_input_extension:{input_ref.suffix or 'none'}"]
    return []


def _resolve_path(base: Path, value: Any) -> Path:
    candidate = Path(str(value))
    return candidate if candidate.is_absolute() else (base / candidate).resolve()


def _read_input(input_ref: Path | None) -> dict[str, Any]:
    if input_ref is None:
        raise ValueError("input_ref_missing")
    if input_ref.is_dir():
        return _read_cellsnp_dir(input_ref)
    return _read_assignment_table(input_ref)


def _read_cellsnp_dir(input_dir: Path) -> dict[str, Any]:
    ad_path = input_dir / "cellSNP.tag.AD.mtx"
    dp_path = input_dir / "cellSNP.tag.DP.mtx"
    vcf_path = input_dir / "cellSNP.base.vcf.gz"
    samples_path = input_dir / "cellSNP.samples.tsv"
    ad = _summarize_mtx(ad_path)
    dp = _summarize_mtx(dp_path)
    if ad["shape"] != dp["shape"]:
        raise ValueError(f"AD/DP matrix shape mismatch: {ad['shape']} vs {dp['shape']}")
    n_snps, n_cells = ad["shape"]
    cells = _read_samples(samples_path, n_cells)
    variants = _read_vcf_variants(vcf_path, n_snps)
    cell_dp = dp["col_sums"]
    cell_ad = ad["col_sums"]
    alt_fraction = np.divide(cell_ad, np.maximum(cell_dp, 1), out=np.zeros_like(cell_ad, dtype=float), where=cell_dp > 0)
    assigned = _assignment_ready_bins(alt_fraction, cell_dp)
    confidence = np.where(cell_dp > 0, np.minimum(1.0, cell_dp / max(float(np.nanpercentile(cell_dp[cell_dp > 0], 95)), 1.0)), 0.0)
    assignments = pd.DataFrame(
        {
            "cell_id": cells,
            "assigned_genotype": assigned,
            "doublet_status": "not_modelled_result_import",
            "assignment_probability": confidence,
            "snp_count": int(n_snps),
            "reference_vcf_status": "provided_cellSNP_base_vcf",
            "total_depth": cell_dp.astype(int),
            "alt_count": cell_ad.astype(int),
            "alt_fraction": alt_fraction,
        }
    )
    snp_qc = variants.copy()
    snp_qc["covered_cell_count"] = dp["row_nnz"].astype(int)
    snp_qc["reference_vcf_status"] = "provided_cellSNP_base_vcf"
    snp_qc["dp_sum"] = dp["row_sums"].astype(int)
    snp_qc["ad_sum"] = ad["row_sums"].astype(int)
    return {
        "input_mode": "cellsnp_matrix_dir",
        "n_cells": int(n_cells),
        "n_snps": int(n_snps),
        "assignments": assignments,
        "snp_qc": snp_qc,
        "matrix_qc": pd.DataFrame(
            [
                {"matrix": "AD", "path": str(ad_path), "n_snps": n_snps, "n_cells": n_cells, "nnz": ad["nnz"], "total_counts": int(ad["row_sums"].sum())},
                {"matrix": "DP", "path": str(dp_path), "n_snps": n_snps, "n_cells": n_cells, "nnz": dp["nnz"], "total_counts": int(dp["row_sums"].sum())},
            ]
        ),
    }


def _read_assignment_table(path: Path) -> dict[str, Any]:
    sep = "\t" if path.suffix.lower() in {".tsv", ".txt"} else ","
    frame = pd.read_csv(path, sep=sep)
    if frame.empty:
        raise ValueError(f"Genotype demux assignment table is empty: {path}")
    rename = {}
    if "cell_id" not in frame.columns:
        rename[frame.columns[0]] = "cell_id"
    if "assigned_genotype" not in frame.columns:
        for candidate in ("assignment", "donor_id", "sample_id", "genotype"):
            if candidate in frame.columns:
                rename[candidate] = "assigned_genotype"
                break
    assignments = frame.rename(columns=rename).copy()
    if "assigned_genotype" not in assignments.columns:
        raise ValueError("assignment table must contain assigned_genotype or assignment/donor_id/sample_id column")
    assignments["doublet_status"] = _series_or_default(assignments, "doublet_status", "not_modelled_result_import")
    assignments["assignment_probability"] = pd.to_numeric(_series_or_default(assignments, "assignment_probability", 1.0), errors="coerce").fillna(0.0)
    assignments["snp_count"] = pd.to_numeric(_series_or_default(assignments, "snp_count", 0), errors="coerce").fillna(0).astype(int)
    assignments["reference_vcf_status"] = _series_or_default(assignments, "reference_vcf_status", "not_provided_existing_result")
    assignments["total_depth"] = pd.to_numeric(_series_or_default(assignments, "total_depth", 0), errors="coerce").fillna(0).astype(int)
    assignments["alt_fraction"] = pd.to_numeric(_series_or_default(assignments, "alt_fraction", 0), errors="coerce").fillna(0.0)
    snp_count = int(assignments["snp_count"].max()) if assignments["snp_count"].max() > 0 else 0
    snp_qc = pd.DataFrame(
        [
            {
                "variant_id": "existing_result_import",
                "chrom": "",
                "pos": 0,
                "covered_cell_count": int(assignments.shape[0]),
                "reference_vcf_status": "not_provided_existing_result",
            }
        ]
    )
    return {
        "input_mode": "assignment_table",
        "n_cells": int(assignments.shape[0]),
        "n_snps": snp_count,
        "assignments": assignments,
        "snp_qc": snp_qc,
        "matrix_qc": pd.DataFrame([{"matrix": "assignment_table", "path": str(path), "n_snps": snp_count, "n_cells": int(assignments.shape[0]), "nnz": 0, "total_counts": int(assignments["total_depth"].sum())}]),
    }


def _series_or_default(frame: pd.DataFrame, column: str, value: Any) -> pd.Series:
    if column in frame.columns:
        return frame[column]
    return pd.Series([value] * frame.shape[0], index=frame.index)


def _write_genotype_tables(*, tables_dir: Path, data: dict[str, Any], input_ref: str, source_dataset: str, analysis_fields: dict[str, Any]) -> dict[str, str]:
    base = _base_fields(analysis_fields, input_ref, source_dataset)
    paths: dict[str, str] = {}
    assignments = data["assignments"].copy()
    assignments.insert(0, "module", "genotype_demux")
    paths["assignment"] = _write_tsv(assignments[["module", "cell_id", "assigned_genotype", "doublet_status", "assignment_probability", "snp_count", "reference_vcf_status"]], tables_dir / "assignment.tsv")

    snp_qc = data["snp_qc"].copy()
    snp_qc.insert(0, "module", "genotype_demux")
    for column in ("variant_id", "chrom", "pos", "covered_cell_count", "reference_vcf_status"):
        if column not in snp_qc.columns:
            snp_qc[column] = ""
    paths["snp_qc"] = _write_tsv(snp_qc[["module", "variant_id", "chrom", "pos", "covered_cell_count", "reference_vcf_status"]], tables_dir / "snp_qc.tsv")

    summary = (
        assignments.groupby("assigned_genotype", observed=False)
        .agg(cell_count=("cell_id", "size"), mean_probability=("assignment_probability", "mean"))
        .reset_index()
    )
    total = max(int(summary["cell_count"].sum()), 1)
    summary["composition_fraction"] = summary["cell_count"] / total
    summary["assignment_status"] = "assignment_ready_result_import"
    summary.insert(0, "module", "genotype_demux")
    paths["sample_composition"] = _write_tsv(summary[["module", "assigned_genotype", "cell_count", "composition_fraction", "assignment_status"]], tables_dir / "sample_composition.tsv")

    doublet = (
        assignments.groupby("assigned_genotype", observed=False)
        .agg(doublet_count=("doublet_status", lambda s: int(s.astype(str).str.contains("doublet", case=False, regex=True).sum())), total=("cell_id", "size"))
        .reset_index()
    )
    doublet["doublet_rate"] = doublet["doublet_count"] / doublet["total"].clip(lower=1)
    doublet["method_status"] = "not_modelled_result_import"
    doublet.insert(0, "module", "genotype_demux")
    paths["doublet_summary"] = _write_tsv(doublet[["module", "assigned_genotype", "doublet_count", "doublet_rate", "method_status"]], tables_dir / "doublet_summary.tsv")

    confidence = assignments[["cell_id", "assigned_genotype", "assignment_probability"]].copy()
    confidence["confidence_class"] = np.where(confidence["assignment_probability"] >= 0.8, "high", np.where(confidence["assignment_probability"] >= 0.4, "medium", "low"))
    confidence.insert(0, "module", "genotype_demux")
    paths["assignment_confidence"] = _write_tsv(confidence, tables_dir / "assignment_confidence.tsv")

    metadata = assignments[["cell_id", "assigned_genotype", "doublet_status", "assignment_probability"]].copy()
    metadata["metadata_handoff_status"] = "ready_for_scrna_metadata_join"
    metadata.insert(0, "module", "genotype_demux")
    paths["cell_metadata_with_genotype"] = _write_tsv(metadata, tables_dir / "cell_metadata_with_genotype.tsv")
    paths["cellsnp_matrix_qc"] = _write_tsv(data["matrix_qc"], tables_dir / "cellsnp_matrix_qc.tsv")
    paths["input_read_summary"] = _write_tsv(pd.DataFrame([{**base, "input_mode": data["input_mode"], "n_cells": data["n_cells"], "n_snps": data["n_snps"]}]), tables_dir / "input_read_summary.tsv")
    return paths


def _write_genotype_figures(*, tables_dir: Path, figures_dir: Path) -> dict[str, str]:
    tokens = apply_clinical_journal_style()
    paths: dict[str, str] = {}
    assignment = pd.read_csv(tables_dir / "assignment.tsv", sep="\t")
    composition = pd.read_csv(tables_dir / "sample_composition.tsv", sep="\t")
    confidence = pd.read_csv(tables_dir / "assignment_confidence.tsv", sep="\t")

    bar_path = figures_dir / "sample_assignment_barplot.png"
    plt.figure(figsize=(7, 4.2))
    order = composition.sort_values("cell_count", ascending=False)
    plt.bar(order["assigned_genotype"].astype(str), order["cell_count"], color=tokens["primary"])
    plt.xticks(rotation=25, ha="right")
    plt.ylabel("Cells")
    plt.title("Genotype assignment summary")
    plt.tight_layout()
    save_figure(bar_path, style=tokens)
    paths["sample_assignment_barplot"] = str(bar_path)

    conf_path = figures_dir / "confidence_distribution.png"
    plt.figure(figsize=(6.2, 4))
    plt.hist(confidence["assignment_probability"], bins=30, color="#6D83B6", edgecolor="white", linewidth=0.3)
    plt.xlabel("Assignment probability / confidence proxy")
    plt.ylabel("Cells")
    plt.title("Assignment confidence")
    plt.tight_layout()
    save_figure(conf_path, style=tokens)
    paths["confidence_distribution"] = str(conf_path)

    box_path = figures_dir / "alt_fraction_by_assignment.png"
    if "alt_fraction" in assignment.columns:
        plt.figure(figsize=(6.5, 4.2))
        labels = sorted(assignment["assigned_genotype"].astype(str).unique())
        values = [assignment.loc[assignment["assigned_genotype"].astype(str).eq(label), "alt_fraction"] for label in labels]
        plt.boxplot(values, tick_labels=labels)
        plt.xticks(rotation=25, ha="right")
        plt.ylabel("Alt allele fraction")
        plt.tight_layout()
        save_figure(box_path, style=tokens)
        paths["alt_fraction_by_assignment"] = str(box_path)
    return paths


def _write_genotype_object(*, objects_dir: Path, data: dict[str, Any], input_ref: str) -> dict[str, str]:
    path = objects_dir / "genotype_demux_mvp_object.rds"
    payload = {
        "object_type": "json_serialized_genotype_demux_mvp",
        "input_ref": input_ref,
        "input_mode": data["input_mode"],
        "n_cells": int(data["n_cells"]),
        "n_snps": int(data["n_snps"]),
        "assignment_counts": data["assignments"]["assigned_genotype"].value_counts().to_dict(),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"mvp_object": str(path)}


def _write_skip_outputs(*, tables_dir: Path, figures_dir: Path, objects_dir: Path, analysis_fields: dict[str, Any]) -> dict[str, dict[str, str]]:
    base = {
        "module": "genotype_demux",
        "analysis_level": analysis_fields.get("analysis_level"),
        "delivery_allowed": analysis_fields.get("delivery_allowed"),
        "skip_status": "skipped_no_valid_genotype_input",
    }
    artifacts = {"tables": {}, "figures": {}, "objects": {}, "reports": {}}
    for name in ("snp_qc", "assignment", "doublet_summary", "sample_composition", "assignment_confidence", "cell_metadata_with_genotype"):
        artifacts["tables"][name] = _write_tsv(pd.DataFrame([base]), tables_dir / f"{name}.tsv")
    for figure_name in ("sample_assignment_barplot", "confidence_distribution"):
        path = figures_dir / f"{figure_name}.png"
        plt.figure(figsize=(5, 3))
        plt.text(0.5, 0.5, "Genotype demux input missing", ha="center", va="center")
        plt.axis("off")
        save_figure(path, style=apply_clinical_journal_style())
        artifacts["figures"][figure_name] = str(path)
    object_path = objects_dir / "genotype_demux_mvp_object.rds"
    object_path.write_text(json.dumps(base, indent=2, ensure_ascii=False), encoding="utf-8")
    artifacts["objects"]["mvp_object"] = str(object_path)
    return artifacts


def _base_fields(analysis_fields: dict[str, Any], input_artifact: str, source_dataset: str) -> dict[str, Any]:
    return {
        "module": "genotype_demux",
        "run_id": source_dataset,
        "sample_id": "all",
        "source_dataset": source_dataset,
        "input_artifact": input_artifact,
        "input_modality": "cellsnp_or_assignment_result",
        "analysis_level": analysis_fields.get("analysis_level"),
        "result_scope": "genotype_demux_result_import_mvp",
        "method_status": "fully_automatic_validated_entrypoint",
        "delivery_allowed": analysis_fields.get("delivery_allowed"),
    }


def _summarize_mtx(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        line = handle.readline()
        if not line.startswith("%%MatrixMarket"):
            raise ValueError(f"Not a MatrixMarket file: {path}")
        for line in handle:
            if not line.startswith("%"):
                n_rows, n_cols, nnz = (int(value) for value in line.split()[:3])
                break
        else:
            raise ValueError(f"Missing MatrixMarket dimension line: {path}")
        row_sums = np.zeros(n_rows, dtype=float)
        col_sums = np.zeros(n_cols, dtype=float)
        row_nnz = np.zeros(n_rows, dtype=int)
        for line in handle:
            if not line.strip():
                continue
            row, col, value = line.split()[:3]
            row_idx = int(row) - 1
            col_idx = int(col) - 1
            count = float(value)
            row_sums[row_idx] += count
            col_sums[col_idx] += count
            row_nnz[row_idx] += 1
    return {"shape": (n_rows, n_cols), "nnz": nnz, "row_sums": row_sums, "col_sums": col_sums, "row_nnz": row_nnz}


def _read_samples(path: Path, expected: int) -> list[str]:
    cells = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(cells) != expected:
        raise ValueError(f"Sample count mismatch: {len(cells)} samples vs {expected} matrix cells")
    return cells


def _read_vcf_variants(path: Path, expected: int) -> pd.DataFrame:
    rows = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("#"):
                continue
            chrom, pos, variant_id, ref, alt, *_ = line.rstrip("\n").split("\t")
            rows.append({"variant_id": variant_id if variant_id != "." else f"{chrom}:{pos}:{ref}>{alt}", "chrom": chrom, "pos": int(pos), "ref": ref, "alt": alt})
    if len(rows) != expected:
        raise ValueError(f"Variant count mismatch: {len(rows)} VCF variants vs {expected} matrix rows")
    return pd.DataFrame(rows)


def _assignment_ready_bins(alt_fraction: np.ndarray, depth: np.ndarray) -> np.ndarray:
    labels = np.array(["low_alt_fraction", "mid_alt_fraction", "high_alt_fraction"], dtype=object)
    bins = np.digitize(alt_fraction, bins=[0.32, 0.65], right=False)
    assignment = labels[bins]
    assignment = assignment.astype(object)
    assignment[depth <= 0] = "unassigned_no_depth"
    return assignment


def _write_tsv(frame: pd.DataFrame, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = _coerce_mvp_table_schema(
        "genotype_demux",
        path.name,
        frame,
        matrix=None,
        samples=None,
        analysis_fields=_analysis_fields_from_frame(frame),
        run_id=_first_frame_value(frame, "run_id"),
        source_dataset=_first_frame_value(frame, "source_dataset"),
        input_artifact=_first_frame_value(frame, "input_artifact"),
        input_modality=_first_frame_value(frame, "input_modality") or "genotype_demux",
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
