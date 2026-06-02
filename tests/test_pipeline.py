from __future__ import annotations

from pathlib import Path

from ultimate.demo import init_project
from ultimate.pipeline import run_pipeline_from_config


BULK_MODULES = {"rnaseq", "methylation", "proteomics", "publicdb", "wgcna", "single_gene", "clinical_assoc"}


def test_pipeline_generates_required_artifacts(tmp_path: Path) -> None:
    manifest = init_project("all", tmp_path / "demo_all", demo_data=True)
    run_manifest = run_pipeline_from_config(Path(manifest["config_path"]))
    run_dir = Path(run_manifest["output_dir"])
    assert (run_dir / "run_manifest.json").exists()
    assert (run_dir / "reports" / "report.html").exists()
    assert (run_dir / "reports" / "methods.md").exists()
    assert len(run_manifest["modules"]) >= 13
    for module in run_manifest["modules"]:
        assert Path(module["artifacts"]["figures"]["pca"]).exists()
        assert Path(module["artifacts"]["tables"]["differential_results"]).exists()
        assert Path(module["artifacts"]["objects"]["rds"]).exists()


def test_bulk_modules_use_python_formal_backend(tmp_path: Path) -> None:
    manifest = init_project("all", tmp_path / "bulk_demo", demo_data=True)
    run_manifest = run_pipeline_from_config(Path(manifest["config_path"]))
    modules = {module["module"]: module for module in run_manifest["modules"]}
    for module_name in BULK_MODULES:
        module = modules[module_name]
        assert module["status"] == "complete_python_bulk_backend"
        assert module["backend"]["primary"] == "python"
        assert Path(module["artifacts"]["tables"]["method_summary"]).exists()
        assert Path(module["artifacts"]["tables"]["normalized_matrix"]).exists()
    assert Path(modules["rnaseq"]["artifacts"]["tables"]["enrichment_ready_genes"]).exists()
    assert Path(modules["methylation"]["artifacts"]["tables"]["m_value_matrix"]).exists()
    assert Path(modules["proteomics"]["artifacts"]["tables"]["abundance_qc"]).exists()
    assert Path(modules["publicdb"]["artifacts"]["tables"]["survival_proxy"]).exists()
    assert Path(modules["wgcna"]["artifacts"]["tables"]["wgcna_module_assignments"]).exists()
    assert Path(modules["single_gene"]["artifacts"]["tables"]["single_gene_summary"]).exists()
    assert Path(modules["clinical_assoc"]["artifacts"]["tables"]["clinical_feature_associations"]).exists()
