from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from ultimate.config import dump_yaml
from ultimate.pipeline import run_pipeline_from_config


def _write_spatial_fixture(tmp_path: Path) -> tuple[Path, Path]:
    matrix = tmp_path / "spatial_counts.tsv"
    matrix.write_text(
        "\n".join(
            [
                "feature_id\tspot_a\tspot_b\tspot_c\tspot_d\tspot_e",
                "GeneA\t10\t12\t2\t1\t4",
                "GeneB\t1\t3\t13\t15\t2",
                "GeneC\t8\t7\t4\t5\t9",
                "GeneD\t0\t1\t3\t2\t8",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    coordinates = tmp_path / "spatial_coordinates.tsv"
    coordinates.write_text(
        "\n".join(
            [
                "spot_id\tpxl_col\tpxl_row\tarray_col\tarray_row\tin_tissue",
                "spot_a\t0\t0\t0\t0\t1",
                "spot_b\t1\t0\t1\t0\t1",
                "spot_c\t0\t1\t0\t1\t1",
                "spot_d\t1\t1\t1\t1\t1",
                "spot_e\t2\t1\t2\t1\t1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return matrix, coordinates


def _write_config(tmp_path: Path, *, matrix: Path, coordinates: Path, output_name: str = "run") -> Path:
    config_path = tmp_path / f"{output_name}.yaml"
    dump_yaml(
        {
            "project": {
                "name": f"spatial_{output_name}",
                "organism": "human",
                "output_dir": str(tmp_path / output_name),
                "server_root": str(tmp_path),
                "run_mode": "interactive",
            },
            "samples": {
                "items": [
                    {"sample_id": "SP1", "condition": "public_validation", "input_path": str(matrix)},
                ]
            },
            "modules": {
                "spatial": {
                    "enabled": True,
                    "preset": "standard",
                    "expression_matrix": str(matrix),
                    "coordinates": str(coordinates),
                    "raw": {
                        "enabled": False,
                        "input_type": "visium_h5ad",
                    },
                }
            },
        },
        config_path,
    )
    return config_path


def test_spatial_backend_generates_visium_mvp_outputs(tmp_path: Path) -> None:
    matrix, coordinates = _write_spatial_fixture(tmp_path)
    config_path = _write_config(tmp_path, matrix=matrix, coordinates=coordinates)

    manifest = run_pipeline_from_config(config_path)
    run_dir = Path(manifest["output_dir"])
    spatial = manifest["modules"][0]

    assert spatial["module"] == "spatial"
    assert spatial["status"] == "complete_spatial_visium_backend"
    assert spatial["backend_id"] == "spatial.visium.squidpy_mvp"
    assert spatial["backend_status"] == "fully_automatic_validated_entrypoint"
    assert spatial["analysis_level"] == "smoke_backend"
    assert spatial["delivery_allowed"] is False
    assert spatial["n_spots"] == 5
    for key in ("spatial_qc", "spot_metadata", "coordinate_check", "domain_summary", "spatial_neighbors", "spatial_marker_handoff", "deconvolution_handoff"):
        path = Path(spatial["artifacts"]["tables"][key])
        assert path.exists() and path.stat().st_size > 0
    for key in ("spatial_qc_plot", "spatial_cluster", "domain_map"):
        path = Path(spatial["artifacts"]["figures"][key])
        assert path.exists() and path.stat().st_size > 0
    assert (run_dir / "objects" / "spatial" / "spatial_mvp.h5ad").exists()
    qc = pd.read_csv(run_dir / "results" / "tables" / "spatial" / "spatial_qc.tsv", sep="\t")
    assert {"spot_id", "total_counts", "detected_genes", "in_tissue", "platform_note"}.issubset(qc.columns)
    assert set(qc["platform_note"]) == {"Visium spot is not a single cell"}
    methods = (run_dir / "reports" / "spatial" / "methods.md").read_text(encoding="utf-8")
    assert "analysis_level" in methods
    assert "Visium spot 不是单细胞" in methods


def test_spatial_backend_missing_inputs_remains_non_deliverable(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, matrix=tmp_path / "missing_counts.tsv", coordinates=tmp_path / "missing_coordinates.tsv", output_name="missing")

    manifest = run_pipeline_from_config(config_path)
    run_dir = Path(manifest["output_dir"])
    spatial = manifest["modules"][0]

    assert spatial["status"] == "partial:spatial_inputs_missing"
    assert spatial["analysis_level"] == "smoke_backend"
    assert spatial["delivery_allowed"] is False
    assert spatial["validation_evidence_allowed"] is False
    assert spatial["skip_reasons"]
    qc_manifest = json.loads((run_dir / "results" / "tables" / "spatial" / "module_qc_manifest.json").read_text(encoding="utf-8"))
    assert qc_manifest["delivery_allowed"] is False
    assert qc_manifest["skip_reasons"]
