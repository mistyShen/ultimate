#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tarfile
import urllib.request
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


DEFAULT_ARRMDATA_URL = "https://bioconductor.org/packages/release/data/experiment/src/contrib/ARRmData_1.48.0.tar.gz"


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate methylation MVP on public ARRmData beta matrix.")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--public-data-dir", type=Path, default=Path("/shared/shen/2026/ultimate/public_data/methylation_arrmdata"))
    parser.add_argument("--arrmdata-url", default=DEFAULT_ARRMDATA_URL)
    parser.add_argument("--max-features", type=int, default=12000)
    args = parser.parse_args()
    manifest = run_validation(
        output_dir=args.output_dir,
        public_data_dir=args.public_data_dir,
        arrmdata_url=args.arrmdata_url,
        max_features=args.max_features,
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


def run_validation(*, output_dir: Path, public_data_dir: Path, arrmdata_url: str, max_features: int) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    public_data_dir = public_data_dir.resolve()
    for directory in (output_dir, public_data_dir, output_dir / "logs"):
        directory.mkdir(parents=True, exist_ok=True)

    prepared = _prepare_arrmdata_inputs(
        public_data_dir=public_data_dir,
        arrmdata_url=arrmdata_url,
        max_features=max_features,
    )
    config_path = _write_project_config(output_dir=output_dir, prepared=prepared)
    run_pipeline_from_config(config_path)
    manifest_path = output_dir / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    module = _single_module_manifest(manifest, "methylation")
    artifacts = module.get("artifacts") if isinstance(module.get("artifacts"), dict) else {}

    manifest.update(
        {
            "module": "methylation",
            "dataset": "ARRmData",
            "dataset_label": "Bioconductor ARRmData public Illumina 450k beta matrix",
            "input_path": str(prepared["beta_matrix"]),
            "input_matrix": str(prepared["beta_matrix"]),
            "samplesheet": str(prepared["samplesheet"]),
            "source_urls": {"arrmdata_tarball": arrmdata_url},
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
        validation_scope="ARRmData public methylation beta-matrix validation",
    )
    manifest["slurm_job_id"] = manifest.get("slurm_job_id") or os.environ.get("SLURM_JOB_ID", "")
    manifest["slurm_job_name"] = manifest.get("slurm_job_name") or os.environ.get("SLURM_JOB_NAME", "")
    manifest["validation_note"] = (
        "Public ARRmData beta matrix validation for Ultimate methylation MVP. "
        "Synthetic validation group labels are derived from sample order for backend testing only; "
        "this is validation evidence, not customer delivery or biological interpretation."
    )
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    return finalize_run_outputs(output_dir, manifest_path, manifest)


def _prepare_arrmdata_inputs(*, public_data_dir: Path, arrmdata_url: str, max_features: int) -> dict[str, Any]:
    tarball = public_data_dir / "ARRmData_1.48.0.tar.gz"
    extract_dir = public_data_dir / "ARRmData_extract"
    beta_matrix = public_data_dir / "arrmdata_beta_matrix.tsv"
    samplesheet = public_data_dir / "arrmdata_samples.tsv"
    raw_samplesheet = public_data_dir / "arrmdata_raw_samples.tsv"
    dataset_manifest = public_data_dir / "dataset_manifest.tsv"

    if not tarball.exists() or tarball.stat().st_size == 0:
        with urllib.request.urlopen(arrmdata_url, timeout=60) as response:
            tarball.write_bytes(response.read())
    rda_path = extract_dir / "ARRmData" / "data" / "betaMatrix.rda"
    if not rda_path.exists():
        extract_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(tarball, "r:gz") as archive:
            archive.extract("ARRmData/data/betaMatrix.rda", path=extract_dir)

    if not beta_matrix.exists() or beta_matrix.stat().st_size == 0:
        _write_beta_matrix_from_rda(rda_path=rda_path, output_tsv=beta_matrix, max_features=max_features)

    matrix = pd.read_csv(beta_matrix, sep="\t")
    sample_ids = [column for column in matrix.columns if column != "feature_id"]
    split = max(1, len(sample_ids) // 2)
    sample_meta = pd.DataFrame(
        {
            "sample_id": sample_ids,
            "condition": ["control" if idx < split else "treated" for idx, _ in enumerate(sample_ids)],
            "batch": [sample.split("_")[0] if "_" in sample else "batch1" for sample in sample_ids],
            "validation_group_note": "sample-order-derived-for-backend-validation-only",
        }
    )
    sample_meta.to_csv(samplesheet, sep="\t", index=False)
    raw_meta = sample_meta[["sample_id", "condition", "batch"]].copy()
    raw_meta["raw_input_type"] = "beta_matrix"
    raw_meta["input_path"] = str(beta_matrix)
    raw_meta.to_csv(raw_samplesheet, sep="\t", index=False)

    pd.DataFrame(
        [
            {"field": "dataset", "value": "ARRmData"},
            {"field": "arrmdata_url", "value": arrmdata_url},
            {"field": "tarball", "value": str(tarball)},
            {"field": "beta_matrix", "value": str(beta_matrix)},
            {"field": "samplesheet", "value": str(samplesheet)},
            {"field": "n_samples", "value": len(sample_ids)},
            {"field": "n_features_used", "value": matrix.shape[0]},
        ]
    ).to_csv(dataset_manifest, sep="\t", index=False)

    return {
        "beta_matrix": beta_matrix,
        "samplesheet": samplesheet,
        "raw_samplesheet": raw_samplesheet,
        "dataset_manifest": dataset_manifest,
        "n_samples": len(sample_ids),
        "n_features": matrix.shape[0],
    }


def _write_beta_matrix_from_rda(*, rda_path: Path, output_tsv: Path, max_features: int) -> None:
    script = f"""
load({str(rda_path)!r})
mat <- betaMatrix
if ({int(max_features)} > 0 && nrow(mat) > {int(max_features)}) {{
  vars <- apply(mat, 1, var, na.rm=TRUE)
  keep <- order(vars, decreasing=TRUE)[seq_len({int(max_features)})]
  mat <- mat[keep, , drop=FALSE]
}}
out <- data.frame(feature_id=rownames(mat), mat, check.names=FALSE)
write.table(out, file={str(output_tsv)!r}, sep="\\t", quote=FALSE, row.names=FALSE)
"""
    subprocess.run(["Rscript", "-e", script], check=True)


def _write_project_config(*, output_dir: Path, prepared: dict[str, Any]) -> Path:
    project_dir = output_dir / "project"
    config_dir = project_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    request_path = config_dir / "analysis_request.yaml"
    request = {
        "request_id": "slurm_methylation_arrmdata_public",
        "project_type": "methylation",
        "enabled_modules": ["methylation"],
        "analysis_presets": ["validated_backend_public_beta_matrix"],
        "comparisons": ["treated_vs_control"],
        "special_notes": "Public ARRmData beta matrix validation evidence; not customer delivery.",
    }
    dump_yaml(request, request_path)
    config = {
        "project": {
            "name": "slurm_methylation_arrmdata_public",
            "organism": "human",
            "output_dir": str(output_dir),
            "server_root": "/shared/shen/2026/ultimate",
            "run_mode": "validation",
            "job_id": "slurm_methylation_arrmdata_public",
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
            "methylation": {
                "enabled": True,
                "preset": "publication",
                "analysis_level": "validated_backend",
                "is_demo": False,
                "input_matrix": str(prepared["beta_matrix"]),
                "samplesheet": str(prepared["samplesheet"]),
                "raw": {
                    "enabled": True,
                    "input_type": "beta_matrix",
                    "samplesheet": str(prepared["raw_samplesheet"]),
                    "matrix_path": str(prepared["beta_matrix"]),
                    "output_matrix": str(output_dir / "raw_qc" / "methylation" / "objects" / "methylation_standard_matrix.tsv"),
                    "output_object": str(output_dir / "raw_qc" / "methylation" / "objects" / "methylation_standard_object.json"),
                    "qc": {"enabled": True},
                    "toolchain": ["ARRmData beta matrix import", "methylation.dmp.limma_beta publication backend", "minfi/ChAMP handoff"],
                },
            }
        },
        "report": {
            "title": "Ultimate 甲基化公开验证报告",
            "language": "zh-CN",
            "style": "soft_color",
            "layout": "clinical_report",
            "figure_format": "png",
            "dpi": 180,
            "notes": "Public ARRmData beta matrix validation evidence; not customer delivery.",
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
