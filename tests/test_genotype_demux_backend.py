from __future__ import annotations

import gzip
import json
from pathlib import Path

import pandas as pd

from ultimate.config import dump_yaml
from ultimate.pipeline import run_pipeline_from_config


def _write_cellsnp_fixture(tmp_path: Path) -> Path:
    input_dir = tmp_path / "cellSNP_mat"
    input_dir.mkdir()
    (input_dir / "cellSNP.samples.tsv").write_text("cellA\ncellB\ncellC\n", encoding="utf-8")
    with gzip.open(input_dir / "cellSNP.base.vcf.gz", "wt", encoding="utf-8") as handle:
        handle.write("##fileformat=VCFv4.2\n")
        handle.write("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n")
        handle.write("1\t100\t.\tA\tG\t.\tPASS\t.\n")
        handle.write("1\t200\t.\tC\tT\t.\tPASS\t.\n")
    (input_dir / "cellSNP.tag.AD.mtx").write_text(
        "\n".join(
            [
                "%%MatrixMarket matrix coordinate integer general",
                "%",
                "2 3 4",
                "1 1 1",
                "1 2 3",
                "2 2 4",
                "2 3 8",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (input_dir / "cellSNP.tag.DP.mtx").write_text(
        "\n".join(
            [
                "%%MatrixMarket matrix coordinate integer general",
                "%",
                "2 3 5",
                "1 1 10",
                "1 2 10",
                "2 2 10",
                "1 3 2",
                "2 3 10",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return input_dir


def _write_assignment_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "assignments.tsv"
    path.write_text(
        "\n".join(
            [
                "cell_id\tassigned_genotype\tassignment_probability\tsnp_count\ttotal_depth",
                "cell1\tDONOR_A\t0.95\t30\t100",
                "cell2\tDONOR_B\t0.80\t30\t90",
                "cell3\tDONOR_A\t0.20\t30\t5",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _write_config(tmp_path: Path, *, input_ref: Path, key: str = "input_dir", output_name: str = "run") -> Path:
    config_path = tmp_path / f"{output_name}.yaml"
    dump_yaml(
        {
            "project": {
                "name": f"genotype_demux_{output_name}",
                "organism": "human",
                "output_dir": str(tmp_path / output_name),
                "server_root": str(tmp_path),
                "run_mode": "interactive",
            },
            "samples": {"items": [{"sample_id": "S1", "condition": "validation", "input_path": str(input_ref)}]},
            "modules": {
                "genotype_demux": {
                    "enabled": True,
                    "preset": "standard",
                    key: str(input_ref),
                    "raw": {"enabled": False, "input_type": "cellsnp_output" if input_ref.is_dir() else "assignment_table"},
                }
            },
        },
        config_path,
    )
    return config_path


def test_genotype_demux_backend_generates_cellsnp_outputs(tmp_path: Path) -> None:
    input_dir = _write_cellsnp_fixture(tmp_path)
    config_path = _write_config(tmp_path, input_ref=input_dir)

    manifest = run_pipeline_from_config(config_path)
    run_dir = Path(manifest["output_dir"])
    module = manifest["modules"][0]

    assert module["module"] == "genotype_demux"
    assert module["status"] == "complete_genotype_demux_import_backend"
    assert module["backend_id"] == "genotype_demux.default.result_import_mvp"
    assert module["analysis_level"] == "smoke_backend"
    assert module["delivery_allowed"] is False
    for key in ("snp_qc", "assignment", "doublet_summary", "sample_composition", "assignment_confidence", "cell_metadata_with_genotype"):
        path = Path(module["artifacts"]["tables"][key])
        assert path.exists() and path.stat().st_size > 0, key
    assert Path(module["artifacts"]["figures"]["sample_assignment_barplot"]).exists()
    assert Path(module["artifacts"]["figures"]["confidence_distribution"]).exists()
    assert Path(module["artifacts"]["objects"]["mvp_object"]).name == "genotype_demux_mvp_object.rds"

    assignment = pd.read_csv(run_dir / "results" / "tables" / "genotype_demux" / "assignment.tsv", sep="\t")
    assert {"low_alt_fraction", "mid_alt_fraction", "high_alt_fraction"}.intersection(set(assignment["assigned_genotype"]))
    metadata = pd.read_csv(run_dir / "results" / "tables" / "genotype_demux" / "cell_metadata_with_genotype.tsv", sep="\t")
    assert "ready_for_scrna_metadata_join" in set(metadata["metadata_handoff_status"])
    methods = (run_dir / "reports" / "genotype_demux" / "methods.md").read_text(encoding="utf-8")
    assert "analysis_level" in methods
    assert "SNP 覆盖不足时不能强行 assignment" in methods


def test_genotype_demux_backend_reads_assignment_table(tmp_path: Path) -> None:
    table = _write_assignment_fixture(tmp_path)
    config_path = _write_config(tmp_path, input_ref=table, key="assignment_table", output_name="table")

    manifest = run_pipeline_from_config(config_path)
    module = manifest["modules"][0]

    assert module["status"] == "complete_genotype_demux_import_backend"
    assert module["n_cells"] == 3
    assert module["n_samples"] == 2


def test_genotype_demux_backend_missing_input_is_non_deliverable(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, input_ref=tmp_path / "missing", output_name="missing")

    manifest = run_pipeline_from_config(config_path)
    run_dir = Path(manifest["output_dir"])
    module = manifest["modules"][0]

    assert module["status"] == "partial:genotype_demux_inputs_missing"
    assert module["analysis_level"] == "smoke_backend"
    assert module["delivery_allowed"] is False
    assert module["validation_evidence_allowed"] is False
    assert module["skip_reasons"]
    qc_manifest = json.loads((run_dir / "results" / "tables" / "genotype_demux" / "module_qc_manifest.json").read_text(encoding="utf-8"))
    assert qc_manifest["delivery_allowed"] is False
    assert qc_manifest["skip_reasons"]
