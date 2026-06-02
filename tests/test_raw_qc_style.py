from __future__ import annotations

from pathlib import Path

from ultimate.demo import init_project
from ultimate.pipeline import run_pipeline_from_config
from ultimate.plot_style import generate_style_review
from ultimate.raw_qc import RAW_CONTRACTS


def test_style_review_generates_expected_figures(tmp_path: Path) -> None:
    manifest = generate_style_review(tmp_path / "style_review")
    assert manifest["status"] == "ready_for_review"
    assert Path(manifest["style_manifest"]).exists()
    assert Path(manifest["figure_manifest"]).exists()
    assert len(manifest["figures"]) == 7
    for figure in manifest["figures"]:
        assert Path(figure).exists()


def test_raw_qc_manifests_for_all_modules(tmp_path: Path) -> None:
    manifest = init_project("all", tmp_path / "raw_demo", demo_data=True)
    run_manifest = run_pipeline_from_config(Path(manifest["config_path"]))
    assert len(run_manifest["modules"]) == len(RAW_CONTRACTS)
    for module in run_manifest["modules"]:
        raw_qc = module["raw_qc"]
        assert raw_qc["status"] in {"ready", "ready_with_open_replacement_or_missing_optional_tools"}
        assert Path(raw_qc["manifest_path"]).exists()
        assert Path(raw_qc["artifacts"]["tables"]["raw_qc_summary"]).exists()
        assert Path(raw_qc["artifacts"]["objects"]["standard_matrix"]).exists()
        assert Path(raw_qc["artifacts"]["figures"]["raw_qc_overview"]).exists()
