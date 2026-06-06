from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

h5py = pytest.importorskip("h5py")

from ultimate.config import dump_yaml
from ultimate.pipeline import run_pipeline_from_config


def _write_h5ad_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "tumor_fixture.h5ad"
    string_dtype = h5py.string_dtype(encoding="utf-8")
    with h5py.File(path, "w") as handle:
        obs = handle.create_group("obs")
        obs.create_dataset("_index", data=np.array(["cell1", "cell2", "cell3", "cell4", "cell5"], dtype=object), dtype=string_dtype)
        cell_type = obs.create_group("cell_type")
        cell_type.create_dataset("categories", data=np.array(["Epithelial tumor", "T cell", "Myeloid", "CAF"], dtype=object), dtype=string_dtype)
        cell_type.create_dataset("codes", data=np.array([0, 1, 2, 3, 0], dtype="i4"))
        sample = obs.create_group("sample_id")
        sample.create_dataset("categories", data=np.array(["S1", "S2"], dtype=object), dtype=string_dtype)
        sample.create_dataset("codes", data=np.array([0, 0, 1, 1, 1], dtype="i4"))
        condition = obs.create_group("condition")
        condition.create_dataset("categories", data=np.array(["baseline", "treated"], dtype=object), dtype=string_dtype)
        condition.create_dataset("codes", data=np.array([0, 0, 1, 1, 1], dtype="i4"))
        var = handle.create_group("var")
        var.create_dataset("_index", data=np.array(["EPCAM", "PTPRC", "LYZ"], dtype=object), dtype=string_dtype)
        handle.create_dataset("X", data=np.ones((5, 3), dtype="f4"))
    return path


def _write_metadata_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "tumor_metadata.tsv"
    path.write_text(
        "\n".join(
            [
                "cell_id\tsample_id\tcell_type\tcondition",
                "cell1\tS1\tEpithelial tumor\tbaseline",
                "cell2\tS1\tT cell\tbaseline",
                "cell3\tS2\tCAF\ttreated",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _write_config(tmp_path: Path, *, input_path: Path, key: str = "input_h5ad", output_name: str = "run", analysis_level: str | None = None) -> Path:
    module_cfg = {
        "enabled": True,
        "preset": "tumor",
        key: str(input_path),
        "raw": {"enabled": False, "input_type": "h5ad" if input_path.suffix == ".h5ad" else "metadata_table"},
    }
    if analysis_level:
        module_cfg["analysis_level"] = analysis_level
        module_cfg["validation_dataset"] = "unit test tumor_sc fixture"
    config_path = tmp_path / f"{output_name}.yaml"
    dump_yaml(
        {
            "project": {
                "name": f"tumor_sc_{output_name}",
                "organism": "human",
                "output_dir": str(tmp_path / output_name),
                "server_root": str(tmp_path),
                "run_mode": "interactive",
            },
            "samples": {"items": [{"sample_id": "S1", "condition": "validation", "input_path": str(input_path)}]},
            "modules": {"tumor_sc": module_cfg},
        },
        config_path,
    )
    return config_path


def test_tumor_sc_backend_generates_summary_outputs(tmp_path: Path) -> None:
    input_h5ad = _write_h5ad_fixture(tmp_path)
    config_path = _write_config(tmp_path, input_path=input_h5ad)

    manifest = run_pipeline_from_config(config_path)
    run_dir = Path(manifest["output_dir"])
    module = manifest["modules"][0]

    assert module["module"] == "tumor_sc"
    assert module["status"] == "complete_tumor_sc_summary_backend"
    assert module["backend_id"] == "tumor_sc.default.summary_handoff"
    assert module["analysis_level"] == "smoke_backend"
    assert module["delivery_allowed"] is False
    assert module["n_malignant_candidates"] == 2
    for key in (
        "malignant_cell_candidates",
        "cnv_inference_summary",
        "tme_composition",
        "immune_state_scores",
        "myeloid_state_scores",
        "caf_subtype_summary",
        "tumor_state_markers",
        "therapy_response_comparison",
    ):
        path = Path(module["artifacts"]["tables"][key])
        assert path.exists() and path.stat().st_size > 0, key
    assert Path(module["artifacts"]["figures"]["tme_composition"]).exists()
    assert Path(module["artifacts"]["figures"]["tumor_state_heatmap"]).exists()
    assert Path(module["artifacts"]["figures"]["malignant_candidate_summary"]).exists()
    assert Path(module["artifacts"]["objects"]["mvp_object"]).name == "tumor_sc_mvp_object.rds"

    malignant = pd.read_csv(run_dir / "results" / "tables" / "tumor_sc" / "malignant_cell_candidates.tsv", sep="\t")
    assert malignant["malignant_candidate"].astype(bool).sum() == 2
    methods = (run_dir / "reports" / "tumor_sc" / "methods.md").read_text(encoding="utf-8")
    assert "analysis_level" in methods
    assert "malignant calling 不能只靠一个 marker" in methods


def test_tumor_sc_backend_reads_metadata_table(tmp_path: Path) -> None:
    table = _write_metadata_fixture(tmp_path)
    config_path = _write_config(tmp_path, input_path=table, key="metadata_table", output_name="table")

    manifest = run_pipeline_from_config(config_path)
    module = manifest["modules"][0]

    assert module["status"] == "complete_tumor_sc_summary_backend"
    assert module["n_cells"] == 3
    assert module["n_malignant_candidates"] == 1


def test_tumor_sc_backend_validated_fixture_is_evidence_not_delivery(tmp_path: Path) -> None:
    input_h5ad = _write_h5ad_fixture(tmp_path)
    config_path = _write_config(tmp_path, input_path=input_h5ad, output_name="validated", analysis_level="validated_backend")

    manifest = run_pipeline_from_config(config_path)
    module = manifest["modules"][0]

    assert module["analysis_level"] == "validated_backend"
    assert module["validation_evidence_allowed"] is True
    assert module["delivery_allowed"] is False
    assert module["non_delivery_reason"] == "validation_evidence_only_not_customer_delivery"


def test_tumor_sc_backend_missing_input_is_non_deliverable(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, input_path=tmp_path / "missing.h5ad", output_name="missing")

    manifest = run_pipeline_from_config(config_path)
    run_dir = Path(manifest["output_dir"])
    module = manifest["modules"][0]

    assert module["status"] == "partial:tumor_sc_inputs_missing"
    assert module["analysis_level"] == "smoke_backend"
    assert module["delivery_allowed"] is False
    assert module["validation_evidence_allowed"] is False
    assert module["skip_reasons"]
    qc_manifest = json.loads((run_dir / "results" / "tables" / "tumor_sc" / "module_qc_manifest.json").read_text(encoding="utf-8"))
    assert qc_manifest["delivery_allowed"] is False
    assert qc_manifest["skip_reasons"]
