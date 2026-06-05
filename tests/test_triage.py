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
        {"request_id": "RNASEQ001", "modules": ["rnaseq"], "samplesheet": str(samplesheet), "presets": ["standard"]},
    )

    manifest = run_triage(request, tmp_path / "triage" / "RNASEQ001")

    assert manifest["status"] == "ready_to_run"
    assert manifest["analysis_level"] == "smoke_backend"
    assert manifest["delivery_allowed"] is False
    assert manifest["validation_evidence_allowed"] is False
    assert manifest["non_delivery_reason"] == "triage_only_not_analysis_run"
    assert Path(manifest["triage_report_md"]).exists()
    assert Path(manifest["suggested_project_yaml"]).exists()
    assert not (Path(manifest["output_dir"]) / "run_manifest.json").exists()
    assert not (Path(manifest["output_dir"]) / "production_approval.json").exists()


def test_triage_scrna_missing_samplesheet_needs_metadata(tmp_path: Path) -> None:
    request = _write_request(tmp_path / "request.yaml", {"request_id": "SCRNA001", "modules": ["scrna"], "presets": ["basic"]})

    manifest = run_triage(request, tmp_path / "triage" / "SCRNA001")

    assert manifest["status"] == "needs_metadata"
    missing = Path(manifest["missing_requirements"]).read_text(encoding="utf-8")
    assert "samplesheet" in missing
    assert "needs_metadata" in missing


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
