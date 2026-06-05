from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ultimate.config import dump_yaml
from ultimate.pipeline import run_pipeline_from_config


def _write_h5ad_fixture(tmp_path: Path) -> Path:
    ad = pytest.importorskip("anndata")

    rng = np.random.default_rng(7)
    obs = pd.DataFrame(
        {
            "cell_id": [f"existing_cell_{idx}" for idx in range(6)],
            "sample_id": ["S1", "S1", "S2", "S2", "S3", "S3"],
            "patient_name": ["Alice", "Alice", "Bob", "Bob", "Carol", "Carol"],
            "batch": ["b1", "b1", "b2", "b2", "b3", "b3"],
        },
        index=[f"cell_{idx}" for idx in range(6)],
    )
    var = pd.DataFrame(index=[f"GENE_{idx}" for idx in range(5)])
    adata = ad.AnnData(X=rng.poisson(3, size=(6, 5)), obs=obs, var=var)
    path = tmp_path / "input.h5ad"
    adata.write_h5ad(path)
    return path


def _write_config(tmp_path: Path, *, h5ad: Path, output_name: str = "run") -> Path:
    config_path = tmp_path / f"{output_name}.yaml"
    dump_yaml(
        {
            "project": {
                "name": f"method_tools_{output_name}",
                "organism": "human",
                "output_dir": str(tmp_path / output_name),
                "server_root": str(tmp_path),
                "run_mode": "interactive",
            },
            "samples": {"items": [{"sample_id": "S1", "condition": "validation", "input_path": str(h5ad)}]},
            "modules": {
                "method_tools": {
                    "enabled": True,
                    "preset": "publication",
                    "input_h5ad": str(h5ad),
                    "raw": {"enabled": False, "input_type": "object"},
                }
            },
        },
        config_path,
    )
    return config_path


def test_method_tools_backend_generates_delivery_outputs(tmp_path: Path) -> None:
    h5ad = _write_h5ad_fixture(tmp_path)
    config_path = _write_config(tmp_path, h5ad=h5ad)

    manifest = run_pipeline_from_config(config_path)
    run_dir = Path(manifest["output_dir"])
    module = manifest["modules"][0]

    assert module["module"] == "method_tools"
    assert module["status"] == "complete_method_tools_delivery_backend"
    assert module["backend_id"] == "method_tools.default.delivery_manifest_mvp"
    assert module["analysis_level"] == "smoke_backend"
    assert module["delivery_allowed"] is False
    for key in ("figure_index", "table_index", "sensitive_metadata_scan", "cellxgene_compatibility", "delivery_manifest_index", "delivery_manifest_json"):
        path = Path(module["artifacts"]["tables"][key])
        assert path.exists() and path.stat().st_size > 0, key
    assert Path(module["artifacts"]["figures"]["figure_index_overview"]).exists()
    assert Path(module["artifacts"]["objects"]["cellxgene_ready"]).exists()
    assert Path(module["artifacts"]["objects"]["mvp_object"]).name == "cellxgene_ready.h5ad"
    sensitive = pd.read_csv(run_dir / "results" / "tables" / "method_tools" / "sensitive_metadata_scan.tsv", sep="\t")
    row = sensitive.loc[sensitive["metadata_field"] == "patient_name"].iloc[0]
    assert bool(row["sensitive_flag"]) is True
    assert row["privacy_action"] == "review_or_remove_before_public_delivery"
    compatibility = pd.read_csv(run_dir / "results" / "tables" / "method_tools" / "cellxgene_compatibility.tsv", sep="\t")
    assert compatibility.loc[0, "cellxgene_ready_status"] == "ready_h5ad_copy"
    methods = (run_dir / "reports" / "method_tools" / "methods.md").read_text(encoding="utf-8")
    assert "analysis_level" in methods
    assert "交互式浏览器只是展示" in methods


def test_method_tools_backend_missing_input_is_non_deliverable(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, h5ad=tmp_path / "missing.h5ad", output_name="missing")

    manifest = run_pipeline_from_config(config_path)
    run_dir = Path(manifest["output_dir"])
    module = manifest["modules"][0]

    assert module["status"] == "partial:method_tools_inputs_missing"
    assert module["analysis_level"] == "smoke_backend"
    assert module["delivery_allowed"] is False
    assert module["validation_evidence_allowed"] is False
    assert module["skip_reasons"]
    qc_manifest = json.loads((run_dir / "results" / "tables" / "method_tools" / "module_qc_manifest.json").read_text(encoding="utf-8"))
    assert qc_manifest["delivery_allowed"] is False
    assert qc_manifest["skip_reasons"]
