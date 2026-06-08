from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

from ultimate.config import dump_yaml
from ultimate.pipeline import run_pipeline_from_config
from ultimate.modules.scepi import backend_metadata, demo, input_contract, preflight, validate


def _write_region_matrix(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "feature_id\tcell_a\tcell_b\tcell_c\tcell_d\tcell_e\tcell_f",
                "chr1:100-200_promoter\t5\t6\t1\t0\t2\t3",
                "chr1:300-420_enhancer\t0\t1\t8\t9\t2\t1",
                "chr2:50-150\t2\t2\t3\t4\t8\t9",
                "chr3:200-260_promoter\t7\t8\t0\t1\t1\t2",
                "chr4:500-700_enhancer\t1\t0\t6\t7\t3\t2",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _write_config(tmp_path: Path, *, matrix: Path, output_name: str = "run") -> Path:
    config_path = tmp_path / f"{output_name}.yaml"
    dump_yaml(
        {
            "project": {
                "name": f"scepi_{output_name}",
                "organism": "human",
                "output_dir": str(tmp_path / output_name),
                "server_root": str(tmp_path),
                "run_mode": "interactive",
            },
            "samples": {
                "items": [
                    {"sample_id": "cell_a", "condition": "control", "input_path": str(matrix)},
                    {"sample_id": "cell_b", "condition": "control", "input_path": str(matrix)},
                    {"sample_id": "cell_c", "condition": "treated", "input_path": str(matrix)},
                    {"sample_id": "cell_d", "condition": "treated", "input_path": str(matrix)},
                    {"sample_id": "cell_e", "condition": "treated", "input_path": str(matrix)},
                    {"sample_id": "cell_f", "condition": "control", "input_path": str(matrix)},
                ]
            },
            "modules": {
                "scepi": {
                    "enabled": True,
                    "preset": "standard",
                    "input_matrix": str(matrix),
                    "raw": {
                        "enabled": False,
                        "input_type": "region_matrix",
                    },
                }
            },
        },
        config_path,
    )
    return config_path


def _load_validate_scepi_public_module():
    path = Path(__file__).resolve().parents[1] / "01_tools" / "validate_scepi_public.py"
    spec = importlib.util.spec_from_file_location("validate_scepi_public", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scepi_backend_generates_matrix_level_outputs(tmp_path: Path) -> None:
    matrix = _write_region_matrix(tmp_path / "region_matrix.tsv")
    config_path = _write_config(tmp_path, matrix=matrix)

    manifest = run_pipeline_from_config(config_path)
    run_dir = Path(manifest["output_dir"])
    scepi = manifest["modules"][0]

    assert scepi["module"] == "scepi"
    assert scepi["status"] == "complete_scepi_matrix_backend"
    assert scepi["backend_id"] == "scepi.default.matrix_handoff_mvp"
    assert scepi["backend_status"] == "fully_automatic_validated_entrypoint"
    assert scepi["analysis_level"] == "smoke_backend"
    assert scepi["delivery_allowed"] is False
    assert scepi["n_features"] == 5
    assert scepi["n_samples"] == 6
    for key in ("feature_qc", "sample_qc", "missing_value_summary", "differential_region_handoff", "promoter_summary", "enhancer_summary", "annotation_summary"):
        path = Path(scepi["artifacts"]["tables"][key])
        assert path.exists() and path.stat().st_size > 0
    for key in ("pca", "sample_correlation_heatmap", "region_heatmap"):
        path = Path(scepi["artifacts"]["figures"][key])
        assert path.exists() and path.stat().st_size > 0
    assert (run_dir / "objects" / "scepi" / "scepi_mvp_object.json").exists()
    assert (run_dir / "objects" / "scepi" / "scepi_mvp_object.rds").exists()
    feature_qc = pd.read_csv(run_dir / "results" / "tables" / "scepi" / "feature_qc.tsv", sep="\t")
    assert {"feature_id", "mean_signal", "variance_signal", "region_class", "interpretation_warning"}.issubset(feature_qc.columns)
    assert {"promoter", "enhancer"}.issubset(set(feature_qc["region_class"]))
    differential = pd.read_csv(run_dir / "results" / "tables" / "scepi" / "differential_region_handoff.tsv", sep="\t")
    assert set(differential["statistical_status"]) == {"design_ready_with_group_effect_preview_not_formal_dmr"}
    methods = (run_dir / "reports" / "scepi" / "methods.md").read_text(encoding="utf-8")
    assert "analysis_level" in methods
    assert "CUT&RUN" in methods


def test_scepi_module_entrypoints_expose_real_backend_metadata(tmp_path: Path) -> None:
    matrix = _write_region_matrix(tmp_path / "region_matrix.tsv")
    config_path = _write_config(tmp_path, matrix=matrix)
    config = json.loads(json.dumps({"modules": {"scepi": {"input_matrix": str(matrix), "raw": {"input_type": "region_matrix"}}}}))
    samples = pd.DataFrame(
        [
            {"sample_id": "cell_a", "condition": "control", "input_path": str(matrix)},
            {"sample_id": "cell_b", "condition": "control", "input_path": str(matrix)},
            {"sample_id": "cell_c", "condition": "treated", "input_path": str(matrix)},
            {"sample_id": "cell_d", "condition": "treated", "input_path": str(matrix)},
        ]
    )

    assert backend_metadata()["backend_id"] == "scepi.default.matrix_handoff_mvp"
    assert validate()["public_validation_entrypoint"].endswith("validate_scepi_public.py")
    assert demo(tmp_path)["backend"]["backend_status"] == "fully_automatic_validated_entrypoint"
    contract = input_contract(config, samples=samples)
    assert contract["status"] == "ready"
    assert contract["numeric_column_count"] == 6
    assert contract["differential_preview_ready"] is True
    report = preflight(config, samples=samples)
    assert report["scepi_matrix_backend"]["status"] == "ready"
    assert Path(config_path).exists()


def test_scepi_differential_handoff_when_groups_have_insufficient_replicates(tmp_path: Path) -> None:
    matrix = _write_region_matrix(tmp_path / "region_matrix.tsv")
    config_path = tmp_path / "insufficient.yaml"
    dump_yaml(
        {
            "project": {
                "name": "scepi_insufficient",
                "organism": "human",
                "output_dir": str(tmp_path / "insufficient"),
                "server_root": str(tmp_path),
                "run_mode": "interactive",
            },
            "samples": {
                "items": [
                    {"sample_id": "cell_a", "condition": "control", "input_path": str(matrix)},
                    {"sample_id": "cell_b", "condition": "treated", "input_path": str(matrix)},
                    {"sample_id": "cell_c", "condition": "other", "input_path": str(matrix)},
                ]
            },
            "modules": {"scepi": {"enabled": True, "input_matrix": str(matrix), "raw": {"enabled": False, "input_type": "region_matrix"}}},
        },
        config_path,
    )

    manifest = run_pipeline_from_config(config_path)
    run_dir = Path(manifest["output_dir"])
    differential = pd.read_csv(run_dir / "results" / "tables" / "scepi" / "differential_region_handoff.tsv", sep="\t")
    assert set(differential["statistical_status"]) == {"handoff_ready_group_replicates_required"}
    assert "formal DMR/DAR requires" in set(differential["required_backend"]).pop()


def test_scepi_h5ad_input_runs_or_clearly_partials(tmp_path: Path) -> None:
    ad = pytest.importorskip("anndata")
    import numpy as np

    matrix = tmp_path / "scepi.h5ad"
    adata = ad.AnnData(X=np.array([[1, 0, 2], [0, 3, 4]], dtype=float))
    adata.obs_names = ["cell_a", "cell_b"]
    adata.var_names = ["chr1:1-100_promoter", "chr1:200-300_enhancer", "chr2:20-80"]
    adata.write_h5ad(matrix)
    config_path = _write_config(tmp_path, matrix=matrix, output_name="h5ad")

    manifest = run_pipeline_from_config(config_path)
    scepi = manifest["modules"][0]
    assert scepi["module"] == "scepi"
    assert scepi["status"] == "complete_scepi_matrix_backend"
    assert scepi["input_modality"] == "region_matrix"
    assert scepi["delivery_allowed"] is False


def test_scepi_backend_missing_inputs_remains_non_deliverable(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, matrix=tmp_path / "missing_region_matrix.tsv", output_name="missing")

    manifest = run_pipeline_from_config(config_path)
    run_dir = Path(manifest["output_dir"])
    scepi = manifest["modules"][0]

    assert scepi["status"] in {"partial:scepi_inputs_missing", "partial:scepi_input_read_failed"}
    assert scepi["analysis_level"] == "smoke_backend"
    assert scepi["delivery_allowed"] is False
    assert scepi["validation_evidence_allowed"] is False
    assert scepi["skip_reasons"]
    qc_manifest = json.loads((run_dir / "results" / "tables" / "scepi" / "module_qc_manifest.json").read_text(encoding="utf-8"))
    assert qc_manifest["delivery_allowed"] is False
    assert qc_manifest["skip_reasons"]


def test_validate_scepi_public_writes_scepi_config_not_methylation(tmp_path: Path) -> None:
    module = _load_validate_scepi_public_module()
    matrix = _write_region_matrix(tmp_path / "region_matrix.tsv")
    prepared = {
        "region_matrix": matrix,
        "samplesheet": tmp_path / "samples.tsv",
        "dataset_manifest": tmp_path / "dataset_manifest.tsv",
        "source_h5": tmp_path / "source.h5",
        "n_samples": 6,
        "n_features": 5,
    }
    prepared["samplesheet"].write_text("sample_id\tcondition\tbatch\tinput_path\ncell_a\tcontrol\tbatch1\t%s\ncell_b\ttreated\tbatch1\t%s\n" % (matrix, matrix), encoding="utf-8")
    config_path = module.write_project_config(output_dir=tmp_path / "validation", prepared=prepared, project_root=tmp_path)
    text = config_path.read_text(encoding="utf-8")
    assert "scepi:" in text
    assert "methylation:" not in text
    assert "analysis_level: validated_backend" in text
    assert "validation_dataset: 10x_pbmc_scatac_derived_region_matrix" in text


def test_validate_scepi_public_skip_manifest_is_not_delivery(tmp_path: Path) -> None:
    module = _load_validate_scepi_public_module()
    manifest = module.run_validation(output_dir=tmp_path / "missing_public", input_h5=tmp_path / "missing.h5", project_root=tmp_path, max_features=10, max_cells=10)
    assert manifest["status"] == "partial:data_required"
    assert manifest["analysis_level"] == "smoke_backend"
    assert manifest["delivery_allowed"] is False
    assert manifest["validation_evidence_allowed"] is False
    assert manifest["delivery_scope"] == "not_customer_delivery"
