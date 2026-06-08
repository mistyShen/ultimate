from __future__ import annotations

import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from ultimate.cli import main
from ultimate.config import load_config
from ultimate.demo import init_project
from ultimate.job import prepare_job
from ultimate.preflight import run_preflight


def test_prepare_job_creates_shared_layout_and_command_plan(tmp_path: Path) -> None:
    source = init_project("rnaseq", tmp_path / "source_project", demo_data=True)
    root = tmp_path / "shared" / "shen" / "2026" / "ultimate"

    manifest = prepare_job(config_path=Path(source["config_path"]), job_id="ORDER 001", root=root)

    job_dir = root / "jobs" / "ORDER_001"
    assert Path(manifest["job_dir"]) == job_dir
    for name in ("raw_links", "config", "samples", "runs", "logs", "deliverables", "reproducible_code", "work"):
        assert (job_dir / name).is_dir()
    assert (job_dir / "config" / "project.yaml").exists()
    assert (job_dir / "config" / "production_approval.json").exists()
    assert (job_dir / "config" / "submit.sh").exists()
    assert (job_dir / "config" / "run_ultimate.sbatch").exists()
    assert manifest["job_slurm_script"] == str(job_dir / "config" / "run_ultimate.sbatch")
    assert manifest["approval_gate"]["required"] is True
    assert manifest["approval_gate"]["status"] == "template_pending_approval"
    assert manifest["samplesheet_status"]["status"] == "copied"
    assert manifest["analysis_request_status"]["status"] == "copied"
    raw_manifest = job_dir / "raw_links" / "input_paths_manifest.tsv"
    assert manifest["raw_input_manifest"] == str(raw_manifest)
    assert raw_manifest.exists()
    assert "read_only_reference" in raw_manifest.read_text(encoding="utf-8")
    assert manifest["slurm_adapter"]["status"] == "missing"
    assert manifest["slurm_adapter"]["path"] == str(root / "slurm" / "ultimate_run.sbatch")
    command_plan = (job_dir / "config" / "command_plan.md").read_text(encoding="utf-8")
    assert "hpc-sbatch" in command_plan
    assert f"hpc-sbatch {job_dir / 'config' / 'run_ultimate.sbatch'}" in command_plan
    assert "ultimate_run.sbatch" in command_plan
    assert "只接收一个远端脚本路径" in command_plan
    assert "未检测到 Slurm wrapper" in command_plan
    assert "production_approval.json" in command_plan
    assert "approved" in command_plan
    assert "true" in command_plan
    assert str(job_dir / "logs") in command_plan
    submit_script = (job_dir / "config" / "submit.sh").read_text(encoding="utf-8")
    assert "slurm_submit_" in submit_script
    assert 'LOG_DIR="$JOB_DIR/logs"' in submit_script
    assert "production approval JSON is not approved=true" in submit_script
    assert "production approval input_path mismatch" in submit_script
    assert "production approval output_dir mismatch" in submit_script
    assert "hpc-sbatch" in submit_script
    assert str(job_dir / "config" / "run_ultimate.sbatch") in submit_script
    assert "ultimate_run.sbatch" not in submit_script
    job_slurm = (job_dir / "config" / "run_ultimate.sbatch").read_text(encoding="utf-8")
    assert "ultimate_run.sbatch" in job_slurm
    assert str(job_dir / "config" / "project.yaml") in job_slurm
    assert str(job_dir / "config" / "production_approval.json") in job_slurm

    config = load_config(job_dir / "config" / "project.yaml").raw
    assert config["project"]["job_id"] == "ORDER_001"
    assert config["project"]["run_mode"] == "production"
    assert Path(config["project"]["output_dir"]) == job_dir / "runs" / "ORDER_001"
    assert config["project"]["production_approval"] == str((job_dir / "config" / "production_approval.json").resolve())
    preflight = run_preflight(config, write=False)
    assert preflight["job_layout"]["status"] == "ready"

    approval = json.loads((job_dir / "config" / "production_approval.json").read_text(encoding="utf-8"))
    assert approval["approved"] is False
    assert approval["input_path"] == str((job_dir / "config" / "project.yaml").resolve())
    assert approval["output_dir"] == str((job_dir / "runs" / "ORDER_001").resolve())


def test_prepare_job_submit_script_blocks_mismatched_approval_before_sbatch(tmp_path: Path) -> None:
    source = init_project("rnaseq", tmp_path / "source_submit_guard", demo_data=True)
    root = tmp_path / "shared" / "shen" / "2026" / "ultimate"
    manifest = prepare_job(config_path=Path(source["config_path"]), job_id="SUBMIT001", root=root)
    job_dir = Path(manifest["job_dir"])
    approval_path = job_dir / "config" / "production_approval.json"
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    approval.update(
        {
            "approved": True,
            "approved_by": "pytest",
            "approved_at": "2026-06-04T00:00:00Z",
            "input_path": str((job_dir / "config" / "wrong_project.yaml").resolve()),
            "reason": "pytest should fail before hpc-sbatch",
        }
    )
    approval_path.write_text(json.dumps(approval, indent=2, ensure_ascii=False), encoding="utf-8")

    result = subprocess.run(
        [str(job_dir / "config" / "submit.sh")],
        cwd=job_dir,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "production approval input_path mismatch" in (result.stderr + result.stdout)
    submit_logs = list((job_dir / "logs").glob("slurm_submit_*.log"))
    assert not submit_logs


def test_prepare_job_interactive_submit_does_not_require_approval(tmp_path: Path) -> None:
    source = init_project("rnaseq", tmp_path / "source_interactive", demo_data=True)
    root = tmp_path / "shared" / "shen" / "2026" / "ultimate"

    manifest = prepare_job(config_path=Path(source["config_path"]), job_id="INTERACTIVE001", root=root, run_mode="interactive")

    job_dir = root / "jobs" / "INTERACTIVE001"
    assert manifest["approval_gate"]["required"] is False
    submit_script = (job_dir / "config" / "submit.sh").read_text(encoding="utf-8")
    assert "production approval JSON is not approved=true" not in submit_script
    config = load_config(job_dir / "config" / "project.yaml").raw
    assert "production_approval" not in config["project"]


def test_prepare_job_records_missing_optional_inputs_without_running(tmp_path: Path) -> None:
    source = init_project("rnaseq", tmp_path / "source_missing_inputs", demo_data=True)
    config_path = Path(source["config_path"])
    config = load_config(config_path).raw
    config["samples"]["samplesheet"] = "missing_samples.tsv"
    config["analysis_request"] = "missing_request.yaml"
    from ultimate.config import dump_yaml

    dump_yaml(config, config_path)
    root = tmp_path / "shared" / "shen" / "2026" / "ultimate"

    manifest = prepare_job(config_path=config_path, job_id="MISSING001", root=root)

    assert manifest["samplesheet_status"]["status"] == "missing_or_not_copied"
    assert manifest["analysis_request_status"]["status"] == "missing_or_not_copied"
    assert not (Path(manifest["job_dir"]) / "run_manifest.json").exists()


def test_prepare_job_copies_explicit_samplesheet_and_analysis_request(tmp_path: Path) -> None:
    source = init_project("rnaseq", tmp_path / "source_explicit", demo_data=True)
    root = tmp_path / "shared" / "shen" / "2026" / "ultimate"
    samplesheet = tmp_path / "explicit_samples.tsv"
    samplesheet.write_text("sample_id\tcondition\nS1\tcontrol\nS2\ttreated\n", encoding="utf-8")
    analysis_request = tmp_path / "explicit_request.yaml"
    analysis_request.write_text("analysis_presets:\n  - standard\nnotes: explicit pytest request\n", encoding="utf-8")

    manifest = prepare_job(
        config_path=Path(source["config_path"]),
        job_id="EXPLICIT001",
        root=root,
        samplesheet=samplesheet,
        analysis_request=analysis_request,
        run_mode="interactive",
    )

    job_dir = Path(manifest["job_dir"])
    copied_samplesheet = job_dir / "samples" / samplesheet.name
    copied_request = job_dir / "config" / analysis_request.name
    assert copied_samplesheet.read_text(encoding="utf-8") == samplesheet.read_text(encoding="utf-8")
    assert copied_request.read_text(encoding="utf-8") == analysis_request.read_text(encoding="utf-8")
    config = load_config(job_dir / "config" / "project.yaml").raw
    assert Path(config["samples"]["samplesheet"]) == copied_samplesheet
    assert Path(config["analysis_request"]) == copied_request
    assert manifest["samplesheet"] == str(copied_samplesheet)
    assert manifest["analysis_request"] == str(copied_request)


def test_cli_prepare_job(tmp_path: Path) -> None:
    source = init_project("rnaseq", tmp_path / "source_cli_project", demo_data=True)
    root = tmp_path / "shared" / "shen" / "2026" / "ultimate"

    result = CliRunner().invoke(
        main,
        [
            "prepare-job",
            "--config",
            source["config_path"],
            "--job-id",
            "ORDER002",
            "--root",
            str(root),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["job_id"] == "ORDER002"
    assert (root / "jobs" / "ORDER002" / "job_manifest.json").exists()
