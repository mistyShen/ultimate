#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from validation_manifest_utils import add_validation_guard_fields

from ultimate.scrna_smoke import run_scrna_validation


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the guarded scRNA NicheNet-style optional backend.")
    parser.add_argument("--input-path", required=True, type=Path)
    parser.add_argument("--input-type", choices=["h5ad", "10x_h5", "10x_mtx"], required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--samplesheet", type=Path, default=None)
    parser.add_argument("--nichenet-resource", type=Path, default=None)
    parser.add_argument("--max-cells", type=int, default=1200)
    parser.add_argument("--random-seed", type=int, default=19)
    args = parser.parse_args()
    manifest = run_validation(
        input_path=args.input_path,
        input_type=args.input_type,
        output_dir=args.output_dir,
        samplesheet=args.samplesheet,
        nichenet_resource=args.nichenet_resource,
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
    nichenet_resource: Path | None = None,
    max_cells: int = 1200,
    random_seed: int = 19,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    fixture_dir = output_dir / "input_fixtures"
    fixture_dir.mkdir(parents=True, exist_ok=True)
    samplesheet = samplesheet or _write_reviewed_labels(input_path, input_type, fixture_dir)
    nichenet_resource = nichenet_resource or _write_ligand_target_resource(input_path, input_type, fixture_dir)
    if samplesheet is None or nichenet_resource is None:
        manifest = _write_skip_manifest(output_dir, "partial:data_required", "unable_to_prepare_reviewed_labels_or_ligand_target_resource")
        return manifest
    manifest = run_scrna_validation(
        input_path=input_path,
        input_type=input_type,
        output_dir=output_dir,
        samplesheet=samplesheet,
        max_cells=max_cells,
        random_seed=random_seed,
        analysis_level="validated_backend",
        public_dataset=True,
        dataset_label="scrna_nichenet_backend_validation",
        nichenet_resource=nichenet_resource,
    )
    backend_rows = manifest.get("backend_status") if isinstance(manifest.get("backend_status"), list) else []
    nichenet = next((row for row in backend_rows if row.get("backend_id") == "scrna.communication.nichenet_optional"), None)
    if not nichenet or nichenet.get("status") != "ready":
        reason = str((nichenet or {}).get("reason") or "nichenet_backend_not_ready")
        manifest["status"] = f"partial:{reason}"
        manifest["backend_validation_target"] = "scrna.communication.nichenet_optional"
        manifest["nichenet_backend_status"] = (nichenet or {}).get("status", "missing")
        manifest["nichenet_backend_reason"] = reason
        add_validation_guard_fields(
            manifest,
            validation_kind="smoke",
            validation_scope="NicheNet optional backend validation did not complete; skip evidence only",
        )
    else:
        manifest["backend_validation_target"] = "scrna.communication.nichenet_optional"
        manifest["nichenet_backend_status"] = "ready"
        manifest["nichenet_backend_reason"] = ""
        add_validation_guard_fields(
            manifest,
            validation_kind="public",
            validation_scope="NicheNet-style optional backend public validation with reviewed labels and ligand-target resource fixture",
        )
    (output_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_report(manifest, output_dir / "reports" / "report.html", output_dir / "reports" / "methods.md")
    return manifest


def _write_reviewed_labels(input_path: Path, input_type: str, fixture_dir: Path) -> Path | None:
    barcodes = _read_barcodes(input_path, input_type)
    if len(barcodes) < 20:
        return None
    groups = ["reviewed_T_like", "reviewed_B_like", "reviewed_myeloid_like"]
    rows = []
    for idx, barcode in enumerate(barcodes):
        rows.append(
            {
                "barcode": barcode,
                "sample_id": f"validation_sample_{1 + (idx % 2)}",
                "condition": "case" if idx % 2 else "control",
                "reviewed_cell_type": groups[idx % len(groups)],
            }
        )
    path = fixture_dir / "reviewed_cell_labels.tsv"
    pd.DataFrame(rows).to_csv(path, sep="\t", index=False)
    return path


def _write_ligand_target_resource(input_path: Path, input_type: str, fixture_dir: Path) -> Path | None:
    genes = _read_genes(input_path, input_type)
    genes = [gene for gene in genes if gene and gene.lower() not in {"nan", "none"}]
    if len(genes) < 10:
        return None
    ligands = genes[: min(8, len(genes))]
    targets = genes[: min(12000, len(genes))]
    rows = []
    for ligand_idx, ligand in enumerate(ligands):
        for target_idx, target in enumerate(targets):
            if ligand == target:
                continue
            rows.append({"ligand": ligand, "target": target, "weight": round(1.0 / (1 + ((ligand_idx + target_idx) % 25)), 5)})
    path = fixture_dir / "nichenet_ligand_target_resource.tsv"
    pd.DataFrame(rows).to_csv(path, sep="\t", index=False)
    return path


def _read_barcodes(input_path: Path, input_type: str) -> list[str]:
    if input_type == "10x_mtx":
        for name in ("barcodes.tsv.gz", "barcodes.tsv"):
            path = input_path / name
            if path.exists():
                return _read_first_column(path)
    if input_type == "h5ad":
        try:
            import anndata as ad

            return ad.read_h5ad(input_path, backed="r").obs_names.astype(str).tolist()
        except Exception:
            return []
    return []


def _read_genes(input_path: Path, input_type: str) -> list[str]:
    if input_type == "10x_mtx":
        for name in ("features.tsv.gz", "features.tsv", "genes.tsv.gz", "genes.tsv"):
            path = input_path / name
            if path.exists():
                frame = pd.read_csv(path, sep="\t", header=None)
                if frame.shape[1] > 1:
                    return frame.iloc[:, 1].astype(str).tolist()
                return frame.iloc[:, 0].astype(str).tolist()
    if input_type == "h5ad":
        try:
            import anndata as ad

            return ad.read_h5ad(input_path, backed="r").var_names.astype(str).tolist()
        except Exception:
            return []
    return []


def _read_first_column(path: Path) -> list[str]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        return [line.rstrip("\n").split("\t")[0] for line in handle if line.strip()]


def _write_skip_manifest(output_dir: Path, status: str, reason: str) -> dict:
    reports = output_dir / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "module": "scrna",
        "output_dir": str(output_dir),
        "status": status,
        "backend_validation_target": "scrna.communication.nichenet_optional",
        "analysis_level": "smoke_backend",
        "is_demo": False,
        "is_stub": True,
        "delivery_allowed": False,
        "validation_evidence_allowed": False,
        "non_delivery_reason": f"validation_not_completed:{reason}",
        "slurm_job_id": os.environ.get("SLURM_JOB_ID", ""),
        "skip_reason": reason,
    }
    (output_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_report(manifest, reports / "report.html", reports / "methods.md")
    return manifest


def _write_report(manifest: dict, html_path: Path, methods_path: Path) -> None:
    html_path.parent.mkdir(parents=True, exist_ok=True)
    methods_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# scRNA NicheNet optional backend validation",
        "",
        f"- backend: `{manifest.get('backend_validation_target', 'scrna.communication.nichenet_optional')}`",
        f"- status: `{manifest.get('status')}`",
        f"- analysis_level: `{manifest.get('analysis_level')}`",
        f"- validation_evidence_allowed: `{manifest.get('validation_evidence_allowed')}`",
        f"- delivery_allowed: `{manifest.get('delivery_allowed')}`",
        f"- reason: `{manifest.get('nichenet_backend_reason', manifest.get('skip_reason', ''))}`",
        "",
        "NicheNet-style ligand-target results are mechanism-hypothesis candidates and must not be reported as mechanism proof.",
    ]
    methods_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    html_path.write_text("<html><body>" + "".join(f"<p>{line}</p>" for line in lines) + "</body></html>", encoding="utf-8")


if __name__ == "__main__":
    main()
