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

from validate_tumor_sc_nsclc import run_validation


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
    attempts = pd.read_csv(tmp_path / "out" / "results" / "tables" / "backend_attempts.tsv", sep="\t")
    assert set(attempts["tool"]) == {"CopyKAT", "inferCNV"}
    assert set(attempts["status"]) == {"blocked"}
