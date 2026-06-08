from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from ultimate.cli import main
from ultimate.handoff_check import run_handoff_check


def test_handoff_check_reports_nfcore_templates_ready(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = run_handoff_check(root=root, output_dir=tmp_path / "handoff")

    assert manifest["status"] == "ready"
    assert manifest["blocked_checks"] == 0
    assert {"nfcore_rnaseq", "nfcore_scrnaseq"} == set(manifest["checked_handoffs"])
    table = Path(manifest["handoff_check_table"])
    assert table.exists()
    text = table.read_text(encoding="utf-8")
    assert "expected_import_not_executed" in text
    assert "raw_fastq_direct_import_forbidden" in text


def test_handoff_check_cli(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    result = CliRunner().invoke(main, ["handoff-check", "--root", str(root), "--output-dir", str(tmp_path / "audit")])

    assert result.exit_code == 0, result.output
    assert "not_executed_by_ultimate" not in result.output
    assert (tmp_path / "audit" / "handoff_check_manifest.json").exists()
