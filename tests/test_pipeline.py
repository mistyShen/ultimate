from __future__ import annotations

import json
from pathlib import Path

from ultimate.demo import init_project
from ultimate.config import dump_yaml, load_config
from ultimate.constants import MODULE_ORDER
from ultimate.job import prepare_job
from ultimate.modules.common import GLOBAL_MVP_TABLE_COLUMNS, MODULE_MVP_FIGURES, MODULE_MVP_OBJECTS, MODULE_MVP_TABLES
from ultimate.pipeline import run_pipeline_from_config
from ultimate.preflight import run_preflight


BULK_MODULES = {"rnaseq", "methylation", "proteomics", "publicdb", "wgcna", "single_gene", "clinical_assoc"}


def _write_real_matrix(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "feature_id\tCTRL_1\tCTRL_2\tTRT_1\tTRT_2",
                "GENE_A\t10\t12\t30\t32",
                "GENE_B\t20\t21\t18\t17",
                "GENE_C\t5\t4\t14\t15",
                "GENE_D\t40\t42\t38\t37",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


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
    assert (run_dir / "logs" / "run_context.json").exists()
    assert run_manifest["analysis_request"]["analysis_presets"] == ["standard"]
    assert "reproducible_package" in run_manifest
    assert run_manifest["logs"]["run_context"] == str(run_dir / "logs" / "run_context.json")
    assert run_manifest["delivery_gate"]["status"] == "blocked"
    assert run_manifest["delivery_gate"]["delivery_allowed"] is False
    assert run_manifest["delivery_gate"]["blocked_modules"]
    assert "no_production_backend_modules" in run_manifest["delivery_gate"]["blockers"]
    report_manifest = json.loads((run_dir / "reports" / "report_manifest.json").read_text(encoding="utf-8"))
    assert report_manifest["delivery_gate"] == run_manifest["delivery_gate"]
    run_context = json.loads((run_dir / "logs" / "run_context.json").read_text(encoding="utf-8"))
    assert run_context["delivery_gate"] == run_manifest["delivery_gate"]
    methods_report = (run_dir / "reports" / "methods.md").read_text(encoding="utf-8")
    html_report = (run_dir / "reports" / "report.html").read_text(encoding="utf-8")
    assert "复现信息" in methods_report
    assert "交付门控" in methods_report
    assert "交付门控" in html_report
    assert "analysis_level" in methods_report
    assert "analysis_level" in html_report
    for token in ("delivery_scope", "handoff_statuses", "reference_only", "rejected_cleaned"):
        assert token in methods_report
        assert token in html_report
    assert len(run_manifest["modules"]) == len(MODULE_ORDER)
    for module in run_manifest["modules"]:
        assert module["analysis_level"] in {"demo_result", "smoke_backend", "validated_backend", "production_backend"}
        assert module["delivery_allowed"] is False
        assert Path(module["artifacts"]["tables"]["module_qc_manifest"]).exists()
        assert Path(module["artifacts"]["tables"]["tool_coverage"]).exists()
        assert Path(module["artifacts"]["objects"]["mvp_object"]).exists()
        assert Path(module["artifacts"]["reports"]["methods_fragment"]).exists()
        assert Path(module["artifacts"]["reports"]["report_html"]).exists()
        assert Path(module["artifacts"]["reports"]["methods_md"]).exists()
        assert Path(module["artifacts"]["reports"]["run_manifest"]).exists()
        assert Path(module["artifacts"]["reports"]["report_html"]).name == "report.html"
        assert Path(module["artifacts"]["reports"]["methods_md"]).name == "methods.md"
        module_local_manifest = json.loads(Path(module["artifacts"]["reports"]["run_manifest"]).read_text(encoding="utf-8"))
        assert module_local_manifest["module"] == module["module"]
        assert module_local_manifest["analysis_level"] == module["analysis_level"]
        assert module_local_manifest["artifacts"]["reports"]["report_html"] == module["artifacts"]["reports"]["report_html"]
        module_name = module["module"]
        first_table = MODULE_MVP_TABLES[module_name][0]
        first_figure = MODULE_MVP_FIGURES[module_name][0]
        assert Path(module["artifacts"]["tables"][first_table.replace(".tsv", "")]).exists()
        assert Path(module["artifacts"]["figures"][first_figure.replace(".png", "")]).exists()
        module_log = run_dir / "logs" / f"{module['module']}.log"
        assert module_log.exists()
        assert "module_completed" in module_log.read_text(encoding="utf-8")

    vdj = {module["module"]: module for module in run_manifest["modules"]}["vdj"]
    assert Path(vdj["artifacts"]["tables"]["clonotype_summary"]).name == "clonotype_summary.tsv"
    assert Path(vdj["artifacts"]["figures"]["clone_size_distribution"]).name == "clone_size_distribution.png"
    methods_text = (run_dir / "reports" / "methods.md").read_text(encoding="utf-8")
    assert "MVP 表格" in methods_text
    assert "clonotype_summary.tsv" in methods_text
    assert "统计结果" not in methods_text


def test_all_modules_emit_declared_mvp_artifacts(tmp_path: Path) -> None:
    manifest = init_project("all", tmp_path / "declared_mvp", demo_data=True)
    run_manifest = run_pipeline_from_config(Path(manifest["config_path"]))
    run_dir = Path(run_manifest["output_dir"])

    assert len(run_manifest["modules"]) == len(MODULE_ORDER)
    modules = {module["module"]: module for module in run_manifest["modules"]}
    assert set(modules) == set(MODULE_ORDER)
    for module_name in MODULE_ORDER:
        module = modules[module_name]
        tables_dir = run_dir / "results" / "tables" / module_name
        figures_dir = run_dir / "results" / "figures" / module_name
        objects_dir = run_dir / "objects" / module_name
        raw_qc_manifest = run_dir / "raw_qc" / module_name / "raw_qc_manifest.json"
        assert raw_qc_manifest.exists() and raw_qc_manifest.stat().st_size > 0, module_name
        assert (run_dir / "results" / "tables" / module_name).is_dir(), module_name
        assert (run_dir / "results" / "figures" / module_name).is_dir(), module_name
        assert (run_dir / "objects" / module_name).is_dir(), module_name
        assert (run_dir / "logs" / f"{module_name}.log").exists(), module_name
        assert module["limitations"], module_name
        assert "template_only" in module["handoff"]["handoff_statuses"], module_name
        assert module["handoff"]["legacy_handoff_status"] == "template_ready", module_name
        assert module["delivery_allowed"] is False, module_name
        assert module["validation_evidence_allowed"] is False, module_name
        for filename in MODULE_MVP_TABLES[module_name]:
            path = tables_dir / filename
            assert path.exists() and path.stat().st_size > 0, f"{module_name}:{filename}"
        for filename in MODULE_MVP_FIGURES[module_name]:
            path = figures_dir / filename
            assert path.exists() and path.stat().st_size > 0, f"{module_name}:{filename}"
        object_name = MODULE_MVP_OBJECTS.get(module_name, f"{module_name}_mvp_object.rds")
        object_path = objects_dir / object_name
        assert object_path.exists() and object_path.stat().st_size > 0, f"{module_name}:{object_name}"
        assert (tables_dir / "module_qc_manifest.json").exists()
        assert (tables_dir / "module_manifest.json").exists()
        assert (run_dir / "reports" / module_name / f"{module_name}_methods.md").exists()
        assert (run_dir / "reports" / module_name / "report.html").exists()
        assert (run_dir / "reports" / module_name / "methods.md").exists()
        assert (run_dir / "reports" / module_name / "run_manifest.json").exists()


def test_mvp_tables_include_global_provenance_and_module_schema(tmp_path: Path) -> None:
    manifest = init_project("all", tmp_path / "mvp_schema", demo_data=True)
    run_manifest = run_pipeline_from_config(Path(manifest["config_path"]))
    run_dir = Path(run_manifest["output_dir"])

    checks = {
        "vdj": ("clonotype_summary.tsv", {"clonotype_id", "antigen_specificity_status"}),
        "mtdna": ("lineage_input.tsv", {"variant_id", "lineage_handoff_status"}),
        "hto_demux": ("hto_assignment.tsv", {"hashtag_id", "assignment_class"}),
        "spatial": ("spatial_qc.tsv", {"spot_id", "platform_note"}),
        "rnaseq": ("counts_raw.tsv", {"feature_id", "matrix_status"}),
    }
    for module_name, (filename, module_columns) in checks.items():
        path = run_dir / "results" / "tables" / module_name / filename
        header = path.read_text(encoding="utf-8").splitlines()[0].split("\t")
        assert list(header[: len(GLOBAL_MVP_TABLE_COLUMNS)]) == list(GLOBAL_MVP_TABLE_COLUMNS), module_name
        assert set(module_columns).issubset(header), module_name
        frame_text = path.read_text(encoding="utf-8")
        assert "analysis_level" in frame_text
        assert "demo_result" in frame_text


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
    assert run_manifest["status"] == "partial"
    assert run_manifest["module_status"]["scrna"] == "partial:validated_run_not_real_evidence"
    module = run_manifest["modules"][0]
    assert module["status"] == "partial:validated_run_not_real_evidence"
    assert module["backend"]["primary"] == "validated_run"
    assert module["analysis_level"] == "smoke_backend"
    assert module["delivery_allowed"] is False
    assert module["validation_evidence_allowed"] is False
    assert "source_not_real_evidence:analysis_level=missing" in module["skip_reasons"]
    assert Path(module["artifacts"]["tables"]["validated_artifact_index"]).exists()
    assert module["artifacts"]["figures"]["umap"] == str(figures / "umap.png")
    assert module["artifacts"]["objects"]["h5ad"] == str(objects / "validated.h5ad")


def test_validated_run_dir_imports_real_evidence_as_validated_backend(tmp_path: Path) -> None:
    manifest = init_project("scrna", tmp_path / "validated_real_source", demo_data=True)
    config_path = Path(manifest["config_path"])
    loaded = load_config(config_path)

    source_run = tmp_path / "validated_real_source" / "validated" / "scrna_source"
    figures = source_run / "results" / "figures"
    tables = source_run / "results" / "tables"
    objects = source_run / "objects"
    for directory in (figures, tables, objects):
        directory.mkdir(parents=True, exist_ok=True)
    (figures / "umap.png").write_text("figure", encoding="utf-8")
    (tables / "markers.tsv").write_text("gene\tscore\nA\t1\n", encoding="utf-8")
    (objects / "validated.h5ad").write_text("object", encoding="utf-8")
    (source_run / "run_manifest.json").write_text(
        json.dumps(
            {
                "status": "ready",
                "analysis_level": "validated_backend",
                "is_demo": False,
                "is_stub": False,
                "delivery_allowed": False,
                "validation_evidence_allowed": True,
                "non_delivery_reason": "validation_evidence_only_not_customer_delivery",
                "validation_scope": "test validated run",
                "n_cells": 12,
                "n_features": 34,
                "figures": [str(figures / "umap.png")],
                "tables": [str(tables / "markers.tsv")],
                "objects": {"h5ad": str(objects / "validated.h5ad")},
            }
        ),
        encoding="utf-8",
    )

    config = loaded.raw
    config["modules"]["scrna"]["validated_run_dir"] = "../validated/scrna_source"
    dump_yaml(config, config_path)

    run_manifest = run_pipeline_from_config(config_path)
    module = run_manifest["modules"][0]

    assert run_manifest["status"] == "ready"
    assert module["status"] == "complete_validated_run_backend"
    assert module["analysis_level"] == "validated_backend"
    assert module["validation_evidence_allowed"] is True
    assert module["delivery_allowed"] is False


def test_validated_run_source_can_be_production_rehearsal_with_current_approval(tmp_path: Path) -> None:
    manifest = init_project("scrna", tmp_path / "validated_source_rehearsal", demo_data=False)
    config_path = Path(manifest["config_path"])
    loaded = load_config(config_path)

    source_run = tmp_path / "validated_source_rehearsal" / "validated" / "scrna_source"
    figures = source_run / "results" / "figures"
    tables = source_run / "results" / "tables"
    objects = source_run / "objects"
    for directory in (figures, tables, objects):
        directory.mkdir(parents=True, exist_ok=True)
    (figures / "umap.png").write_text("figure", encoding="utf-8")
    (tables / "markers.tsv").write_text("gene\tscore\nA\t1\n", encoding="utf-8")
    (objects / "validated.h5ad").write_text("object", encoding="utf-8")
    (source_run / "run_manifest.json").write_text(
        json.dumps(
            {
                "status": "ready",
                "analysis_level": "validated_backend",
                "is_demo": False,
                "is_stub": False,
                "delivery_allowed": False,
                "validation_evidence_allowed": True,
                "non_delivery_reason": "validation_evidence_only_not_customer_delivery",
                "figures": [str(figures / "umap.png")],
                "tables": [str(tables / "markers.tsv")],
                "objects": {"h5ad": str(objects / "validated.h5ad")},
            }
        ),
        encoding="utf-8",
    )

    config = loaded.raw
    config["modules"]["scrna"]["validated_run_dir"] = "../validated/scrna_source"
    config["modules"]["scrna"]["analysis_level"] = "production_backend"
    config["modules"]["scrna"]["is_demo"] = False
    config["modules"]["scrna"].setdefault("raw", {})["enabled"] = False
    dump_yaml(config, config_path)
    output_dir = Path(load_config(config_path).raw["project"]["output_dir"])
    approval_path = tmp_path / "scrna_rehearsal_approval.json"
    approval_path.write_text(
        json.dumps(
            {
                "approved": True,
                "approved_by": "pytest",
                "approved_at": "2026-06-05T00:00:00Z",
                "project_id": "validated_source_rehearsal",
                "input_path": str(config_path.resolve()),
                "output_dir": str(output_dir.resolve()),
                "delivery_scope": "internal_rehearsal",
                "reason": "pytest scrna production-style rehearsal",
            }
        ),
        encoding="utf-8",
    )

    run_manifest = run_pipeline_from_config(config_path, production_approval_path=approval_path)
    module = run_manifest["modules"][0]

    assert run_manifest["delivery_gate"]["status"] == "ready"
    assert run_manifest["delivery_gate"]["delivery_scope"] == "internal_rehearsal"
    assert module["analysis_level"] == "production_backend"
    assert module["delivery_allowed"] is True
    assert module["validation_evidence_allowed"] is True
    assert "source_validated_backend_promoted_by_current_production_approval" in module["skip_reasons"]
    delivery_index = (output_dir / "delivery_index.tsv").read_text(encoding="utf-8")
    assert f"figure\t{figures / 'umap.png'}" in delivery_index
    assert f"table\t{tables / 'markers.tsv'}" in delivery_index
    assert f"object\t{objects / 'validated.h5ad'}" in delivery_index
    assert "\texternal_declared" in delivery_index


def test_validated_run_source_production_level_is_not_delivery_without_current_approval(tmp_path: Path) -> None:
    manifest = init_project("scrna", tmp_path / "validated_source_production", demo_data=True)
    config_path = Path(manifest["config_path"])
    loaded = load_config(config_path)

    source_run = tmp_path / "validated_source_production" / "validated" / "production_source"
    figures = source_run / "results" / "figures"
    tables = source_run / "results" / "tables"
    objects = source_run / "objects"
    for directory in (figures, tables, objects):
        directory.mkdir(parents=True, exist_ok=True)
    (figures / "umap.png").write_text("figure", encoding="utf-8")
    (tables / "markers.tsv").write_text("gene\tscore\nA\t1\n", encoding="utf-8")
    (objects / "production.h5ad").write_text("object", encoding="utf-8")
    (source_run / "run_manifest.json").write_text(
        json.dumps(
            {
                "status": "ready",
                "analysis_level": "production_backend",
                "is_demo": False,
                "is_stub": False,
                "delivery_allowed": True,
                "validation_evidence_allowed": True,
                "figures": [str(figures / "umap.png")],
                "tables": [str(tables / "markers.tsv")],
                "objects": {"h5ad": str(objects / "production.h5ad")},
            }
        ),
        encoding="utf-8",
    )

    config = loaded.raw
    config["modules"]["scrna"]["validated_run_dir"] = "../validated/production_source"
    dump_yaml(config, config_path)

    run_manifest = run_pipeline_from_config(config_path)
    module = run_manifest["modules"][0]

    assert module["analysis_level"] == "validated_backend"
    assert module["delivery_allowed"] is False
    assert module["validation_evidence_allowed"] is True
    assert "source_production_backend_downgraded:current_run_not_production_approved" in module["skip_reasons"]


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


def test_preflight_requires_job_id_in_production_mode(tmp_path: Path) -> None:
    manifest = init_project("rnaseq", tmp_path / "missing_job_id", demo_data=True)
    loaded = load_config(Path(manifest["config_path"]))
    config = loaded.raw
    config["project"]["run_mode"] = "production"
    config["project"].pop("job_id", None)

    preflight = run_preflight(config, write=False)

    assert preflight["status"] == "blocked:missing_job_id"
    assert preflight["job_layout"]["status"] == "blocked:missing_job_id"


def test_preflight_accepts_production_job_output_under_shared_jobs(tmp_path: Path) -> None:
    manifest = init_project("rnaseq", tmp_path / "shared_job_layout", demo_data=True)
    loaded = load_config(Path(manifest["config_path"]))
    config = loaded.raw
    server_root = tmp_path / "shared" / "shen" / "2026" / "ultimate"
    job_id = "JOB001"
    config["project"]["run_mode"] = "production"
    config["project"]["server_root"] = str(server_root)
    config["project"]["job_id"] = job_id
    config["project"]["output_dir"] = str(server_root / "jobs" / job_id / "runs" / "primary")

    preflight = run_preflight(config, write=False)

    assert preflight["job_layout"]["status"] == "ready"
    assert preflight["status"] != "blocked:output_not_under_job_dir"
    assert preflight["status"] != "blocked:missing_job_id"


def test_preflight_blocks_missing_analysis_request_in_production_job(tmp_path: Path) -> None:
    source = init_project("rnaseq", tmp_path / "missing_request_source", demo_data=True)
    root = tmp_path / "shared" / "shen" / "2026" / "ultimate"
    job_manifest = prepare_job(config_path=Path(source["config_path"]), job_id="REQ001", root=root, run_mode="production")
    job_config = Path(job_manifest["config_path"])
    loaded = load_config(job_config)
    config = loaded.raw
    config.pop("analysis_request", None)
    config.get("project", {}).pop("analysis_request", None)
    config["modules"]["rnaseq"].setdefault("raw", {})["enabled"] = False

    preflight = run_preflight(config, write=False)

    assert preflight["status"] == "blocked:missing_analysis_request"
    assert preflight["analysis_request_status"]["status"] == "missing"


def test_unified_run_requires_production_approval_for_production_backend(tmp_path: Path) -> None:
    manifest = init_project("rnaseq", tmp_path / "approval_required", demo_data=True)
    config_path = Path(manifest["config_path"])
    loaded = load_config(config_path)
    config = loaded.raw
    config["modules"]["rnaseq"]["analysis_level"] = "production_backend"
    dump_yaml(config, config_path)

    try:
        run_pipeline_from_config(config_path)
    except RuntimeError as exc:
        assert "production_backend requires --production-approval" in str(exc)
    else:
        raise AssertionError("production_backend unified run should require approval")


def test_unified_run_rejects_demo_data_even_with_production_approval(tmp_path: Path) -> None:
    manifest = init_project("rnaseq", tmp_path / "approved_demo_order", demo_data=True)
    config_path = Path(manifest["config_path"])
    loaded = load_config(config_path)
    config = loaded.raw
    config["modules"]["rnaseq"]["analysis_level"] = "production_backend"
    dump_yaml(config, config_path)
    output_dir = Path(load_config(config_path).raw["project"]["output_dir"])
    approval_path = tmp_path / "production_approval.json"
    approval_path.write_text(
        json.dumps(
            {
                "approved": True,
                "approved_by": "pytest",
                "approved_at": "2026-06-04T00:00:00Z",
                "project_id": "approved_demo_order",
                "input_path": str(config_path.resolve()),
                "output_dir": str(output_dir.resolve()),
                "delivery_scope": "internal_rehearsal",
                "reason": "pytest unified run production gate",
            }
        ),
        encoding="utf-8",
    )

    try:
        run_pipeline_from_config(config_path, production_approval_path=approval_path)
    except ValueError as exc:
        assert "demo inputs cannot be labeled as production_backend" in str(exc)
    else:
        raise AssertionError("demo production run should be rejected even with approval")


def test_unified_run_accepts_valid_production_approval_for_real_input(tmp_path: Path) -> None:
    manifest = init_project("rnaseq", tmp_path / "approved_order", demo_data=False)
    config_path = Path(manifest["config_path"])
    loaded = load_config(config_path)
    config = loaded.raw
    _write_real_matrix(Path(config["modules"]["rnaseq"]["input_matrix"]))
    config["modules"]["rnaseq"]["analysis_level"] = "production_backend"
    config["modules"]["rnaseq"]["is_demo"] = False
    config["modules"]["rnaseq"].setdefault("raw", {})["enabled"] = False
    dump_yaml(config, config_path)
    output_dir = Path(load_config(config_path).raw["project"]["output_dir"])
    approval_path = tmp_path / "production_approval.json"
    approval_path.write_text(
        json.dumps(
            {
                "approved": True,
                "approved_by": "pytest",
                "approved_at": "2026-06-04T00:00:00Z",
                "project_id": "approved_order",
                "input_path": str(config_path.resolve()),
                "output_dir": str(output_dir.resolve()),
                "delivery_scope": "internal_rehearsal",
                "reason": "pytest unified run production gate",
            }
        ),
        encoding="utf-8",
    )

    run_manifest = run_pipeline_from_config(config_path, production_approval_path=approval_path)

    assert run_manifest["analysis_level"] == "production_backend"
    assert run_manifest["is_demo"] is False
    assert run_manifest["is_stub"] is False
    assert run_manifest["delivery_allowed"] is True
    assert run_manifest["validation_evidence_allowed"] is True
    assert run_manifest["non_delivery_reason"] == ""
    assert "slurm_job_id" in run_manifest
    assert "slurm" in run_manifest
    assert run_manifest["production_approval"]["approved"] is True
    assert run_manifest["production_approval"]["approval_path"] == str(approval_path.resolve())
    assert run_manifest["production_approval"]["input_path"] == str(config_path.resolve())
    assert run_manifest["production_approval"]["output_dir"] == str(output_dir.resolve())
    assert run_manifest["delivery_gate"]["status"] == "ready"
    assert run_manifest["delivery_gate"]["delivery_allowed"] is True
    assert run_manifest["delivery_gate"]["approval_status"] == "approved"
    assert run_manifest["delivery_gate"]["production_modules"] == ["rnaseq"]
    assert run_manifest["delivery_gate"]["blocked_modules"] == []
    rnaseq = run_manifest["modules"][0]
    assert rnaseq["analysis_level"] == "production_backend"
    assert rnaseq["delivery_allowed"] is True
    counts_text = Path(rnaseq["artifacts"]["tables"]["counts_raw"]).read_text(encoding="utf-8")
    counts_header = counts_text.splitlines()[0].split("\t")
    counts_values = counts_text.splitlines()[1].split("\t")
    counts_row = dict(zip(counts_header, counts_values))
    assert counts_row["run_id"] == run_manifest["run_id"]
    assert counts_row["analysis_level"] == "production_backend"
    assert counts_row["delivery_allowed"] in {"True", "true"}


def test_prepared_job_run_mirrors_latest_deliverables_to_job_root(tmp_path: Path) -> None:
    source = init_project("rnaseq", tmp_path / "job_delivery_source", demo_data=True)
    root = tmp_path / "shared" / "shen" / "2026" / "ultimate"
    job_manifest = prepare_job(config_path=Path(source["config_path"]), job_id="DELIVERY001", root=root, run_mode="interactive")
    job_dir = Path(job_manifest["job_dir"])

    run_manifest = run_pipeline_from_config(job_dir / "config" / "project.yaml")

    assert Path(run_manifest["output_dir"]) == job_dir / "runs" / "DELIVERY001"
    assert (job_dir / "deliverables" / "latest_report.html").exists()
    assert (job_dir / "deliverables" / "latest_methods.md").exists()
    assert (job_dir / "deliverables" / "latest_delivery_index.tsv").exists()
    assert (job_dir / "deliverables" / "latest_run_pointer.json").exists()
    assert (job_dir / "deliverables" / "module_reports" / "rnaseq" / "report.html").exists()
    assert (job_dir / "deliverables" / "module_reports" / "rnaseq" / "methods.md").exists()
    assert (job_dir / "deliverables" / "module_reports" / "rnaseq" / "run_manifest.json").exists()
    assert (job_dir / "reproducible_code" / "rerun.sh").exists()
    assert (job_dir / "reproducible_code" / "software_versions.tsv").exists()
    assert (job_dir / "reproducible_code" / "input_checksums.tsv").exists()
    assert (job_dir / "reproducible_code" / "latest_repro_manifest.json").exists()
    pointer = json.loads((job_dir / "deliverables" / "latest_run_pointer.json").read_text(encoding="utf-8"))
    mirrored_run_manifest = json.loads((job_dir / "deliverables" / "latest_run_manifest.json").read_text(encoding="utf-8"))
    final_run_manifest = json.loads((job_dir / "runs" / "DELIVERY001" / "run_manifest.json").read_text(encoding="utf-8"))
    mirrored_repro = json.loads((job_dir / "reproducible_code" / "latest_repro_manifest.json").read_text(encoding="utf-8"))
    run_repro = json.loads((job_dir / "runs" / "DELIVERY001" / "reproducible_code" / "repro_manifest.json").read_text(encoding="utf-8"))
    mirrored_checksums = (job_dir / "reproducible_code" / "input_checksums.tsv").read_text(encoding="utf-8")
    run_checksums = (job_dir / "runs" / "DELIVERY001" / "reproducible_code" / "input_checksums.tsv").read_text(encoding="utf-8")
    assert pointer["latest_run_dir"] == str(job_dir / "runs" / "DELIVERY001")
    assert pointer["policy"].startswith("job-level files are small")
    assert Path(pointer["copied_artifacts"]["delivery_index"]).exists()
    assert Path(pointer["copied_artifacts"]["module_reports"]["rnaseq"]["report_html"]).exists()
    assert Path(pointer["copied_artifacts"]["module_reports"]["rnaseq"]["methods_md"]).exists()
    assert Path(pointer["copied_artifacts"]["module_reports"]["rnaseq"]["run_manifest"]).exists()
    assert mirrored_run_manifest == final_run_manifest
    assert mirrored_repro == run_repro
    assert mirrored_checksums == run_checksums
    assert "job_level_delivery" in run_repro


def test_prepared_production_job_with_approval_writes_delivery_mirrors(tmp_path: Path) -> None:
    source = init_project("rnaseq", tmp_path / "source_order", demo_data=False)
    source_config = load_config(Path(source["config_path"])).raw
    _write_real_matrix(Path(source_config["modules"]["rnaseq"]["input_matrix"]))
    root = tmp_path / "shared" / "shen" / "2026" / "ultimate"
    job_manifest = prepare_job(config_path=Path(source["config_path"]), job_id="PROD001", root=root, run_mode="production")
    job_dir = Path(job_manifest["job_dir"])
    job_config = job_dir / "config" / "project.yaml"

    loaded = load_config(job_config)
    config = loaded.raw
    config["analysis_request"] = {"analysis_presets": ["standard"], "notes": "pytest production order"}
    config["modules"]["rnaseq"]["analysis_level"] = "production_backend"
    config["modules"]["rnaseq"]["is_demo"] = False
    config["modules"]["rnaseq"].setdefault("raw", {})["enabled"] = False
    dump_yaml(config, job_config)

    approval_path = job_dir / "config" / "production_approval.json"
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    approval.update(
        {
            "approved": True,
            "approved_by": "pytest",
            "approved_at": "2026-06-04T00:00:00Z",
            "reason": "pytest prepared production job approval",
        }
    )
    approval_path.write_text(json.dumps(approval, indent=2, ensure_ascii=False), encoding="utf-8")

    run_manifest = run_pipeline_from_config(job_config, production_approval_path=approval_path)

    run_dir = job_dir / "runs" / "PROD001"
    assert Path(run_manifest["output_dir"]) == run_dir
    assert run_manifest["production_approval"]["approved"] is True
    assert run_manifest["delivery_gate"]["status"] == "ready"
    assert run_manifest["delivery_gate"]["delivery_allowed"] is True
    rnaseq = {module["module"]: module for module in run_manifest["modules"]}["rnaseq"]
    assert rnaseq["analysis_level"] == "production_backend"
    assert rnaseq["delivery_allowed"] is True
    assert rnaseq["validation_evidence_allowed"] is True

    assert (job_dir / "deliverables" / "latest_report.html").exists()
    assert (job_dir / "deliverables" / "latest_methods.md").exists()
    assert (job_dir / "deliverables" / "latest_run_manifest.json").exists()
    assert (job_dir / "deliverables" / "latest_delivery_index.tsv").exists()
    assert (job_dir / "deliverables" / "latest_run_pointer.json").exists()
    assert (job_dir / "deliverables" / "module_reports" / "rnaseq" / "report.html").exists()
    assert (job_dir / "deliverables" / "module_reports" / "rnaseq" / "methods.md").exists()
    assert (job_dir / "deliverables" / "module_reports" / "rnaseq" / "run_manifest.json").exists()
    assert (job_dir / "reproducible_code" / "rerun.sh").exists()
    assert (job_dir / "reproducible_code" / "software_versions.tsv").exists()
    assert (job_dir / "reproducible_code" / "input_checksums.tsv").exists()
    assert (job_dir / "reproducible_code" / "latest_repro_manifest.json").exists()

    mirrored_run_manifest = json.loads((job_dir / "deliverables" / "latest_run_manifest.json").read_text(encoding="utf-8"))
    final_run_manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert (job_dir / "reproducible_code" / "input_checksums.tsv").read_text(encoding="utf-8") == (
        run_dir / "reproducible_code" / "input_checksums.tsv"
    ).read_text(encoding="utf-8")
    assert mirrored_run_manifest == final_run_manifest
    assert mirrored_run_manifest["analysis_level"] == "production_backend"
    assert mirrored_run_manifest["delivery_allowed"] is True
    assert mirrored_run_manifest["validation_evidence_allowed"] is True
    assert "slurm_job_id" in mirrored_run_manifest
    assert "slurm" in mirrored_run_manifest
    assert mirrored_run_manifest["delivery_gate"]["status"] == "ready"
    assert mirrored_run_manifest["delivery_gate"]["delivery_allowed"] is True
    assert mirrored_run_manifest["production_approval"]["approved"] is True
    assert mirrored_run_manifest["production_approval"]["input_path"] == str(job_config.resolve())
    assert mirrored_run_manifest["production_approval"]["output_dir"] == str(run_dir.resolve())
    assert {module["module"]: module for module in mirrored_run_manifest["modules"]}["rnaseq"]["delivery_allowed"] is True

    delivery_index = (job_dir / "deliverables" / "latest_delivery_index.tsv").read_text(encoding="utf-8")
    assert "category\tpath\tsize_bytes\tmodule\tartifact_key\tartifact_scope" in delivery_index
    for category in ("figure", "table", "object", "report", "module_report", "reproducible_code"):
        assert f"\n{category}\t" in delivery_index
    assert "\trnaseq\treport\tmodule" in delivery_index
    assert "\trnaseq\tmethods\tmodule" in delivery_index
    assert "\trnaseq\trun_manifest\tmodule" in delivery_index

    rerun_script = (job_dir / "reproducible_code" / "rerun.sh").read_text(encoding="utf-8")
    assert 'CONDA_SH="${CONDA_SH:-}"' in rerun_script
    assert "for candidate in" in rerun_script
    assert 'export PATH="$ENV_PREFIX/bin:$PATH"' in rerun_script
    assert "/share/home/nshen" not in rerun_script
    assert "Full rerun must be submitted through Slurm" in rerun_script
    assert 'if [ -z "${SLURM_JOB_ID:-}" ]; then' in rerun_script
    assert 'if [ "${ULTIMATE_ALLOW_OVERWRITE:-}" != "1" ]; then' in rerun_script
