from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from ultimate.config import dump_yaml
from ultimate.pipeline import run_pipeline_from_config


def _write_matrix(path: Path, prefix: str, *, beta: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if beta:
        rows = [
            [f"{prefix}_001", 0.22, 0.24, 0.72, 0.74],
            [f"{prefix}_002", 0.31, 0.29, 0.35, 0.36],
            [f"{prefix}_003", 0.64, 0.62, 0.18, 0.20],
            [f"{prefix}_004", 0.42, 0.44, 0.49, 0.51],
        ]
    else:
        rows = [
            [f"{prefix}_001", 12.0, 12.5, 20.0, 21.0],
            [f"{prefix}_002", 8.0, 8.5, 7.8, 8.2],
            [f"{prefix}_003", 3.0, 3.5, 12.0, 13.5],
            [f"{prefix}_004", 16.0, 15.0, 11.0, 10.5],
        ]
    lines = ["feature_id\tCTRL_1\tCTRL_2\tTRT_1\tTRT_2"]
    lines.extend("\t".join(map(str, row)) for row in rows)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_config(tmp_path: Path, module_name: str, matrix: Path, *, output_name: str = "run") -> Path:
    config_path = tmp_path / f"{module_name}_{output_name}.yaml"
    dump_yaml(
        {
            "project": {
                "name": f"{module_name}_{output_name}",
                "organism": "human",
                "output_dir": str(tmp_path / f"{module_name}_{output_name}"),
                "server_root": str(tmp_path),
                "run_mode": "interactive",
            },
            "samples": {
                "items": [
                    {"sample_id": "CTRL_1", "condition": "control", "input_path": str(matrix)},
                    {"sample_id": "CTRL_2", "condition": "control", "input_path": str(matrix)},
                    {"sample_id": "TRT_1", "condition": "treated", "input_path": str(matrix)},
                    {"sample_id": "TRT_2", "condition": "treated", "input_path": str(matrix)},
                ]
            },
            "design": {"condition_column": "condition", "control": "control", "case": "treated"},
            "modules": {
                module_name: {
                    "enabled": True,
                    "preset": "publication",
                    "input_matrix": str(matrix),
                    "raw": {"enabled": False, "input_type": "matrix"},
                }
            },
        },
        config_path,
    )
    return config_path


def test_proteomics_publication_runs_limma_optional_backend(tmp_path: Path) -> None:
    matrix = _write_matrix(tmp_path / "protein_abundance.tsv", "PROT")
    config_path = _write_config(tmp_path, "proteomics", matrix)

    manifest = run_pipeline_from_config(config_path)
    run_dir = Path(manifest["output_dir"])
    module = manifest["modules"][0]
    active_ids = {row["backend_id"] for row in module["backend_plan"]["active_backends"]}
    execution = {row["backend_id"]: row for row in module["backend_execution"]}

    assert "proteomics.de.limma_optional" in active_ids
    assert execution["proteomics.de.limma_optional"]["status"] == "ready"
    for relative in [
        "results/tables/proteomics/limma_de_results.tsv",
        "results/tables/proteomics/proteomics_limma_backend_status.tsv",
        "results/tables/proteomics/proteomics_limma_backend_manifest.json",
        "results/tables/proteomics/proteomics_limma_backend_versions.tsv",
        "results/figures/proteomics/proteomics_limma_volcano.png",
        "results/figures/proteomics/proteomics_limma_heatmap.png",
        "objects/proteomics/proteomics_limma_backend.rds",
    ]:
        path = run_dir / relative
        assert path.exists() and path.stat().st_size > 0
    result = pd.read_csv(run_dir / "results/tables/proteomics/limma_de_results.tsv", sep="\t")
    assert {"protein_id", "log2_abundance_delta", "padj", "method_boundary"}.issubset(result.columns)
    assert "不能写成真实物理互作" in result.loc[0, "method_boundary"]
    status = pd.read_csv(run_dir / "results/tables/proteomics/proteomics_limma_backend_status.tsv", sep="\t")
    assert bool(status.loc[0, "delivery_allowed"]) is False


def test_methylation_publication_runs_beta_dmp_backend(tmp_path: Path) -> None:
    matrix = _write_matrix(tmp_path / "beta_matrix.tsv", "cg", beta=True)
    config_path = _write_config(tmp_path, "methylation", matrix)

    manifest = run_pipeline_from_config(config_path)
    run_dir = Path(manifest["output_dir"])
    module = manifest["modules"][0]
    active_ids = {row["backend_id"] for row in module["backend_plan"]["active_backends"]}
    execution = {row["backend_id"]: row for row in module["backend_execution"]}

    assert "methylation.dmp.limma_beta" in active_ids
    assert execution["methylation.dmp.limma_beta"]["status"] == "ready"
    for relative in [
        "results/tables/methylation/dmp_limma_results.tsv",
        "results/tables/methylation/methylation_dmp_backend_status.tsv",
        "results/tables/methylation/methylation_dmp_backend_manifest.json",
        "results/tables/methylation/methylation_dmp_backend_versions.tsv",
        "results/tables/methylation/methylation_mvalue_summary.tsv",
        "results/figures/methylation/methylation_dmp_volcano.png",
        "results/figures/methylation/methylation_dmp_heatmap.png",
        "objects/methylation/methylation_dmp_backend.rds",
    ]:
        path = run_dir / relative
        assert path.exists() and path.stat().st_size > 0
    result = pd.read_csv(run_dir / "results/tables/methylation/dmp_limma_results.tsv", sep="\t")
    assert {"region_id", "m_value_delta", "beta_delta", "padj", "method_boundary", "annotation_status"}.issubset(result.columns)
    assert "不是完整 DMR" in result.loc[0, "method_boundary"]


def test_proteomics_limma_backend_skips_when_replicates_are_insufficient(tmp_path: Path) -> None:
    matrix = _write_matrix(tmp_path / "protein_abundance.tsv", "PROT")
    config_path = _write_config(tmp_path, "proteomics", matrix, output_name="skip")
    loaded = config_path.read_text(encoding="utf-8")
    config_path.write_text(loaded.replace("condition: treated", "condition: control", 1), encoding="utf-8")

    manifest = run_pipeline_from_config(config_path)
    run_dir = Path(manifest["output_dir"])
    module = manifest["modules"][0]
    execution = {row["backend_id"]: row for row in module["backend_execution"]}

    assert execution["proteomics.de.limma_optional"]["status"] == "skipped"
    assert "insufficient_replicates" in execution["proteomics.de.limma_optional"]["reason"]
    backend_manifest = json.loads((run_dir / "results/tables/proteomics/proteomics_limma_backend_manifest.json").read_text(encoding="utf-8"))
    assert backend_manifest["delivery_allowed"] is False
