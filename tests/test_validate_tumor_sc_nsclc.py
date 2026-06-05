from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ad = pytest.importorskip("anndata")


TOOLS_DIR = Path(__file__).parents[1] / "01_tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from validate_tumor_sc_nsclc import _export_copykat_counts, _missing_copykat_runtime_dependencies, run_validation


def test_tumor_sc_validation_writes_guarded_artifacts(tmp_path: Path) -> None:
    rng = np.random.default_rng(3)
    genes = ["EPCAM", "KRT8", "KRT18", "MKI67", "HIF1A", "VIM", "PTPRC", "LYZ", "COL1A1", "ACTA2", "GAPDH", "ACTB"]
    x = rng.poisson(2, size=(30, len(genes))).astype(float)
    obs = pd.DataFrame(
        {
            "sample_origin_harmonized": ["S1"] * 15 + ["S2"] * 15,
            "cell_type_level1_harmonized": ["Epithelial"] * 10 + ["Immune"] * 10 + ["Fibroblast"] * 10,
            "stemness_score": rng.normal(size=30),
            "proliferation_score": rng.normal(size=30),
            "hypoxia_score": rng.normal(size=30),
            "emt_score": rng.normal(size=30),
            "immune_escape_score": rng.normal(size=30),
            "inflammation_score": rng.normal(size=30),
        },
        index=[f"cell{i}" for i in range(30)],
    )
    var = pd.DataFrame(
        {
            "Chromosome.Name": ["1", "1", "1", "1", "1", "2", "2", "2", "2", "2", "3", "3"],
            "Gene.Start..bp.": np.arange(1, 13) * 100,
            "Gene.End..bp.": np.arange(1, 13) * 100 + 50,
        },
        index=genes,
    )
    adata = ad.AnnData(X=x, obs=obs, var=var)
    adata.obsm["X_umap"] = rng.normal(size=(30, 2))
    input_h5ad = tmp_path / "input.h5ad"
    adata.write_h5ad(input_h5ad)

    manifest = run_validation(
        input_h5ad=input_h5ad,
        output_dir=tmp_path / "out",
        max_cells=30,
        random_seed=1,
        rscript=tmp_path / "missing_Rscript",
        run_copykat=True,
        run_infercnv=True,
    )

    assert manifest["status"] == "ready"
    assert manifest["analysis_level"] == "validated_backend"
    assert manifest["delivery_allowed"] is False
    assert manifest["validation_evidence_allowed"] is True
    assert (tmp_path / "out" / "results" / "tables" / "malignant_cell_candidates.tsv").exists()
    assert (tmp_path / "out" / "results" / "tables" / "tool_status.tsv").exists()
    assert (tmp_path / "out" / "results" / "tables" / "backend_matrix_qc.tsv").exists()
    assert (tmp_path / "out" / "results" / "tables" / "backend_attempts.tsv").exists()
    assert (tmp_path / "out" / "results" / "figures" / "tumor_state_heatmap.png").exists()

    payload = json.loads((tmp_path / "out" / "run_manifest.json").read_text(encoding="utf-8"))
    assert payload["non_delivery_reason"] == "validation_evidence_only_not_customer_delivery"
    assert payload["copykat_requested"] is True
    assert payload["infercnv_requested"] is True
    assert payload["approve_full_cnv_backend"] is False
    attempts = pd.read_csv(tmp_path / "out" / "results" / "tables" / "backend_attempts.tsv", sep="\t")
    assert set(attempts["tool"]) == {"CopyKAT", "inferCNV"}
    assert set(attempts["status"]) == {"blocked"}
    tool_status = pd.read_csv(tmp_path / "out" / "results" / "tables" / "tool_status.tsv", sep="\t")
    assert "CopyKAT_dependency:dlm" in set(tool_status["tool"])
    assert "CopyKAT_dependency:MCMCpack" in set(tool_status["tool"])


def test_copykat_count_export_writes_gene_by_cell_matrix(tmp_path: Path) -> None:
    scipy_sparse = pytest.importorskip("scipy.sparse")
    genes = ["Gene A", "Gene A", "Gene/B", "Gene_C"]
    matrix = scipy_sparse.csr_matrix(
        np.array(
            [
                [1, 0, 3, 4],
                [0, 2, 0, 1],
                [5, 5, 0, 0],
            ],
            dtype=float,
        )
    )
    adata = ad.AnnData(
        X=matrix,
        obs=pd.DataFrame(index=["cell 1", "cell/2", "cell:3"]),
        var=pd.DataFrame(index=genes),
    )
    output_path = tmp_path / "copykat_counts.tsv.gz"

    n_cells, n_genes = _export_copykat_counts(matrix, adata, pd.Index(adata.var_names.astype(str)), output_path, max_cells=3, max_genes=4)

    assert n_cells == 3
    assert n_genes == 3
    exported = pd.read_csv(output_path, sep="\t")
    assert exported.columns.tolist() == ["gene", "cell_1", "cell_2", "cell_3"]
    assert set(exported["gene"]) == {"Gene A", "Gene/B", "Gene_C"}
    gene_a = exported.set_index("gene").loc["Gene A"]
    assert gene_a.tolist() == [1, 2, 10]


def test_copykat_count_export_uses_raw_var_names(tmp_path: Path) -> None:
    genes = ["RAW1", "RAW2", "RAW1"]
    matrix = np.array([[1, 2, 3], [4, 0, 0]], dtype=float)
    adata = ad.AnnData(
        X=np.ones((2, 2)),
        obs=pd.DataFrame(index=["cell1", "cell2"]),
        var=pd.DataFrame(index=["CURRENT1", "CURRENT2"]),
    )
    output_path = tmp_path / "raw_copykat_counts.tsv.gz"

    n_cells, n_genes = _export_copykat_counts(matrix, adata, pd.Index(genes), output_path, max_cells=2, max_genes=3)

    assert n_cells == 2
    assert n_genes == 2
    exported = pd.read_csv(output_path, sep="\t").set_index("gene")
    assert "CURRENT1" not in exported.index
    assert exported.loc["RAW1"].tolist() == [4, 4]


def test_copykat_approved_failure_does_not_emit_validated_evidence(tmp_path: Path) -> None:
    rng = np.random.default_rng(4)
    genes = [f"Gene{i}" for i in range(20)]
    x = rng.poisson(2, size=(25, len(genes))).astype(float)
    obs = pd.DataFrame(
        {
            "sample_origin_harmonized": ["S1"] * 25,
            "cell_type_level1_harmonized": ["Epithelial"] * 25,
        },
        index=[f"cell{i}" for i in range(25)],
    )
    var = pd.DataFrame(index=genes)
    adata = ad.AnnData(X=x, obs=obs, var=var)
    input_h5ad = tmp_path / "input.h5ad"
    adata.write_h5ad(input_h5ad)

    manifest = run_validation(
        input_h5ad=input_h5ad,
        output_dir=tmp_path / "out_failed",
        max_cells=25,
        random_seed=1,
        rscript=tmp_path / "missing_Rscript",
        run_copykat=True,
        approve_full_cnv_backend=True,
    )

    assert manifest["status"].startswith("partial:copykat_backend_not_ready")
    assert manifest["analysis_level"] == "smoke_backend"
    assert manifest["validation_evidence_allowed"] is False


def test_tumor_sc_slurm_exposes_guarded_copykat_knobs() -> None:
    script = (Path(__file__).parents[1] / "slurm" / "tumor_sc_validation.sbatch").read_text(encoding="utf-8")
    assert "ULTIMATE_TUMOR_SC_APPROVE_FULL_CNV" in script
    assert "--approve-full-cnv-backend" in script
    assert "--copykat-max-cells" in script
    assert "--copykat-max-genes" in script

    copykat_script = (Path(__file__).parents[1] / "slurm" / "tumor_sc_copykat_small_validation.sbatch").read_text(encoding="utf-8")
    assert "ULTIMATE_TUMOR_SC_APPROVE_FULL_CNV" in copykat_script
    assert "slurm_tumor_sc_copykat_small" in copykat_script


def test_copykat_runtime_dependency_checker_reports_missing_packages() -> None:
    status = pd.DataFrame(
        {
            "tool": ["CopyKAT_dependency:dlm", "CopyKAT_dependency:MCMCpack"],
            "available": [True, False],
        }
    )

    assert _missing_copykat_runtime_dependencies(status) == ["MCMCpack"]
