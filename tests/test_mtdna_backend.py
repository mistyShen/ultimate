from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from ultimate.config import dump_yaml
from ultimate.pipeline import run_pipeline_from_config


def _write_mtdna_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "mtdna_fixture"
    counts = root / "analysis_mtDNA" / "singlecell_mgatk_like" / "counts"
    variants = root / "analysis_mtDNA" / "singlecell_mgatk_like" / "variants"
    counts.mkdir(parents=True)
    variants.mkdir(parents=True)
    (counts / "cell_mtDNA_depth.tsv").write_text(
        "\n".join(
            [
                "cell_id\tmean_depth\tmedian_depth",
                "cell1\t120\t118",
                "cell2\t42\t40",
                "cell3\t8\t7",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (variants / "high_confidence_informative_variants.tsv").write_text(
        "\n".join(
            [
                "variant_id\tchrom\tpos\tref\talt\tmean_vaf\tquality_class",
                "chrM:100:A>G\tchrM\t100\tA\tG\t0.18\tinformative_heteroplasmy",
                "chrM:200:C>T\tchrM\t200\tC\tT\t1.0\thomoplasmic_shared",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (variants / "cell_by_variant_vaf_matrix.tsv").write_text(
        "\n".join(
            [
                "cell_id\tchrM:100:A>G\tchrM:200:C>T",
                "cell1\t0.20\t1.0",
                "cell2\t0.12\t1.0",
                "cell3\t0.00\t0.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return root


def _write_config(tmp_path: Path, *, source_root: Path, output_name: str = "run", analysis_level: str | None = None) -> Path:
    module_cfg = {
        "enabled": True,
        "preset": "standard",
        "source_root": str(source_root),
        "raw": {"enabled": False, "input_type": "mtdna_result_tables"},
    }
    if analysis_level:
        module_cfg["analysis_level"] = analysis_level
        module_cfg["validation_dataset"] = "unit test mtDNA fixture"
    config_path = tmp_path / f"{output_name}.yaml"
    dump_yaml(
        {
            "project": {
                "name": f"mtdna_{output_name}",
                "organism": "human",
                "output_dir": str(tmp_path / output_name),
                "server_root": str(tmp_path),
                "run_mode": "interactive",
            },
            "samples": {"items": [{"sample_id": "S1", "condition": "validation", "input_path": str(source_root)}]},
            "modules": {"mtdna": module_cfg},
        },
        config_path,
    )
    return config_path


def test_mtdna_backend_generates_lineage_ready_outputs(tmp_path: Path) -> None:
    source_root = _write_mtdna_fixture(tmp_path)
    config_path = _write_config(tmp_path, source_root=source_root)

    manifest = run_pipeline_from_config(config_path)
    run_dir = Path(manifest["output_dir"])
    module = manifest["modules"][0]

    assert module["module"] == "mtdna"
    assert module["status"] == "complete_mtdna_lineage_backend"
    assert module["backend_id"] == "mtdna.default.lineage_ready_mvp"
    assert module["analysis_level"] == "smoke_backend"
    assert module["delivery_allowed"] is False
    assert module["lineage_ready_cells"] == 2
    for key in (
        "mtdna_depth_by_cell",
        "mtdna_depth_by_position",
        "variant_candidates",
        "high_confidence_variants",
        "cell_variant_vaf_matrix",
        "cell_variant_alt_count_matrix",
        "shared_variant_matrix",
        "lineage_input",
    ):
        path = Path(module["artifacts"]["tables"][key])
        assert path.exists() and path.stat().st_size > 0, key
    assert Path(module["artifacts"]["figures"]["depth_distribution"]).exists()
    assert Path(module["artifacts"]["figures"]["vaf_heatmap"]).exists()
    assert Path(module["artifacts"]["figures"]["shared_variant_heatmap"]).exists()
    assert Path(module["artifacts"]["objects"]["mvp_object"]).name == "mtdna_mvp_object.rds"

    lineage = pd.read_csv(run_dir / "results" / "tables" / "mtdna" / "lineage_input.tsv", sep="\t")
    assert "lineage_ready_variant" in set(lineage["lineage_handoff_status"])
    methods = (run_dir / "reports" / "mtdna" / "methods.md").read_text(encoding="utf-8")
    assert "analysis_level" in methods
    assert "shared variant 不能自动当作真实克隆关系" in methods


def test_mtdna_backend_validated_fixture_is_evidence_not_delivery(tmp_path: Path) -> None:
    source_root = _write_mtdna_fixture(tmp_path)
    config_path = _write_config(tmp_path, source_root=source_root, output_name="validated", analysis_level="validated_backend")

    manifest = run_pipeline_from_config(config_path)
    module = manifest["modules"][0]

    assert module["analysis_level"] == "validated_backend"
    assert module["validation_evidence_allowed"] is True
    assert module["delivery_allowed"] is False
    assert module["non_delivery_reason"] == "validation_evidence_only_not_customer_delivery"


def test_mtdna_backend_missing_input_is_non_deliverable(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, source_root=tmp_path / "missing", output_name="missing")

    manifest = run_pipeline_from_config(config_path)
    run_dir = Path(manifest["output_dir"])
    module = manifest["modules"][0]

    assert module["status"] == "partial:mtdna_inputs_missing"
    assert module["analysis_level"] == "smoke_backend"
    assert module["delivery_allowed"] is False
    assert module["validation_evidence_allowed"] is False
    assert module["skip_reasons"]
    qc_manifest = json.loads((run_dir / "results" / "tables" / "mtdna" / "module_qc_manifest.json").read_text(encoding="utf-8"))
    assert qc_manifest["delivery_allowed"] is False
    assert qc_manifest["skip_reasons"]
