from __future__ import annotations

import json
import importlib.util
from pathlib import Path

import pytest
from click.testing import CliRunner

from ultimate.cli import main
from ultimate.scrna_smoke import create_demo_inputs, run_scrna_validation


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
    backend_ids = {row["backend_id"] for row in manifest["backend_status"]}
    assert {
        "scrna.qc.scrublet",
        "scrna.annotation.celltypist",
        "scrna.functional.decoupler_gseapy",
        "scrna.communication.liana",
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
        "results/tables/pseudobulk_de_backend_status.tsv",
        "results/tables/pseudobulk_de_results.tsv",
        "results/tables/pseudobulk_deseq2_edgeR_handoff.R",
        "results/figures/qc_violin.png",
        "results/figures/pca_condition.png",
        "results/figures/umap_cluster_condition.png",
        "results/figures/communication_dotplot.png",
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
