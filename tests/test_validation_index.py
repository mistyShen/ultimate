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
        "analysis_level": "validated_backend",
        "is_demo": False,
        "is_stub": False,
        "delivery_allowed": False,
        "validation_evidence_allowed": True,
        "non_delivery_reason": "validation_evidence_only_not_customer_delivery",
        "slurm_job_id": "123",
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
    text = Path(result["validation_index_tsv"]).read_text(encoding="utf-8")
    assert "guard_status" in text
    assert "validated_backend" in text
    assert "123" in text


def test_cli_validation_index(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    run = root / "validations" / "demo_run"
    run.mkdir(parents=True)
    (run / "run_manifest.json").write_text(json.dumps({"status": "ready"}), encoding="utf-8")

    result = CliRunner().invoke(main, ["validation-index", "--root", str(root), "--output-dir", str(tmp_path / "index")])

    assert result.exit_code == 0, result.output
    assert "validation_index_tsv" in result.output
    text = (tmp_path / "index" / "validation_index.tsv").read_text(encoding="utf-8")
    assert "missing_guard_fields" in text


def test_validation_index_includes_nested_validation_roots(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    for run in (
        root / "validations" / "direct_run",
        root / "validation_runs" / "scrna_mvp_validation" / "h5ad",
        root / "validations" / "bulk_demo_python" / "project" / "runs" / "bulk_demo",
    ):
        run.mkdir(parents=True)
        (run / "run_manifest.json").write_text(
            json.dumps(
                {
                    "status": "ready",
                    "analysis_level": "validated_backend",
                    "is_demo": False,
                    "is_stub": False,
                    "delivery_allowed": False,
                    "validation_evidence_allowed": True,
                    "non_delivery_reason": "validation_evidence_only_not_customer_delivery",
                }
            ),
            encoding="utf-8",
        )

    result = build_validation_index(root=root, output_dir=tmp_path / "index")

    assert result["n_runs"] == 3
    text = (tmp_path / "index" / "validation_index.tsv").read_text(encoding="utf-8")
    assert "direct_run" in text
    assert "h5ad" in text
    assert "bulk_demo" in text
