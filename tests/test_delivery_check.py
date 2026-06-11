from __future__ import annotations

import json
import shutil
from pathlib import Path

from click.testing import CliRunner

from ultimate.cli import main
from ultimate.customer_package import build_customer_package
from ultimate.delivery_check import run_delivery_check


def test_delivery_check_accepts_production_job_with_required_artifacts(tmp_path: Path) -> None:
    job_dir, run_dir = _write_delivery_ready_job(tmp_path)

    manifest = run_delivery_check(job_dir)

    assert manifest["status"] == "ready"
    assert manifest["delivery_allowed"] is True
    assert (run_dir / "reports" / "delivery_check.json").exists()
    assert (job_dir / "deliverables" / "latest_delivery_check.json").exists()


def test_delivery_check_blocks_validated_only_run(tmp_path: Path) -> None:
    _, run_dir = _write_delivery_ready_job(tmp_path)
    payload = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    payload["analysis_level"] = "validated_backend"
    payload["delivery_allowed"] = False
    payload["delivery_gate"]["delivery_allowed"] = False
    (run_dir / "run_manifest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    manifest = run_delivery_check(run_dir)

    assert manifest["status"] == "blocked"
    assert "analysis_level_production" in manifest["blockers"]
    assert "delivery_allowed_true" in manifest["blockers"]


def test_delivery_check_blocks_missing_slurm_and_repro_artifacts(tmp_path: Path) -> None:
    _, run_dir = _write_delivery_ready_job(tmp_path)
    payload = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    payload["slurm_job_id"] = ""
    payload["slurm"]["slurm_job_id"] = ""
    (run_dir / "run_manifest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (run_dir / "reproducible_code" / "input_checksums.tsv").unlink()

    manifest = run_delivery_check(run_dir)

    assert manifest["status"] == "blocked"
    assert "slurm_job_id" in manifest["blockers"]
    assert "input_checksums" in manifest["blockers"]


def test_cli_delivery_check_exits_nonzero_when_blocked(tmp_path: Path) -> None:
    _, run_dir = _write_delivery_ready_job(tmp_path)
    payload = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    payload["is_demo"] = True
    (run_dir / "run_manifest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    result = CliRunner().invoke(main, ["delivery-check", "--run-dir", str(run_dir)])

    assert result.exit_code != 0
    assert "not_demo" in result.output


def _write_delivery_ready_job(tmp_path: Path, *, delivery_scope: str = "internal_rehearsal") -> tuple[Path, Path]:
    job_dir = tmp_path / "jobs" / "ORDER001"
    run_dir = job_dir / "runs" / "ORDER001"
    for directory in (
        run_dir / "reports",
        run_dir / "results" / "tables",
        run_dir / "results" / "figures",
        run_dir / "objects",
        run_dir / "reproducible_code",
        job_dir / "deliverables",
        job_dir / "reproducible_code",
        job_dir / "config",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    (job_dir / "job_manifest.json").write_text('{"job_id": "ORDER001"}', encoding="utf-8")
    config_path = job_dir / "config" / "project.yaml"
    config_path.write_text("project:\n  name: ORDER001\n", encoding="utf-8")

    files = {
        run_dir / "reports" / "report.html": "<html>analysis_level delivery_allowed 警示 不能伪装</html>",
        run_dir / "reports" / "methods.md": "# methods\nanalysis_level delivery_allowed 警示\n",
        run_dir / "results" / "tables" / "markers.tsv": "gene\tscore\nA\t1\n",
        run_dir / "results" / "figures" / "umap.png": "png",
        run_dir / "objects" / "object.h5ad": "object",
        run_dir / "reproducible_code" / "rerun.sh": "#!/usr/bin/env bash\n",
        run_dir / "reproducible_code" / "software_versions.tsv": "kind\tname\tversion\npython\tultimate\ttest\n",
        run_dir / "reproducible_code" / "input_checksums.tsv": "key\tpath\texists\nconfig\tproject.yaml\ttrue\n",
        run_dir / "reproducible_code" / "README.md": "# Reproducible package\n",
        run_dir / "results" / "tables" / "figure_manifest.tsv": (
            "figure_id\tmodule\tkind\tpath\tstyle_id\ttitle\tstatus\tlayout_status\tlayout_warning\n"
            f"umap\tscrna\tumap\t{run_dir / 'results' / 'figures' / 'umap.png'}\ttest\tUMAP\tready\tlayout_pass\t\n"
        ),
        run_dir / "results" / "tables" / "layout_qc.tsv": (
            "figure_id\tpath\tlayout_status\tlayout_warning\n"
            f"umap\t{run_dir / 'results' / 'figures' / 'umap.png'}\tlayout_pass\t\n"
        ),
        run_dir / "results" / "tables" / "advanced_backend_execution_manifest.json": json.dumps(
            {
                "status": "ready",
                "backend_count": 1,
                "rows": [
                    {
                        "module": "scrna",
                        "backend_id": "scrna.communication.cellchat_optional",
                        "backend_registry_status": "fully_automatic_validated_entrypoint",
                        "execution_status": "ready",
                        "interpretation_warning": "candidate communication inference, not mechanism proof",
                    }
                ],
            }
        ),
    }
    for path, text in files.items():
        path.write_text(text, encoding="utf-8")

    delivery_rows = [
        ("figure", run_dir / "results" / "figures" / "umap.png"),
        ("table", run_dir / "results" / "tables" / "markers.tsv"),
        ("object", run_dir / "objects" / "object.h5ad"),
        ("report", run_dir / "reports" / "report.html"),
        ("reproducible_code", run_dir / "reproducible_code" / "rerun.sh"),
    ]
    delivery_index = "category\tpath\tsize_bytes\tmodule\tartifact_key\tartifact_scope\n" + "\n".join(
        f"{category}\t{path}\t{path.stat().st_size}\tscrna\t{path.stem}\trun" for category, path in delivery_rows
    )
    (run_dir / "delivery_index.tsv").write_text(delivery_index + "\n", encoding="utf-8")
    repro_manifest = {
        "rerun_script": str(run_dir / "reproducible_code" / "rerun.sh"),
        "software_versions": str(run_dir / "reproducible_code" / "software_versions.tsv"),
        "input_checksums": str(run_dir / "reproducible_code" / "input_checksums.tsv"),
        "delivery_index": str(run_dir / "delivery_index.tsv"),
    }
    (run_dir / "reproducible_code" / "repro_manifest.json").write_text(json.dumps(repro_manifest, indent=2), encoding="utf-8")

    manifest = {
        "status": "ready",
        "analysis_level": "production_backend",
        "is_demo": False,
        "is_stub": False,
        "delivery_allowed": True,
        "validation_evidence_allowed": True,
        "non_delivery_reason": "",
        "delivery_scope": delivery_scope,
        "delivery_mode": "customer_delivery_rehearsal" if delivery_scope == "customer_delivery" else "internal_rehearsal",
        "slurm_job_id": "12345",
        "slurm": {"slurm_job_id": "12345", "slurm_job_name": "pytest_rehearsal"},
        "production_approval": {
            "approved": True,
            "approved_by": "pytest",
            "approved_at": "2026-06-08T00:00:00Z",
            "project_id": "ORDER001",
            "input_path": str(config_path),
            "output_dir": str(run_dir),
            "delivery_scope": delivery_scope,
            "delivery_mode": "customer_delivery_rehearsal" if delivery_scope == "customer_delivery" else "internal_rehearsal",
            "reason": "pytest delivery check",
        },
        "delivery_gate": {
            "status": "ready",
            "delivery_allowed": True,
            "approval_status": "approved",
            "delivery_scope": delivery_scope,
            "delivery_mode": "customer_delivery_rehearsal" if delivery_scope == "customer_delivery" else "internal_rehearsal",
            "blockers": [],
        },
        "modules": [
            {
                "module": "scrna",
                "status": "ready",
                "analysis_level": "production_backend",
                "delivery_allowed": True,
                "validation_evidence_allowed": True,
                "is_demo": False,
                "is_stub": False,
            }
        ],
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (job_dir / "deliverables" / "latest_run_pointer.json").write_text(
        json.dumps({"latest_run_dir": str(run_dir)}, indent=2),
        encoding="utf-8",
    )
    return job_dir, run_dir


def test_delivery_check_blocks_layout_warning(tmp_path: Path) -> None:
    _, run_dir = _write_delivery_ready_job(tmp_path)
    (run_dir / "results" / "tables" / "layout_qc.tsv").write_text(
        "figure_id\tpath\tlayout_status\tlayout_warning\n"
        f"umap\t{run_dir / 'results' / 'figures' / 'umap.png'}\tlayout_warning\tsmall_canvas\n",
        encoding="utf-8",
    )

    manifest = run_delivery_check(run_dir)

    assert manifest["status"] == "blocked"
    assert "layout_qc_no_warnings" in manifest["blockers"]


def test_delivery_check_blocks_missing_backend_warning(tmp_path: Path) -> None:
    _, run_dir = _write_delivery_ready_job(tmp_path)
    advanced_path = run_dir / "results" / "tables" / "advanced_backend_execution_manifest.json"
    payload = json.loads(advanced_path.read_text(encoding="utf-8"))
    payload["rows"][0]["interpretation_warning"] = ""
    advanced_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    manifest = run_delivery_check(run_dir)

    assert manifest["status"] == "blocked"
    assert "advanced_backend_warnings_present" in manifest["blockers"]


def test_delivery_check_blocks_customer_delivery_without_sanitized_package(tmp_path: Path) -> None:
    _, run_dir = _write_delivery_ready_job(tmp_path, delivery_scope="customer_delivery")

    manifest = run_delivery_check(run_dir)

    assert manifest["status"] == "blocked"
    assert "customer_package_dir" in manifest["blockers"]


def test_delivery_check_blocks_customer_delivery_without_delivery_mode(tmp_path: Path) -> None:
    job_dir, run_dir = _write_delivery_ready_job(tmp_path, delivery_scope="customer_delivery")
    manifest_path = run_dir / "run_manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload.pop("delivery_mode", None)
    payload["production_approval"].pop("delivery_mode", None)
    payload["delivery_gate"].pop("delivery_mode", None)
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _write_customer_package(job_dir)

    manifest = run_delivery_check(job_dir)

    assert manifest["status"] == "blocked"
    assert "delivery_mode_customer_declared" in manifest["blockers"]


def test_delivery_check_blocks_customer_package_internal_path_leak(tmp_path: Path) -> None:
    job_dir, _ = _write_delivery_ready_job(tmp_path, delivery_scope="customer_delivery")
    _write_customer_package(job_dir, extra_report_text="/shared/shen/2026/ultimate/jobs/ORDER001")

    manifest = run_delivery_check(job_dir)

    assert manifest["status"] == "blocked"
    assert "customer_package_no_internal_path_leaks" in manifest["blockers"]


def test_delivery_check_blocks_customer_package_raw_and_slurm_hints(tmp_path: Path) -> None:
    job_dir, _ = _write_delivery_ready_job(tmp_path, delivery_scope="customer_delivery")
    _write_customer_package(job_dir, extra_table_text="raw data path\tSLURM_JOB_ID\n/customer/raw\t12345\n")

    manifest = run_delivery_check(job_dir)

    assert manifest["status"] == "blocked"
    assert "customer_package_no_internal_path_leaks" in manifest["blockers"]


def test_delivery_check_blocks_customer_package_manifest_internal_path_leak(tmp_path: Path) -> None:
    job_dir, _ = _write_delivery_ready_job(tmp_path, delivery_scope="customer_delivery")
    _write_customer_package(job_dir)
    (job_dir / "deliverables" / "customer" / "customer_package_manifest.tsv").write_text(
        "artifact_type\tcustomer_path\tnote\n"
        "report\treport.html\t/shared/shen/2026/ultimate/jobs/ORDER001/reports/report.html\n",
        encoding="utf-8",
    )

    manifest = run_delivery_check(job_dir)

    assert manifest["status"] == "blocked"
    assert "customer_package_no_internal_path_leaks" in manifest["blockers"]


def test_delivery_check_blocks_customer_package_missing_rich_contents(tmp_path: Path) -> None:
    job_dir, _ = _write_delivery_ready_job(tmp_path, delivery_scope="customer_delivery")
    _write_customer_package(job_dir)
    (job_dir / "deliverables" / "customer" / "readme_for_customer.md").unlink()
    (job_dir / "deliverables" / "customer" / "customer_package_manifest.tsv").unlink()
    (job_dir / "deliverables" / "customer" / "figures" / "umap.png").unlink()
    (job_dir / "deliverables" / "customer" / "tables" / "markers.tsv").unlink()

    manifest = run_delivery_check(job_dir)

    assert manifest["status"] == "blocked"
    assert "customer_package_readme_for_customer.md" in manifest["blockers"]
    assert "customer_package_customer_package_manifest.tsv" in manifest["blockers"]
    assert "customer_package_figures_nonempty" in manifest["blockers"]
    assert "customer_package_tables_nonempty" in manifest["blockers"]


def test_delivery_check_blocks_customer_package_without_interpretation_warning(tmp_path: Path) -> None:
    job_dir, _ = _write_delivery_ready_job(tmp_path, delivery_scope="customer_delivery")
    _write_customer_package(job_dir, include_warning=False)

    manifest = run_delivery_check(job_dir)

    assert manifest["status"] == "blocked"
    assert "customer_package_interpretation_warning" in manifest["blockers"]


def test_delivery_check_accepts_sanitized_customer_delivery_package(tmp_path: Path) -> None:
    job_dir, _ = _write_delivery_ready_job(tmp_path, delivery_scope="customer_delivery")
    _write_customer_package(job_dir)

    manifest = run_delivery_check(job_dir)

    assert manifest["status"] == "ready"
    assert manifest["delivery_allowed"] is True


def test_customer_package_cli_builds_sanitized_package_from_job(tmp_path: Path) -> None:
    job_dir, run_dir = _write_delivery_ready_job(tmp_path, delivery_scope="customer_delivery")
    (run_dir / "reports" / "report.html").write_text(
        "<html>analysis_level production_backend delivery_allowed true /shared/shen/2026/ultimate/jobs/ORDER001 raw data path warning</html>",
        encoding="utf-8",
    )

    package_manifest = build_customer_package(run_dir=job_dir)

    assert package_manifest["status"] == "ready"
    customer_dir = job_dir / "deliverables" / "customer"
    assert (customer_dir / "sanitization.tsv").exists()
    assert (customer_dir / "customer_delivery_sanitization.tsv").exists()
    assert (customer_dir / "customer_package_manifest.tsv").exists()
    assert "/shared" not in (customer_dir / "report.html").read_text(encoding="utf-8")
    assert "raw data path" not in (customer_dir / "report.html").read_text(encoding="utf-8")
    check = run_delivery_check(job_dir)
    assert check["status"] == "ready"


def test_customer_package_cli_command(tmp_path: Path) -> None:
    job_dir, _ = _write_delivery_ready_job(tmp_path, delivery_scope="customer_delivery")

    result = CliRunner().invoke(main, ["customer-package", "--run-dir", str(job_dir)])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ready"
    assert (job_dir / "deliverables" / "customer" / "readme_for_customer.md").exists()


def _write_customer_package(
    job_dir: Path,
    *,
    extra_report_text: str = "",
    extra_table_text: str = "",
    include_warning: bool = True,
) -> None:
    customer_dir = job_dir / "deliverables" / "customer"
    customer_dir.mkdir(parents=True, exist_ok=True)
    (customer_dir / "figures").mkdir(parents=True, exist_ok=True)
    (customer_dir / "tables").mkdir(parents=True, exist_ok=True)
    report_warning = "警示：统计结果不是机制证明。" if include_warning else "Results are summarized for review."
    methods_warning = "警示：推断结果需要人工解释。" if include_warning else "Analyses were run with the approved preset."
    readme_warning = "Interpretation warning: results require human review." if include_warning else "Customer package contents are listed below."
    (customer_dir / "report.html").write_text(
        f"<html><body>Customer report. analysis_level production_backend. {report_warning}{extra_report_text}</body></html>",
        encoding="utf-8",
    )
    (customer_dir / "methods.md").write_text(
        f"# Customer methods\n\nanalysis_level: production_backend\n\n{methods_warning}\n",
        encoding="utf-8",
    )
    (customer_dir / "readme_for_customer.md").write_text(
        f"# Customer package\n\n{readme_warning}\n\nFiles under figures/ and tables/ are sanitized delivery artifacts.\n",
        encoding="utf-8",
    )
    (customer_dir / "delivery_index.tsv").write_text(
        "category\tfile\tnote\n"
        "report\treport.html\tcustomer-facing sanitized report\n"
        "methods\tmethods.md\tcustomer-facing methods\n"
        "readme\treadme_for_customer.md\tcustomer package guide\n"
        "figure\tfigures/umap.png\tcustomer-facing figure\n"
        "table\ttables/markers.tsv\tcustomer-facing table\n",
        encoding="utf-8",
    )
    (customer_dir / "customer_package_manifest.tsv").write_text(
        "artifact_type\tcustomer_path\tnote\n"
        "report\treport.html\tcustomer-facing sanitized report\n"
        "methods\tmethods.md\tcustomer-facing methods\n"
        "readme\treadme_for_customer.md\tcustomer package guide\n"
        "sanitization\tsanitization.tsv\tcustomer-facing sanitization checks\n"
        "figure\tfigures/umap.png\tcustomer-facing figure\n"
        "table\ttables/markers.tsv\tcustomer-facing table\n",
        encoding="utf-8",
    )
    (customer_dir / "customer_delivery_sanitization.tsv").write_text(
        "check_id\tstatus\tnote\tpath\n"
        "internal_path_exposure\tpass\tno internal path in customer package\t\n"
        "raw_path_exposure\tpass\tno raw path in customer package\t\n"
        "sensitive_metadata\tpass\tno sensitive metadata fields detected\t\n"
        "interpretation_warning\tpass\tcustomer report includes boundary warning\t\n",
        encoding="utf-8",
    )
    shutil.copyfile(customer_dir / "customer_delivery_sanitization.tsv", customer_dir / "sanitization.tsv")
    (customer_dir / "customer_package_manifest.tsv").write_text(
        "artifact_type\tfile\tcustomer_visible\tsanitized\tnote\n"
        "report\treport.html\ttrue\ttrue\tsanitized report\n"
        "methods\tmethods.md\ttrue\ttrue\tsanitized methods\n"
        "readme\treadme_for_customer.md\ttrue\ttrue\tcustomer guide\n"
        "figure\tfigures/umap.png\ttrue\ttrue\tcustomer figure\n"
        "table\ttables/markers.tsv\ttrue\ttrue\tcustomer table\n",
        encoding="utf-8",
    )
    (customer_dir / "figures" / "umap.png").write_text("png", encoding="utf-8")
    (customer_dir / "tables" / "markers.tsv").write_text(
        "gene\tscore\nA\t1\n" + extra_table_text,
        encoding="utf-8",
    )
