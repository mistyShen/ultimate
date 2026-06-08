from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_tool_module():
    script = Path(__file__).resolve().parents[1] / "01_tools" / "write_v3_5_intake_ready_report.py"
    spec = importlib.util.spec_from_file_location("write_v3_5_intake_ready_report", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v35_intake_report_summarizes_triage_manifests(tmp_path: Path) -> None:
    module = _load_tool_module()
    triage_dir = tmp_path / "triage" / "JOB001"
    triage_dir.mkdir(parents=True)
    (triage_dir / "triage_manifest.json").write_text(
        json.dumps(
            {
                "request_path": str(tmp_path / "request.yaml"),
                "status": "needs_manual_review",
                "suggested_project_yaml": str(triage_dir / "suggested_project.yaml"),
                "missing_requirements": str(triage_dir / "missing_requirements.tsv"),
                "input_summary": {"handoff_required": True},
            }
        ),
        encoding="utf-8",
    )

    manifest = module.build_report(tmp_path, tmp_path / "reports")

    assert manifest["triage_manifest_count"] == 1
    assert manifest["status_counts"]["needs_manual_review"] == 1
    assert manifest["handoff_required_count"] == 1
    report = Path(manifest["report"]).read_text(encoding="utf-8")
    assert "Ultimate V3.5 intake readiness report" in report
    assert "Customer delivery still requires" in report
