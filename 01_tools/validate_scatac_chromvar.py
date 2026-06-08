#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from validation_manifest_utils import add_validation_guard_fields

import h5py
import pandas as pd

from ultimate.config import dump_yaml
from ultimate.pipeline import run_pipeline_from_config


DEFAULT_H5 = Path(
    "/shared/shen/2026/ultimate/public_data/scatac/"
    "10k_pbmc_ATACv2_nextgem_Chromium_Controller_filtered_peak_bc_matrix.h5"
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the scATAC chromVAR/Signac-compatible motif backend.")
    parser.add_argument("--input-h5", type=Path, default=DEFAULT_H5)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--max-peaks", type=int, default=120)
    args = parser.parse_args()
    manifest = run_validation(input_h5=args.input_h5, output_dir=args.output_dir, max_peaks=args.max_peaks)
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


def run_validation(*, input_h5: Path, output_dir: Path, max_peaks: int = 120) -> dict:
    if not input_h5.exists():
        manifest = _skip_manifest(output_dir, f"missing_input_h5:{input_h5}")
        (output_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        _write_skip_report(output_dir, manifest)
        return manifest
    output_dir.mkdir(parents=True, exist_ok=True)
    fixture_dir = output_dir / "input_fixtures"
    fixture_dir.mkdir(parents=True, exist_ok=True)
    motif_table, gene_table = _write_mapping_fixtures(input_h5, fixture_dir, max_peaks=max_peaks)
    config_path = output_dir / "config" / "project.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    dump_yaml(
        {
            "project": {
                "name": "slurm_scatac_chromvar_signac",
                "organism": "human",
                "output_dir": str(output_dir),
                "server_root": str(output_dir.parents[1] if len(output_dir.parents) > 1 else output_dir),
                "run_mode": "interactive",
                "overwrite": True,
            },
            "samples": {"items": [{"sample_id": "pbmc_scatac", "condition": "public_validation", "input_path": str(input_h5)}]},
            "design": {"condition_column": "condition", "control": "public_validation", "case": "public_validation"},
            "modules": {
                "scatac": {
                    "enabled": True,
                    "preset": "publication",
                    "input_h5": str(input_h5),
                    "motif_peak_table": str(motif_table),
                    "gene_peak_table": str(gene_table),
                    "analysis_level": "validated_backend",
                    "public_dataset": True,
                    "backends": {"motif": "chromvar"},
                    "raw": {"enabled": False, "input_type": "peak_matrix"},
                }
            },
            "report": {"title": "scATAC chromVAR/Signac-compatible backend validation", "style": "soft_color"},
        },
        config_path,
    )
    manifest = run_pipeline_from_config(config_path)
    scatac = next((module for module in manifest.get("modules", []) if module.get("module") == "scatac"), {})
    backend_status_path = output_dir / "results" / "tables" / "scatac" / "chromvar_signac_backend_status.tsv"
    ready = False
    reason = "missing_chromvar_signac_backend_status"
    if backend_status_path.exists():
        status = pd.read_csv(backend_status_path, sep="\t")
        if not status.empty:
            ready = str(status.iloc[0].get("status")) == "ready"
            raw_reason = status.iloc[0].get("reason")
            reason = "" if pd.isna(raw_reason) else str(raw_reason)
    manifest["backend_validation_target"] = "scatac.motif.chromvar_signac"
    manifest["chromvar_signac_backend_status"] = "ready" if ready else "partial"
    manifest["chromvar_signac_backend_reason"] = reason
    if ready and scatac.get("analysis_level") == "validated_backend":
        add_validation_guard_fields(
            manifest,
            validation_kind="public",
            validation_scope="scATAC chromVAR/Signac-compatible public validation with lightweight motif/gene mapping fixture",
        )
    else:
        manifest["status"] = f"partial:{reason}"
        add_validation_guard_fields(
            manifest,
            validation_kind="smoke",
            validation_scope="scATAC chromVAR/Signac-compatible backend validation did not complete",
        )
    (output_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def _write_mapping_fixtures(input_h5: Path, fixture_dir: Path, *, max_peaks: int) -> tuple[Path, Path]:
    peaks = _read_peak_names(input_h5)[:max_peaks]
    motif_rows = []
    gene_rows = []
    for idx, peak in enumerate(peaks):
        motif_rows.append({"peak_id": peak, "motif_id": f"PBMC_MOTIF_{idx % 8:02d}"})
        gene_rows.append({"peak_id": peak, "gene_id": f"GENE_ACTIVITY_{idx % 12:02d}"})
    motif_table = fixture_dir / "motif_peak_table.tsv"
    gene_table = fixture_dir / "gene_peak_table.tsv"
    pd.DataFrame(motif_rows).to_csv(motif_table, sep="\t", index=False)
    pd.DataFrame(gene_rows).to_csv(gene_table, sep="\t", index=False)
    return motif_table, gene_table


def _read_peak_names(input_h5: Path) -> list[str]:
    with h5py.File(input_h5, "r") as handle:
        features = handle["matrix"]["features"]
        key = "name" if "name" in features else "id"
        values = features[key][:]
    return [value.decode("utf-8") if isinstance(value, bytes) else str(value) for value in values]


def _skip_manifest(output_dir: Path, reason: str) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "module": "scatac",
        "output_dir": str(output_dir),
        "status": f"partial:{reason}",
        "backend_validation_target": "scatac.motif.chromvar_signac",
        "chromvar_signac_backend_status": "partial",
        "chromvar_signac_backend_reason": reason,
        "tables": [],
        "figures": [],
        "objects": {},
    }
    add_validation_guard_fields(
        manifest,
        validation_kind="smoke",
        validation_scope="scATAC chromVAR/Signac-compatible backend validation missing input",
    )
    return manifest


def _write_skip_report(output_dir: Path, manifest: dict) -> None:
    reports = output_dir / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    text = "\n".join(
        [
            "# scATAC chromVAR/Signac backend validation skipped",
            "",
            f"- status: `{manifest.get('status')}`",
            f"- analysis_level: `{manifest.get('analysis_level')}`",
            f"- delivery_allowed: `{manifest.get('delivery_allowed')}`",
            f"- reason: `{manifest.get('chromvar_signac_backend_reason')}`",
        ]
    )
    (reports / "methods.md").write_text(text + "\n", encoding="utf-8")
    (reports / "report.html").write_text("<html><body>" + "".join(f"<p>{line}</p>" for line in text.splitlines()) + "</body></html>", encoding="utf-8")


if __name__ == "__main__":
    main()
