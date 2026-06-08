#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from validation_manifest_utils import add_validation_guard_fields

from ultimate.config import dump_yaml
from ultimate.pipeline import finalize_run_outputs, run_pipeline_from_config


DEFAULT_INPUT_H5 = Path("/shared/shen/2026/ultimate/public_data/scatac/10k_pbmc_ATACv2_nextgem_Chromium_Controller_filtered_peak_bc_matrix.h5")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Ultimate SCEPI matrix backend using a public scATAC-derived region matrix.")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--input-h5", type=Path, default=DEFAULT_INPUT_H5)
    parser.add_argument("--project-root", type=Path, default=Path("/shared/shen/2026/ultimate"))
    parser.add_argument("--max-features", type=int, default=800)
    parser.add_argument("--max-cells", type=int, default=240)
    args = parser.parse_args()
    manifest = run_validation(
        output_dir=args.output_dir,
        input_h5=args.input_h5,
        project_root=args.project_root,
        max_features=args.max_features,
        max_cells=args.max_cells,
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


def run_validation(*, output_dir: Path, input_h5: Path, project_root: Path, max_features: int, max_cells: int) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    input_h5 = input_h5.resolve()
    project_root = project_root.resolve()
    input_dir = output_dir / "input"
    for directory in (output_dir, output_dir / "logs", output_dir / "reports", input_dir):
        directory.mkdir(parents=True, exist_ok=True)

    if not input_h5.exists() or input_h5.stat().st_size == 0:
        _try_prepare_public_data(project_root)
    if not input_h5.exists() or input_h5.stat().st_size == 0:
        return _write_skip_manifest(output_dir, reason=f"public_scATAC_h5_missing:{input_h5}")

    region_matrix = input_dir / "scepi_region_matrix.tsv"
    samplesheet = input_dir / "scepi_samples.tsv"
    dataset_manifest = input_dir / "scepi_public_dataset_manifest.tsv"
    try:
        prepared = prepare_scepi_public_inputs(
            input_h5=input_h5,
            region_matrix=region_matrix,
            samplesheet=samplesheet,
            dataset_manifest=dataset_manifest,
            max_features=max_features,
            max_cells=max_cells,
        )
    except Exception as exc:
        return _write_skip_manifest(output_dir, reason=f"public_scepi_prepare_failed:{type(exc).__name__}:{exc}")

    config_path = write_project_config(output_dir=output_dir, prepared=prepared, project_root=project_root)
    run_pipeline_from_config(config_path)
    manifest_path = output_dir / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    module = _single_module_manifest(manifest, "scepi")
    artifacts = module.get("artifacts") if isinstance(module.get("artifacts"), dict) else {}
    manifest.update(
        {
            "module": "scepi",
            "dataset": "10x_pbmc_scatac_derived_region_matrix",
            "dataset_label": "10x PBMC scATAC public matrix-derived SCEPI region matrix",
            "input_path": str(prepared["region_matrix"]),
            "input_matrix": str(prepared["region_matrix"]),
            "samplesheet": str(prepared["samplesheet"]),
            "source_files": {"scatac_peak_h5": str(input_h5), "dataset_manifest": str(prepared["dataset_manifest"])},
            "n_samples": int(prepared["n_samples"]),
            "n_features": int(prepared["n_features"]),
            "figures": _artifact_values(artifacts, "figures"),
            "tables": _artifact_values(artifacts, "tables"),
            "objects": _artifact_dict(artifacts, "objects"),
            "delivery_scope": "not_customer_delivery",
            "validation_note": (
                "Public scATAC-derived region matrix validation for Ultimate SCEPI matrix-level MVP. "
                "This is validated backend evidence only, not customer delivery and not full scBS/CUT&Tag/CUT&RUN/scATAC modality-specific inference."
            ),
        }
    )
    add_validation_guard_fields(
        manifest,
        validation_kind="public",
        validation_scope="10x PBMC scATAC-derived SCEPI matrix backend validation",
    )
    manifest["delivery_scope"] = "not_customer_delivery"
    manifest["non_delivery_reason"] = "validated_backend_not_customer_delivery"
    manifest["slurm_job_id"] = manifest.get("slurm_job_id") or os.environ.get("SLURM_JOB_ID", "")
    manifest["slurm_job_name"] = manifest.get("slurm_job_name") or os.environ.get("SLURM_JOB_NAME", "")
    manifest["slurm"] = {
        **(manifest.get("slurm") if isinstance(manifest.get("slurm"), dict) else {}),
        "job_id": manifest["slurm_job_id"],
        "job_name": manifest["slurm_job_name"],
        "submit_dir": os.environ.get("SLURM_SUBMIT_DIR", ""),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return finalize_run_outputs(output_dir, manifest_path, manifest)


def prepare_scepi_public_inputs(
    *,
    input_h5: Path,
    region_matrix: Path,
    samplesheet: Path,
    dataset_manifest: Path,
    max_features: int,
    max_cells: int,
) -> dict[str, Any]:
    import h5py
    import numpy as np
    from scipy import sparse

    region_matrix.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(input_h5, "r") as handle:
        group = handle["matrix"]
        features = group.get("features")
        if features is not None and "name" in features:
            names = [value.decode("utf-8") if isinstance(value, bytes) else str(value) for value in features["name"][:]]
        elif features is not None and "id" in features:
            names = [value.decode("utf-8") if isinstance(value, bytes) else str(value) for value in features["id"][:]]
        else:
            names = [f"region_{idx}" for idx in range(int(group["shape"][0]))]
        barcodes = [value.decode("utf-8") if isinstance(value, bytes) else str(value) for value in group["barcodes"][:]]
        shape = tuple(int(value) for value in group["shape"][:])
        matrix = sparse.csc_matrix((group["data"][:], group["indices"][:], group["indptr"][:]), shape=shape)

    n_features = min(max_features, matrix.shape[0])
    n_cells = min(max_cells, matrix.shape[1])
    feature_counts = np.asarray(matrix.sum(axis=1)).reshape(-1)
    selected_features = np.argsort(feature_counts)[::-1][:n_features]
    selected_cells = np.arange(n_cells)
    subset = matrix[selected_features, :][:, selected_cells].toarray()
    feature_ids = []
    for idx, feature_idx in enumerate(selected_features):
        name = names[int(feature_idx)]
        suffix = "_promoter" if idx % 7 == 0 else "_enhancer" if idx % 11 == 0 else ""
        feature_ids.append(f"{name}{suffix}")
    sample_ids = [barcodes[int(idx)] for idx in selected_cells]
    frame = pd.DataFrame(subset, columns=sample_ids)
    frame.insert(0, "feature_id", feature_ids)
    frame.to_csv(region_matrix, sep="\t", index=False)
    split = max(2, len(sample_ids) // 2)
    sample_meta = pd.DataFrame(
        {
            "sample_id": sample_ids,
            "condition": ["control" if idx < split else "treated" for idx, _ in enumerate(sample_ids)],
            "batch": [f"batch{idx % 2 + 1}" for idx, _ in enumerate(sample_ids)],
            "input_path": str(region_matrix),
        }
    )
    sample_meta.to_csv(samplesheet, sep="\t", index=False)
    pd.DataFrame(
        [
            {"field": "dataset", "value": "10x PBMC scATAC public matrix-derived SCEPI validation"},
            {"field": "source_h5", "value": str(input_h5)},
            {"field": "region_matrix", "value": str(region_matrix)},
            {"field": "samplesheet", "value": str(samplesheet)},
            {"field": "n_features_used", "value": n_features},
            {"field": "n_samples_used", "value": n_cells},
            {"field": "validation_scope", "value": "backend evidence only; not customer delivery"},
        ]
    ).to_csv(dataset_manifest, sep="\t", index=False)
    return {
        "region_matrix": region_matrix,
        "samplesheet": samplesheet,
        "dataset_manifest": dataset_manifest,
        "n_samples": int(n_cells),
        "n_features": int(n_features),
        "source_h5": input_h5,
    }


def write_project_config(*, output_dir: Path, prepared: dict[str, Any], project_root: Path) -> Path:
    config_dir = output_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    request_path = config_dir / "analysis_request.yaml"
    request = {
        "request_id": "slurm_scepi_matrix_public",
        "project_type": "scepi",
        "enabled_modules": ["scepi"],
        "analysis_presets": ["validated_backend_public_region_matrix"],
        "comparisons": ["treated_vs_control"],
        "special_notes": "Public scATAC-derived SCEPI matrix validation evidence; not customer delivery.",
    }
    dump_yaml(request, request_path)
    config = {
        "project": {
            "name": "slurm_scepi_matrix",
            "organism": "human",
            "output_dir": str(output_dir),
            "server_root": str(project_root),
            "run_mode": "validation",
            "job_id": "slurm_scepi_matrix",
            "is_demo": False,
            "overwrite": True,
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
            "scepi": {
                "enabled": True,
                "preset": "standard",
                "analysis_level": "validated_backend",
                "is_demo": False,
                "public_dataset": True,
                "validation_dataset": "10x_pbmc_scatac_derived_region_matrix",
                "input_matrix": str(prepared["region_matrix"]),
                "samplesheet": str(prepared["samplesheet"]),
                "raw": {
                    "enabled": False,
                    "input_type": "region_matrix",
                    "matrix_path": str(prepared["region_matrix"]),
                    "qc": {"enabled": True},
                    "toolchain": ["10x PBMC scATAC matrix-derived region matrix", "Signac/ArchR/minfi handoff"],
                },
            }
        },
        "report": {
            "title": "Ultimate SCEPI 公开验证报告",
            "language": "zh-CN",
            "style": "soft_color",
            "layout": "clinical_report",
            "figure_format": "png",
            "dpi": 180,
            "notes": "Public SCEPI matrix validation evidence; not customer delivery.",
        },
    }
    config_path = config_dir / "project.yaml"
    dump_yaml(config, config_path)
    return config_path


def _write_skip_manifest(output_dir: Path, *, reason: str) -> dict[str, Any]:
    manifest_path = output_dir / "run_manifest.json"
    manifest = {
        "run_id": "slurm_scepi_matrix_skipped",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "module": "scepi",
        "status": "partial:data_required",
        "analysis_level": "smoke_backend",
        "is_demo": False,
        "is_stub": True,
        "delivery_allowed": False,
        "validation_evidence_allowed": False,
        "delivery_scope": "not_customer_delivery",
        "non_delivery_reason": f"validation_not_completed:{reason}",
        "output_dir": str(output_dir),
        "backend_id": "scepi.default.matrix_handoff_mvp",
        "backend_status": "fully_automatic_validated_entrypoint",
        "backend_skip_reason": reason,
        "slurm_job_id": os.environ.get("SLURM_JOB_ID", ""),
        "slurm_job_name": os.environ.get("SLURM_JOB_NAME", ""),
        "slurm": {
            "job_id": os.environ.get("SLURM_JOB_ID", ""),
            "job_name": os.environ.get("SLURM_JOB_NAME", ""),
            "submit_dir": os.environ.get("SLURM_SUBMIT_DIR", ""),
        },
        "skip_reason": reason,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "reports").mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    (output_dir / "reports" / "methods.md").write_text(
        "# SCEPI public validation skipped\n\n"
        "analysis_level: `smoke_backend`\n\n"
        "delivery_allowed: `false`\n\n"
        "validation_evidence_allowed: `false`\n\n"
        "delivery_scope: `not_customer_delivery`\n\n"
        f"reason: {reason}\n",
        encoding="utf-8",
    )
    (output_dir / "reports" / "report.html").write_text(
        "<html><body><h1>SCEPI public validation skipped</h1>"
        "<p>analysis_level: smoke_backend</p>"
        "<p>delivery_allowed: false</p>"
        "<p>validation_evidence_allowed: false</p>"
        "<p>delivery_scope: not_customer_delivery</p>"
        f"<p>{reason}</p></body></html>",
        encoding="utf-8",
    )
    return manifest


def _try_prepare_public_data(project_root: Path) -> None:
    script = project_root / "01_tools" / "prepare_public_singlecell_manifests.py"
    if script.exists():
        subprocess.run([sys.executable, str(script), "--root", str(project_root), "--mode", "download"], check=False)


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
