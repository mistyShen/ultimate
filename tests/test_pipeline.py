from __future__ import annotations

from pathlib import Path

from ultimate.demo import init_project
from ultimate.pipeline import run_pipeline_from_config


def test_pipeline_generates_required_artifacts(tmp_path: Path) -> None:
    manifest = init_project("all", tmp_path / "demo_all", demo_data=True)
    run_manifest = run_pipeline_from_config(Path(manifest["config_path"]))
    run_dir = Path(run_manifest["output_dir"])
    assert (run_dir / "run_manifest.json").exists()
    assert (run_dir / "reports" / "report.html").exists()
    assert (run_dir / "reports" / "methods.md").exists()
    assert len(run_manifest["modules"]) >= 13
    for module in run_manifest["modules"]:
        assert Path(module["artifacts"]["figures"]["pca"]).exists()
        assert Path(module["artifacts"]["tables"]["differential_results"]).exists()
        assert Path(module["artifacts"]["objects"]["rds"]).exists()
