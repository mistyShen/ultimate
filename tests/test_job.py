from __future__ import annotations

import json
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
    for name in ("raw_links", "config", "samples", "runs", "logs", "deliverables", "reproducible_code"):
        assert (job_dir / name).is_dir()
    assert (job_dir / "config" / "project.yaml").exists()
    assert (job_dir / "config" / "production_approval.json").exists()
    assert (job_dir / "config" / "submit.sh").exists()
    command_plan = (job_dir / "config" / "command_plan.md").read_text(encoding="utf-8")
    assert "hpc-sbatch" in command_plan
    assert "ultimate_run.sbatch" in command_plan
    assert "production_approval.json" in command_plan
    assert str(job_dir / "logs") in command_plan
    submit_script = (job_dir / "config" / "submit.sh").read_text(encoding="utf-8")
    assert "slurm_submit_" in submit_script
    assert 'LOG_DIR="$JOB_DIR/logs"' in submit_script

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
