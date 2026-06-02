from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from ultimate.cli import main


def test_cli_init_preflight_run(tmp_path: Path) -> None:
    runner = CliRunner()
    project_dir = tmp_path / "cli_demo"
    result = runner.invoke(main, ["init-project", "--type", "rnaseq", "--output-dir", str(project_dir), "--demo-data"])
    assert result.exit_code == 0, result.output
    config_path = project_dir / "config" / "project.yaml"
    result = runner.invoke(main, ["preflight", "--config", str(config_path)])
    assert result.exit_code == 0, result.output
    result = runner.invoke(main, ["run", "--config", str(config_path)])
    assert result.exit_code == 0, result.output
    assert (project_dir / "runs" / "cli_demo" / "run_manifest.json").exists()
