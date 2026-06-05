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


def _write_cite_fixture(tmp_path: Path) -> tuple[Path, Path]:
    cells = ["cell_a", "cell_b", "cell_c", "cell_d"]
    rna = tmp_path / "rna_counts.tsv"
    adt = tmp_path / "adt_counts.tsv"
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
        adt,
        [
            ("CD3_TotalSeqB", [100, 120, 20, 18]),
            ("CD19_TotalSeqB", [10, 9, 90, 110]),
            ("CD14_TotalSeqB", [30, 25, 60, 58]),
        ],
        cells,
    )
    return rna, adt


def _write_config(tmp_path: Path, *, rna: Path, adt: Path, output_name: str = "run") -> Path:
    config_path = tmp_path / f"{output_name}.yaml"
    dump_yaml(
        {
            "project": {
                "name": f"cite_{output_name}",
                "organism": "human",
                "output_dir": str(tmp_path / output_name),
                "server_root": str(tmp_path),
                "run_mode": "interactive",
            },
            "samples": {
                "items": [
                    {"sample_id": "S1", "condition": "control", "input_path": str(rna)},
                    {"sample_id": "S2", "condition": "treated", "input_path": str(adt)},
                ]
            },
            "modules": {
                "cite_seq": {
                    "enabled": True,
                    "raw": {
                        "enabled": False,
                        "input_type": "rna_adt_matrix",
                        "count_matrix": str(rna),
                        "adt_counts": str(adt),
                    },
                }
            },
        },
        config_path,
    )
    return config_path


def test_cite_seq_backend_generates_mvp_outputs(tmp_path: Path) -> None:
    rna, adt = _write_cite_fixture(tmp_path)
    config_path = _write_config(tmp_path, rna=rna, adt=adt)

    manifest = run_pipeline_from_config(config_path)
    run_dir = Path(manifest["output_dir"])
    cite = manifest["modules"][0]

    assert cite["module"] == "cite_seq"
    assert cite["status"] == "complete_cite_seq_clr_backend"
    assert cite["backend_id"] == "cite_seq.default.clr_mvp"
    assert cite["backend_status"] == "fully_automatic_validated_entrypoint"
    assert cite["analysis_level"] == "smoke_backend"
    assert cite["delivery_allowed"] is False
    for key in ("adt_qc", "antibody_panel", "adt_normalized_matrix", "adt_marker_summary", "rna_protein_consistency"):
        path = Path(cite["artifacts"]["tables"][key])
        assert path.exists() and path.stat().st_size > 0
    for key in ("adt_count_distribution", "adt_heatmap", "rna_protein_consistency"):
        path = Path(cite["artifacts"]["figures"][key])
        assert path.exists() and path.stat().st_size > 0
    assert (run_dir / "objects" / "cite_seq" / "cite_mvp.h5mu").exists()
    adt_qc = pd.read_csv(run_dir / "results" / "tables" / "cite_seq" / "adt_qc.tsv", sep="\t")
    assert {"cell_id", "adt_total_counts", "background_status", "isotype_control_status"}.issubset(adt_qc.columns)
    normalized = pd.read_csv(run_dir / "results" / "tables" / "cite_seq" / "adt_normalized_matrix.tsv", sep="\t")
    assert set(normalized["normalization_method"]) == {"CLR_log1p_centered_per_cell"}
    methods = (run_dir / "reports" / "cite_seq" / "methods.md").read_text(encoding="utf-8")
    assert "analysis_level" in methods
    assert "ADT 不是全蛋白组" in methods


def test_cite_seq_backend_missing_inputs_remains_non_deliverable(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, rna=tmp_path / "missing_rna.tsv", adt=tmp_path / "missing_adt.tsv", output_name="missing")

    manifest = run_pipeline_from_config(config_path)
    cite = manifest["modules"][0]
    run_dir = Path(manifest["output_dir"])

    assert cite["status"] == "partial:cite_seq_inputs_missing"
    assert cite["analysis_level"] == "smoke_backend"
    assert cite["delivery_allowed"] is False
    assert cite["validation_evidence_allowed"] is False
    assert cite["skip_reasons"]
    qc_manifest = json.loads((run_dir / "results" / "tables" / "cite_seq" / "module_qc_manifest.json").read_text(encoding="utf-8"))
    assert qc_manifest["delivery_allowed"] is False
    assert qc_manifest["skip_reasons"]
