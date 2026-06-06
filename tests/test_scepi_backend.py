from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from ultimate.config import dump_yaml
from ultimate.pipeline import run_pipeline_from_config


def _write_region_matrix(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "feature_id\tcell_a\tcell_b\tcell_c\tcell_d\tcell_e\tcell_f",
                "chr1:100-200_promoter\t5\t6\t1\t0\t2\t3",
                "chr1:300-420_enhancer\t0\t1\t8\t9\t2\t1",
                "chr2:50-150\t2\t2\t3\t4\t8\t9",
                "chr3:200-260_promoter\t7\t8\t0\t1\t1\t2",
                "chr4:500-700_enhancer\t1\t0\t6\t7\t3\t2",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _write_config(tmp_path: Path, *, matrix: Path, output_name: str = "run") -> Path:
    config_path = tmp_path / f"{output_name}.yaml"
    dump_yaml(
        {
            "project": {
                "name": f"scepi_{output_name}",
                "organism": "human",
                "output_dir": str(tmp_path / output_name),
                "server_root": str(tmp_path),
                "run_mode": "interactive",
            },
            "samples": {
                "items": [
                    {"sample_id": "cell_a", "condition": "control", "input_path": str(matrix)},
                    {"sample_id": "cell_b", "condition": "control", "input_path": str(matrix)},
                    {"sample_id": "cell_c", "condition": "treated", "input_path": str(matrix)},
                    {"sample_id": "cell_d", "condition": "treated", "input_path": str(matrix)},
                    {"sample_id": "cell_e", "condition": "treated", "input_path": str(matrix)},
                    {"sample_id": "cell_f", "condition": "control", "input_path": str(matrix)},
                ]
            },
            "modules": {
                "scepi": {
                    "enabled": True,
                    "preset": "standard",
                    "input_matrix": str(matrix),
                    "raw": {
                        "enabled": False,
                        "input_type": "region_matrix",
                    },
                }
            },
        },
        config_path,
    )
    return config_path


def test_scepi_backend_generates_matrix_level_outputs(tmp_path: Path) -> None:
    matrix = _write_region_matrix(tmp_path / "region_matrix.tsv")
    config_path = _write_config(tmp_path, matrix=matrix)

    manifest = run_pipeline_from_config(config_path)
    run_dir = Path(manifest["output_dir"])
    scepi = manifest["modules"][0]

    assert scepi["module"] == "scepi"
    assert scepi["status"] == "complete_scepi_matrix_backend"
    assert scepi["backend_id"] == "scepi.default.matrix_handoff_mvp"
    assert scepi["backend_status"] == "fully_automatic_validated_entrypoint"
    assert scepi["analysis_level"] == "smoke_backend"
    assert scepi["delivery_allowed"] is False
    assert scepi["n_features"] == 5
    assert scepi["n_samples"] == 6
    for key in ("feature_qc", "sample_qc", "missing_value_summary", "differential_region_handoff", "promoter_summary", "enhancer_summary", "annotation_summary"):
        path = Path(scepi["artifacts"]["tables"][key])
        assert path.exists() and path.stat().st_size > 0
    for key in ("pca", "sample_correlation_heatmap", "region_heatmap"):
        path = Path(scepi["artifacts"]["figures"][key])
        assert path.exists() and path.stat().st_size > 0
    assert (run_dir / "objects" / "scepi" / "scepi_mvp_object.rds").exists()
    feature_qc = pd.read_csv(run_dir / "results" / "tables" / "scepi" / "feature_qc.tsv", sep="\t")
    assert {"feature_id", "mean_signal", "variance_signal", "region_class", "interpretation_warning"}.issubset(feature_qc.columns)
    assert {"promoter", "enhancer"}.issubset(set(feature_qc["region_class"]))
    differential = pd.read_csv(run_dir / "results" / "tables" / "scepi" / "differential_region_handoff.tsv", sep="\t")
    assert set(differential["statistical_status"]) == {"design_ready_with_group_effect_preview_not_formal_dmr"}
    methods = (run_dir / "reports" / "scepi" / "methods.md").read_text(encoding="utf-8")
    assert "analysis_level" in methods
    assert "CUT&RUN" in methods


def test_scepi_backend_missing_inputs_remains_non_deliverable(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, matrix=tmp_path / "missing_region_matrix.tsv", output_name="missing")

    manifest = run_pipeline_from_config(config_path)
    run_dir = Path(manifest["output_dir"])
    scepi = manifest["modules"][0]

    assert scepi["status"] in {"partial:scepi_inputs_missing", "partial:scepi_input_read_failed"}
    assert scepi["analysis_level"] == "smoke_backend"
    assert scepi["delivery_allowed"] is False
    assert scepi["validation_evidence_allowed"] is False
    assert scepi["skip_reasons"]
    qc_manifest = json.loads((run_dir / "results" / "tables" / "scepi" / "module_qc_manifest.json").read_text(encoding="utf-8"))
    assert qc_manifest["delivery_allowed"] is False
    assert qc_manifest["skip_reasons"]
