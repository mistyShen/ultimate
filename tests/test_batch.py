from __future__ import annotations

import csv
import json
from pathlib import Path

import yaml

from ultimate.batch import BATCH_NON_DELIVERY_REASON, prepare_batch
from ultimate.batch_status import build_batch_status
from ultimate.cli import main
from ultimate.config import dump_yaml


def test_prepare_batch_scaffolds_two_jobs_without_copying_raw_data(tmp_path: Path) -> None:
    raw_dir = tmp_path / "customer_raw"
    raw_dir.mkdir()
    raw_counts = raw_dir / "raw_counts.tsv"
    raw_counts.write_text("gene\tS1\tS2\nG1\t10\t20\n", encoding="utf-8")
    samplesheet = tmp_path / "samples.tsv"
    samplesheet.write_text(f"sample_id\tcondition\tinput_path\nS1\tcontrol\t{raw_counts}\n", encoding="utf-8")
    request = tmp_path / "request.yaml"
    request.write_text("analysis_presets:\n  - basic\n", encoding="utf-8")

    config_a = _write_project_config(tmp_path / "config_a.yaml", raw_counts)
    config_b = _write_project_config(tmp_path / "config_b.yaml", raw_counts)
    root = tmp_path / "shared" / "shen" / "2026" / "ultimate"
    batch_path = tmp_path / "batch.yaml"
    batch_path.write_text(
        yaml.safe_dump(
            {
                "batch_id": "pytest_batch",
                "root": str(root),
                "jobs": [
                    {"job_id": "ORDER_A", "config": str(config_a), "request": str(request), "samplesheet": str(samplesheet)},
                    {"job_id": "ORDER_B", "config": str(config_b), "request": str(request), "samplesheet": str(samplesheet)},
                    {"job_id": "ORDER_BLOCKED", "config": str(tmp_path / "missing.yaml")},
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    manifest = prepare_batch(batch_path=batch_path)

    assert manifest["jobs_total"] == 3
    assert manifest["jobs_ready"] == 2
    assert manifest["jobs_blocked"] == 1
    assert manifest["status_counts"]["ready_to_run"] == 2
    assert manifest["status_counts"]["blocked"] == 1
    assert manifest["delivery_allowed"] is False
    assert manifest["non_delivery_reason"] == BATCH_NON_DELIVERY_REASON
    assert manifest["policy"]["runs_analysis"] is False
    assert manifest["policy"]["submits_slurm"] is False
    assert manifest["policy"]["remote_commands"] is False

    for job_id in ("ORDER_A", "ORDER_B"):
        job_dir = root / "jobs" / job_id
        assert job_dir.is_dir()
        assert (job_dir / "config" / "project.yaml").exists()
        assert not list(job_dir.rglob(raw_counts.name))
        approval = json.loads((job_dir / "config" / "production_approval.json").read_text(encoding="utf-8"))
        assert approval["approved"] is False
        assert approval["delivery_scope"] == "internal_rehearsal"

    blocked_dir = root / "jobs" / "ORDER_BLOCKED"
    assert not blocked_dir.exists()
    rows = _read_summary(Path(manifest["artifacts"]["summary_tsv"]))
    assert [row["status"] for row in rows] == ["ready_to_run", "ready_to_run", "blocked"]
    assert {row["scaffold_status"] for row in rows} == {"scaffolded", "not_scaffolded"}
    assert all(row["delivery_allowed"] == "false" for row in rows)
    assert all(row["non_delivery_reason"] == BATCH_NON_DELIVERY_REASON for row in rows)
    assert rows[0]["production_approval_allowed"] == "true"
    assert rows[0]["next_action"] == "run_preflight_then_request_production_approval"
    assert (root / "jobs" / "ORDER_A" / "failure_recovery.md").exists()
    assert rows[0]["approval_status"] == "template_pending_approval"
    assert "config does not exist" in rows[2]["blockers"]
    report = Path(manifest["artifacts"]["report_md"]).read_text(encoding="utf-8")
    assert "delivery_allowed: false" in report
    assert "jobs_ready_to_run: 2" in report
    assert "no analysis, Slurm submission, or remote command is run" in report


def test_prepare_batch_cli_scaffolds_jobs(tmp_path: Path) -> None:
    from click.testing import CliRunner

    raw_counts = tmp_path / "raw_counts.tsv"
    raw_counts.write_text("gene\tS1\nG1\t5\n", encoding="utf-8")
    config_path = _write_project_config(tmp_path / "config.yaml", raw_counts)
    root = tmp_path / "shared" / "shen" / "2026" / "ultimate"
    batch_path = tmp_path / "batch.yaml"
    batch_path.write_text(
        yaml.safe_dump({"batch_id": "cli_batch", "root": str(root), "jobs": [{"job_id": "CLI001", "config": str(config_path)}]}),
        encoding="utf-8",
    )

    result = CliRunner().invoke(main, ["prepare-batch", "--batch", str(batch_path)])

    assert result.exit_code == 0, result.output
    manifest = json.loads(result.output)
    assert manifest["analysis_level"] == "smoke_backend"
    assert manifest["delivery_allowed"] is False
    assert (root / "jobs" / "CLI001" / "config" / "project.yaml").exists()


def test_prepare_batch_supports_json_and_explicit_customer_approval_without_delivery(tmp_path: Path) -> None:
    raw_counts = tmp_path / "raw_counts.tsv"
    raw_counts.write_text("gene\tS1\nG1\t5\n", encoding="utf-8")
    config_path = _write_project_config(tmp_path / "config.yaml", raw_counts)
    root = tmp_path / "shared" / "shen" / "2026" / "ultimate"
    batch_path = tmp_path / "batch.json"
    batch_path.write_text(
        json.dumps(
            {
                "batch_id": "json_batch",
                "root": str(root),
                "jobs": [
                    {
                        "job_id": "JSON001",
                        "config": str(config_path),
                        "approval": {
                            "approved": True,
                            "approved_by": "pytest",
                            "approved_at": "2026-06-11T00:00:00Z",
                            "delivery_scope": "customer_delivery",
                            "reason": "pytest explicit approval metadata only",
                        },
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    manifest = prepare_batch(batch_path=batch_path)

    assert manifest["jobs_ready"] == 0
    assert manifest["delivery_allowed"] is False
    assert manifest["non_delivery_reason"] == BATCH_NON_DELIVERY_REASON
    rows = _read_summary(Path(manifest["artifacts"]["summary_tsv"]))
    assert rows[0]["status"] == "needs_metadata"
    assert rows[0]["approval_status"] == "customer_approved"
    assert rows[0]["production_approval_allowed"] == "false"
    assert rows[0]["delivery_allowed"] == "false"
    approval = json.loads((root / "jobs" / "JSON001" / "config" / "production_approval.json").read_text(encoding="utf-8"))
    assert approval["approved"] is True
    assert approval["delivery_scope"] == "customer_delivery"


def test_prepare_batch_marks_fastq_inputs_as_raw_upstream_required(tmp_path: Path) -> None:
    fastq = tmp_path / "reads.fastq"
    fastq.write_text("@r1\nACGT\n+\n!!!!\n", encoding="utf-8")
    samplesheet = tmp_path / "samples.tsv"
    samplesheet.write_text(f"sample_id\tcondition\tfastq_1\nS1\tcase\t{fastq}\n", encoding="utf-8")
    request = tmp_path / "request.md"
    request.write_text("Run rnaseq standard after raw upstream handoff.\n", encoding="utf-8")
    config_path = _write_project_config(tmp_path / "fastq_config.yaml", fastq)
    root = tmp_path / "shared" / "shen" / "2026" / "ultimate"
    batch_path = tmp_path / "batch.yaml"
    batch_path.write_text(
        yaml.safe_dump(
            {
                "batch_id": "fastq_batch",
                "root": str(root),
                "jobs": [{"job_id": "FASTQ001", "config": str(config_path), "samplesheet": str(samplesheet), "request": str(request)}],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    manifest = prepare_batch(batch_path=batch_path)

    assert manifest["jobs_ready"] == 0
    assert manifest["status_counts"]["raw_upstream_required"] == 1
    rows = _read_summary(Path(manifest["artifacts"]["summary_tsv"]))
    assert rows[0]["status"] == "raw_upstream_required"
    assert rows[0]["production_approval_allowed"] == "false"
    recovery = (root / "jobs" / "FASTQ001" / "failure_recovery.md").read_text(encoding="utf-8")
    assert "failure_stage: `raw_upstream`" in recovery
    assert "slurm_required: `true`" in recovery


def test_batch_status_summarizes_raw_run_customer_and_delivery(tmp_path: Path) -> None:
    raw_counts = tmp_path / "raw_counts.tsv"
    raw_counts.write_text("gene\tS1\nG1\t5\n", encoding="utf-8")
    config_path = _write_project_config(tmp_path / "config.yaml", raw_counts)
    root = tmp_path / "shared" / "shen" / "2026" / "ultimate"
    batch_path = tmp_path / "batch.yaml"
    batch_path.write_text(
        yaml.safe_dump({"batch_id": "status_batch", "root": str(root), "jobs": [{"job_id": "STATUS001", "config": str(config_path)}]}),
        encoding="utf-8",
    )
    prepare_batch(batch_path=batch_path)
    job_dir = root / "jobs" / "STATUS001"
    raw_dir = job_dir / "raw_upstream" / "rnaseq"
    raw_dir.mkdir(parents=True)
    (raw_dir / "raw_upstream_manifest.json").write_text('{"status": "ready"}', encoding="utf-8")
    run_dir = job_dir / "runs" / "STATUS001"
    run_dir.mkdir(parents=True)
    (run_dir / "run_manifest.json").write_text('{"status": "ready"}', encoding="utf-8")
    (job_dir / "deliverables" / "latest_run_pointer.json").write_text(json.dumps({"latest_run_dir": str(run_dir)}), encoding="utf-8")
    customer_dir = job_dir / "deliverables" / "customer"
    customer_dir.mkdir(parents=True)
    for name in ("report.html", "methods.md", "delivery_index.tsv", "sanitization.tsv", "customer_package_manifest.tsv", "readme_for_customer.md"):
        (customer_dir / name).write_text("ok\n", encoding="utf-8")
    (job_dir / "deliverables" / "latest_delivery_check.json").write_text('{"status": "ready"}', encoding="utf-8")

    manifest = build_batch_status(batch_dir=root / "batches" / "status_batch")

    assert manifest["job_count"] == 1
    row = manifest["rows"][0]
    assert row["raw_upstream_status"] == "ready"
    assert row["run_status"] == "ready"
    assert row["customer_package_status"] == "ready"
    assert row["delivery_check_status"] == "ready"
    assert row["overall_status"] == "ready_for_customer_delivery_rehearsal"
    assert Path(manifest["artifacts"]["batch_status_tsv"]).exists()


def test_batch_status_cli(tmp_path: Path) -> None:
    batch_dir = tmp_path / "batch"
    jobs_dir = batch_dir / "jobs" / "JOB001"
    jobs_dir.mkdir(parents=True)
    (jobs_dir / "job_manifest.json").write_text('{"job_id": "JOB001"}', encoding="utf-8")

    from click.testing import CliRunner

    result = CliRunner().invoke(main, ["batch-status", "--batch-dir", str(batch_dir)])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["job_count"] == 1
    assert payload["rows"][0]["overall_status"] == "blocked"


def test_batch_status_job_glob_limits_large_job_roots(tmp_path: Path) -> None:
    jobs_root = tmp_path / "jobs"
    for job_id in ("v4_2_rnaseq_trial_20260611", "v4_2_scrna_trial_20260611", "old_historical_job"):
        job_dir = jobs_root / job_id
        job_dir.mkdir(parents=True)
        (job_dir / "job_manifest.json").write_text(json.dumps({"job_id": job_id}), encoding="utf-8")

    manifest = build_batch_status(batch_dir=jobs_root, output_dir=tmp_path / "status", job_glob="v4_2_*_20260611")

    assert manifest["job_count"] == 2
    assert manifest["job_glob"] == "v4_2_*_20260611"
    assert {row["job_id"] for row in manifest["rows"]} == {"v4_2_rnaseq_trial_20260611", "v4_2_scrna_trial_20260611"}


def test_batch_status_cli_job_glob(tmp_path: Path) -> None:
    jobs_root = tmp_path / "jobs"
    for job_id in ("KEEP_A", "DROP_A"):
        job_dir = jobs_root / job_id
        job_dir.mkdir(parents=True)
        (job_dir / "job_manifest.json").write_text(json.dumps({"job_id": job_id}), encoding="utf-8")

    from click.testing import CliRunner

    result = CliRunner().invoke(main, ["batch-status", "--batch-dir", str(jobs_root), "--job-glob", "KEEP_*"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["job_count"] == 1
    assert payload["rows"][0]["job_id"] == "KEEP_A"


def _write_project_config(path: Path, raw_counts: Path) -> Path:
    return dump_yaml(
        {
            "project": {
                "name": path.stem,
                "organism": "human",
                "output_dir": "../runs/placeholder",
                "server_root": "/shared/shen/2026/ultimate",
            },
            "modules": {
                "rnaseq": {
                    "enabled": True,
                    "raw": {"input_path": str(raw_counts)},
                }
            },
        },
        path,
    )


def _read_summary(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))
