from __future__ import annotations

import sys
from pathlib import Path


def test_write_v3_status_report_uses_backend_audit_tables(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / "01_tools"))
    try:
        from write_v3_status_report import write_v3_status_report
    finally:
        sys.path.pop(0)

    from ultimate.production_audit import run_production_audit

    root = tmp_path / "ultimate"
    manifest = run_production_audit(root=root, output_dir=root / "audits" / "production_latest")
    report_path = write_v3_status_report(
        root=root,
        output_dir=root / "reports",
        production_audit=Path(manifest["manifest_path"]),
    )

    text = report_path.read_text(encoding="utf-8")
    assert "Ultimate V3 Backend Status Report" in text
    assert "fully automatic" in text
    assert "planned fully automatic" in text
    assert "scrna.mvp.validate_scrna" in text
    assert "V3 声明边界" in text
