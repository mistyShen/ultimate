from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from ultimate.cli import main
from ultimate.constants import MODULE_ORDER
from ultimate.production_audit import run_production_audit
from ultimate.validation_index import build_validation_index


def test_production_audit_writes_readiness_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    (root / ".conda" / "envs" / "ultimate-core").mkdir(parents=True)
    manifest = run_production_audit(root=root, output_dir=tmp_path / "audit")
    assert Path(manifest["capability_matrix"]).exists()
    assert Path(manifest["organism_support"]).exists()
    assert Path(manifest["style_options"]).exists()
    assert Path(manifest["order_readiness_checklist"]).exists()
    assert Path(manifest["validation_evidence_matrix"]).exists()
    assert Path(manifest["final_acceptance_checklist"]).exists()
    assert Path(manifest["module_maturity_table"]).exists()
    assert Path(manifest["module_standardization_matrix"]).exists()
    assert Path(manifest["tool_coverage_by_module"]).exists()
    assert "final_acceptance_summary" in manifest
    assert manifest["module_standardization_summary"]["ready"] == len(MODULE_ORDER)
    assert Path(manifest["next_steps"]).exists()
    assert sum(manifest["summary"].values()) == len(MODULE_ORDER)


def test_cli_styles_generates_review(tmp_path: Path) -> None:
    runner = CliRunner()
    out_dir = tmp_path / "style"
    result = runner.invoke(main, ["styles", "--style", "warm_academic", "--output-dir", str(out_dir)])
    assert result.exit_code == 0, result.output
    assert (out_dir / "style_review_manifest.json").exists()
    assert (out_dir / "qc_bar_review.png").exists()


def test_cli_audit_modules_generates_standardization_matrix(tmp_path: Path) -> None:
    runner = CliRunner()
    out_dir = tmp_path / "module_audit"
    repo_root = Path(__file__).resolve().parents[1]
    result = runner.invoke(main, ["audit-modules", "--root", str(repo_root), "--output-dir", str(out_dir)])
    assert result.exit_code == 0, result.output
    assert (out_dir / "run_manifest.json").exists()
    matrix = out_dir / "module_standardization_matrix.tsv"
    assert matrix.exists()
    text = matrix.read_text(encoding="utf-8")
    assert "demo_manifest_status" in text
    assert "overall_status" in text


def test_production_audit_rejects_demo_scrna_mvp_as_real_evidence(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    run_dir = root / "validation_runs" / "scrna_mvp_validation" / "10x_mtx"
    (run_dir / "results" / "tables").mkdir(parents=True)
    (run_dir / "results" / "figures").mkdir(parents=True)
    (run_dir / "objects").mkdir(parents=True)
    (run_dir / "reports").mkdir(parents=True)
    (run_dir / "run_manifest.json").write_text(
        """
{
  "status": "ready",
  "analysis_level": "demo_result",
  "is_demo": true,
  "is_stub": false,
  "delivery_allowed": false
}
""",
        encoding="utf-8",
    )
    for idx in range(8):
        (run_dir / "results" / "tables" / f"table_{idx}.tsv").write_text("a\\n1\\n", encoding="utf-8")
    for idx in range(3):
        (run_dir / "results" / "figures" / f"fig_{idx}.png").write_text("png", encoding="utf-8")
    (run_dir / "objects" / "scrna_mvp.h5ad").write_text("object", encoding="utf-8")
    (run_dir / "reports" / "report.md").write_text("report", encoding="utf-8")
    (run_dir / "reports" / "report.html").write_text("report", encoding="utf-8")

    manifest = run_production_audit(root=root, output_dir=tmp_path / "audit")
    evidence = Path(manifest["validation_evidence_matrix"]).read_text(encoding="utf-8")
    assert "scrna_mvp_10x_mtx" in evidence
    assert "analysis_level=demo_result" in evidence
    assert "guard_status=missing_guard_fields" in evidence


def test_production_capability_requires_guarded_validation_evidence(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    run_dir = root / "validations" / "slurm_tumor_sc_maynard_raw_counts"
    run_dir.mkdir(parents=True)
    (run_dir / "run_manifest.json").write_text('{"status": "ready"}', encoding="utf-8")

    manifest = run_production_audit(root=root, output_dir=tmp_path / "audit")

    matrix = Path(manifest["capability_matrix"]).read_text(encoding="utf-8")
    tumor_row = next(line for line in matrix.splitlines() if line.startswith("tumor_sc\t"))
    assert "partial:validation_manifest_not_ready" in tumor_row


def test_production_audit_accepts_perturb_public_validation_path(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    run_dir = root / "validations" / "slurm_perturb_seq_adamson_public"
    (run_dir / "results" / "tables").mkdir(parents=True)
    (run_dir / "results" / "figures").mkdir(parents=True)
    (run_dir / "objects").mkdir(parents=True)
    (run_dir / "reports").mkdir(parents=True)
    (run_dir / "run_manifest.json").write_text(
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
    for idx in range(6):
        (run_dir / "results" / "tables" / f"table_{idx}.tsv").write_text("a\n1\n", encoding="utf-8")
    for idx in range(3):
        (run_dir / "results" / "figures" / f"fig_{idx}.png").write_text("png", encoding="utf-8")
    (run_dir / "objects" / "perturb_seq_public_fixture_object.json").write_text("{}", encoding="utf-8")
    (run_dir / "reports" / "report.md").write_text("report", encoding="utf-8")
    (run_dir / "reports" / "report.html").write_text("report", encoding="utf-8")

    manifest = run_production_audit(root=root, output_dir=tmp_path / "audit")

    evidence = Path(manifest["validation_evidence_matrix"]).read_text(encoding="utf-8")
    assert "slurm_perturb_seq_adamson_public" in evidence
    perturb_evidence_row = next(line for line in evidence.splitlines() if line.startswith("slurm_perturb_seq\t"))
    assert "\tready\t" in perturb_evidence_row
    matrix = Path(manifest["capability_matrix"]).read_text(encoding="utf-8")
    perturb_row = next(line for line in matrix.splitlines() if line.startswith("perturb_seq\t"))
    assert "ready:public_or_existing_data_validation" in perturb_row
    assert "ready_basic" in perturb_row


def test_production_audit_final_acceptance_requires_prepared_job_delivery_mirror(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    job_dir = root / "jobs" / "JOB001"
    run_dir = job_dir / "runs" / "JOB001"
    run_dir.mkdir(parents=True)
    (job_dir / "job_manifest.json").write_text('{"job_id": "JOB001"}', encoding="utf-8")
    (run_dir / "run_manifest.json").write_text('{"status": "ready"}', encoding="utf-8")

    manifest = run_production_audit(root=root, output_dir=tmp_path / "audit")

    final = Path(manifest["final_acceptance_checklist"]).read_text(encoding="utf-8")
    row = next(line for line in final.splitlines() if line.startswith("prepared_job_delivery_mirror_ready\t"))
    assert "\tpartial\t" in row
    assert "checked_jobs=1" in row
    assert "latest_run_pointer" in row


def test_production_audit_final_acceptance_accepts_prepared_job_delivery_mirror(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    job_dir = root / "jobs" / "JOB001"
    run_dir = job_dir / "runs" / "JOB001"
    (job_dir / "deliverables").mkdir(parents=True)
    (job_dir / "reproducible_code").mkdir(parents=True)
    (run_dir / "results" / "figures" / "rnaseq").mkdir(parents=True)
    (run_dir / "results" / "tables" / "rnaseq").mkdir(parents=True)
    (run_dir / "objects" / "rnaseq").mkdir(parents=True)
    (run_dir / "reports").mkdir(parents=True)
    (run_dir / "reproducible_code").mkdir(parents=True)
    figure_path = run_dir / "results" / "figures" / "rnaseq" / "pca.png"
    table_path = run_dir / "results" / "tables" / "rnaseq" / "sample_qc.tsv"
    object_path = run_dir / "objects" / "rnaseq" / "rnaseq_mvp_object.rds"
    report_path = run_dir / "reports" / "report.html"
    methods_path = run_dir / "reports" / "methods.md"
    rerun_path = run_dir / "reproducible_code" / "rerun.sh"
    for path, text in {
        figure_path: "png",
        table_path: "sample_id\tqc\nS1\tok\n",
        object_path: "object",
        report_path: "<html>report</html>",
        methods_path: "methods",
        rerun_path: "#!/usr/bin/env bash\n",
    }.items():
        path.write_text(text, encoding="utf-8")
    (job_dir / "job_manifest.json").write_text('{"job_id": "JOB001"}', encoding="utf-8")
    run_manifest = {
        "status": "ready",
        "modules": [
            {
                "module": "rnaseq",
                "status": "complete_python_bulk_backend",
                "analysis_level": "demo_result",
                "is_demo": True,
                "is_stub": False,
                "delivery_allowed": False,
                "validation_evidence_allowed": False,
                "non_delivery_reason": "demo_result_not_customer_delivery",
                "artifacts": {
                    "figures": {"pca": str(figure_path)},
                    "tables": {"sample_qc": str(table_path)},
                    "objects": {"mvp_object": str(object_path)},
                },
            }
        ],
        "production_approval": {},
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(run_manifest), encoding="utf-8")
    required = {
        job_dir / "deliverables" / "latest_run_manifest.json": json.dumps(run_manifest),
        job_dir / "deliverables" / "latest_report.html": "<html>report</html>",
        job_dir / "deliverables" / "latest_methods.md": "methods",
        job_dir
        / "deliverables"
        / "latest_delivery_index.tsv": "\n".join(
            [
                "category\tpath\tsize_bytes",
                f"figure\t{figure_path}\t{figure_path.stat().st_size}",
                f"table\t{table_path}\t{table_path.stat().st_size}",
                f"object\t{object_path}\t{object_path.stat().st_size}",
                f"report\t{report_path}\t{report_path.stat().st_size}",
                f"report\t{methods_path}\t{methods_path.stat().st_size}",
                f"reproducible_code\t{rerun_path}\t{rerun_path.stat().st_size}",
            ]
        )
        + "\n",
        job_dir / "reproducible_code" / "rerun.sh": rerun_path.read_text(encoding="utf-8"),
        job_dir / "reproducible_code" / "software_versions.tsv": "name\tversion\nultimate\ttest\n",
        job_dir / "reproducible_code" / "latest_repro_manifest.json": '{"run_dir": "test"}',
        run_dir / "reproducible_code" / "repro_manifest.json": '{"run_dir": "test"}',
    }
    for path, text in required.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (job_dir / "deliverables" / "latest_run_pointer.json").write_text(
        json.dumps(
            {
                "latest_run_dir": str(run_dir),
                "run_manifest": str(run_dir / "run_manifest.json"),
                "copied_artifacts": {
                    "run_manifest": str(job_dir / "deliverables" / "latest_run_manifest.json"),
                    "report_html": str(job_dir / "deliverables" / "latest_report.html"),
                    "methods_md": str(job_dir / "deliverables" / "latest_methods.md"),
                    "delivery_index": str(job_dir / "deliverables" / "latest_delivery_index.tsv"),
                },
                "policy": "job-level files are small latest-run mirrors; large result objects remain referenced from the run directory",
            }
        ),
        encoding="utf-8",
    )

    manifest = run_production_audit(root=root, output_dir=tmp_path / "audit")

    final = Path(manifest["final_acceptance_checklist"]).read_text(encoding="utf-8")
    row = next(line for line in final.splitlines() if line.startswith("prepared_job_delivery_mirror_ready\t"))
    assert "\tpass\t" in row
    assert "checked_jobs=1 ready_jobs=1" in row


def test_production_audit_rejects_delivery_index_without_result_categories(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    job_dir = root / "jobs" / "JOB001"
    run_dir = job_dir / "runs" / "JOB001"
    (job_dir / "deliverables").mkdir(parents=True)
    (job_dir / "reproducible_code").mkdir(parents=True)
    (run_dir / "reports").mkdir(parents=True)
    (run_dir / "reproducible_code").mkdir(parents=True)
    (job_dir / "job_manifest.json").write_text('{"job_id": "JOB001"}', encoding="utf-8")
    run_manifest = {
        "status": "ready",
        "modules": [
            {
                "module": "rnaseq",
                "status": "complete_python_bulk_backend",
                "analysis_level": "demo_result",
                "is_demo": True,
                "is_stub": False,
                "delivery_allowed": False,
                "validation_evidence_allowed": False,
                "non_delivery_reason": "demo_result_not_customer_delivery",
            }
        ],
        "production_approval": {},
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(run_manifest), encoding="utf-8")
    report_path = run_dir / "reports" / "report.html"
    methods_path = run_dir / "reports" / "methods.md"
    rerun_path = run_dir / "reproducible_code" / "rerun.sh"
    for path, text in {
        report_path: "<html>report</html>",
        methods_path: "methods",
        rerun_path: "#!/usr/bin/env bash\n",
        run_dir / "reproducible_code" / "repro_manifest.json": '{"run_dir": "test"}',
    }.items():
        path.write_text(text, encoding="utf-8")
    required = {
        job_dir / "deliverables" / "latest_run_manifest.json": json.dumps(run_manifest),
        job_dir / "deliverables" / "latest_report.html": report_path.read_text(encoding="utf-8"),
        job_dir / "deliverables" / "latest_methods.md": methods_path.read_text(encoding="utf-8"),
        job_dir
        / "deliverables"
        / "latest_delivery_index.tsv": "\n".join(
            [
                "category\tpath\tsize_bytes",
                f"report\t{report_path}\t{report_path.stat().st_size}",
                f"report\t{methods_path}\t{methods_path.stat().st_size}",
                f"reproducible_code\t{rerun_path}\t{rerun_path.stat().st_size}",
            ]
        )
        + "\n",
        job_dir / "reproducible_code" / "rerun.sh": rerun_path.read_text(encoding="utf-8"),
        job_dir / "reproducible_code" / "software_versions.tsv": "name\tversion\nultimate\ttest\n",
        job_dir / "reproducible_code" / "latest_repro_manifest.json": '{"run_dir": "test"}',
    }
    for path, text in required.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (job_dir / "deliverables" / "latest_run_pointer.json").write_text(
        json.dumps(
            {
                "latest_run_dir": str(run_dir),
                "run_manifest": str(run_dir / "run_manifest.json"),
                "copied_artifacts": {
                    "run_manifest": str(job_dir / "deliverables" / "latest_run_manifest.json"),
                    "report_html": str(job_dir / "deliverables" / "latest_report.html"),
                    "methods_md": str(job_dir / "deliverables" / "latest_methods.md"),
                    "delivery_index": str(job_dir / "deliverables" / "latest_delivery_index.tsv"),
                },
                "policy": "job-level files are small latest-run mirrors; large result objects remain referenced from the run directory",
            }
        ),
        encoding="utf-8",
    )

    manifest = run_production_audit(root=root, output_dir=tmp_path / "audit")

    final = Path(manifest["final_acceptance_checklist"]).read_text(encoding="utf-8")
    row = next(line for line in final.splitlines() if line.startswith("prepared_job_delivery_mirror_ready\t"))
    assert "\tpartial\t" in row
    assert "delivery_index_missing_categories:figure,object,table" in row


def test_production_audit_final_acceptance_requires_validation_index_summary(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"

    manifest = run_production_audit(root=root, output_dir=tmp_path / "audit")

    final = Path(manifest["final_acceptance_checklist"]).read_text(encoding="utf-8")
    row = next(line for line in final.splitlines() if line.startswith("validation_index_summary_ready\t"))
    assert "\tpartial\t" in row
    assert "manifest_missing=" in row


def test_production_audit_final_acceptance_accepts_validation_index_summary(tmp_path: Path) -> None:
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
    build_validation_index(root=root, output_dir=root / "reports" / "validation_index")

    manifest = run_production_audit(root=root, output_dir=tmp_path / "audit")

    final = Path(manifest["final_acceptance_checklist"]).read_text(encoding="utf-8")
    row = next(line for line in final.splitlines() if line.startswith("validation_index_summary_ready\t"))
    assert "\tpass\t" in row
    assert "n_runs=1" in row
    assert "ready_validation_evidence=1" in row
