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
import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from validation_manifest_utils import add_validation_guard_fields

from ultimate.config import dump_yaml
from ultimate.pipeline import finalize_run_outputs, run_pipeline_from_config


DEFAULT_MATRIX_URL = "https://raw.githubusercontent.com/bioconnector/workshops/master/data/airway_rawcounts.csv"
DEFAULT_METADATA_URL = "https://raw.githubusercontent.com/bioconnector/workshops/master/data/airway_metadata.csv"


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate bulk RNA-seq MVP on the public airway count matrix.")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--public-data-dir", type=Path, default=Path("/shared/shen/2026/ultimate/public_data/rnaseq_airway"))
    parser.add_argument("--input-matrix", type=Path, default=None)
    parser.add_argument("--samplesheet", type=Path, default=None)
    parser.add_argument("--matrix-url", default=DEFAULT_MATRIX_URL)
    parser.add_argument("--metadata-url", default=DEFAULT_METADATA_URL)
    parser.add_argument("--max-features", type=int, default=12000)
    args = parser.parse_args()
    manifest = run_validation(
        output_dir=args.output_dir,
        public_data_dir=args.public_data_dir,
        input_matrix=args.input_matrix,
        samplesheet=args.samplesheet,
        matrix_url=args.matrix_url,
        metadata_url=args.metadata_url,
        max_features=args.max_features,
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


def run_validation(
    *,
    output_dir: Path,
    public_data_dir: Path,
    input_matrix: Path | None,
    samplesheet: Path | None,
    matrix_url: str,
    metadata_url: str,
    max_features: int,
) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    public_data_dir = public_data_dir.resolve()
    for directory in (output_dir, public_data_dir, output_dir / "logs"):
        directory.mkdir(parents=True, exist_ok=True)

    prepared = _prepare_airway_inputs(
        public_data_dir=public_data_dir,
        input_matrix=input_matrix,
        samplesheet=samplesheet,
        matrix_url=matrix_url,
        metadata_url=metadata_url,
        max_features=max_features,
    )
    config_path = _write_project_config(output_dir=output_dir, prepared=prepared)
    run_manifest = run_pipeline_from_config(config_path)
    manifest_path = output_dir / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    module = _single_module_manifest(manifest, "rnaseq")
    artifacts = module.get("artifacts") if isinstance(module.get("artifacts"), dict) else {}

    manifest.update(
        {
            "module": "rnaseq",
            "dataset": "airway",
            "dataset_label": "Bioconductor airway public bulk RNA-seq count matrix",
            "input_path": str(prepared["matrix_tsv"]),
            "input_matrix": str(prepared["matrix_tsv"]),
            "samplesheet": str(prepared["samplesheet"]),
            "source_urls": {
                "count_matrix": matrix_url,
                "metadata": metadata_url,
            },
            "n_samples": int(prepared["n_samples"]),
            "n_features": int(prepared["n_features"]),
            "figures": _artifact_values(artifacts, "figures"),
            "tables": _artifact_values(artifacts, "tables"),
            "objects": _artifact_dict(artifacts, "objects"),
        }
    )
    add_validation_guard_fields(
        manifest,
        validation_kind="public",
        validation_scope="bulk RNA-seq public airway count-matrix validation",
    )
    manifest["slurm_job_id"] = manifest.get("slurm_job_id") or os.environ.get("SLURM_JOB_ID", "")
    manifest["slurm_job_name"] = manifest.get("slurm_job_name") or os.environ.get("SLURM_JOB_NAME", "")
    manifest["validation_note"] = (
        "Public airway count matrix validation for Ultimate rnaseq MVP. "
        "This is validation evidence only and is not customer delivery."
    )
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    return finalize_run_outputs(output_dir, manifest_path, manifest)


def _prepare_airway_inputs(
    *,
    public_data_dir: Path,
    input_matrix: Path | None,
    samplesheet: Path | None,
    matrix_url: str,
    metadata_url: str,
    max_features: int,
) -> dict[str, Any]:
    raw_matrix_csv = public_data_dir / "airway_rawcounts.csv"
    metadata_csv = public_data_dir / "airway_metadata.csv"
    matrix_tsv = public_data_dir / "airway_rawcounts.tsv"
    samplesheet_tsv = public_data_dir / "airway_samples.tsv"
    raw_samplesheet_tsv = public_data_dir / "airway_raw_samples.tsv"
    dataset_manifest = public_data_dir / "dataset_manifest.tsv"

    if input_matrix is None:
        if raw_matrix_csv.exists() and raw_matrix_csv.stat().st_size > 0:
            matrix = pd.read_csv(raw_matrix_csv)
        else:
            matrix = pd.read_csv(matrix_url)
            raw_matrix_csv.write_text(matrix.to_csv(index=False), encoding="utf-8")
    else:
        matrix = pd.read_csv(input_matrix, sep=None, engine="python")
        raw_matrix_csv.write_text(matrix.to_csv(index=False), encoding="utf-8")
    if samplesheet is None:
        if metadata_csv.exists() and metadata_csv.stat().st_size > 0:
            metadata = pd.read_csv(metadata_csv)
        else:
            metadata = pd.read_csv(metadata_url)
            metadata_csv.write_text(metadata.to_csv(index=False), encoding="utf-8")
    else:
        metadata = pd.read_csv(samplesheet, sep=None, engine="python")
        metadata_csv.write_text(metadata.to_csv(index=False), encoding="utf-8")

    first_col = matrix.columns[0]
    matrix = matrix.rename(columns={first_col: "feature_id"})
    sample_ids = [column for column in matrix.columns if column != "feature_id"]
    matrix[sample_ids] = matrix[sample_ids].apply(pd.to_numeric, errors="coerce").fillna(0).round().astype(int)
    matrix["total_count"] = matrix[sample_ids].sum(axis=1)
    matrix = matrix.sort_values("total_count", ascending=False).drop(columns=["total_count"])
    if max_features > 0:
        matrix = matrix.head(max_features)
    matrix.to_csv(matrix_tsv, sep="\t", index=False)

    id_col = "id" if "id" in metadata.columns else metadata.columns[0]
    condition_col = "dex" if "dex" in metadata.columns else "condition"
    if condition_col not in metadata.columns:
        raise ValueError("Airway metadata must contain a dex or condition column.")
    sample_meta = pd.DataFrame(
        {
            "sample_id": metadata[id_col].astype(str),
            "condition": metadata[condition_col].astype(str),
            "batch": metadata["celltype"].astype(str) if "celltype" in metadata.columns else "batch1",
            "geo_id": metadata["geo_id"].astype(str) if "geo_id" in metadata.columns else "",
        }
    )
    sample_meta.to_csv(samplesheet_tsv, sep="\t", index=False)
    raw_meta = sample_meta.copy()
    raw_meta["raw_input_type"] = "count_matrix"
    raw_meta["fastq_1"] = str(matrix_tsv)
    raw_meta["input_path"] = str(matrix_tsv)
    raw_meta.to_csv(raw_samplesheet_tsv, sep="\t", index=False)

    pd.DataFrame(
        [
            {"field": "dataset", "value": "airway"},
            {"field": "matrix_url", "value": matrix_url},
            {"field": "metadata_url", "value": metadata_url},
            {"field": "matrix_tsv", "value": str(matrix_tsv)},
            {"field": "samplesheet", "value": str(samplesheet_tsv)},
            {"field": "n_samples", "value": len(sample_ids)},
            {"field": "n_features_used", "value": matrix.shape[0]},
        ]
    ).to_csv(dataset_manifest, sep="\t", index=False)

    return {
        "matrix_tsv": matrix_tsv,
        "samplesheet": samplesheet_tsv,
        "raw_samplesheet": raw_samplesheet_tsv,
        "dataset_manifest": dataset_manifest,
        "n_samples": len(sample_ids),
        "n_features": matrix.shape[0],
    }


def _write_project_config(*, output_dir: Path, prepared: dict[str, Any]) -> Path:
    project_dir = output_dir / "project"
    config_dir = project_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    request_path = config_dir / "analysis_request.yaml"
    request = {
        "request_id": "slurm_rnaseq_airway_public",
        "project_type": "rnaseq",
        "enabled_modules": ["rnaseq"],
        "analysis_presets": ["validated_backend_public_matrix"],
        "comparisons": ["treated_vs_control"],
        "special_notes": "Public airway count matrix validation evidence; not customer delivery.",
    }
    dump_yaml(request, request_path)
    rscript_path = Path(
        os.environ.get(
            "ULTIMATE_RNASEQ_RSCRIPT",
            str(Path(__file__).resolve().parents[1] / ".conda" / "envs" / "ultimate-rnaseq" / "bin" / "Rscript"),
        )
    )
    config = {
        "project": {
            "name": "slurm_rnaseq_airway_public",
            "organism": "human",
            "output_dir": str(output_dir),
            "server_root": "/shared/shen/2026/ultimate",
            "run_mode": "validation",
            "job_id": "slurm_rnaseq_airway_public",
            "is_demo": False,
        },
        "analysis_request": str(request_path),
        "samples": {"samplesheet": str(prepared["samplesheet"])},
        "design": {
            "condition_column": "condition",
            "control": "control",
            "case": "treated",
            "batch_column": "batch",
            "comparisons": ["treated_vs_control"],
        },
        "resources": {"human": {"genome": "GRCh38", "orgdb": "org.Hs.eg.db"}},
        "modules": {
            "rnaseq": {
                "enabled": True,
                "analysis_level": "validated_backend",
                "is_demo": False,
                "input_matrix": str(prepared["matrix_tsv"]),
                "samplesheet": str(prepared["samplesheet"]),
                "preset": "publication",
                "backends": {"de": "deseq2_edger"},
                "de_backend": {
                    "enabled": True,
                    "rscript": str(rscript_path),
                    "script": str(Path(__file__).resolve().parents[1] / "scripts" / "R" / "rnaseq_de_backend.R"),
                },
                "raw": {
                    "enabled": True,
                    "input_type": "count_matrix",
                    "samplesheet": str(prepared["raw_samplesheet"]),
                    "matrix_path": str(prepared["matrix_tsv"]),
                    "output_matrix": str(output_dir / "raw_qc" / "rnaseq" / "objects" / "rnaseq_standard_matrix.tsv"),
                    "output_object": str(output_dir / "raw_qc" / "rnaseq" / "objects" / "rnaseq_standard_object.json"),
                    "qc": {"enabled": True},
                    "toolchain": ["nf-core/rnaseq handoff", "featureCounts count matrix import"],
                },
            }
        },
        "report": {
            "title": "Ultimate bulk RNA-seq 公开验证报告",
            "language": "zh-CN",
            "style": "soft_color",
            "layout": "clinical_report",
            "figure_format": "png",
            "dpi": 180,
            "notes": "Public airway count matrix validation evidence; not customer delivery.",
        },
    }
    config_path = config_dir / "project.yaml"
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return config_path


def _single_module_manifest(manifest: dict[str, Any], module_name: str) -> dict[str, Any]:
    for module in manifest.get("modules", []):
        if isinstance(module, dict) and module.get("module") == module_name:
            return module
    raise RuntimeError(f"Run manifest did not contain module {module_name!r}")


def _artifact_values(artifacts: dict[str, Any], key: str) -> list[str]:
    values = artifacts.get(key)
    if isinstance(values, dict):
        return [str(value) for value in values.values()]
    if isinstance(values, list):
        return [str(value) for value in values]
    return []


def _artifact_dict(artifacts: dict[str, Any], key: str) -> dict[str, str]:
    values = artifacts.get(key)
    if isinstance(values, dict):
        return {str(name): str(value) for name, value in values.items()}
    return {}


if __name__ == "__main__":
    main()
