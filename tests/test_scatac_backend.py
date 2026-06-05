from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from ultimate.config import dump_yaml
from ultimate.pipeline import run_pipeline_from_config


def _write_peak_matrix(path: Path, rows: list[tuple[str, list[int]]], cells: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["peak_id\t" + "\t".join(cells)]
    for peak, values in rows:
        lines.append(peak + "\t" + "\t".join(map(str, values)))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_scatac_fixture(tmp_path: Path) -> Path:
    cells = ["cell_a", "cell_b", "cell_c", "cell_d", "cell_e", "cell_f"]
    peak_matrix = tmp_path / "peak_counts.tsv"
    _write_peak_matrix(
        peak_matrix,
        [
            ("chr1:100-200", [5, 6, 1, 0, 2, 3]),
            ("chr1:300-420", [0, 1, 8, 9, 2, 1]),
            ("chr2:50-150", [2, 2, 3, 4, 8, 9]),
            ("chr3:200-260", [7, 8, 0, 1, 1, 2]),
        ],
        cells,
    )
    return peak_matrix


def _write_config(tmp_path: Path, *, peak_matrix: Path, output_name: str = "run") -> Path:
    config_path = tmp_path / f"{output_name}.yaml"
    dump_yaml(
        {
            "project": {
                "name": f"scatac_{output_name}",
                "organism": "human",
                "output_dir": str(tmp_path / output_name),
                "server_root": str(tmp_path),
                "run_mode": "interactive",
            },
            "samples": {
                "items": [
                    {"sample_id": "A1", "condition": "control", "input_path": str(peak_matrix)},
                ]
            },
            "modules": {
                "scatac": {
                    "enabled": True,
                    "preset": "standard",
                    "peak_matrix": str(peak_matrix),
                    "raw": {
                        "enabled": False,
                        "input_type": "peak_matrix",
                    },
                }
            },
        },
        config_path,
    )
    return config_path


def test_scatac_backend_generates_mvp_outputs(tmp_path: Path) -> None:
    peak_matrix = _write_scatac_fixture(tmp_path)
    config_path = _write_config(tmp_path, peak_matrix=peak_matrix)

    manifest = run_pipeline_from_config(config_path)
    run_dir = Path(manifest["output_dir"])
    scatac = manifest["modules"][0]

    assert scatac["module"] == "scatac"
    assert scatac["status"] == "complete_scatac_peak_matrix_backend"
    assert scatac["backend_id"] == "scatac.matrix.signac_or_snapatac2_mvp"
    assert scatac["backend_status"] == "fully_automatic_validated_entrypoint"
    assert scatac["analysis_level"] == "smoke_backend"
    assert scatac["delivery_allowed"] is False
    assert scatac["n_cells"] == 6
    for key in ("cell_qc", "fragment_qc", "peak_matrix_summary", "tss_handoff", "frip_handoff", "marker_peaks", "gene_activity_handoff", "motif_enrichment_handoff"):
        path = Path(scatac["artifacts"]["tables"][key])
        assert path.exists() and path.stat().st_size > 0
    for key in ("lsi_umap", "fragment_qc", "peak_accessibility_heatmap"):
        path = Path(scatac["artifacts"]["figures"][key])
        assert path.exists() and path.stat().st_size > 0
    assert (run_dir / "objects" / "scatac" / "scatac_mvp.h5ad").exists()
    cell_qc = pd.read_csv(run_dir / "results" / "tables" / "scatac" / "cell_qc.tsv", sep="\t")
    assert {"cell_id", "n_fragments", "peak_region_fragments", "tss_enrichment_status", "frip_status"}.issubset(cell_qc.columns)
    assert set(cell_qc["tss_enrichment_status"]) == {"handoff_fragments_required"}
    peaks = pd.read_csv(run_dir / "results" / "tables" / "scatac" / "peak_matrix_summary.tsv", sep="\t")
    assert {"peak_id", "chrom", "start", "end", "detected_cell_count", "accessibility_status"}.issubset(peaks.columns)
    methods = (run_dir / "reports" / "scatac" / "methods.md").read_text(encoding="utf-8")
    assert "analysis_level" in methods
    assert "没有 fragments" in methods


def test_scatac_backend_missing_inputs_remains_non_deliverable(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, peak_matrix=tmp_path / "missing_peaks.tsv", output_name="missing")

    manifest = run_pipeline_from_config(config_path)
    run_dir = Path(manifest["output_dir"])
    scatac = manifest["modules"][0]

    assert scatac["status"] == "partial:scatac_inputs_missing"
    assert scatac["analysis_level"] == "smoke_backend"
    assert scatac["delivery_allowed"] is False
    assert scatac["validation_evidence_allowed"] is False
    assert scatac["skip_reasons"]
    qc_manifest = json.loads((run_dir / "results" / "tables" / "scatac" / "module_qc_manifest.json").read_text(encoding="utf-8"))
    assert qc_manifest["delivery_allowed"] is False
    assert qc_manifest["skip_reasons"]
