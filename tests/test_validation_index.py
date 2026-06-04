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


def test_validation_index_adds_module_and_order_readiness_fields(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    run = root / "validations" / "scrna_public"
    (run / "reports").mkdir(parents=True)
    (run / "logs").mkdir(parents=True)
    (run / "results" / "figures").mkdir(parents=True)
    (run / "results" / "tables").mkdir(parents=True)
    (run / "objects").mkdir(parents=True)
    (run / "reports" / "report.html").write_text("<html></html>", encoding="utf-8")
    (run / "reports" / "methods.md").write_text("methods", encoding="utf-8")
    (run / "logs" / "run.log").write_text("ok", encoding="utf-8")
    (run / "results" / "figures" / "umap.png").write_text("png", encoding="utf-8")
    (run / "results" / "tables" / "qc.tsv").write_text("a\n1\n", encoding="utf-8")
    (run / "objects" / "scrna_mvp.h5ad").write_text("object", encoding="utf-8")
    (run / "run_manifest.json").write_text(
        json.dumps(
            {
                "module": "scrna",
                "status": "ready",
                "analysis_level": "validated_backend",
                "is_demo": False,
                "is_stub": False,
                "delivery_allowed": False,
                "validation_evidence_allowed": True,
                "non_delivery_reason": "validation_evidence_only_not_customer_delivery",
                "slurm_job_id": "777",
                "figures": ["results/figures/umap.png"],
                "tables": ["results/tables/qc.tsv"],
                "objects": {"h5ad": "objects/scrna_mvp.h5ad"},
            }
        ),
        encoding="utf-8",
    )

    result = build_validation_index(root=root, output_dir=tmp_path / "index")

    text = Path(result["validation_index_tsv"]).read_text(encoding="utf-8")
    assert "module" in text
    assert "evidence_status" in text
    assert "order_readiness_status" in text
    assert "missing_or_gap" in text
    row = next(line for line in text.splitlines() if line.startswith("scrna_public\t"))
    assert "scrna" in row
    assert "ready_real_evidence" in row
    assert "ready_for_validation_evidence" in row
    assert result["summary"]["ready_for_validation_evidence"] == 1
    assert result["summary"]["module_counts"]["scrna"] == 1


def test_validation_index_flags_delivery_without_approval(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    run = root / "validations" / "customer_like_run"
    (run / "reports").mkdir(parents=True)
    (run / "reports" / "report.html").write_text("<html></html>", encoding="utf-8")
    (run / "reports" / "methods.md").write_text("methods", encoding="utf-8")
    (run / "run_manifest.json").write_text(
        json.dumps(
            {
                "module": "rnaseq",
                "status": "ready",
                "analysis_level": "production_backend",
                "is_demo": False,
                "is_stub": False,
                "delivery_allowed": True,
                "validation_evidence_allowed": True,
                "non_delivery_reason": "",
            }
        ),
        encoding="utf-8",
    )

    result = build_validation_index(root=root, output_dir=tmp_path / "index")

    text = Path(result["validation_index_tsv"]).read_text(encoding="utf-8")
    row = next(line for line in text.splitlines() if line.startswith("customer_like_run\t"))
    assert "production_backend" in row
    assert "missing" in row
    assert "ready_for_delivery" not in row
    assert "production_approval=missing" in row


def test_validation_index_checks_required_delivery_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    run = root / "validations" / "artifact_gap"
    (run / "reports").mkdir(parents=True)
    (run / "reports" / "report.html").write_text("<html></html>", encoding="utf-8")
    (run / "reports" / "methods.md").write_text("methods", encoding="utf-8")
    (run / "run_manifest.json").write_text(
        json.dumps(
            {
                "module": "vdj",
                "status": "ready",
                "analysis_level": "validated_backend",
                "is_demo": False,
                "is_stub": False,
                "delivery_allowed": False,
                "validation_evidence_allowed": True,
                "non_delivery_reason": "validation_evidence_only_not_customer_delivery",
                "slurm_job_id": "888",
                "figures": ["results/figures/missing.png"],
                "tables": ["results/tables/missing.tsv"],
                "objects": {"h5ad": "objects/missing.h5ad"},
            }
        ),
        encoding="utf-8",
    )

    result = build_validation_index(root=root, output_dir=tmp_path / "index")

    text = Path(result["validation_index_tsv"]).read_text(encoding="utf-8")
    row = next(line for line in text.splitlines() if line.startswith("artifact_gap\t"))
    assert "missing_or_empty_artifacts" in row
    assert "missing_figures:results/figures/missing.png" in row
    assert result["summary"]["artifact_status_counts"]["missing_or_empty_artifacts"] == 1


def test_validation_index_summary_counts_readiness(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    fixtures = {
        "ready_evidence": {
            "status": "ready",
            "analysis_level": "validated_backend",
            "is_demo": False,
            "is_stub": False,
            "delivery_allowed": False,
            "validation_evidence_allowed": True,
            "non_delivery_reason": "validation_evidence_only_not_customer_delivery",
            "slurm_job_id": "1",
        },
        "missing_guard": {"status": "ready"},
        "approval_missing": {
            "status": "ready",
            "analysis_level": "production_backend",
            "is_demo": False,
            "is_stub": False,
            "delivery_allowed": True,
            "validation_evidence_allowed": True,
            "non_delivery_reason": "",
        },
    }
    for name, manifest in fixtures.items():
        run = root / "validations" / name
        (run / "reports").mkdir(parents=True)
        (run / "reports" / "report.html").write_text("<html></html>", encoding="utf-8")
        (run / "reports" / "methods.md").write_text("methods", encoding="utf-8")
        (run / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = build_validation_index(root=root, output_dir=tmp_path / "index")

    assert result["summary"]["guard_status_counts"]["ready"] == 2
    assert result["summary"]["guard_status_counts"]["missing_guard_fields"] == 1
    assert result["summary"]["order_readiness_status_counts"]["ready_for_validation_evidence"] == 1
    assert result["summary"]["order_readiness_status_counts"]["needs_manual_review"] == 1
    assert result["summary"]["order_readiness_status_counts"]["not_ready"] == 1
    summary_text = Path(result["validation_summary_tsv"]).read_text(encoding="utf-8")
    assert "order_readiness_status_counts.ready_for_validation_evidence\t1" in summary_text
