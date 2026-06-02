from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


def _load_validator():
    script = Path(__file__).resolve().parents[1] / "01_tools" / "validate_vdj_public.py"
    spec = importlib.util.spec_from_file_location("validate_vdj_public", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_validate_vdj_public_parses_string_booleans(tmp_path: Path) -> None:
    validator = _load_validator()
    input_dir = tmp_path / "vdj"
    input_dir.mkdir()
    pd.DataFrame(
        [
            {
                "contig_id": "c1",
                "barcode": "cell_a",
                "is_cell": "True",
                "productive": "True",
                "chain": "TRA",
                "reads": 10,
                "umis": 2,
                "raw_clonotype_id": "clonotype1",
            },
            {
                "contig_id": "c2",
                "barcode": "cell_b",
                "is_cell": "False",
                "productive": "True",
                "chain": "TRB",
                "reads": 20,
                "umis": 4,
                "raw_clonotype_id": "clonotype2",
            },
            {
                "contig_id": "c3",
                "barcode": "cell_c",
                "is_cell": "True",
                "productive": "False",
                "chain": "TRB",
                "reads": 30,
                "umis": 6,
                "raw_clonotype_id": "clonotype3",
            },
        ]
    ).to_csv(input_dir / "filtered_contig_annotations.csv", index=False)
    pd.DataFrame(
        [
            {"clonotype_id": "clonotype1", "frequency": 3},
            {"clonotype_id": "clonotype2", "frequency": 1},
        ]
    ).to_csv(input_dir / "clonotypes.csv", index=False)

    manifest = validator.run_validation(input_dir, tmp_path / "out")

    assert manifest["n_cell_contigs"] == 2
    assert manifest["n_productive_contigs"] == 1
    assert manifest["n_cells"] == 1
    assert Path(manifest["tables"][0]).exists()
