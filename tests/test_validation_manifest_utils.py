from __future__ import annotations

import sys
from pathlib import Path


TOOLS_DIR = Path(__file__).parents[1] / "01_tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from validation_manifest_utils import add_validation_guard_fields
from check_validation_manifests import check_validation_manifests, normalize_validation_manifests, summarize_rows, write_tsv
from ensure_validation_methods import ensure_validation_methods
from ensure_validation_mvp_artifacts import ensure_validation_mvp_artifacts


VALIDATION_SCRIPTS = (
    "validate_cite_seq_public.py",
    "validate_genotype_demux_demo.py",
    "validate_hto_demux_demo.py",
    "validate_method_tools_scrna.py",
    "validate_mtdna_0518.py",
    "validate_multiome_public.py",
    "validate_perturb_seq_demo.py",
    "validate_scatac_public.py",
    "validate_scdna_0518.py",
    "validate_scrna_nsclc.py",
    "validate_spatial_public.py",
    "validate_vdj_public.py",
)


def test_public_validation_manifest_is_evidence_not_delivery(monkeypatch) -> None:
    monkeypatch.setenv("SLURM_JOB_ID", "12345")
    monkeypatch.setenv("SLURM_JOB_NAME", "ult_validate")
    monkeypatch.setenv("SLURM_SUBMIT_DIR", "/shared/shen/2026/ultimate")

    manifest = add_validation_guard_fields({"status": "ready"}, validation_kind="public", validation_scope="public run")

    assert manifest["analysis_level"] == "validated_backend"
    assert manifest["is_demo"] is False
    assert manifest["is_stub"] is False
    assert manifest["delivery_allowed"] is False
    assert manifest["validation_evidence_allowed"] is True
    assert manifest["non_delivery_reason"] == "validation_evidence_only_not_customer_delivery"
    assert manifest["slurm_job_id"] == "12345"
    assert manifest["slurm"]["job_name"] == "ult_validate"


def test_guard_fields_preserve_existing_slurm_metadata() -> None:
    manifest = add_validation_guard_fields(
        {"status": "ready", "slurm_job_id": "777", "slurm": {"job_name": "old_job"}},
        validation_kind="internal",
    )

    assert manifest["slurm_job_id"] == "777"
    assert manifest["slurm"]["job_id"] == "777"
    assert manifest["slurm"]["job_name"] == "old_job"


def test_synthetic_validation_manifest_is_demo_only() -> None:
    manifest = add_validation_guard_fields({"status": "ready"}, validation_kind="synthetic", validation_scope="synthetic run")

    assert manifest["analysis_level"] == "demo_result"
    assert manifest["is_demo"] is True
    assert manifest["is_stub"] is False
    assert manifest["delivery_allowed"] is False
    assert manifest["validation_evidence_allowed"] is False
    assert manifest["non_delivery_reason"] == "generated_demo_data_not_customer_delivery"


def test_not_ready_manifest_is_smoke_backend() -> None:
    manifest = add_validation_guard_fields({"status": "missing_source_outputs"}, validation_kind="internal")

    assert manifest["analysis_level"] == "smoke_backend"
    assert manifest["is_stub"] is True
    assert manifest["delivery_allowed"] is False
    assert manifest["validation_evidence_allowed"] is False
    assert manifest["non_delivery_reason"] == "validation_status_not_ready:missing_source_outputs"


def test_all_validation_scripts_apply_guard_fields() -> None:
    for filename in VALIDATION_SCRIPTS:
        text = (TOOLS_DIR / filename).read_text(encoding="utf-8")
        assert "from validation_manifest_utils import add_validation_guard_fields" in text, filename
        assert "add_validation_guard_fields(" in text, filename


def test_check_validation_manifests_reports_guard_gaps(tmp_path: Path) -> None:
    old_run = tmp_path / "validations" / "old_ready"
    old_run.mkdir(parents=True)
    (old_run / "run_manifest.json").write_text('{"status": "ready"}', encoding="utf-8")

    ready_run = tmp_path / "validations" / "new_ready"
    (ready_run / "reports").mkdir(parents=True)
    (ready_run / "reports" / "report.html").write_text("<html></html>", encoding="utf-8")
    manifest = add_validation_guard_fields(
        {
            "status": "ready",
            "figures": ["a.png"],
            "tables": ["a.tsv"],
            "objects": {"json": "object.json"},
        },
        validation_kind="internal",
    )
    (ready_run / "run_manifest.json").write_text(__import__("json").dumps(manifest), encoding="utf-8")

    rows = check_validation_manifests(tmp_path / "validations")
    by_name = {row["run_name"]: row for row in rows}

    assert by_name["old_ready"]["guard_status"] == "missing_guard_fields"
    assert by_name["new_ready"]["guard_status"] == "ready"
    assert by_name["new_ready"]["report_html_exists"] is True
    assert summarize_rows(rows) == {"ready": 1, "missing_guard_fields": 1}

    output_tsv = tmp_path / "review" / "validation_guard_check.tsv"
    write_tsv(output_tsv, rows)
    assert output_tsv.exists()
    assert "missing_guard_fields" in output_tsv.read_text(encoding="utf-8")


def test_normalize_validation_manifests_backs_up_and_adds_guards(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    old_run = root / "validations" / "slurm_scrna_nsclc_lambrechts"
    old_run.mkdir(parents=True)
    manifest_path = old_run / "run_manifest.json"
    manifest_path.write_text('{"status": "ready", "dataset": "NSCLC"}', encoding="utf-8")

    rows = normalize_validation_manifests(
        root=root,
        validations_dir=root / "validations",
        backup_dir=root / "audits" / "validation_guard_latest" / "backups",
    )

    assert rows[0]["guard_status"] == "ready"
    assert rows[0]["normalization_action"] == "normalized"
    assert Path(rows[0]["backup_path"]).exists()
    text = manifest_path.read_text(encoding="utf-8")
    assert '"analysis_level": "validated_backend"' in text
    assert '"delivery_allowed": false' in text


def test_ensure_validation_methods_creates_transparent_methods_file(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    run = root / "validations" / "slurm_vdj_10x_pbmc"
    run.mkdir(parents=True)
    manifest = add_validation_guard_fields(
        {
            "status": "ready",
            "module": "vdj",
            "input_dir": "/shared/shen/2026/ultimate/public_data/vdj",
            "tables": ["results/tables/clonotype_summary.tsv"],
            "figures": ["results/figures/clone_size_distribution.png"],
            "objects": {"h5ad": "objects/vdj_mvp.h5ad"},
        },
        validation_kind="public",
    )
    (run / "run_manifest.json").write_text(__import__("json").dumps(manifest), encoding="utf-8")

    rows = ensure_validation_methods(root=root, validations_dir=root / "validations")

    methods = run / "reports" / "methods.md"
    assert rows[0]["action"] == "created"
    assert methods.exists()
    text = methods.read_text(encoding="utf-8")
    assert "由 `ensure_validation_methods.py`" in text
    assert "不新增分析结论" in text
    assert "analysis_level：`validated_backend`" in text


def test_ensure_validation_mvp_artifacts_creates_standard_vdj_aliases(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    run = root / "validations" / "slurm_vdj_10x_pbmc"
    (run / "results" / "tables").mkdir(parents=True)
    (run / "results" / "figures").mkdir(parents=True)
    (run / "objects").mkdir(parents=True)
    (run / "results" / "tables" / "top_clonotypes.tsv").write_text("clonotype_id\tcell_count\nc1\t3\n", encoding="utf-8")
    (run / "results" / "figures" / "top_clonotype_frequency.png").write_text("png", encoding="utf-8")
    (run / "objects" / "vdj_validation_object.json").write_text("{}", encoding="utf-8")
    manifest = add_validation_guard_fields(
        {
            "status": "ready",
            "module": "vdj",
            "tables": ["results/tables/top_clonotypes.tsv"],
            "figures": ["results/figures/top_clonotype_frequency.png"],
            "objects": {"json": "objects/vdj_validation_object.json"},
        },
        validation_kind="public",
    )
    (run / "run_manifest.json").write_text(__import__("json").dumps(manifest), encoding="utf-8")

    rows = ensure_validation_mvp_artifacts(root=root, validations_dir=root / "validations")

    actions = {(row["artifact_kind"], row["artifact_name"]): row["action"] for row in rows}
    assert actions[("table", "clonotype_summary.tsv")] == "created"
    assert (run / "results" / "tables" / "clonotype_summary.tsv").exists()
    assert (run / "results" / "figures" / "clone_size_distribution.png").exists()
    assert (run / "objects" / "vdj_mvp.h5ad").exists()
    table_text = (run / "results" / "tables" / "clonotype_summary.tsv").read_text(encoding="utf-8")
    assert "clonotype_id" in table_text
    assert "antigen_specificity_status" in table_text
    assert "analysis_level" in table_text
    assert "input_artifact" in table_text
    assert "derived_from_existing_validation_artifact" in table_text
    updated = __import__("json").loads((run / "run_manifest.json").read_text(encoding="utf-8"))
    assert "results/tables/clonotype_summary.tsv" in updated["tables"]
    assert updated["objects"]["mvp_object"] == "objects/vdj_mvp.h5ad"
    assert updated["mvp_artifact_standardization"]["status"] == "created_or_verified"


def test_ensure_validation_mvp_artifacts_updates_existing_tables_missing_global_columns(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    run = root / "validations" / "slurm_vdj_10x_pbmc"
    (run / "results" / "tables").mkdir(parents=True)
    (run / "results" / "figures").mkdir(parents=True)
    (run / "objects").mkdir(parents=True)
    (run / "results" / "tables" / "clonotype_summary.tsv").write_text(
        "module\tclonotype_id\nvdj\tc1\n",
        encoding="utf-8",
    )
    manifest = add_validation_guard_fields(
        {
            "status": "ready",
            "module": "vdj",
            "tables": ["results/tables/clonotype_summary.tsv"],
            "figures": [],
            "objects": {},
        },
        validation_kind="public",
    )
    (run / "run_manifest.json").write_text(__import__("json").dumps(manifest), encoding="utf-8")

    rows = ensure_validation_mvp_artifacts(root=root, validations_dir=root / "validations")

    actions = {(row["artifact_kind"], row["artifact_name"]): row["action"] for row in rows}
    assert actions[("table", "clonotype_summary.tsv")] == "updated_schema"
    header = (run / "results" / "tables" / "clonotype_summary.tsv").read_text(encoding="utf-8").splitlines()[0].split("\t")
    assert "run_id" in header
    assert "analysis_level" in header
    assert "method_status" in header
