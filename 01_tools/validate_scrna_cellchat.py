#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from validation_manifest_utils import add_validation_guard_fields

from ultimate.scrna_smoke import run_scrna_validation


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the guarded scRNA CellChat optional backend.")
    parser.add_argument("--input-path", required=True, type=Path)
    parser.add_argument("--input-type", choices=["h5ad", "10x_h5", "10x_mtx"], required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--samplesheet", type=Path, default=None)
    parser.add_argument("--celltypist-model", type=Path, default=None)
    parser.add_argument("--max-cells", type=int, default=1200)
    parser.add_argument("--random-seed", type=int, default=13)
    args = parser.parse_args()
    manifest = run_validation(
        input_path=args.input_path,
        input_type=args.input_type,
        output_dir=args.output_dir,
        samplesheet=args.samplesheet,
        celltypist_model=args.celltypist_model,
        max_cells=args.max_cells,
        random_seed=args.random_seed,
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


def run_validation(
    *,
    input_path: Path,
    input_type: str,
    output_dir: Path,
    samplesheet: Path | None = None,
    celltypist_model: Path | None = None,
    max_cells: int = 1200,
    random_seed: int = 13,
) -> dict:
    manifest = run_scrna_validation(
        input_path=input_path,
        input_type=input_type,
        output_dir=output_dir,
        samplesheet=samplesheet,
        max_cells=max_cells,
        random_seed=random_seed,
        analysis_level="validated_backend",
        public_dataset=True,
        dataset_label="scrna_cellchat_backend_validation",
        celltypist_model=celltypist_model,
    )
    backend_rows = manifest.get("backend_status") if isinstance(manifest.get("backend_status"), list) else []
    cellchat = next((row for row in backend_rows if row.get("backend_id") == "scrna.communication.cellchat_optional"), None)
    if not cellchat or cellchat.get("status") != "ready":
        reason = str((cellchat or {}).get("reason") or "cellchat_backend_not_ready")
        manifest["status"] = f"partial:{reason}"
        manifest["backend_validation_target"] = "scrna.communication.cellchat_optional"
        manifest["cellchat_backend_status"] = (cellchat or {}).get("status", "missing")
        manifest["cellchat_backend_reason"] = reason
        add_validation_guard_fields(
            manifest,
            validation_kind="smoke",
            validation_scope="CellChat optional backend validation did not complete; skip evidence only",
        )
    else:
        manifest["backend_validation_target"] = "scrna.communication.cellchat_optional"
        manifest["cellchat_backend_status"] = "ready"
        manifest["cellchat_backend_reason"] = ""
        add_validation_guard_fields(
            manifest,
            validation_kind="public",
            validation_scope="CellChat optional backend public validation with reviewed/celltypist labels",
        )
    (output_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_report(manifest, output_dir / "reports" / "report.html", output_dir / "reports" / "methods.md")
    return manifest


def _write_report(manifest: dict, html_path: Path, methods_path: Path) -> None:
    html_path.parent.mkdir(parents=True, exist_ok=True)
    methods_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# scRNA CellChat optional backend validation",
        "",
        f"- backend: `{manifest.get('backend_validation_target', 'scrna.communication.cellchat_optional')}`",
        f"- status: `{manifest.get('status')}`",
        f"- analysis_level: `{manifest.get('analysis_level')}`",
        f"- validation_evidence_allowed: `{manifest.get('validation_evidence_allowed')}`",
        f"- delivery_allowed: `{manifest.get('delivery_allowed')}`",
        f"- reason: `{manifest.get('cellchat_backend_reason', '')}`",
        "",
        "CellChat ligand-receptor results are expression-derived candidates and must not be reported as direct mechanism proof.",
    ]
    methods_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    html_path.write_text("<html><body>" + "".join(f"<p>{line}</p>" for line in lines) + "</body></html>", encoding="utf-8")


if __name__ == "__main__":
    main()
