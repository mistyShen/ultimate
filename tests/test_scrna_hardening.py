from __future__ import annotations

import json
import tomllib
from pathlib import Path

from click.testing import CliRunner

from ultimate import scrna_smoke
from ultimate.cli import main


def test_validate_scrna_requires_approval_for_production_backend(tmp_path: Path) -> None:
    input_path = tmp_path / "input.h5ad"
    input_path.write_text("placeholder", encoding="utf-8")
    result = CliRunner().invoke(
        main,
        [
            "validate-scrna",
            "--input-path",
            str(input_path),
            "--input-type",
            "h5ad",
            "--output-dir",
            str(tmp_path / "out"),
            "--analysis-level",
            "production_backend",
        ],
    )
    assert result.exit_code != 0
    assert "production_backend requires --production-approval" in result.output


def test_validate_scrna_rejects_invalid_production_approval(tmp_path: Path) -> None:
    input_path = tmp_path / "input.h5ad"
    output_dir = tmp_path / "out"
    input_path.write_text("placeholder", encoding="utf-8")
    approval_path = tmp_path / "approval.json"
    approval_path.write_text(json.dumps({"approved": False}), encoding="utf-8")
    result = CliRunner().invoke(
        main,
        [
            "validate-scrna",
            "--input-path",
            str(input_path),
            "--input-type",
            "h5ad",
            "--output-dir",
            str(output_dir),
            "--analysis-level",
            "production_backend",
            "--production-approval",
            str(approval_path),
        ],
    )
    assert result.exit_code != 0
    assert "missing required fields" in result.output


def test_validate_scrna_rejects_unapproved_production_approval(tmp_path: Path) -> None:
    input_path = tmp_path / "input.h5ad"
    output_dir = tmp_path / "out"
    input_path.write_text("placeholder", encoding="utf-8")
    approval_path = tmp_path / "approval.json"
    _write_approval(approval_path, input_path=input_path, output_dir=output_dir, approved=False)
    result = CliRunner().invoke(
        main,
        [
            "validate-scrna",
            "--input-path",
            str(input_path),
            "--input-type",
            "h5ad",
            "--output-dir",
            str(output_dir),
            "--analysis-level",
            "production_backend",
            "--production-approval",
            str(approval_path),
        ],
    )
    assert result.exit_code != 0
    assert "approved=true" in result.output


def test_validate_scrna_rejects_production_approval_path_mismatch(tmp_path: Path) -> None:
    input_path = tmp_path / "input.h5ad"
    output_dir = tmp_path / "out"
    input_path.write_text("placeholder", encoding="utf-8")
    approval_path = tmp_path / "approval.json"
    _write_approval(approval_path, input_path=tmp_path / "other.h5ad", output_dir=output_dir)
    result = CliRunner().invoke(
        main,
        [
            "validate-scrna",
            "--input-path",
            str(input_path),
            "--input-type",
            "h5ad",
            "--output-dir",
            str(output_dir),
            "--analysis-level",
            "production_backend",
            "--production-approval",
            str(approval_path),
        ],
    )
    assert result.exit_code != 0
    assert "input_path mismatch" in result.output


def test_validate_scrna_accepts_valid_production_approval(tmp_path: Path, monkeypatch) -> None:
    input_path = tmp_path / "input.h5ad"
    output_dir = tmp_path / "out"
    input_path.write_text("placeholder", encoding="utf-8")
    approval_path = tmp_path / "approval.json"
    _write_approval(approval_path, input_path=input_path, output_dir=output_dir)

    def fake_run_scrna_validation(**kwargs):
        approval = kwargs["production_approval"]
        return {
            "status": "ready",
            "analysis_level": kwargs["analysis_level"],
            "input_path": str(kwargs["input_path"]),
            "output_dir": str(kwargs["output_dir"]),
            "production_approval": {
                "approved": approval["approved"],
                "approved_by": approval["approved_by"],
                "approval_path": approval["_approval_path"],
            },
        }

    monkeypatch.setattr(scrna_smoke, "run_scrna_validation", fake_run_scrna_validation)
    result = CliRunner().invoke(
        main,
        [
            "validate-scrna",
            "--input-path",
            str(input_path),
            "--input-type",
            "h5ad",
            "--output-dir",
            str(output_dir),
            "--analysis-level",
            "production_backend",
            "--production-approval",
            str(approval_path),
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["analysis_level"] == "production_backend"
    assert payload["production_approval"]["approved"] is True
    assert payload["production_approval"]["approval_path"] == str(approval_path.resolve())


def test_validate_scrna_passes_optional_nichenet_resource(tmp_path: Path, monkeypatch) -> None:
    input_path = tmp_path / "input.h5ad"
    output_dir = tmp_path / "out"
    resource_path = tmp_path / "ligand_target.tsv"
    input_path.write_text("placeholder", encoding="utf-8")
    resource_path.write_text("ligand\ttarget\tweight\nTGFB1\tCOL1A1\t1.0\n", encoding="utf-8")

    def fake_run_scrna_validation(**kwargs):
        return {
            "status": "ready",
            "analysis_level": kwargs["analysis_level"],
            "nichenet_resource": str(kwargs["nichenet_resource"]) if kwargs["nichenet_resource"] else "",
        }

    monkeypatch.setattr(scrna_smoke, "run_scrna_validation", fake_run_scrna_validation)
    result = CliRunner().invoke(
        main,
        [
            "validate-scrna",
            "--input-path",
            str(input_path),
            "--input-type",
            "h5ad",
            "--output-dir",
            str(output_dir),
            "--nichenet-resource",
            str(resource_path),
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["nichenet_resource"] == str(resource_path)


def test_scrna_mvp_skip_manifest_is_not_validated_backend() -> None:
    root = _ultimate_root()
    script = (root / "slurm/scrna_mvp_validation.sbatch").read_text(encoding="utf-8")
    skip_block = script.split("write_skip_manifest()", 1)[1].split("select_scrna_python()", 1)[0]
    assert '"analysis_level": "smoke_backend"' in skip_block
    assert "validation_not_completed:" in skip_block
    assert "analysis_level：`smoke_backend`" in skip_block
    assert '"analysis_level": "validated_backend"' not in skip_block


def test_scrna_extra_and_handoff_templates_are_packaged() -> None:
    root = _ultimate_root()
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    scrna = set(pyproject["project"]["optional-dependencies"]["scrna"])
    assert {"scanpy>=1.10", "anndata>=0.10", "pytest>=8.0"}.issubset(scrna)
    package_data = pyproject["tool"]["setuptools"]["package-data"]["ultimate"]
    assert "templates/handoffs/nfcore_scrnaseq/*" in package_data
    handoff_dir = root / "templates/handoffs/nfcore_scrnaseq"
    for filename in ("README.md", "samplesheet.csv", "params.yaml", "nextflow.config"):
        assert (handoff_dir / filename).exists()
    handoff_readme = (handoff_dir / "README.md").read_text(encoding="utf-8")
    assert "validate-scrna --analysis-level production_backend" not in handoff_readme
    assert "production approval JSON" in handoff_readme


def test_readme_documents_scrna_mvp_validation() -> None:
    readme = (_ultimate_root() / "README.md").read_text(encoding="utf-8")
    assert "## scRNA MVP Validation" in readme
    assert "scrna_mvp_validation.sbatch" in readme
    assert "validation_runs/scrna_mvp_validation/{10x_mtx,h5ad}" in readme
    assert "objects/scrna_mvp.h5ad" in readme
    assert "validated_backend" in readme


def test_readme_uses_prepared_job_slurm_entrypoint() -> None:
    readme = (_ultimate_root() / "README.md").read_text(encoding="utf-8")
    assert "ultimate prepare-job --config" in readme
    assert "jobs/demo_all_001/config/run_ultimate.sbatch" in readme
    assert "Do not rely on passing extra\nconfig arguments through the wrapper" in readme
    assert "hpc-sbatch /shared/shen/2026/ultimate/slurm/ultimate_run.sbatch projects/demo_all/config/project.yaml" not in readme


def _write_approval(path: Path, *, input_path: Path, output_dir: Path, approved: bool = True) -> None:
    path.write_text(
        json.dumps(
            {
                "approved": approved,
                "approved_by": "nshen",
                "approved_at": "2026-06-03T12:00:00+08:00",
                "project_id": "test_project",
                "input_path": str(input_path.resolve()),
                "output_dir": str(output_dir.resolve()),
                "delivery_scope": "internal_rehearsal",
                "reason": "pytest production approval gate",
            }
        ),
        encoding="utf-8",
    )


def _ultimate_root() -> Path:
    return Path(__file__).resolve().parents[1]
