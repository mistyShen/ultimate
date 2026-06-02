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
