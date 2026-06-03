from __future__ import annotations

from pathlib import Path

from ultimate.singlecell_audit import run_singlecell_audit


def test_singlecell_audit_writes_matrix(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    (root / ".conda" / "envs" / "ultimate-core" / "bin").mkdir(parents=True)
    manifest = run_singlecell_audit(root=root, output_dir=tmp_path / "audit")
    assert Path(manifest["capability_matrix"]).exists()
    assert Path(manifest["dependency_report"]).exists()
    assert len(manifest["capabilities"]) >= 13
    assert "delivery_summary" in manifest


def test_genotype_demux_accepts_alternative_command_route(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    bin_dir = root / ".conda" / "envs" / "ultimate-genome-mtdna" / "bin"
    bin_dir.mkdir(parents=True)
    for command in ("python", "cellsnp-lite", "vireo"):
        path = bin_dir / command
        path.write_text("#!/usr/bin/env sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)
    (root / ".conda" / "envs" / "ultimate-core" / "bin").mkdir(parents=True)
    manifest = run_singlecell_audit(root=root, output_dir=tmp_path / "audit")
    genotype = next(row for row in manifest["capabilities"] if row["capability"] == "genotype_demux")
    assert "souporcell" not in genotype["command_missing"]
