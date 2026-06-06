from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ultimate.scrna_velocity_backend import has_scrna_velocity_backend_config, run_scrna_velocity_backend


def _write_h5ad_without_velocity(path: Path) -> None:
    ad = pytest.importorskip("anndata")
    from scipy import sparse

    matrix = sparse.csr_matrix(np.array([[1, 0, 2], [0, 3, 1], [2, 1, 0]], dtype=np.float32))
    adata = ad.AnnData(
        X=matrix,
        obs=pd.DataFrame(index=["cell1", "cell2", "cell3"]),
        var=pd.DataFrame(index=["GeneA", "GeneB", "GeneC"]),
    )
    adata.write_h5ad(path)


def test_scrna_velocity_config_detection(tmp_path: Path) -> None:
    input_path = tmp_path / "velocity.h5ad"
    config = {
        "_config_path": str(tmp_path / "project.yaml"),
        "modules": {"scrna": {"enabled": True, "velocity": {"enabled": True, "input_h5ad": str(input_path)}}},
    }

    assert has_scrna_velocity_backend_config(config) is True


def test_scrna_velocity_missing_input_is_guarded(tmp_path: Path) -> None:
    config = {
        "_config_path": str(tmp_path / "project.yaml"),
        "project": {"name": "velocity_missing_input", "output_dir": str(tmp_path / "run")},
        "modules": {
            "scrna": {
                "enabled": True,
                "analysis_level": "validated_backend",
                "velocity": {"enabled": True, "input_h5ad": str(tmp_path / "missing.h5ad")},
            }
        },
    }

    manifest = run_scrna_velocity_backend(config=config, output_dir=tmp_path / "run", samples=pd.DataFrame())

    assert manifest["status"].startswith("partial")
    assert manifest["analysis_level"] == "smoke_backend"
    assert manifest["delivery_allowed"] is False
    assert manifest["validation_evidence_allowed"] is False
    assert "missing_velocity_input_path" in ";".join(manifest["skip_reasons"])
    assert Path(manifest["artifacts"]["tables"]["velocity_summary"]).exists()
    assert Path(manifest["artifacts"]["figures"]["velocity_embedding"]).exists()


def test_scrna_velocity_requires_spliced_layers_or_dependency(tmp_path: Path) -> None:
    h5ad = tmp_path / "plain.h5ad"
    _write_h5ad_without_velocity(h5ad)
    config = {
        "_config_path": str(tmp_path / "project.yaml"),
        "project": {"name": "velocity_plain_input", "output_dir": str(tmp_path / "run")},
        "modules": {
            "scrna": {
                "enabled": True,
                "analysis_level": "validated_backend",
                "velocity": {"enabled": True, "input_h5ad": str(h5ad), "public_dataset": True},
            }
        },
    }

    manifest = run_scrna_velocity_backend(config=config, output_dir=tmp_path / "run", samples=pd.DataFrame())

    assert manifest["status"].startswith("partial")
    assert manifest["delivery_allowed"] is False
    assert manifest["backend_id"] == "scrna.velocity.scvelo"
    reason_text = ";".join(manifest["skip_reasons"])
    assert "dependency_missing:scvelo" in reason_text or "missing_velocity_layers" in reason_text
    module_manifest = json.loads((tmp_path / "run" / "results" / "tables" / "scrna" / "velocity_backend_manifest.json").read_text())
    assert module_manifest["is_stub"] is True
