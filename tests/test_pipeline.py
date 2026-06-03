from __future__ import annotations

from pathlib import Path

from ultimate.demo import init_project
from ultimate.config import dump_yaml, load_config
from ultimate.pipeline import run_pipeline_from_config
from ultimate.preflight import run_preflight


BULK_MODULES = {"rnaseq", "methylation", "proteomics", "publicdb", "wgcna", "single_gene", "clinical_assoc"}


def test_pipeline_generates_required_artifacts(tmp_path: Path) -> None:
    manifest = init_project("all", tmp_path / "demo_all", demo_data=True)
    run_manifest = run_pipeline_from_config(Path(manifest["config_path"]))
    run_dir = Path(run_manifest["output_dir"])
    assert (run_dir / "run_manifest.json").exists()
    assert run_manifest["status"] == "ready"
    assert run_manifest["summary"]["module_count"] == len(run_manifest["modules"])
    assert set(run_manifest["module_status"]) == {module["module"] for module in run_manifest["modules"]}
    assert (run_dir / "reports" / "report.html").exists()
    assert (run_dir / "reports" / "methods.md").exists()
    assert (run_dir / "reproducible_code" / "rerun.sh").exists()
    assert (run_dir / "reproducible_code" / "software_versions.tsv").exists()
    assert (run_dir / "reproducible_code" / "input_checksums.tsv").exists()
    assert (run_dir / "delivery_index.tsv").exists()
    assert run_manifest["analysis_request"]["analysis_presets"] == ["standard"]
    assert "reproducible_package" in run_manifest
    assert "复现信息" in (run_dir / "reports" / "methods.md").read_text(encoding="utf-8")
    assert "analysis_level" in (run_dir / "reports" / "methods.md").read_text(encoding="utf-8")
    assert "analysis_level" in (run_dir / "reports" / "report.html").read_text(encoding="utf-8")
    assert len(run_manifest["modules"]) >= 13
    for module in run_manifest["modules"]:
        assert module["analysis_level"] in {"demo_result", "smoke_backend", "validated_backend", "production_backend"}
        assert module["delivery_allowed"] is False
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


def test_validated_run_dir_is_imported_by_unified_run(tmp_path: Path) -> None:
    manifest = init_project("scrna", tmp_path / "validated_demo", demo_data=True)
    config_path = Path(manifest["config_path"])
    loaded = load_config(config_path)

    source_run = tmp_path / "validated_demo" / "validated" / "scrna_source"
    figures = source_run / "results" / "figures"
    tables = source_run / "results" / "tables"
    objects = source_run / "objects"
    reports = source_run / "reports"
    for directory in (figures, tables, objects, reports):
        directory.mkdir(parents=True, exist_ok=True)
    (figures / "umap.png").write_text("figure", encoding="utf-8")
    (tables / "markers.tsv").write_text("gene\tscore\nA\t1\n", encoding="utf-8")
    (objects / "validated.h5ad").write_text("object", encoding="utf-8")
    (source_run / "run_manifest.json").write_text(
        """
{
  "status": "ready",
  "validation_scope": "test validated run",
  "n_cells": 12,
  "n_features": 34,
  "figures": ["RESULTS_FIG"],
  "tables": ["RESULTS_TABLE"],
  "objects": {"h5ad": "RESULTS_OBJECT"}
}
""".replace("RESULTS_FIG", str(figures / "umap.png"))
        .replace("RESULTS_TABLE", str(tables / "markers.tsv"))
        .replace("RESULTS_OBJECT", str(objects / "validated.h5ad")),
        encoding="utf-8",
    )

    config = loaded.raw
    config["modules"]["scrna"]["validated_run_dir"] = "../validated/scrna_source"
    dump_yaml(config, config_path)

    run_manifest = run_pipeline_from_config(config_path)
    assert run_manifest["status"] == "ready"
    assert run_manifest["module_status"]["scrna"] == "complete_validated_run_backend"
    module = run_manifest["modules"][0]
    assert module["status"] == "complete_validated_run_backend"
    assert module["backend"]["primary"] == "validated_run"
    assert module["analysis_level"] == "validated_backend"
    assert module["delivery_allowed"] is False
    assert Path(module["artifacts"]["tables"]["validated_artifact_index"]).exists()
    assert module["artifacts"]["figures"]["umap"] == str(figures / "umap.png")
    assert module["artifacts"]["objects"]["h5ad"] == str(objects / "validated.h5ad")


def test_preflight_blocks_existing_run_manifest_in_production_mode(tmp_path: Path) -> None:
    manifest = init_project("rnaseq", tmp_path / "overwrite_guard", demo_data=True)
    run_manifest = run_pipeline_from_config(Path(manifest["config_path"]))
    loaded = load_config(Path(manifest["config_path"]))
    config = loaded.raw
    config["project"]["run_mode"] = "production"
    config["project"]["overwrite"] = False
    preflight = run_preflight(config, write=False)
    assert preflight["status"] == "blocked:existing_run_manifest"
    assert preflight["output_safety"]["existing_run_manifest"] == str(Path(run_manifest["output_dir"]) / "run_manifest.json")
