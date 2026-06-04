from __future__ import annotations

import json
import sys
from pathlib import Path


TOOLS_DIR = Path(__file__).parents[1] / "01_tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from validate_hto_demux_demo import run_public_fixture_validation


def test_hto_public_fixture_validation(tmp_path: Path) -> None:
    input_table = tmp_path / "hto_counts.tsv"
    input_table.write_text(
        "\n".join(
            [
                "cell_id\tHTO_A\tHTO_B\tHTO_C",
                "cell1\t90\t2\t1",
                "cell2\t3\t88\t2",
                "cell3\t1\t4\t92",
                "cell4\t65\t61\t2",
                "cell5\t3\t2\t1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    manifest = run_public_fixture_validation(input_table, tmp_path / "out", source_url="https://satijalab.org/seurat/articles/hashing_vignette.html")

    assert manifest["analysis_level"] == "validated_backend"
    assert manifest["validation_evidence_allowed"] is True
    assert manifest["delivery_allowed"] is False
    assert manifest["is_demo"] is False
    assert manifest["is_stub"] is False
    assert (tmp_path / "out" / "results" / "tables" / "hto_handoff.tsv").exists()
    assert (tmp_path / "out" / "results" / "tables" / "hto_demux_assignments.tsv").exists()
    payload = json.loads((tmp_path / "out" / "run_manifest.json").read_text(encoding="utf-8"))
    assert payload["dataset"] == "Satija Lab / Seurat 12-HTO hashing vignette fixture"
