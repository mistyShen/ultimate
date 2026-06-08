from __future__ import annotations

import json
import importlib.util
from pathlib import Path

import pandas as pd
import pytest
from click.testing import CliRunner

import ultimate.scrna_smoke as scrna_smoke
from ultimate.cli import main
from ultimate.config import dump_yaml
from ultimate.pipeline import run_pipeline_from_config
from ultimate.scrna_smoke import create_demo_inputs, run_scrna_validation
from ultimate.scrna_velocity_backend import has_scrna_velocity_backend_config


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


def test_validate_scrna_h5ad_outputs_scrna_mvp_artifacts(tmp_path: Path) -> None:
    _require_scrna_runtime()
    demo = create_demo_inputs(tmp_path / "demo_h5ad", n_cells=48, n_genes=60, seed=11)
    manifest = run_scrna_validation(
        input_path=Path(demo["h5ad"]),
        input_type="h5ad",
        output_dir=tmp_path / "run_h5ad",
        samplesheet=Path(demo["samplesheet"]),
        max_cells=48,
    )
    _assert_mvp_outputs(manifest)
    assert manifest["analysis_level"] == "demo_result"
    assert manifest["delivery_allowed"] is False
    assert manifest["non_delivery_reason"] == "generated_demo_data_not_customer_delivery"


def test_validate_scrna_10x_h5_outputs_scrna_mvp_artifacts(tmp_path: Path) -> None:
    _require_scrna_runtime()
    demo = create_demo_inputs(tmp_path / "demo_h5", n_cells=48, n_genes=60, seed=12)
    manifest = run_scrna_validation(
        input_path=Path(demo["tenx_h5"]),
        input_type="10x_h5",
        output_dir=tmp_path / "run_10x_h5",
        samplesheet=Path(demo["samplesheet"]),
        max_cells=48,
    )
    _assert_mvp_outputs(manifest)
    assert manifest["analysis_level"] == "demo_result"


def test_validate_scrna_10x_mtx_outputs_scrna_mvp_artifacts(tmp_path: Path) -> None:
    _require_scrna_runtime()
    demo = create_demo_inputs(tmp_path / "demo_mtx", n_cells=48, n_genes=60, seed=13)
    manifest = run_scrna_validation(
        input_path=Path(demo["tenx_mtx"]),
        input_type="10x_mtx",
        output_dir=tmp_path / "run_10x_mtx",
        samplesheet=Path(demo["samplesheet"]),
        max_cells=48,
    )
    _assert_mvp_outputs(manifest)
    assert manifest["analysis_level"] == "demo_result"


def test_validate_scrna_cli_refuses_demo_as_validated_backend(tmp_path: Path) -> None:
    _require_scrna_runtime()
    demo = create_demo_inputs(tmp_path / "demo_cli_guard", n_cells=32, n_genes=50, seed=14)
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "validate-scrna",
            "--input-path",
            str(demo["tenx_mtx"]),
            "--input-type",
            "10x_mtx",
            "--output-dir",
            str(tmp_path / "bad"),
            "--analysis-level",
            "validated_backend",
        ],
    )
    assert result.exit_code != 0
    assert "cannot be labeled as validated_backend" in result.output


def test_validate_scrna_cli_rejects_bad_input_type(tmp_path: Path) -> None:
    runner = CliRunner()
    path = tmp_path / "input.h5ad"
    path.write_text("not used", encoding="utf-8")
    result = runner.invoke(
        main,
        ["validate-scrna", "--input-path", str(path), "--input-type", "bad", "--output-dir", str(tmp_path / "out")],
    )
    assert result.exit_code != 0
    assert "Invalid value for '--input-type'" in result.output


def test_validate_scrna_cli_rejects_missing_input_path(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["validate-scrna", "--input-path", str(tmp_path / "missing.h5ad"), "--input-type", "h5ad", "--output-dir", str(tmp_path / "out")],
    )
    assert result.exit_code != 0
    assert "does not exist" in result.output


def test_unified_run_scrna_preset_uses_scrna_mvp_backend(tmp_path: Path) -> None:
    _require_scrna_runtime()
    demo = create_demo_inputs(tmp_path / "demo", n_cells=36, n_genes=45, seed=9)
    if not demo.get("h5ad"):
        pytest.skip("anndata is required to create h5ad demo input")
    config_path = tmp_path / "project.yaml"
    dump_yaml(
        {
            "project": {
                "name": "scrna_communication_unified",
                "organism": "human",
                "output_dir": str(tmp_path / "run"),
                "server_root": str(tmp_path),
                "run_mode": "interactive",
            },
            "samples": {"items": [{"sample_id": "S1", "condition": "control", "input_path": demo["h5ad"]}]},
            "modules": {
                "scrna": {
                    "enabled": True,
                    "preset": "communication",
                    "input_h5ad": demo["h5ad"],
                    "samplesheet": demo["samplesheet"],
                    "max_cells": 30,
                    "backends": {"communication": "liana,cellchat,nichenet"},
                }
            },
        },
        config_path,
    )

    manifest = run_pipeline_from_config(config_path)
    run_dir = Path(manifest["output_dir"])
    scrna = manifest["modules"][0]
    active_ids = {row["backend_id"] for row in scrna["backend_plan"]["active_backends"]}

    assert scrna["module"] == "scrna"
    assert scrna["backend_id"] == "scrna.mvp.validate_scrna"
    assert "scrna.communication.cellchat_optional" in active_ids
    assert "scrna.communication.liana" in active_ids
    assert "scrna.communication.nichenet_optional" in active_ids
    assert any(row["backend_id"] == "scrna.communication.cellchat_optional" for row in scrna["backend_execution_rows"])
    assert any(row["backend_id"] == "scrna.communication.nichenet_optional" for row in scrna["backend_execution_rows"])
    assert (run_dir / "objects" / "scrna_mvp.h5ad").exists()
    assert (run_dir / "results" / "tables" / "backend_execution_manifest.json").exists()
    assert (run_dir / "results" / "tables" / "advanced_backend_execution_manifest.json").exists()
    advanced = json.loads((run_dir / "results" / "tables" / "advanced_backend_execution_manifest.json").read_text(encoding="utf-8"))
    cellchat_rows = [row for row in advanced["rows"] if row["backend_id"] == "scrna.communication.cellchat_optional"]
    assert cellchat_rows and cellchat_rows[0]["execution_status"] != "registered_active"
    nichenet_rows = [row for row in advanced["rows"] if row["backend_id"] == "scrna.communication.nichenet_optional"]
    assert nichenet_rows and nichenet_rows[0]["execution_status"] != "registered_active"
    methods = (run_dir / "reports" / "methods.md").read_text(encoding="utf-8")
    assert "Advanced Backend Execution" in methods
    assert "scrna.communication.cellchat_optional" in methods
    assert "scrna.communication.nichenet_optional" in methods


def test_scrna_nichenet_backend_runs_with_reviewed_labels_and_resource(tmp_path: Path) -> None:
    _require_scrna_runtime()
    demo = create_demo_inputs(tmp_path / "demo_nichenet", n_cells=60, n_genes=70, seed=22)
    samples = pd.read_csv(demo["samplesheet"], sep="\t")
    labels = ["reviewed_T_like", "reviewed_B_like", "reviewed_myeloid_like"]
    samples["reviewed_cell_type"] = [labels[idx % len(labels)] for idx in range(len(samples))]
    samplesheet = tmp_path / "reviewed_labels.tsv"
    samples.to_csv(samplesheet, sep="\t", index=False)
    resource = tmp_path / "nichenet_resource.tsv"
    pd.DataFrame(
        [
            {"ligand": "IL6", "target": "MKI67", "weight": 0.9},
            {"ligand": "IL6", "target": "TOP2A", "weight": 0.8},
            {"ligand": "VEGFA", "target": "LDHA", "weight": 0.7},
            {"ligand": "VEGFA", "target": "VIM", "weight": 0.6},
        ]
    ).to_csv(resource, sep="\t", index=False)

    manifest = run_scrna_validation(
        input_path=Path(demo["tenx_mtx"]),
        input_type="10x_mtx",
        output_dir=tmp_path / "run_nichenet",
        samplesheet=samplesheet,
        max_cells=60,
        nichenet_resource=resource,
    )

    row = next(row for row in manifest["backend_status"] if row["backend_id"] == "scrna.communication.nichenet_optional")
    assert row["status"] == "ready"
    activity = pd.read_csv(tmp_path / "run_nichenet" / "results" / "tables" / "nichenet_ligand_activity.tsv", sep="\t")
    assert {"ligand", "activity_score", "warning"}.issubset(activity.columns)
    assert not activity.empty
    backend_manifest = json.loads((tmp_path / "run_nichenet" / "results" / "tables" / "nichenet_backend_manifest.json").read_text(encoding="utf-8"))
    assert backend_manifest["delivery_allowed"] is False


def test_cellchat_r_script_uses_raw_expression_for_small_validation_sets() -> None:
    source = (Path(__file__).parents[1] / "src" / "ultimate" / "scrna_smoke.py").read_text(encoding="utf-8")

    assert "computeCommunProb(cellchat, raw.use = TRUE, population.size = TRUE)" in source


def test_scrna_communication_input_does_not_auto_select_velocity() -> None:
    config = {
        "modules": {
            "scrna": {
                "enabled": True,
                "preset": "communication",
                "input_path": "/shared/example/pbmc3k",
                "input_type": "10x_mtx",
                "backends": {"communication": "liana,cellchat"},
            }
        }
    }

    assert has_scrna_velocity_backend_config(config) is False


def test_scrna_trajectory_input_selects_velocity() -> None:
    config = {
        "modules": {
            "scrna": {
                "enabled": True,
                "preset": "trajectory",
                "input_h5ad": "/shared/example/velocity.h5ad",
            }
        }
    }

    assert has_scrna_velocity_backend_config(config) is True


def test_scrna_mvp_slurm_uses_explicit_celltypist_reference_cache() -> None:
    script = (Path(__file__).parents[1] / "slurm" / "scrna_mvp_validation.sbatch").read_text(encoding="utf-8")

    assert "CELLTYPIST_FOLDER" in script
    assert "references/celltypist" in script
    assert "Immune_All_Low.pkl" in script
    assert "--celltypist-model" in script
    assert "export CELLTYPIST_FOLDER" in script


def test_scrna_backend_rows_record_slurm_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _require_scrna_runtime()
    monkeypatch.setenv("SLURM_JOB_ID", "pytest-123")
    monkeypatch.setenv("SLURM_JOB_NAME", "pytest_scrna")
    demo = create_demo_inputs(tmp_path / "demo_slurm_context", n_cells=32, n_genes=50, seed=15)

    manifest = run_scrna_validation(
        input_path=Path(demo["h5ad"]),
        input_type="h5ad",
        output_dir=tmp_path / "run_slurm_context",
        samplesheet=Path(demo["samplesheet"]),
        max_cells=32,
    )

    for row in manifest["backend_status"]:
        assert row["backend_slurm_job_id"] == "pytest-123"
        assert row["backend_slurm_job_name"] == "pytest_scrna"


def test_pseudobulk_de_backend_executes_when_r_backend_available(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tables = tmp_path / "results" / "tables"
    tables.mkdir(parents=True)
    counts = pd.DataFrame(
        {
            "feature_id": ["GeneA", "GeneB"],
            "S1__control__cluster0": [10, 20],
            "S2__control__cluster0": [12, 18],
            "S3__case__cluster0": [30, 5],
            "S4__case__cluster0": [28, 6],
        }
    )
    design = pd.DataFrame(
        {
            "pseudobulk_id": ["S1__control__cluster0", "S2__control__cluster0", "S3__case__cluster0", "S4__case__cluster0"],
            "sample_id": ["S1", "S2", "S3", "S4"],
            "condition": ["control", "control", "case", "case"],
            "cluster": ["0", "0", "0", "0"],
        }
    )
    counts.to_csv(tables / "pseudobulk_counts.tsv", sep="\t", index=False)
    design.to_csv(tables / "pseudobulk_design.tsv", sep="\t", index=False)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_rscript = fake_bin / "Rscript"
    fake_rscript.write_text(
        """#!/usr/bin/env python3
import json
import sys
from pathlib import Path
if "-e" in sys.argv:
    print("DESeq2\\nedgeR\\njsonlite")
    raise SystemExit(0)
args = sys.argv[1:]
tables = Path(args[args.index("--tables-dir") + 1])
figures = tables.parent / "figures"
objects = tables.parent.parent / "objects"
figures.mkdir(parents=True, exist_ok=True)
objects.mkdir(parents=True, exist_ok=True)
(tables / "pseudobulk_de_results.tsv").write_text("feature_id\\tcluster\\tlog2FoldChange\\tpvalue\\tpadj\\tbackend_id\\tbackend_method\\tanalysis_level\\nGeneA\\t0\\t1.5\\t0.01\\t0.05\\tscrna.pseudobulk.deseq2_edger\\tDESeq2\\tvalidated_backend\\n")
(tables / "pseudobulk_de_backend_status.tsv").write_text("backend_id\\tcluster\\tstatus\\tanalysis_level\\tbackend_method\\nscrna.pseudobulk.deseq2_edger\\t0\\tready\\tvalidated_backend\\tDESeq2\\n")
(tables / "pseudobulk_de_backend_versions.tsv").write_text("package\\tversion\\nDESeq2\\t1.0\\nedgeR\\t1.0\\njsonlite\\t1.0\\n")
(tables / "pseudobulk_de_backend_manifest.json").write_text(json.dumps({"backend_id":"scrna.pseudobulk.deseq2_edger","status":"ready","analysis_level":"validated_backend"}))
(figures / "pseudobulk_de_volcano.png").write_text("png")
(objects / "scrna_pseudobulk_de_backend.rds").write_text("rds")
""",
        encoding="utf-8",
    )
    fake_rscript.chmod(0o755)
    import os

    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}")

    row, artifacts = scrna_smoke._run_pseudobulk_de_backend(tables=tables, analysis_level="validated_backend")

    assert row["status"] == "ready"
    assert Path(artifacts["pseudobulk_de_backend_manifest"]).exists()
    assert Path(artifacts["pseudobulk_de_volcano"]).exists()
    assert Path(artifacts["pseudobulk_de_rds"]).exists()


def _require_scrna_runtime() -> None:
    pytest.importorskip("scanpy")
    pytest.importorskip("anndata")
    pytest.importorskip("h5py")
    pytest.importorskip("scipy")


def _assert_mvp_outputs(manifest: dict) -> None:
    run_dir = Path(manifest["output_dir"])
    assert manifest["status"] == "ready"
    assert manifest["objects"]["h5ad"].endswith("objects/scrna_mvp.h5ad")
    assert Path(manifest["objects"]["h5ad"]).exists()
    assert not (run_dir / "objects" / "scrna_smoke_validated.h5ad").exists()
    assert manifest["cell_type_annotation_status"] == "placeholder_not_cell_type"
    assert manifest["pseudobulk_de_status"] == "design_ready_matrix_only"
    assert "backend_execution_manifest" in manifest
    assert "backend_execution_status" in manifest
    assert Path(manifest["backend_execution_manifest"]).exists()
    handoff_text = (run_dir / "results/tables/pseudobulk_deseq2_edgeR_handoff.R").read_text(encoding="utf-8")
    assert "Guarded backend" in handoff_text
    assert "not a formal DE result" in handoff_text
    assert "TODO" not in handoff_text
    backend_ids = {row["backend_id"] for row in manifest["backend_status"]}
    assert {
        "scrna.qc.scrublet",
        "scrna.annotation.celltypist",
        "scrna.functional.decoupler_gseapy",
        "scrna.communication.liana",
        "scrna.communication.cellchat_optional",
        "scrna.communication.nichenet_optional",
        "scrna.pseudobulk.deseq2_edger",
    }.issubset(backend_ids)
    assert Path(manifest["raw_qc_manifest"]).exists()
    for relative in [
        "results/tables/qc_metrics.tsv",
        "results/tables/marker_genes.tsv",
        "results/tables/de_condition.tsv",
        "results/tables/cell_type_composition.tsv",
        "results/tables/basic_enrichment.tsv",
        "results/tables/cell_type_annotation_placeholder.tsv",
        "results/tables/pseudobulk_counts.tsv",
        "results/tables/pseudobulk_design.tsv",
        "results/tables/pseudobulk_feature_metadata.tsv",
        "results/tables/backend_execution.tsv",
        "results/tables/backend_execution_manifest.json",
        "results/tables/doublet_scores.tsv",
        "results/tables/doublet_summary.tsv",
        "results/tables/celltypist_annotation.tsv",
        "results/tables/annotation_confidence.tsv",
        "results/tables/annotation_warning.tsv",
        "results/tables/signature_scores.tsv",
        "results/tables/pathway_activity.tsv",
        "results/tables/tf_activity.tsv",
        "results/tables/functional_backend_status.tsv",
        "results/tables/liana_interactions.tsv",
        "results/tables/communication_network.tsv",
        "results/tables/communication_backend_status.tsv",
        "results/tables/cellchat_interactions.tsv",
        "results/tables/cellchat_pathway_summary.tsv",
        "results/tables/cellchat_backend_status.tsv",
        "results/tables/cellchat_backend_manifest.json",
        "results/tables/nichenet_ligand_activity.tsv",
        "results/tables/nichenet_ligand_target_links.tsv",
        "results/tables/nichenet_backend_status.tsv",
        "results/tables/nichenet_backend_manifest.json",
        "results/tables/pseudobulk_de_backend_status.tsv",
        "results/tables/pseudobulk_de_results.tsv",
        "results/tables/pseudobulk_deseq2_edgeR_handoff.R",
        "results/figures/qc_violin.png",
        "results/figures/pca_condition.png",
        "results/figures/umap_cluster_condition.png",
        "results/figures/communication_dotplot.png",
        "results/figures/cellchat_network.png",
        "results/figures/nichenet_activity.png",
        "reports/report.md",
        "reports/report.html",
        "run_manifest.json",
    ]:
        path = run_dir / relative
        assert path.exists(), relative
        assert path.stat().st_size > 0, relative
    report = (run_dir / "reports" / "report.md").read_text(encoding="utf-8")
    assert "analysis_level" in report
    assert "delivery_allowed" in report
    assert "backend 执行摘要" in report
    assert "cluster placeholder" in report
    assert "LIANA" in report
    manifest_from_disk = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest_from_disk["analysis_level"] == manifest["analysis_level"]
    annotation = Path(run_dir / "results/tables/cell_type_annotation_placeholder.tsv").read_text(encoding="utf-8")
    assert "placeholder_not_cell_type" in annotation
    design = Path(run_dir / "results/tables/pseudobulk_design.tsv").read_text(encoding="utf-8")
    assert "analysis_level" in design
