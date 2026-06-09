from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from ultimate.config import dump_yaml
from ultimate.pipeline import run_pipeline_from_config


def _write_matrix(path: Path, rows: list[tuple[str, list[int]]], cells: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["feature_id\t" + "\t".join(cells)]
    for feature, values in rows:
        lines.append(feature + "\t" + "\t".join(map(str, values)))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_multiome_fixture(tmp_path: Path) -> tuple[Path, Path]:
    cells = ["cell_a", "cell_b", "cell_c", "cell_d"]
    rna = tmp_path / "rna_counts.tsv"
    atac = tmp_path / "atac_peaks.tsv"
    _write_matrix(
        rna,
        [
            ("CD3D", [10, 12, 2, 1]),
            ("MS4A1", [1, 2, 11, 13]),
            ("LYZ", [4, 3, 8, 7]),
        ],
        cells,
    )
    _write_matrix(
        atac,
        [
            ("chr1:100-200", [5, 6, 1, 0]),
            ("chr1:300-420", [0, 1, 8, 9]),
            ("chr2:50-150", [2, 2, 3, 4]),
        ],
        cells,
    )
    return rna, atac


def _write_config(tmp_path: Path, *, rna: Path, atac: Path, output_name: str = "run") -> Path:
    config_path = tmp_path / f"{output_name}.yaml"
    dump_yaml(
        {
            "project": {
                "name": f"multiome_{output_name}",
                "organism": "human",
                "output_dir": str(tmp_path / output_name),
                "server_root": str(tmp_path),
                "run_mode": "interactive",
            },
            "samples": {
                "items": [
                    {"sample_id": "S1", "condition": "control", "input_path": str(rna)},
                    {"sample_id": "S2", "condition": "treated", "input_path": str(atac)},
                ]
            },
            "modules": {
                "multiome": {
                    "enabled": True,
                    "preset": "multiome",
                    "rna_matrix": str(rna),
                    "atac_matrix": str(atac),
                    "raw": {
                        "enabled": False,
                        "input_type": "rna_atac_matrix",
                    },
                }
            },
        },
        config_path,
    )
    return config_path


def test_multiome_backend_generates_mvp_outputs(tmp_path: Path) -> None:
    rna, atac = _write_multiome_fixture(tmp_path)
    config_path = _write_config(tmp_path, rna=rna, atac=atac)

    manifest = run_pipeline_from_config(config_path)
    run_dir = Path(manifest["output_dir"])
    multiome = manifest["modules"][0]

    assert multiome["module"] == "multiome"
    assert multiome["status"] == "complete_multiome_muon_backend"
    assert multiome["backend_id"] == "multiome.default.muon_mvp"
    assert multiome["backend_status"] == "fully_automatic_validated_entrypoint"
    assert multiome["analysis_level"] == "smoke_backend"
    assert multiome["delivery_allowed"] is False
    assert multiome["n_cells"] == 4
    for key in ("rna_qc", "atac_qc", "barcode_overlap", "modality_consistency", "rna_marker_handoff", "atac_marker_peak_handoff", "peak_gene_link_handoff"):
        path = Path(multiome["artifacts"]["tables"][key])
        assert path.exists() and path.stat().st_size > 0
    for key in ("joint_embedding_placeholder", "modality_qc"):
        path = Path(multiome["artifacts"]["figures"][key])
        assert path.exists() and path.stat().st_size > 0
    assert (run_dir / "objects" / "multiome" / "multiome_mvp.h5mu").exists()
    overlap = pd.read_csv(run_dir / "results" / "tables" / "multiome" / "barcode_overlap.tsv", sep="\t")
    assert {"rna_barcode_count", "atac_barcode_count", "overlap_count", "overlap_fraction", "overlap_status"}.issubset(overlap.columns)
    assert float(overlap.loc[0, "overlap_fraction"]) == 1.0
    consistency = pd.read_csv(run_dir / "results" / "tables" / "multiome" / "modality_consistency.tsv", sep="\t")
    assert {"rna_qc_status", "atac_qc_status", "joint_object_status", "modality_warning"}.issubset(consistency.columns)
    methods = (run_dir / "reports" / "multiome" / "methods.md").read_text(encoding="utf-8")
    assert "analysis_level" in methods
    assert "Multiome 不等于 scRNA 与 scATAC 简单拼接" in methods


def test_multiome_backend_missing_inputs_remains_non_deliverable(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, rna=tmp_path / "missing_rna.tsv", atac=tmp_path / "missing_atac.tsv", output_name="missing")

    manifest = run_pipeline_from_config(config_path)
    run_dir = Path(manifest["output_dir"])
    multiome = manifest["modules"][0]

    assert multiome["status"] == "partial:multiome_inputs_missing"
    assert multiome["analysis_level"] == "smoke_backend"
    assert multiome["delivery_allowed"] is False
    assert multiome["validation_evidence_allowed"] is False
    assert multiome["skip_reasons"]
    qc_manifest = json.loads((run_dir / "results" / "tables" / "multiome" / "module_qc_manifest.json").read_text(encoding="utf-8"))
    assert qc_manifest["delivery_allowed"] is False
    assert qc_manifest["skip_reasons"]


def test_multiome_publication_preset_runs_peak_gene_correlation_outputs(tmp_path: Path) -> None:
    rna, atac = _write_multiome_fixture(tmp_path)
    config_path = _write_config(tmp_path, rna=rna, atac=atac, output_name="publication")
    raw = config_path.read_text(encoding="utf-8")
    config_path.write_text(raw.replace("preset: multiome", "preset: publication"), encoding="utf-8")

    manifest = run_pipeline_from_config(config_path)
    run_dir = Path(manifest["output_dir"])
    multiome = manifest["modules"][0]
    active_ids = {row["backend_id"] for row in multiome["backend_plan"]["active_backends"]}
    execution_rows = {row["backend_id"]: row for row in multiome["backend_execution_rows"]}

    assert "multiome.peak_gene.correlation" in active_ids
    assert execution_rows["multiome.peak_gene.correlation"]["status"] == "ready"
    for relative in [
        "results/tables/multiome/peak_gene_links.tsv",
        "results/tables/multiome/peak_gene_modality_correlation.tsv",
        "results/tables/multiome/peak_gene_correlation_backend_status.tsv",
        "results/tables/multiome/peak_gene_correlation_backend_manifest.json",
        "results/tables/multiome/peak_gene_correlation_backend_versions.tsv",
        "results/figures/multiome/peak_gene_correlation_heatmap.png",
        "objects/multiome/peak_gene_correlation_backend.rds",
    ]:
        path = run_dir / relative
        assert path.exists() and path.stat().st_size > 0
    links = pd.read_csv(run_dir / "results/tables/multiome/peak_gene_links.tsv", sep="\t")
    assert {"peak_id", "gene_id", "correlation", "method_boundary", "n_shared_barcodes"}.issubset(links.columns)
    assert "not enhancer-gene experimental proof" in links.loc[0, "method_boundary"]
