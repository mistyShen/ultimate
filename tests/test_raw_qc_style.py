from __future__ import annotations

from pathlib import Path

import pandas as pd

from ultimate.demo import init_project
from ultimate.pipeline import run_pipeline_from_config
from ultimate.plot_style import generate_style_review
from ultimate.raw_qc import run_raw_qc
from ultimate.raw_qc import RAW_CONTRACTS


def test_style_review_generates_expected_figures(tmp_path: Path) -> None:
    manifest = generate_style_review(tmp_path / "style_review")
    assert manifest["status"] == "ready_for_review"
    assert Path(manifest["style_manifest"]).exists()
    assert Path(manifest["figure_manifest"]).exists()
    assert len(manifest["figures"]) >= 7
    assert any(Path(figure).name == "qc_bar_review.png" for figure in manifest["figures"])
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
        assert Path(raw_qc["artifacts"]["tables"]["external_command_plan"]).exists()
        assert Path(raw_qc["artifacts"]["objects"]["standard_matrix"]).exists()
        assert Path(raw_qc["artifacts"]["figures"]["raw_qc_overview"]).exists()


def test_gap_fill_raw_contracts_cover_new_single_cell_inputs(tmp_path: Path) -> None:
    assert "bcl" in RAW_CONTRACTS["scrna"].input_types
    assert "bd_rhapsody_matrix" in RAW_CONTRACTS["scrna"].input_types
    assert "fastq" in RAW_CONTRACTS["scatac"].input_types
    assert "arc_output" in RAW_CONTRACTS["multiome"].input_types
    assert "fastq" in RAW_CONTRACTS["vdj"].input_types
    assert "xenium_dir" in RAW_CONTRACTS["spatial"].input_types
    assert "perturb_seq" in RAW_CONTRACTS
    assert "hto_demux" in RAW_CONTRACTS
    assert "genotype_demux" in RAW_CONTRACTS

    samples = pd.DataFrame([{"sample_id": "POOL_1", "condition": "mixed", "input_path": "raw/pool_1"}])
    manifest = run_raw_qc(
        module_name="genotype_demux",
        config={
            "project": {"server_root": str(tmp_path)},
            "modules": {"genotype_demux": {"raw": {"enabled": True, "input_type": "bam_vcf_barcode"}}},
        },
        output_dir=tmp_path / "run",
        samples=samples,
    )
    command_plan = pd.read_csv(manifest["artifacts"]["tables"]["external_command_plan"], sep="\t")
    assert "cellsnp-lite" in command_plan.loc[0, "command"]
    assert manifest["output_kind"] == "genotype_demux_table"
