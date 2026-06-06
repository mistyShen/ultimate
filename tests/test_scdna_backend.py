from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from ultimate.config import dump_yaml
from ultimate.pipeline import run_pipeline_from_config


def _write_scdna_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "scdna_fixture"
    stats = root / "analysis_dna" / "stats"
    stats.mkdir(parents=True)
    (stats / "dna_mt_depth_summary.tsv").write_text(
        "\n".join(
            [
                "sample_id\ttotal_reads\tmapped_reads\tchrM_reads\tnuclear_reads\tmtDNA_depth\tmean_nuclear_depth\tnuclear_bases",
                "cell1\t1000\t950\t20\t930\t35\t4.2\t10000",
                "cell2\t900\t820\t10\t810\t12\t0.5\t2500",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (stats / "mapped_unmapped_summary.tsv").write_text(
        "\n".join(
            [
                "sample_id\ttotal_reads\tmapped_reads\tunmapped_reads\tmapped_fraction\tunmapped_fraction",
                "cell1\t1000\t950\t50\t0.95\t0.05",
                "cell2\t900\t820\t80\t0.91\t0.09",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (stats / "method_reference_sanity_check.tsv").write_text(
        "\n".join(
            [
                "sample\tbam_quickcheck\tcontig_naming_consistent\tfinal_call",
                "cell1\tOK\tyes\tsanity checks pass",
                "cell2\tOK\tyes\tlow coverage warning",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return root


def _write_variant_fixture(tmp_path: Path) -> tuple[Path, Path]:
    coverage = tmp_path / "coverage.tsv"
    coverage.write_text(
        "\n".join(
            [
                "sample_id\tmean_nuclear_depth\tnuclear_bases",
                "cell1\t8\t10000",
                "cell2\t7\t9500",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    vaf = tmp_path / "cell_vaf_matrix.tsv"
    vaf.write_text(
        "\n".join(
            [
                "cell_id\tchr1:10:A>G\tchr1:20:C>T",
                "cell1\t0.42\t0.00",
                "cell2\t0.39\t0.31",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return coverage, vaf


def _write_config(tmp_path: Path, *, source_root: Path, output_name: str = "run", analysis_level: str | None = None, extra_module: dict | None = None) -> Path:
    module_cfg = {
        "enabled": True,
        "preset": "standard",
        "source_root": str(source_root),
        "raw": {"enabled": False, "input_type": "dna_qc_result_tables"},
    }
    if analysis_level:
        module_cfg["analysis_level"] = analysis_level
        module_cfg["validation_dataset"] = "unit test scDNA fixture"
    if extra_module:
        module_cfg.update(extra_module)
    config_path = tmp_path / f"{output_name}.yaml"
    dump_yaml(
        {
            "project": {
                "name": f"scdna_{output_name}",
                "organism": "human",
                "output_dir": str(tmp_path / output_name),
                "server_root": str(tmp_path),
                "run_mode": "interactive",
            },
            "samples": {"items": [{"sample_id": "S1", "condition": "validation", "input_path": str(source_root)}]},
            "modules": {"scdna": module_cfg},
        },
        config_path,
    )
    return config_path


def test_scdna_backend_generates_matrix_ready_outputs(tmp_path: Path) -> None:
    source_root = _write_scdna_fixture(tmp_path)
    config_path = _write_config(tmp_path, source_root=source_root)

    manifest = run_pipeline_from_config(config_path)
    run_dir = Path(manifest["output_dir"])
    module = manifest["modules"][0]

    assert module["module"] == "scdna"
    assert module["status"] == "complete_scdna_matrix_ready_backend"
    assert module["backend_id"] == "scdna.default.matrix_ready_handoff"
    assert module["analysis_level"] == "smoke_backend"
    assert module["delivery_allowed"] is False
    for key in (
        "coverage_qc",
        "variant_qc",
        "cell_variant_matrix",
        "cell_vaf_matrix",
        "cell_cnv_matrix",
        "clone_summary",
        "mutation_cooccurrence",
        "phylogeny_input",
    ):
        path = Path(module["artifacts"]["tables"][key])
        assert path.exists() and path.stat().st_size > 0, key
    assert Path(module["artifacts"]["figures"]["coverage_distribution"]).exists()
    assert Path(module["artifacts"]["figures"]["vaf_heatmap"]).exists()
    assert Path(module["artifacts"]["figures"]["clone_summary"]).exists()
    assert Path(module["artifacts"]["objects"]["mvp_object"]).name == "scdna_mvp_object.rds"

    variant_qc = pd.read_csv(run_dir / "results" / "tables" / "scdna" / "variant_qc.tsv", sep="\t")
    assert "variant_calling_not_run" in variant_qc["filter_status"].iloc[0]
    methods = (run_dir / "reports" / "scdna" / "methods.md").read_text(encoding="utf-8")
    assert "analysis_level" in methods
    assert "克隆树是模型结果，不是唯一真实进化历史" in methods


def test_scdna_backend_reads_vaf_matrix_and_marks_candidates(tmp_path: Path) -> None:
    coverage, vaf = _write_variant_fixture(tmp_path)
    config_path = _write_config(
        tmp_path,
        source_root=coverage,
        output_name="vaf",
        extra_module={"coverage_table": str(coverage), "vaf_matrix": str(vaf)},
    )

    manifest = run_pipeline_from_config(config_path)
    run_dir = Path(manifest["output_dir"])
    module = manifest["modules"][0]

    assert module["status"] == "complete_scdna_matrix_ready_backend"
    cell_variant = pd.read_csv(run_dir / "results" / "tables" / "scdna" / "cell_variant_matrix.tsv", sep="\t")
    assert "alt_detected" in set(cell_variant["genotype_call"])
    phylogeny = pd.read_csv(run_dir / "results" / "tables" / "scdna" / "phylogeny_input.tsv", sep="\t")
    assert "phylogeny_ready_binary_variant" in set(phylogeny["phylogeny_handoff_status"])


def test_scdna_backend_validated_fixture_is_evidence_not_delivery(tmp_path: Path) -> None:
    source_root = _write_scdna_fixture(tmp_path)
    config_path = _write_config(tmp_path, source_root=source_root, output_name="validated", analysis_level="validated_backend")

    manifest = run_pipeline_from_config(config_path)
    module = manifest["modules"][0]

    assert module["analysis_level"] == "validated_backend"
    assert module["validation_evidence_allowed"] is True
    assert module["delivery_allowed"] is False
    assert module["non_delivery_reason"] == "validation_evidence_only_not_customer_delivery"


def test_scdna_backend_missing_input_is_non_deliverable(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, source_root=tmp_path / "missing", output_name="missing")

    manifest = run_pipeline_from_config(config_path)
    run_dir = Path(manifest["output_dir"])
    module = manifest["modules"][0]

    assert module["status"] == "partial:scdna_inputs_missing"
    assert module["analysis_level"] == "smoke_backend"
    assert module["delivery_allowed"] is False
    assert module["validation_evidence_allowed"] is False
    assert module["skip_reasons"]
    qc_manifest = json.loads((run_dir / "results" / "tables" / "scdna" / "module_qc_manifest.json").read_text(encoding="utf-8"))
    assert qc_manifest["delivery_allowed"] is False
    assert qc_manifest["skip_reasons"]
