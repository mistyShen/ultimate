from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from ultimate.cli import main
from ultimate.tool_registry import TOOL_REGISTRY, run_audit_tools, run_trial_tools


def test_tool_registry_covers_expected_packages() -> None:
    names = {tool.name for tool in TOOL_REGISTRY}
    assert len(names) >= 100
    for expected in {
        "scanpy",
        "anndata",
        "nf-core/scrnaseq",
        "scrublet",
        "SoupX",
        "GSEApy",
        "CellChat",
        "SnapATAC2",
        "scirpy",
        "squidpy",
        "inferCNV",
        "CopyKAT",
        "Quarto",
    }:
        assert expected in names


def test_audit_tools_writes_registry_and_storage(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    root.mkdir()
    manifest = run_audit_tools(root=root, output_dir=tmp_path / "audit")
    assert manifest["tool_count"] == len(TOOL_REGISTRY)
    assert Path(manifest["registry_tsv"]).exists()
    assert Path(manifest["tool_audit_matrix"]).exists()
    assert Path(manifest["storage_estimate"]).exists()
    assert Path(manifest["report_html"]).exists()


def test_trial_tools_no_install_writes_manifest(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    root.mkdir()
    manifest = run_trial_tools(root=root, batch="scrna_core", output_dir=tmp_path / "trial", install=False, project_root=root)
    assert manifest["batch"] == "scrna_core"
    assert manifest["install_requested"] is False
    assert Path(manifest["trial_tools"]).exists()
    assert Path(manifest["storage_before_tsv"]).exists()


def test_cli_audit_tools(tmp_path: Path) -> None:
    runner = CliRunner()
    root = tmp_path / "ultimate"
    root.mkdir()
    result = runner.invoke(main, ["audit-tools", "--root", str(root), "--output-dir", str(tmp_path / "audit")])
    assert result.exit_code == 0, result.output
    assert "tool_audit_matrix" in result.output
