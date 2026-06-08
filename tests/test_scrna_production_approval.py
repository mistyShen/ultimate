from __future__ import annotations

from pathlib import Path

import pandas as pd

from ultimate.modules.runner import run_scrna_mvp_module_backend


def test_scrna_mvp_backend_receives_pipeline_production_approval(tmp_path: Path, monkeypatch) -> None:
    input_dir = tmp_path / "matrix_ready_input"
    input_dir.mkdir()
    approval = {
        "approved": True,
        "approved_by": "pytest",
        "approved_at": "2026-06-08T00:00:00Z",
        "project_id": "SCRNA_APPROVAL",
        "input_path": str(tmp_path / "config.yaml"),
        "output_dir": str(tmp_path / "run"),
        "delivery_scope": "internal_rehearsal",
        "reason": "pytest approval forwarding",
    }
    captured = {}

    def fake_run_scrna_validation(**kwargs):
        captured["production_approval"] = kwargs.get("production_approval")
        output_dir = Path(kwargs["output_dir"])
        (output_dir / "results" / "tables").mkdir(parents=True, exist_ok=True)
        (output_dir / "results" / "figures").mkdir(parents=True, exist_ok=True)
        (output_dir / "reports").mkdir(parents=True, exist_ok=True)
        return {
            "status": "ready",
            "analysis_level": "production_backend",
            "is_demo": False,
            "is_stub": False,
            "delivery_allowed": True,
            "validation_evidence_allowed": True,
            "non_delivery_reason": "",
            "backend_status": [],
            "objects": {},
        }

    monkeypatch.setattr("ultimate.modules.runner.run_scrna_validation", fake_run_scrna_validation)

    manifest = run_scrna_mvp_module_backend(
        config={
            "_production_approval": approval,
            "modules": {
                "scrna": {
                    "enabled": True,
                    "input_path": str(input_dir),
                    "input_type": "10x_mtx",
                    "analysis_level": "production_backend",
                }
            },
        },
        output_dir=tmp_path / "run",
        samples=pd.DataFrame({"sample_id": ["S1"], "condition": ["case"]}),
    )

    assert captured["production_approval"] == approval
    assert manifest["analysis_level"] == "production_backend"
    assert manifest["delivery_allowed"] is True
    assert any(row["backend_id"] == manifest["backend_id"] and row["status"] == "ready" for row in manifest["backend_execution_rows"])
