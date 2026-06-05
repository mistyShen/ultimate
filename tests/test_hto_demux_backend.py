from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from ultimate.config import dump_yaml
from ultimate.pipeline import run_pipeline_from_config


def _write_hto_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "hto_counts.tsv"
    path.write_text(
        "\n".join(
            [
                "cell_id\tHTO_A\tHTO_B\tHTO_C",
                "cell1\t90\t2\t1",
                "cell2\t3\t88\t2",
                "cell3\t1\t4\t92",
                "cell4\t65\t61\t2",
                "cell5\t3\t2\t1",
                "cell6\t77\t5\t4",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _write_hto_fixture_with_summary_columns(tmp_path: Path) -> Path:
    path = tmp_path / "hto_counts_summary.tsv"
    path.write_text(
        "\n".join(
            [
                "cell_id\tHTO_A\tHTO_B\tno_match\tambiguous\ttotal_reads\tbad_struct",
                "cell1\t90\t2\t4\t0\t96\t0",
                "cell2\t3\t88\t1\t0\t92\t0",
                "cell3\t65\t61\t2\t0\t128\t1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _write_mapping(tmp_path: Path) -> Path:
    path = tmp_path / "hto_mapping.tsv"
    path.write_text(
        "\n".join(
            [
                "hashtag_id\tsample_id",
                "HTO_A\tSample_A",
                "HTO_B\tSample_B",
                "HTO_C\tSample_C",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _write_config(tmp_path: Path, *, input_table: Path, mapping: Path | None = None, output_name: str = "run") -> Path:
    module_cfg = {
        "enabled": True,
        "preset": "standard",
        "input_table": str(input_table),
        "min_positive_count": 20,
        "min_margin": 20,
        "raw": {"enabled": False, "input_type": "hto_count_matrix"},
    }
    if mapping is not None:
        module_cfg["sample_hashtag_mapping"] = str(mapping)
    config_path = tmp_path / f"{output_name}.yaml"
    dump_yaml(
        {
            "project": {
                "name": f"hto_demux_{output_name}",
                "organism": "human",
                "output_dir": str(tmp_path / output_name),
                "server_root": str(tmp_path),
                "run_mode": "interactive",
            },
            "samples": {"items": [{"sample_id": "S1", "condition": "validation", "input_path": str(input_table)}]},
            "modules": {"hto_demux": module_cfg},
        },
        config_path,
    )
    return config_path


def test_hto_demux_backend_generates_assignment_outputs(tmp_path: Path) -> None:
    input_table = _write_hto_fixture(tmp_path)
    mapping = _write_mapping(tmp_path)
    config_path = _write_config(tmp_path, input_table=input_table, mapping=mapping)

    manifest = run_pipeline_from_config(config_path)
    run_dir = Path(manifest["output_dir"])
    module = manifest["modules"][0]

    assert module["module"] == "hto_demux"
    assert module["status"] == "complete_hto_demux_matrix_backend"
    assert module["backend_id"] == "hto_demux.default.matrix_assignment_mvp"
    assert module["analysis_level"] == "smoke_backend"
    assert module["delivery_allowed"] is False
    for key in ("hto_qc", "hto_assignment", "sample_assignment_summary", "doublet_summary", "cell_metadata_with_sample"):
        path = Path(module["artifacts"]["tables"][key])
        assert path.exists() and path.stat().st_size > 0, key
    assert Path(module["artifacts"]["figures"]["hto_density"]).exists()
    assert Path(module["artifacts"]["figures"]["hto_heatmap"]).exists()
    assert Path(module["artifacts"]["objects"]["mvp_object"]).name == "hto_demux_mvp_object.rds"

    assignments = pd.read_csv(run_dir / "results" / "tables" / "hto_demux" / "hto_assignment.tsv", sep="\t")
    assert {"singlet", "doublet", "negative"}.issubset(set(assignments["assignment_class"]))
    assert "Sample_A" in set(assignments["assigned_sample"])
    metadata = pd.read_csv(run_dir / "results" / "tables" / "hto_demux" / "cell_metadata_with_sample.tsv", sep="\t")
    assert "ready_for_scrna_metadata_join" in set(metadata["metadata_handoff_status"])
    methods = (run_dir / "reports" / "hto_demux" / "methods.md").read_text(encoding="utf-8")
    assert "analysis_level" in methods
    assert "negative 不能强行分样本" in methods


def test_hto_demux_backend_missing_input_is_non_deliverable(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, input_table=tmp_path / "missing.tsv", output_name="missing")

    manifest = run_pipeline_from_config(config_path)
    run_dir = Path(manifest["output_dir"])
    module = manifest["modules"][0]

    assert module["status"] == "partial:hto_demux_inputs_missing"
    assert module["analysis_level"] == "smoke_backend"
    assert module["delivery_allowed"] is False
    assert module["validation_evidence_allowed"] is False
    assert module["skip_reasons"]
    qc_manifest = json.loads((run_dir / "results" / "tables" / "hto_demux" / "module_qc_manifest.json").read_text(encoding="utf-8"))
    assert qc_manifest["delivery_allowed"] is False
    assert qc_manifest["skip_reasons"]


def test_hto_demux_backend_excludes_summary_columns_from_tags(tmp_path: Path) -> None:
    input_table = _write_hto_fixture_with_summary_columns(tmp_path)
    config_path = _write_config(tmp_path, input_table=input_table, output_name="summary_cols")

    manifest = run_pipeline_from_config(config_path)
    run_dir = Path(manifest["output_dir"])
    module = manifest["modules"][0]

    assert module["n_features"] == 2
    assignments = pd.read_csv(run_dir / "results" / "tables" / "hto_demux" / "hto_assignment.tsv", sep="\t")
    assert set(assignments["hashtag_id"]).issubset({"HTO_A", "HTO_B"})
    tag_summary = pd.read_csv(run_dir / "results" / "tables" / "hto_demux" / "hto_tag_qc_summary.tsv", sep="\t")
    assert set(tag_summary["hashtag_id"]) == {"HTO_A", "HTO_B"}
