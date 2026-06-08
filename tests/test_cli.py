from __future__ import annotations

import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from ultimate.cli import main
from ultimate.config import dump_yaml, load_config


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
    manifest = json.loads((output_dir / "intake_package_manifest.json").read_text(encoding="utf-8"))
    assert manifest["template_status"]["status"] == "ready"
    assert (output_dir / "module_input_catalog.tsv").exists()
    assert (output_dir / "figure_style_catalog.tsv").exists()
    assert (output_dir / "quote_preflight_checklist.md").exists()


def test_cli_run_requires_approval_for_production_backend(tmp_path: Path) -> None:
    runner = CliRunner()
    project_dir = tmp_path / "cli_production_gate"
    result = runner.invoke(main, ["init-project", "--type", "rnaseq", "--output-dir", str(project_dir), "--demo-data"])
    assert result.exit_code == 0, result.output
    config_path = project_dir / "config" / "project.yaml"
    loaded = load_config(config_path)
    config = loaded.raw
    config["modules"]["rnaseq"]["analysis_level"] = "production_backend"
    dump_yaml(config, config_path)

    result = runner.invoke(main, ["run", "--config", str(config_path)])

    assert result.exit_code != 0
    assert "production_backend requires --production-approval" in result.output


def test_cli_run_accepts_production_approval(tmp_path: Path) -> None:
    runner = CliRunner()
    project_dir = tmp_path / "cli_approved_order"
    result = runner.invoke(main, ["init-project", "--type", "rnaseq", "--output-dir", str(project_dir)])
    assert result.exit_code == 0, result.output
    config_path = project_dir / "config" / "project.yaml"
    loaded = load_config(config_path)
    config = loaded.raw
    _write_real_matrix(Path(config["modules"]["rnaseq"]["input_matrix"]))
    config["modules"]["rnaseq"]["analysis_level"] = "production_backend"
    config["modules"]["rnaseq"]["is_demo"] = False
    config["modules"]["rnaseq"].setdefault("raw", {})["enabled"] = False
    dump_yaml(config, config_path)
    output_dir = Path(load_config(config_path).raw["project"]["output_dir"])
    approval_path = tmp_path / "approval.json"
    approval_path.write_text(
        json.dumps(
            {
                "approved": True,
                "approved_by": "pytest",
                "approved_at": "2026-06-04T00:00:00Z",
                "project_id": "cli_approved_order",
                "input_path": str(config_path.resolve()),
                "output_dir": str(output_dir.resolve()),
                "delivery_scope": "internal_rehearsal",
                "reason": "pytest CLI unified run production gate",
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(main, ["run", "--config", str(config_path), "--production-approval", str(approval_path)])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["production_approval"]["approved"] is True
