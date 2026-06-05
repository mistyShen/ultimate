#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import numpy as np
import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from validation_manifest_utils import add_validation_guard_fields

from ultimate.config import dump_yaml
from ultimate.pipeline import finalize_run_outputs, run_pipeline_from_config


DEFAULT_PROTEINGROUPS_URL = "https://raw.githubusercontent.com/MonashBioinformaticsPlatform/LFQ-Analyst/master/data/proteinGroups.txt"
DEFAULT_DESIGN_URL = "https://raw.githubusercontent.com/MonashBioinformaticsPlatform/LFQ-Analyst/master/data/exp_design_p10_0144.txt"


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the proteomics abundance-table MVP on a public MaxQuant proteinGroups table.")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--public-data-dir", type=Path, default=Path("/shared/shen/2026/ultimate/public_data/proteomics_lfq_analyst"))
    parser.add_argument("--protein-groups", type=Path, default=None)
    parser.add_argument("--design-table", type=Path, default=None)
    parser.add_argument("--protein-groups-url", default=DEFAULT_PROTEINGROUPS_URL)
    parser.add_argument("--design-url", default=DEFAULT_DESIGN_URL)
    parser.add_argument("--max-features", type=int, default=5000)
    args = parser.parse_args()
    manifest = run_validation(
        output_dir=args.output_dir,
        public_data_dir=args.public_data_dir,
        protein_groups=args.protein_groups,
        design_table=args.design_table,
        protein_groups_url=args.protein_groups_url,
        design_url=args.design_url,
        max_features=args.max_features,
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


def run_validation(
    *,
    output_dir: Path,
    public_data_dir: Path,
    protein_groups: Path | None,
    design_table: Path | None,
    protein_groups_url: str,
    design_url: str,
    max_features: int,
) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    public_data_dir = public_data_dir.resolve()
    for directory in (output_dir, public_data_dir, output_dir / "logs"):
        directory.mkdir(parents=True, exist_ok=True)

    prepared = _prepare_lfq_inputs(
        public_data_dir=public_data_dir,
        protein_groups=protein_groups,
        design_table=design_table,
        protein_groups_url=protein_groups_url,
        design_url=design_url,
        max_features=max_features,
    )
    config_path = _write_project_config(output_dir=output_dir, prepared=prepared)
    run_pipeline_from_config(config_path)
    manifest_path = output_dir / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    module = _single_module_manifest(manifest, "proteomics")
    artifacts = module.get("artifacts") if isinstance(module.get("artifacts"), dict) else {}

    manifest.update(
        {
            "module": "proteomics",
            "dataset": "lfq_analyst",
            "dataset_label": "LFQ-Analyst public MaxQuant proteinGroups.txt",
            "input_path": str(prepared["abundance_matrix"]),
            "input_matrix": str(prepared["abundance_matrix"]),
            "protein_groups": str(prepared["protein_groups"]),
            "samplesheet": str(prepared["samplesheet"]),
            "source_urls": {
                "protein_groups": protein_groups_url,
                "design": design_url,
            },
            "n_samples": int(prepared["n_samples"]),
            "n_features": int(prepared["n_features"]),
            "figures": _artifact_values(artifacts, "figures"),
            "tables": _artifact_values(artifacts, "tables"),
            "objects": _artifact_dict(artifacts, "objects"),
            "backend_id": module.get("backend_id", "proteomics.default.abundance_python_mvp"),
            "backend_status": module.get("backend_status", "fully_automatic_validated_entrypoint"),
            "backend_slurm_job_id": module.get("backend_slurm_job_id") or os.environ.get("SLURM_JOB_ID", ""),
        }
    )
    add_validation_guard_fields(
        manifest,
        validation_kind="public",
        validation_scope="proteomics public MaxQuant LFQ abundance-table validation",
    )
    manifest["slurm_job_id"] = manifest.get("slurm_job_id") or os.environ.get("SLURM_JOB_ID", "")
    manifest["slurm_job_name"] = manifest.get("slurm_job_name") or os.environ.get("SLURM_JOB_NAME", "")
    manifest["validation_note"] = (
        "Public LFQ-Analyst MaxQuant proteinGroups validation for the Ultimate proteomics abundance-table backend. "
        "This is validation evidence only and is not customer delivery. Differential abundance uses the Python MVP "
        "proxy table; limma remains the publication-grade handoff/backend target."
    )
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return finalize_run_outputs(output_dir, manifest_path, manifest)


def _prepare_lfq_inputs(
    *,
    public_data_dir: Path,
    protein_groups: Path | None,
    design_table: Path | None,
    protein_groups_url: str,
    design_url: str,
    max_features: int,
) -> dict[str, Any]:
    raw_protein_groups = public_data_dir / "proteinGroups.txt"
    raw_design = public_data_dir / "exp_design_p10_0144.txt"
    abundance_matrix = public_data_dir / "lfq_analyst_abundance.tsv"
    samplesheet_tsv = public_data_dir / "lfq_analyst_samples.tsv"
    raw_samplesheet_tsv = public_data_dir / "lfq_analyst_raw_samples.tsv"
    dataset_manifest = public_data_dir / "dataset_manifest.tsv"

    if protein_groups is None:
        if raw_protein_groups.exists() and raw_protein_groups.stat().st_size > 0:
            protein_df = pd.read_csv(raw_protein_groups, sep="\t")
        else:
            protein_df = pd.read_csv(protein_groups_url, sep="\t")
            raw_protein_groups.write_text(protein_df.to_csv(sep="\t", index=False), encoding="utf-8")
    else:
        protein_df = pd.read_csv(protein_groups, sep=None, engine="python")
        raw_protein_groups.write_text(protein_df.to_csv(sep="\t", index=False), encoding="utf-8")

    if design_table is None:
        if raw_design.exists() and raw_design.stat().st_size > 0:
            design = pd.read_csv(raw_design, sep="\t")
        else:
            design = pd.read_csv(design_url, sep="\t")
            raw_design.write_text(design.to_csv(sep="\t", index=False), encoding="utf-8")
    else:
        design = pd.read_csv(design_table, sep=None, engine="python")
        raw_design.write_text(design.to_csv(sep="\t", index=False), encoding="utf-8")

    protein_df = _filter_maxquant_rows(protein_df)
    lfq_columns = [column for column in protein_df.columns if str(column).startswith("LFQ intensity ")]
    if not lfq_columns:
        raise ValueError("proteinGroups table must contain LFQ intensity sample columns.")
    sample_labels = [column.replace("LFQ intensity ", "", 1) for column in lfq_columns]
    design = _standardize_design(design)
    design = design[design["sample_id"].isin(sample_labels)].copy()
    if design.empty:
        design = pd.DataFrame({"sample_id": sample_labels, "condition": ["sample"] * len(sample_labels), "replicate": list(range(1, len(sample_labels) + 1))})
    sample_order = [sample for sample in design["sample_id"].astype(str) if sample in sample_labels]
    selected_columns = [f"LFQ intensity {sample}" for sample in sample_order]

    feature_ids = _feature_ids(protein_df)
    matrix = protein_df.loc[:, selected_columns].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    matrix.columns = sample_order
    matrix.insert(0, "feature_id", feature_ids)
    matrix = matrix.groupby("feature_id", as_index=False).max(numeric_only=True)
    sample_cols = [column for column in matrix.columns if column != "feature_id"]
    matrix["observed_sample_count"] = (matrix[sample_cols] > 0).sum(axis=1)
    matrix["mean_lfq_intensity"] = matrix[sample_cols].replace(0, np.nan).mean(axis=1).fillna(0)
    matrix = matrix.sort_values(["observed_sample_count", "mean_lfq_intensity"], ascending=False).drop(columns=["observed_sample_count", "mean_lfq_intensity"])
    if max_features > 0:
        matrix = matrix.head(max_features)
    matrix.to_csv(abundance_matrix, sep="\t", index=False)

    samplesheet = design.loc[:, ["sample_id", "condition", "replicate"]].copy()
    conditions = list(dict.fromkeys(samplesheet["condition"].astype(str)))
    control = "CD34Low" if "CD34Low" in conditions else conditions[0]
    case = "CD34High" if "CD34High" in conditions else (conditions[1] if len(conditions) > 1 else conditions[0])
    samplesheet["batch"] = "lfq_analyst"
    samplesheet["input_path"] = str(abundance_matrix)
    samplesheet.to_csv(samplesheet_tsv, sep="\t", index=False)
    raw_meta = samplesheet[["sample_id", "condition", "batch", "input_path"]].copy()
    raw_meta["raw_input_type"] = "maxquant_proteinGroups"
    raw_meta["protein_groups"] = str(raw_protein_groups)
    raw_meta.to_csv(raw_samplesheet_tsv, sep="\t", index=False)

    pd.DataFrame(
        [
            {"field": "dataset", "value": "LFQ-Analyst"},
            {"field": "protein_groups_url", "value": protein_groups_url},
            {"field": "design_url", "value": design_url},
            {"field": "protein_groups", "value": str(raw_protein_groups)},
            {"field": "abundance_matrix", "value": str(abundance_matrix)},
            {"field": "samplesheet", "value": str(samplesheet_tsv)},
            {"field": "control", "value": control},
            {"field": "case", "value": case},
            {"field": "n_samples", "value": len(sample_order)},
            {"field": "n_features_used", "value": matrix.shape[0]},
        ]
    ).to_csv(dataset_manifest, sep="\t", index=False)

    return {
        "protein_groups": raw_protein_groups,
        "design": raw_design,
        "abundance_matrix": abundance_matrix,
        "samplesheet": samplesheet_tsv,
        "raw_samplesheet": raw_samplesheet_tsv,
        "dataset_manifest": dataset_manifest,
        "control": control,
        "case": case,
        "n_samples": len(sample_order),
        "n_features": matrix.shape[0],
    }


def _filter_maxquant_rows(frame: pd.DataFrame) -> pd.DataFrame:
    filtered = frame.copy()
    for column in ("Only identified by site", "Reverse", "Potential contaminant"):
        if column in filtered.columns:
            values = filtered[column].astype(str).str.strip()
            filtered = filtered[~values.isin(["+", "True", "true", "1"])]
    return filtered


def _standardize_design(design: pd.DataFrame) -> pd.DataFrame:
    frame = design.copy()
    if "sample_id" not in frame.columns:
        if "label" in frame.columns:
            frame = frame.rename(columns={"label": "sample_id"})
        else:
            frame = frame.rename(columns={frame.columns[0]: "sample_id"})
    if "condition" not in frame.columns:
        frame["condition"] = "sample"
    if "replicate" not in frame.columns:
        frame["replicate"] = list(range(1, len(frame) + 1))
    frame["sample_id"] = frame["sample_id"].astype(str)
    frame["condition"] = frame["condition"].astype(str)
    return frame


def _feature_ids(frame: pd.DataFrame) -> pd.Series:
    for column in ("Gene names", "Protein names", "Majority protein IDs", "Protein IDs"):
        if column in frame.columns:
            values = frame[column].fillna("").astype(str).str.split(";").str[0].str.strip()
            values = values.where(values != "", other=frame.index.astype(str))
            return _make_unique(values)
    return pd.Series([f"PROT_{idx:05d}" for idx in range(1, len(frame) + 1)])


def _make_unique(values: pd.Series) -> pd.Series:
    counts: dict[str, int] = {}
    result = []
    for raw in values.astype(str):
        value = raw or "protein"
        counts[value] = counts.get(value, 0) + 1
        result.append(value if counts[value] == 1 else f"{value}_{counts[value]}")
    return pd.Series(result, index=values.index)


def _write_project_config(*, output_dir: Path, prepared: dict[str, Any]) -> Path:
    project_dir = output_dir / "project"
    config_dir = project_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    request_path = config_dir / "analysis_request.yaml"
    request = {
        "request_id": "slurm_proteomics_lfq_analyst_public",
        "project_type": "proteomics",
        "enabled_modules": ["proteomics"],
        "analysis_presets": ["validated_backend_public_maxquant_lfq"],
        "comparisons": [f"{prepared['case']}_vs_{prepared['control']}"],
        "special_notes": "Public MaxQuant proteinGroups LFQ validation evidence; not customer delivery.",
    }
    dump_yaml(request, request_path)
    config = {
        "project": {
            "name": "slurm_proteomics_lfq_analyst_public",
            "organism": "human",
            "output_dir": str(output_dir),
            "server_root": "/shared/shen/2026/ultimate",
            "run_mode": "validation",
            "job_id": "slurm_proteomics_lfq_analyst_public",
            "is_demo": False,
        },
        "analysis_request": str(request_path),
        "samples": {"samplesheet": str(prepared["samplesheet"])},
        "design": {
            "condition_column": "condition",
            "control": prepared["control"],
            "case": prepared["case"],
            "batch_column": "batch",
            "comparisons": [f"{prepared['case']}_vs_{prepared['control']}"],
        },
        "resources": {"human": {"orgdb": "org.Hs.eg.db"}},
        "modules": {
            "proteomics": {
                "enabled": True,
                "analysis_level": "validated_backend",
                "is_demo": False,
                "input_matrix": str(prepared["abundance_matrix"]),
                "samplesheet": str(prepared["samplesheet"]),
                "raw": {
                    "enabled": True,
                    "input_type": "maxquant_proteinGroups",
                    "samplesheet": str(prepared["raw_samplesheet"]),
                    "matrix_path": str(prepared["abundance_matrix"]),
                    "protein_groups": str(prepared["protein_groups"]),
                    "output_matrix": str(output_dir / "raw_qc" / "proteomics" / "objects" / "proteomics_standard_matrix.tsv"),
                    "output_object": str(output_dir / "raw_qc" / "proteomics" / "objects" / "proteomics_standard_object.json"),
                    "qc": {"enabled": True},
                    "toolchain": ["MaxQuant proteinGroups import", "LFQ abundance matrix", "Python MVP differential abundance"],
                },
            }
        },
        "report": {
            "title": "Ultimate 蛋白组公开验证报告",
            "language": "zh-CN",
            "style": "soft_color",
            "layout": "clinical_report",
            "figure_format": "png",
            "dpi": 180,
            "notes": "Public LFQ-Analyst MaxQuant proteinGroups validation evidence; not customer delivery.",
        },
    }
    config_path = config_dir / "project.yaml"
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return config_path


def _single_module_manifest(manifest: dict[str, Any], module_name: str) -> dict[str, Any]:
    for module in manifest.get("modules", []):
        if isinstance(module, dict) and module.get("module") == module_name:
            return module
    raise RuntimeError(f"{module_name} module manifest not found.")


def _artifact_values(artifacts: dict[str, Any], key: str) -> list[str]:
    values = artifacts.get(key) if isinstance(artifacts, dict) else {}
    if isinstance(values, dict):
        return [str(value) for value in values.values()]
    return []


def _artifact_dict(artifacts: dict[str, Any], key: str) -> dict[str, str]:
    values = artifacts.get(key) if isinstance(artifacts, dict) else {}
    if isinstance(values, dict):
        return {str(name): str(value) for name, value in values.items()}
    return {}


if __name__ == "__main__":
    main()
