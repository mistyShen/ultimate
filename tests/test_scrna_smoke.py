from __future__ import annotations

import json
import importlib.util
from pathlib import Path

import pytest
from click.testing import CliRunner

from ultimate.cli import main
from ultimate.scrna_smoke import create_demo_inputs


def test_create_scrna_demo_inputs(tmp_path: Path) -> None:
    pytest.importorskip("h5py")
    pytest.importorskip("scipy")
    manifest = create_demo_inputs(tmp_path / "demo", n_cells=16, n_genes=32, seed=3)

    assert Path(manifest["tenx_h5"]).exists()
    assert (Path(manifest["tenx_mtx"]) / "matrix.mtx.gz").exists()
    assert (Path(manifest["tenx_mtx"]) / "barcodes.tsv.gz").exists()
    assert (Path(manifest["tenx_mtx"]) / "features.tsv.gz").exists()
    assert Path(manifest["samplesheet"]).exists()
    assert manifest["n_cells"] == 16
    assert manifest["n_genes"] >= 32


def test_create_scrna_demo_inputs_cli(tmp_path: Path) -> None:
    if importlib.util.find_spec("h5py") is None or importlib.util.find_spec("scipy") is None:
        pytest.skip("h5py and scipy are required to materialize 10x demo files")
    runner = CliRunner()
    result = runner.invoke(main, ["create-scrna-demo-inputs", "--output-dir", str(tmp_path / "demo"), "--n-cells", "10", "--n-genes", "30"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert Path(payload["tenx_h5"]).exists()
    assert (Path(payload["tenx_mtx"]) / "matrix.mtx.gz").exists()
