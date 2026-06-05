from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

h5py = pytest.importorskip("h5py")


TOOLS_DIR = Path(__file__).parents[1] / "01_tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from validate_perturb_seq_demo import run_public_h5ad_validation


def test_perturb_seq_public_h5ad_validation(tmp_path: Path) -> None:
    input_h5ad = tmp_path / "adamson_fixture.h5ad"
    string_dtype = h5py.string_dtype(encoding="utf-8")
    with h5py.File(input_h5ad, "w") as handle:
        obs = handle.create_group("obs")
        obs.create_dataset("cell_barcode", data=np.array(["cell1", "cell2", "cell3", "cell4", "cell5"], dtype=object), dtype=string_dtype)
        perturb = obs.create_group("perturbation")
        perturb.create_dataset("categories", data=np.array(["control", "KRAS", "TP53"], dtype=object), dtype=string_dtype)
        perturb.create_dataset("codes", data=np.array([0, 1, 1, 2, 0], dtype="i4"))
        perturb_type = obs.create_group("perturbation_type")
        perturb_type.create_dataset("categories", data=np.array(["control", "targeting"], dtype=object), dtype=string_dtype)
        perturb_type.create_dataset("codes", data=np.array([0, 1, 1, 1, 0], dtype="i4"))
        obs.create_dataset("ncounts", data=np.array([100, 140, 150, 90, 110], dtype="f8"))
        obs.create_dataset("ngenes", data=np.array([45, 50, 52, 38, 46], dtype="f8"))
        var = handle.create_group("var")
        var.create_dataset("index", data=np.array(["GeneA", "GeneB", "GeneC"], dtype=object), dtype=string_dtype)

    manifest = run_public_h5ad_validation(input_h5ad, tmp_path / "out", source_url="https://exampledata.scverse.org/pertpy/adamson_2016_pilot.h5ad")

    assert manifest["analysis_level"] == "validated_backend"
    assert manifest["validation_evidence_allowed"] is True
    assert manifest["delivery_allowed"] is False
    assert manifest["is_demo"] is False
    assert manifest["is_stub"] is False
    assert manifest["dataset"] == "pertpy Adamson 2016 pilot Perturb-seq fixture"
    assert manifest["n_cells"] == 5
    assert manifest["n_features"] == 3
    assert (tmp_path / "out" / "results" / "tables" / "guide_assignments.tsv").exists()
    assert (tmp_path / "out" / "results" / "tables" / "pseudobulk_by_perturbation.tsv").exists()
    assert (tmp_path / "out" / "results" / "tables" / "perturbation_model_handoff.tsv").exists()
    payload = json.loads((tmp_path / "out" / "run_manifest.json").read_text(encoding="utf-8"))
    assert payload["validation_evidence_allowed"] is True
