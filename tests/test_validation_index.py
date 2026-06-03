from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from ultimate.cli import main
from ultimate.validation_index import build_validation_index


def test_build_validation_index_reads_run_manifests(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    run = root / "validations" / "demo_run"
    (run / "reports").mkdir(parents=True)
    (run / "reports" / "report.html").write_text("<html></html>", encoding="utf-8")
    manifest = {
        "status": "ready",
        "input_h5": "/data/input.h5",
        "n_cells": 12,
        "figures": ["a.png", "b.png"],
        "tables": ["a.tsv"],
        "objects": {"h5ad": "obj.h5ad"},
    }
    (run / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = build_validation_index(root=root, output_dir=tmp_path / "index")

    assert result["n_runs"] == 1
    assert Path(result["validation_index_tsv"]).exists()
    assert Path(result["validation_index_json"]).exists()
    assert Path(result["report_html"]).exists()


def test_cli_validation_index(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    run = root / "validations" / "demo_run"
    run.mkdir(parents=True)
    (run / "run_manifest.json").write_text(json.dumps({"status": "ready"}), encoding="utf-8")

    result = CliRunner().invoke(main, ["validation-index", "--root", str(root), "--output-dir", str(tmp_path / "index")])

    assert result.exit_code == 0, result.output
    assert "validation_index_tsv" in result.output
