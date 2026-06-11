from __future__ import annotations

import json
import gzip
from pathlib import Path

from click.testing import CliRunner

from ultimate.cli import main
from ultimate.raw_upstream import run_raw_upstream_evidence


def test_raw_upstream_rnaseq_fastq_evidence_ready(tmp_path: Path) -> None:
    fastq_dir = tmp_path / "fastq"
    fastq_dir.mkdir()
    fastq = fastq_dir / "S1.fastq"
    fastq.write_text("@r1\nACGT\n+\n!!!!\n@r2\nTGCA\n+\n!!!!\n", encoding="utf-8")
    samplesheet = tmp_path / "samples.tsv"
    samplesheet.write_text(f"sample_id\tcondition\tfastq_1\nS1\tcase\t{fastq}\n", encoding="utf-8")

    manifest = run_raw_upstream_evidence(module="rnaseq", input_path=fastq_dir, samplesheet=samplesheet, output_dir=tmp_path / "out")

    assert manifest["status"] == "ready"
    assert manifest["validation_evidence_allowed"] is True
    matrix = Path(manifest["artifacts"]["output_matrix"])
    assert matrix.exists()
    assert "FASTQ_READS_CONTROLLED_IMPORT\t2" in matrix.read_text(encoding="utf-8")
    assert Path(manifest["artifacts"]["raw_upstream_evidence"]).exists()
    assert Path(manifest["artifacts"]["failure_recovery"]).exists()


def test_raw_upstream_rnaseq_tiny_counts_requires_tool_and_reference(tmp_path: Path, monkeypatch) -> None:
    fastq_dir = tmp_path / "fastq"
    fastq_dir.mkdir()
    fastq = fastq_dir / "S1.fastq"
    fastq.write_text("@r1\nACGT\n+\n!!!!\n@r2\nTGCA\n+\n!!!!\n", encoding="utf-8")
    reference = tmp_path / "tiny.fa"
    reference.write_text(">GENE_A\nACGT\n>GENE_B\nTGCA\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    salmon = bin_dir / "salmon"
    salmon.write_text("#!/usr/bin/env bash\necho salmon-test\n", encoding="utf-8")
    salmon.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}")
    monkeypatch.setenv("SLURM_JOB_ID", "999")

    manifest = run_raw_upstream_evidence(
        module="rnaseq",
        input_path=fastq_dir,
        samplesheet=None,
        output_dir=tmp_path / "tiny_out",
        stage="rnaseq_fastq_tiny_counts",
        tiny_reference=reference,
        quant_tool="salmon",
    )

    assert manifest["status"] == "ready"
    assert manifest["slurm_job_id"] == "999"
    assert manifest["quant_tool"] == "salmon"
    matrix = Path(manifest["artifacts"]["output_matrix"]).read_text(encoding="utf-8")
    assert "GENE_A" in matrix
    assert "GENE_B" in matrix


def test_raw_upstream_rnaseq_tiny_counts_blocks_missing_reference(tmp_path: Path, monkeypatch) -> None:
    fastq = tmp_path / "S1.fastq"
    fastq.write_text("@r1\nACGT\n+\n!!!!\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    salmon = bin_dir / "salmon"
    salmon.write_text("#!/usr/bin/env bash\necho salmon-test\n", encoding="utf-8")
    salmon.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}")

    manifest = run_raw_upstream_evidence(
        module="rnaseq",
        input_path=fastq,
        samplesheet=None,
        output_dir=tmp_path / "blocked_ref",
        stage="rnaseq_fastq_tiny_counts",
        tiny_reference=None,
        quant_tool="salmon",
    )

    assert manifest["status"] == "blocked"
    assert "tiny_reference" in manifest["blocked_reason"]


def test_raw_upstream_rnaseq_tiny_counts_blocks_missing_quant_tool(tmp_path: Path, monkeypatch) -> None:
    fastq = tmp_path / "S1.fastq"
    fastq.write_text("@r1\nACGT\n+\n!!!!\n", encoding="utf-8")
    reference = tmp_path / "tiny.fa"
    reference.write_text(">GENE_A\nACGT\n", encoding="utf-8")
    monkeypatch.setenv("PATH", str(tmp_path / "empty_bin"))

    manifest = run_raw_upstream_evidence(
        module="rnaseq",
        input_path=fastq,
        samplesheet=None,
        output_dir=tmp_path / "blocked_tool",
        stage="rnaseq_fastq_tiny_counts",
        tiny_reference=reference,
        quant_tool="salmon",
    )

    assert manifest["status"] == "blocked"
    assert "required quant tool not found" in manifest["blocked_reason"]


def test_raw_upstream_scrna_10x_mtx_evidence_ready(tmp_path: Path) -> None:
    mtx = tmp_path / "tenx_mtx"
    mtx.mkdir()
    (mtx / "matrix.mtx").write_text(
        "%%MatrixMarket matrix coordinate integer general\n"
        "%\n"
        "2 2 2\n"
        "1 1 3\n"
        "2 2 4\n",
        encoding="utf-8",
    )
    (mtx / "features.tsv").write_text("GENE1\tGENE1\tGene Expression\nGENE2\tGENE2\tGene Expression\n", encoding="utf-8")
    (mtx / "barcodes.tsv").write_text("CELL1\nCELL2\n", encoding="utf-8")

    manifest = run_raw_upstream_evidence(module="scrna", input_path=mtx, samplesheet=None, output_dir=tmp_path / "out")

    assert manifest["status"] == "ready"
    matrix = Path(manifest["artifacts"]["output_matrix"])
    assert "GENE1\t3" in matrix.read_text(encoding="utf-8")
    raw_qc = json.loads(Path(manifest["artifacts"]["raw_qc_manifest"]).read_text(encoding="utf-8"))
    assert raw_qc["status"] == "ready"


def test_raw_upstream_scrna_10x_mtx_gz_evidence_ready(tmp_path: Path) -> None:
    mtx = tmp_path / "tenx_mtx_gz"
    mtx.mkdir()
    _gzip_write(
        mtx / "matrix.mtx.gz",
        "%%MatrixMarket matrix coordinate integer general\n%\n2 1 1\n1 1 5\n",
    )
    _gzip_write(mtx / "features.tsv.gz", "GENE1\tGENE1\tGene Expression\nGENE2\tGENE2\tGene Expression\n")
    _gzip_write(mtx / "barcodes.tsv.gz", "CELL1\n")

    manifest = run_raw_upstream_evidence(module="scrna", input_path=mtx, samplesheet=None, output_dir=tmp_path / "out_gz")

    assert manifest["status"] == "ready"
    assert "GENE1\t5" in Path(manifest["artifacts"]["output_matrix"]).read_text(encoding="utf-8")


def test_raw_upstream_missing_input_writes_blocked_manifest(tmp_path: Path) -> None:
    manifest = run_raw_upstream_evidence(module="rnaseq", input_path=tmp_path / "missing.fastq", samplesheet=None, output_dir=tmp_path / "out")

    assert manifest["status"] == "blocked"
    assert manifest["validation_evidence_allowed"] is False
    assert "FileNotFoundError" in manifest["blocked_reason"]
    assert Path(manifest["artifacts"]["raw_upstream_evidence"]).exists()


def test_raw_upstream_cli_returns_nonzero_when_blocked(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        main,
        [
            "raw-upstream-evidence",
            "--module",
            "rnaseq",
            "--input-path",
            str(tmp_path / "missing.fastq"),
            "--output-dir",
            str(tmp_path / "out"),
        ],
    )

    assert result.exit_code != 0
    assert "raw-upstream-evidence blocked" in result.output


def _gzip_write(path: Path, text: str) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(text)
