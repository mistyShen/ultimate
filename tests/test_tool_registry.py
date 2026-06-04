from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from ultimate.cli import main
from ultimate.modules.common import module_contract
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
        "WGCNA",
        "GEOquery",
        "TCGAbiolinks",
        "lifelines",
        "statsmodels",
        "MACS3",
        "bedtools",
        "samtools",
        "bcftools",
        "pysam",
        "pertpy",
        "SCEPTRE",
        "hashsolo",
        "sopa",
    }:
        assert expected in names


def test_high_value_tools_are_surfaced_by_module_contracts() -> None:
    checks = {
        "method_tools": {"cellxgene"},
        "scrna": {"CellChat", "LIANA", "NicheNet", "pySCENIC"},
        "tumor_sc": {"CellChat", "LIANA", "NicheNet", "inferCNV", "CopyKAT"},
        "scatac": {"MACS3", "bedtools", "samtools"},
        "multiome": {"MACS3", "bedtools", "samtools"},
        "mtdna": {"samtools", "bcftools", "pysam"},
        "scdna": {"samtools", "bcftools", "pysam"},
        "perturb_seq": {"pertpy", "SCEPTRE"},
        "hto_demux": {"hashsolo"},
        "publicdb": {"GEOquery", "TCGAbiolinks"},
        "wgcna": {"WGCNA"},
        "clinical_assoc": {"lifelines", "statsmodels"},
        "spatial": {"sopa"},
    }
    for module_name, expected in checks.items():
        contract = module_contract(module_name)
        surfaced = set(contract.primary_tools) | set(contract.handoff_tools)
        assert expected <= surfaced, module_name


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
