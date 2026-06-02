from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from ultimate.cli import main
from ultimate.constants import MODULE_ORDER
from ultimate.production_audit import run_production_audit


def test_production_audit_writes_readiness_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    (root / ".conda" / "envs" / "ultimate-core").mkdir(parents=True)
    manifest = run_production_audit(root=root, output_dir=tmp_path / "audit")
    assert Path(manifest["capability_matrix"]).exists()
    assert Path(manifest["organism_support"]).exists()
    assert Path(manifest["style_options"]).exists()
    assert Path(manifest["next_steps"]).exists()
    assert sum(manifest["summary"].values()) == len(MODULE_ORDER)


def test_cli_styles_generates_review(tmp_path: Path) -> None:
    runner = CliRunner()
    out_dir = tmp_path / "style"
    result = runner.invoke(main, ["styles", "--style", "warm_academic", "--output-dir", str(out_dir)])
    assert result.exit_code == 0, result.output
    assert (out_dir / "style_review_manifest.json").exists()
    assert (out_dir / "qc_bar_review.png").exists()
