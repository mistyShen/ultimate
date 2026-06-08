from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path


TOOLS_DIR = Path(__file__).parents[1] / "01_tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from validate_genotype_demux_demo import run_public_fixture_validation
from ultimate.modules.common import GLOBAL_MVP_TABLE_COLUMNS


def test_genotype_demux_public_fixture_validation(tmp_path: Path) -> None:
    input_dir = tmp_path / "cellSNP_mat"
    input_dir.mkdir()
    (input_dir / "cellSNP.samples.tsv").write_text("cellA\ncellB\ncellC\n", encoding="utf-8")
    with gzip.open(input_dir / "cellSNP.base.vcf.gz", "wt", encoding="utf-8") as handle:
        handle.write("##fileformat=VCFv4.2\n")
        handle.write("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n")
        handle.write("1\t100\t.\tA\tG\t.\tPASS\t.\n")
        handle.write("1\t200\t.\tC\tT\t.\tPASS\t.\n")
    (input_dir / "cellSNP.tag.AD.mtx").write_text(
        "\n".join(
            [
                "%%MatrixMarket matrix coordinate integer general",
                "%",
                "2 3 4",
                "1 1 1",
                "1 2 3",
                "2 2 4",
                "2 3 8",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (input_dir / "cellSNP.tag.DP.mtx").write_text(
        "\n".join(
            [
                "%%MatrixMarket matrix coordinate integer general",
                "%",
                "2 3 5",
                "1 1 10",
                "1 2 10",
                "2 2 10",
                "1 3 2",
                "2 3 10",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    manifest = run_public_fixture_validation(input_dir, tmp_path / "out", source_url="https://github.com/single-cell-genetics/vireo")

    assert manifest["analysis_level"] == "validated_backend"
    assert manifest["validation_evidence_allowed"] is True
    assert manifest["delivery_allowed"] is False
    assert manifest["is_demo"] is False
    assert manifest["is_stub"] is False
    assert (tmp_path / "out" / "results" / "tables" / "snp_qc.tsv").exists()
    assert (tmp_path / "out" / "results" / "tables" / "vireo_handoff.tsv").exists()
    for filename in ("snp_qc.tsv", "assignment.tsv", "sample_composition.tsv", "cell_metadata_with_genotype.tsv"):
        header = (tmp_path / "out" / "results" / "tables" / filename).read_text(encoding="utf-8").splitlines()[0].split("\t")
        assert header[: len(GLOBAL_MVP_TABLE_COLUMNS)] == list(GLOBAL_MVP_TABLE_COLUMNS)
    payload = json.loads((tmp_path / "out" / "run_manifest.json").read_text(encoding="utf-8"))
    assert payload["dataset"] == "single-cell-genetics/vireo data/cellSNP_mat"
