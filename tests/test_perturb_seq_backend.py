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
    path = tmp_path / "perturb_fixture.h5ad"
    string_dtype = h5py.string_dtype(encoding="utf-8")
    with h5py.File(path, "w") as handle:
        obs = handle.create_group("obs")
        obs.create_dataset("cell_barcode", data=np.array(["cell1", "cell2", "cell3", "cell4", "cell5"], dtype=object), dtype=string_dtype)
        perturb = obs.create_group("perturbation")
        perturb.create_dataset("categories", data=np.array(["control", "KRAS_g1", "TP53_g1"], dtype=object), dtype=string_dtype)
        perturb.create_dataset("codes", data=np.array([0, 1, 1, 2, 0], dtype="i4"))
        perturb_type = obs.create_group("perturbation_type")
        perturb_type.create_dataset("categories", data=np.array(["control", "targeting"], dtype=object), dtype=string_dtype)
        perturb_type.create_dataset("codes", data=np.array([0, 1, 1, 1, 0], dtype="i4"))
        obs.create_dataset("ncounts", data=np.array([100, 140, 150, 90, 110], dtype="f8"))
        obs.create_dataset("ngenes", data=np.array([45, 50, 52, 38, 46], dtype="f8"))
        var = handle.create_group("var")
        var.create_dataset("index", data=np.array(["GeneA", "GeneB", "GeneC"], dtype=object), dtype=string_dtype)
    return path


def _write_assignment_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "guide_assignment.tsv"
    path.write_text(
        "\n".join(
            [
                "cell_id\tguide_id\tperturbation_type\tncounts\tngenes",
                "cell1\tcontrol\tcontrol\t100\t50",
                "cell2\tKRAS_g1\ttargeting\t140\t60",
                "cell3\tTP53_g1\ttargeting\t120\t55",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _write_config(tmp_path: Path, *, input_path: Path, key: str = "input_h5ad", output_name: str = "run") -> Path:
    config_path = tmp_path / f"{output_name}.yaml"
    dump_yaml(
        {
            "project": {
                "name": f"perturb_seq_{output_name}",
                "organism": "human",
                "output_dir": str(tmp_path / output_name),
                "server_root": str(tmp_path),
                "run_mode": "interactive",
            },
            "samples": {"items": [{"sample_id": "S1", "condition": "validation", "input_path": str(input_path)}]},
            "modules": {
                "perturb_seq": {
                    "enabled": True,
                    "preset": "standard",
                    key: str(input_path),
                    "raw": {"enabled": False, "input_type": "h5ad" if input_path.suffix == ".h5ad" else "guide_assignment_table"},
                }
            },
        },
        config_path,
    )
    return config_path


def test_perturb_seq_backend_generates_design_ready_outputs(tmp_path: Path) -> None:
    input_h5ad = _write_h5ad_fixture(tmp_path)
    config_path = _write_config(tmp_path, input_path=input_h5ad)

    manifest = run_pipeline_from_config(config_path)
    run_dir = Path(manifest["output_dir"])
    module = manifest["modules"][0]

    assert module["module"] == "perturb_seq"
    assert module["status"] == "complete_perturb_seq_guide_backend"
    assert module["backend_id"] == "perturb_seq.default.guide_assignment_mvp"
    assert module["analysis_level"] == "smoke_backend"
    assert module["delivery_allowed"] is False
    for key in ("guide_qc", "guide_assignment", "perturbation_summary", "perturbation_expression_effect", "pseudobulk_by_perturbation", "target_response"):
        path = Path(module["artifacts"]["tables"][key])
        assert path.exists() and path.stat().st_size > 0, key
    assert Path(module["artifacts"]["figures"]["guide_distribution"]).exists()
    assert Path(module["artifacts"]["figures"]["perturbation_umap_placeholder"]).exists()
    assert Path(module["artifacts"]["objects"]["mvp_object"]).name == "perturb_seq_mvp_object.rds"

    assignment = pd.read_csv(run_dir / "results" / "tables" / "perturb_seq" / "guide_assignment.tsv", sep="\t")
    assert {"control", "targeting"}.issubset(set(assignment["assignment_class"]))
    pseudobulk = pd.read_csv(run_dir / "results" / "tables" / "perturb_seq" / "pseudobulk_by_perturbation.tsv", sep="\t")
    assert "ready_for_expression_matrix_backend" in set(pseudobulk["design_ready_status"])
    methods = (run_dir / "reports" / "perturb_seq" / "methods.md").read_text(encoding="utf-8")
    assert "analysis_level" in methods
    assert "perturbation effect 不能自动写成直接机制" in methods


def test_perturb_seq_backend_reads_assignment_table(tmp_path: Path) -> None:
    table = _write_assignment_fixture(tmp_path)
    config_path = _write_config(tmp_path, input_path=table, key="guide_assignment_table", output_name="table")

    manifest = run_pipeline_from_config(config_path)
    module = manifest["modules"][0]

    assert module["status"] == "complete_perturb_seq_guide_backend"
    assert module["n_cells"] == 3
    assert module["n_guides"] == 3


def test_perturb_seq_backend_missing_input_is_non_deliverable(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, input_path=tmp_path / "missing.h5ad", output_name="missing")

    manifest = run_pipeline_from_config(config_path)
    run_dir = Path(manifest["output_dir"])
    module = manifest["modules"][0]

    assert module["status"] == "partial:perturb_seq_inputs_missing"
    assert module["analysis_level"] == "smoke_backend"
    assert module["delivery_allowed"] is False
    assert module["validation_evidence_allowed"] is False
    assert module["skip_reasons"]
    qc_manifest = json.loads((run_dir / "results" / "tables" / "perturb_seq" / "module_qc_manifest.json").read_text(encoding="utf-8"))
    assert qc_manifest["delivery_allowed"] is False
    assert qc_manifest["skip_reasons"]
