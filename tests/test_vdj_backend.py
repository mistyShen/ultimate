from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from ultimate.config import dump_yaml
from ultimate.pipeline import run_pipeline_from_config


def _write_vdj_fixture(input_dir: Path) -> None:
    input_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "contig_id": "c1",
                "barcode": "S1_cell_a",
                "is_cell": "True",
                "productive": "True",
                "chain": "TRA",
                "reads": 100,
                "umis": 12,
                "raw_clonotype_id": "clonotype1",
                "v_gene": "TRAV1-2",
                "j_gene": "TRAJ33",
                "cdr3": "CAVRDSNYQLIW",
            },
            {
                "contig_id": "c2",
                "barcode": "S1_cell_a",
                "is_cell": "True",
                "productive": "True",
                "chain": "TRB",
                "reads": 120,
                "umis": 15,
                "raw_clonotype_id": "clonotype1",
                "v_gene": "TRBV6-5",
                "j_gene": "TRBJ2-7",
                "cdr3": "CASSLGQETQYF",
            },
            {
                "contig_id": "c3",
                "barcode": "S2_cell_b",
                "is_cell": "True",
                "productive": "True",
                "chain": "TRB",
                "reads": 80,
                "umis": 9,
                "raw_clonotype_id": "clonotype2",
                "v_gene": "TRBV7-9",
                "j_gene": "TRBJ1-2",
                "cdr3": "CASSPPSGGYNEQFF",
            },
            {
                "contig_id": "c4",
                "barcode": "S2_cell_c",
                "is_cell": "False",
                "productive": "True",
                "chain": "TRB",
                "reads": 50,
                "umis": 3,
                "raw_clonotype_id": "clonotype3",
                "v_gene": "TRBV5-1",
                "j_gene": "TRBJ2-1",
                "cdr3": "CASSQETQYF",
            },
        ]
    ).to_csv(input_dir / "filtered_contig_annotations.csv", index=False)
    pd.DataFrame(
        [
            {"clonotype_id": "clonotype1", "frequency": 1, "cdr3s_aa": "TRA:CAVRDSNYQLIW;TRB:CASSLGQETQYF"},
            {"clonotype_id": "clonotype2", "frequency": 1, "cdr3s_aa": "TRB:CASSPPSGGYNEQFF"},
        ]
    ).to_csv(input_dir / "clonotypes.csv", index=False)


def _write_config(tmp_path: Path, *, input_dir: Path, output_name: str = "run") -> Path:
    config_path = tmp_path / f"{output_name}.yaml"
    dump_yaml(
        {
            "project": {
                "name": f"vdj_{output_name}",
                "organism": "human",
                "output_dir": str(tmp_path / output_name),
                "server_root": str(tmp_path),
                "run_mode": "interactive",
            },
            "samples": {
                "items": [
                    {"sample_id": "S1", "condition": "control", "barcode": "S1_cell_a", "input_path": str(input_dir)},
                    {"sample_id": "S2", "condition": "treated", "barcode": "S2_cell_b", "input_path": str(input_dir)},
                ]
            },
            "design": {"condition_column": "condition", "control": "control", "case": "treated"},
            "modules": {
                "vdj": {
                    "enabled": True,
                    "input_dir": str(input_dir),
                    "raw": {"enabled": False, "input_type": "cellranger_vdj_out"},
                }
            },
        },
        config_path,
    )
    return config_path


def test_vdj_backend_generates_mvp_outputs(tmp_path: Path) -> None:
    input_dir = tmp_path / "public_vdj"
    _write_vdj_fixture(input_dir)
    config_path = _write_config(tmp_path, input_dir=input_dir)

    manifest = run_pipeline_from_config(config_path)
    run_dir = Path(manifest["output_dir"])
    vdj = manifest["modules"][0]

    assert vdj["module"] == "vdj"
    assert vdj["status"] == "complete_vdj_10x_backend"
    assert vdj["backend_id"] == "vdj.default.scirpy_mvp"
    assert vdj["backend_status"] == "fully_automatic_validated_entrypoint"
    assert vdj["analysis_level"] == "smoke_backend"
    assert vdj["delivery_allowed"] is False
    assert vdj["backend"]["primary"] == "vdj_10x_contig_clonotype"

    required_tables = {
        "vdj_qc",
        "clonotype_summary",
        "clone_expansion",
        "clone_sharing",
        "v_gene_usage",
        "j_gene_usage",
        "cdr3_length",
        "clone_condition_summary",
    }
    assert required_tables.issubset(vdj["artifacts"]["tables"])
    for key in required_tables:
        path = Path(vdj["artifacts"]["tables"][key])
        assert path.exists() and path.stat().st_size > 0
    for key in ("clone_size_distribution", "v_gene_usage", "clone_sharing_heatmap"):
        path = Path(vdj["artifacts"]["figures"][key])
        assert path.exists() and path.stat().st_size > 0
    object_path = run_dir / "objects" / "vdj" / "vdj_mvp.h5ad"
    assert object_path.exists() and object_path.stat().st_size > 0

    clonotypes = pd.read_csv(run_dir / "results" / "tables" / "vdj" / "clonotype_summary.tsv", sep="\t")
    assert set(clonotypes["antigen_specificity_status"]) == {"not_inferred"}
    assert "clonotype1" in set(clonotypes["clonotype_id"].astype(str))
    methods = (run_dir / "reports" / "vdj" / "methods.md").read_text(encoding="utf-8")
    assert "analysis_level" in methods
    assert "clonotype 相同不等于抗原相同" in methods


def test_vdj_backend_missing_inputs_remains_non_deliverable(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, input_dir=tmp_path / "missing_vdj", output_name="missing")

    manifest = run_pipeline_from_config(config_path)
    vdj = manifest["modules"][0]
    run_dir = Path(manifest["output_dir"])

    assert vdj["status"] == "partial:vdj_inputs_missing"
    assert vdj["analysis_level"] == "smoke_backend"
    assert vdj["delivery_allowed"] is False
    assert vdj["validation_evidence_allowed"] is False
    assert any("missing_contig_annotations" in reason for reason in vdj["skip_reasons"])
    qc_manifest = json.loads((run_dir / "results" / "tables" / "vdj" / "module_qc_manifest.json").read_text(encoding="utf-8"))
    assert qc_manifest["delivery_allowed"] is False
    assert qc_manifest["skip_reasons"]
