from __future__ import annotations

import json
from pathlib import Path

import yaml
from click.testing import CliRunner

from ultimate.cli import main
from ultimate.triage import run_triage


def _write_request(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def test_triage_rnaseq_minimal_request_ready_to_run(tmp_path: Path) -> None:
    samplesheet = tmp_path / "samples.tsv"
    samplesheet.write_text("sample_id\tcondition\nS1\tcontrol\n", encoding="utf-8")
    request = _write_request(
        tmp_path / "analysis_request.yaml",
        {"request_id": "RNASEQ001", "modules": ["rnaseq"], "samplesheet": str(samplesheet), "presets": ["standard"], "matrix_path": str(tmp_path / "counts.tsv")},
    )
    (tmp_path / "counts.tsv").write_text("gene\tS1\nG1\t10\n", encoding="utf-8")

    manifest = run_triage(request, tmp_path / "triage" / "RNASEQ001")

    assert manifest["status"] == "ready_to_run"
    assert manifest["input_summary"]["standard_input_detected"] is True
    assert manifest["input_summary"]["handoff_required"] is False
    assert manifest["analysis_level"] == "smoke_backend"
    assert manifest["delivery_allowed"] is False
    assert manifest["validation_evidence_allowed"] is False
    assert manifest["non_delivery_reason"] == "triage_only_not_analysis_run"
    assert Path(manifest["triage_report_md"]).exists()
    assert Path(manifest["suggested_project_yaml"]).exists()
    assert Path(manifest["input_assessment"]).exists()
    assert Path(manifest["handoff_plan"]).exists()
    slurm_command = Path(manifest["slurm_command"]).read_text(encoding="utf-8")
    assert "ultimate prepare-job" in slurm_command
    assert "ultimate_run.sbatch" not in slurm_command
    assert not (Path(manifest["output_dir"]) / "run_manifest.json").exists()
    assert not (Path(manifest["output_dir"]) / "production_approval.json").exists()


def test_triage_scrna_missing_samplesheet_needs_metadata(tmp_path: Path) -> None:
    request = _write_request(tmp_path / "request.yaml", {"request_id": "SCRNA001", "modules": ["scrna"], "presets": ["basic"]})

    manifest = run_triage(request, tmp_path / "triage" / "SCRNA001")

    assert manifest["status"] == "needs_metadata"
    missing = Path(manifest["missing_requirements"]).read_text(encoding="utf-8")
    assert "samplesheet" in missing
    assert "needs_metadata" in missing


def test_triage_fastq_requires_handoff_review(tmp_path: Path) -> None:
    samplesheet = tmp_path / "samples.tsv"
    fastq = tmp_path / "S1_R1.fastq.gz"
    fastq.write_text("tiny", encoding="utf-8")
    samplesheet.write_text(f"sample_id\tcondition\tfastq_1\nS1\tcontrol\t{fastq}\n", encoding="utf-8")
    request = _write_request(
        tmp_path / "request.yaml",
        {"request_id": "FASTQ001", "modules": ["rnaseq"], "samplesheet": str(samplesheet), "fastq_dir": str(tmp_path / "fastq")},
    )

    manifest = run_triage(request, tmp_path / "triage" / "FASTQ001")

    assert manifest["status"] == "needs_manual_review"
    assert manifest["input_summary"]["raw_upstream_detected"] is True
    assert manifest["input_summary"]["standard_input_detected"] is False
    assert manifest["input_summary"]["handoff_required"] is True
    assert "handoff_required" in manifest["presets"]
    assert "nfcore_rnaseq" in Path(manifest["handoff_plan"]).read_text(encoding="utf-8")


def test_triage_relative_samplesheet_and_missing_condition(tmp_path: Path) -> None:
    request_dir = tmp_path / "request_dir"
    request_dir.mkdir()
    samplesheet = request_dir / "samples.tsv"
    matrix = request_dir / "counts.tsv"
    samplesheet.write_text("sample_id\tmatrix_path\nS1\tcounts.tsv\n", encoding="utf-8")
    matrix.write_text("gene\tS1\nG1\t1\n", encoding="utf-8")
    request = _write_request(request_dir / "request.yaml", {"request_id": "REL001", "modules": ["rnaseq"], "samplesheet": "samples.tsv"})

    manifest = run_triage(request, tmp_path / "triage" / "REL001")

    assert manifest["status"] == "needs_metadata"
    assert "samplesheet.condition" in Path(manifest["missing_requirements"]).read_text(encoding="utf-8")
    assert str(matrix.resolve()) in Path(manifest["input_assessment"]).read_text(encoding="utf-8")


def test_triage_markdown_request_parses_basic_hints(tmp_path: Path) -> None:
    samplesheet = tmp_path / "samples.tsv"
    h5ad = tmp_path / "pbmc.h5ad"
    samplesheet.write_text(f"sample_id\tcondition\tinput_path\nS1\tcontrol\t{h5ad}\n", encoding="utf-8")
    h5ad.write_text("mock", encoding="utf-8")
    request = tmp_path / "request.md"
    request.write_text(f"请做单细胞 h5ad 的 communication 分析。\nsamplesheet: {samplesheet}\n", encoding="utf-8")

    manifest = run_triage(request, tmp_path / "triage" / "MD001")

    assert manifest["requested_modules"] == ["scrna"]
    assert "communication" in manifest["presets"]
    assert manifest["analysis_level"] == "smoke_backend"


def test_triage_authorized_tool_request_needs_license(tmp_path: Path) -> None:
    samplesheet = tmp_path / "samples.tsv"
    samplesheet.write_text("sample_id\tcondition\nS1\tcontrol\n", encoding="utf-8")
    request = _write_request(
        tmp_path / "request.yaml",
        {"request_id": "VDJ001", "modules": ["vdj"], "samplesheet": str(samplesheet), "licensed_tools": ["Cell Ranger VDJ"]},
    )

    manifest = run_triage(request, tmp_path / "triage" / "VDJ001")

    assert manifest["status"] == "needs_license"
    assert manifest["delivery_allowed"] is False
    assert "Cell Ranger VDJ" in Path(manifest["missing_requirements"]).read_text(encoding="utf-8")


def test_triage_cli_does_not_create_run_manifest_or_delivery(tmp_path: Path) -> None:
    samplesheet = tmp_path / "samples.tsv"
    samplesheet.write_text("sample_id\tcondition\nS1\tcontrol\n", encoding="utf-8")
    request = _write_request(tmp_path / "request.yaml", {"modules": ["rnaseq"], "samplesheet": str(samplesheet)})
    out = tmp_path / "triage"

    result = CliRunner().invoke(main, ["triage", "--request", str(request), "--output-dir", str(out)])

    assert result.exit_code == 0, result.output
    manifest = json.loads(result.output)
    assert manifest["delivery_allowed"] is False
    assert (out / "triage_manifest.json").exists()
    assert not (out / "run_manifest.json").exists()
    assert not (out / "production_approval.json").exists()
