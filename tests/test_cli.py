from __future__ import annotations

import subprocess
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
    run_dir = project_dir / "runs" / "cli_demo"
    assert (run_dir / "run_manifest.json").exists()
    result = runner.invoke(main, ["export-repro", "--run-dir", str(run_dir)])
    assert result.exit_code == 0, result.output
    assert (run_dir / "reproducible_code" / "README.md").exists()
    completed = subprocess.run(
        [str(run_dir / "reproducible_code" / "rerun.sh"), "report"],
        check=False,
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr


def test_cli_prepare_intake(tmp_path: Path) -> None:
    runner = CliRunner()
    root = tmp_path / "ultimate_root"
    output_dir = tmp_path / "intake_package"
    (root / ".conda" / "envs" / "ultimate-core").mkdir(parents=True)
    result = runner.invoke(main, ["prepare-intake", "--root", str(root), "--output-dir", str(output_dir), "--refresh-audit"])
    assert result.exit_code == 0, result.output
    assert (output_dir / "intake_package_manifest.json").exists()
    assert (output_dir / "module_input_catalog.tsv").exists()
    assert (output_dir / "figure_style_catalog.tsv").exists()
    assert (output_dir / "quote_preflight_checklist.md").exists()
