from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from ultimate.cli import main
from ultimate.delivery_check import run_delivery_check


def test_delivery_check_accepts_production_job_with_required_artifacts(tmp_path: Path) -> None:
    job_dir, run_dir = _write_delivery_ready_job(tmp_path)

    manifest = run_delivery_check(job_dir)

    assert manifest["status"] == "ready"
    assert manifest["delivery_allowed"] is True
    assert (run_dir / "reports" / "delivery_check.json").exists()
    assert (job_dir / "deliverables" / "latest_delivery_check.json").exists()


def test_delivery_check_blocks_validated_only_run(tmp_path: Path) -> None:
    _, run_dir = _write_delivery_ready_job(tmp_path)
    payload = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    payload["analysis_level"] = "validated_backend"
    payload["delivery_allowed"] = False
    payload["delivery_gate"]["delivery_allowed"] = False
    (run_dir / "run_manifest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    manifest = run_delivery_check(run_dir)

    assert manifest["status"] == "blocked"
    assert "analysis_level_production" in manifest["blockers"]
    assert "delivery_allowed_true" in manifest["blockers"]


def test_delivery_check_blocks_missing_slurm_and_repro_artifacts(tmp_path: Path) -> None:
    _, run_dir = _write_delivery_ready_job(tmp_path)
    payload = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    payload["slurm_job_id"] = ""
    payload["slurm"]["slurm_job_id"] = ""
    (run_dir / "run_manifest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (run_dir / "reproducible_code" / "input_checksums.tsv").unlink()

    manifest = run_delivery_check(run_dir)

    assert manifest["status"] == "blocked"
    assert "slurm_job_id" in manifest["blockers"]
    assert "input_checksums" in manifest["blockers"]


def test_cli_delivery_check_exits_nonzero_when_blocked(tmp_path: Path) -> None:
    _, run_dir = _write_delivery_ready_job(tmp_path)
    payload = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    payload["is_demo"] = True
    (run_dir / "run_manifest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    result = CliRunner().invoke(main, ["delivery-check", "--run-dir", str(run_dir)])

    assert result.exit_code != 0
    assert "not_demo" in result.output


def _write_delivery_ready_job(tmp_path: Path) -> tuple[Path, Path]:
    job_dir = tmp_path / "jobs" / "ORDER001"
    run_dir = job_dir / "runs" / "ORDER001"
    for directory in (
        run_dir / "reports",
        run_dir / "results" / "tables",
        run_dir / "results" / "figures",
        run_dir / "objects",
        run_dir / "reproducible_code",
        job_dir / "deliverables",
        job_dir / "reproducible_code",
        job_dir / "config",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    (job_dir / "job_manifest.json").write_text('{"job_id": "ORDER001"}', encoding="utf-8")
    config_path = job_dir / "config" / "project.yaml"
    config_path.write_text("project:\n  name: ORDER001\n", encoding="utf-8")

    files = {
        run_dir / "reports" / "report.html": "<html>analysis_level delivery_allowed 警示 不能伪装</html>",
        run_dir / "reports" / "methods.md": "# methods\nanalysis_level delivery_allowed 警示\n",
        run_dir / "results" / "tables" / "markers.tsv": "gene\tscore\nA\t1\n",
        run_dir / "results" / "figures" / "umap.png": "png",
        run_dir / "objects" / "object.h5ad": "object",
        run_dir / "reproducible_code" / "rerun.sh": "#!/usr/bin/env bash\n",
        run_dir / "reproducible_code" / "software_versions.tsv": "kind\tname\tversion\npython\tultimate\ttest\n",
        run_dir / "reproducible_code" / "input_checksums.tsv": "key\tpath\texists\nconfig\tproject.yaml\ttrue\n",
        run_dir / "results" / "tables" / "advanced_backend_execution_manifest.json": json.dumps(
            {
                "status": "ready",
                "backend_count": 1,
                "rows": [
                    {
                        "module": "scrna",
                        "backend_id": "scrna.communication.cellchat_optional",
                        "backend_registry_status": "fully_automatic_validated_entrypoint",
                        "execution_status": "ready",
                    }
                ],
            }
        ),
    }
    for path, text in files.items():
        path.write_text(text, encoding="utf-8")

    delivery_rows = [
        ("figure", run_dir / "results" / "figures" / "umap.png"),
        ("table", run_dir / "results" / "tables" / "markers.tsv"),
        ("object", run_dir / "objects" / "object.h5ad"),
        ("report", run_dir / "reports" / "report.html"),
        ("reproducible_code", run_dir / "reproducible_code" / "rerun.sh"),
    ]
    delivery_index = "category\tpath\tsize_bytes\tmodule\tartifact_key\tartifact_scope\n" + "\n".join(
        f"{category}\t{path}\t{path.stat().st_size}\tscrna\t{path.stem}\trun" for category, path in delivery_rows
    )
    (run_dir / "delivery_index.tsv").write_text(delivery_index + "\n", encoding="utf-8")

    manifest = {
        "status": "ready",
        "analysis_level": "production_backend",
        "is_demo": False,
        "is_stub": False,
        "delivery_allowed": True,
        "validation_evidence_allowed": True,
        "non_delivery_reason": "",
        "delivery_scope": "internal_rehearsal",
        "slurm_job_id": "12345",
        "slurm": {"slurm_job_id": "12345", "slurm_job_name": "pytest_rehearsal"},
        "production_approval": {
            "approved": True,
            "approved_by": "pytest",
            "approved_at": "2026-06-08T00:00:00Z",
            "project_id": "ORDER001",
            "input_path": str(config_path),
            "output_dir": str(run_dir),
            "delivery_scope": "internal_rehearsal",
            "reason": "pytest delivery check",
        },
        "delivery_gate": {
            "status": "ready",
            "delivery_allowed": True,
            "approval_status": "approved",
            "delivery_scope": "internal_rehearsal",
            "blockers": [],
        },
        "modules": [
            {
                "module": "scrna",
                "status": "ready",
                "analysis_level": "production_backend",
                "delivery_allowed": True,
                "validation_evidence_allowed": True,
                "is_demo": False,
                "is_stub": False,
            }
        ],
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (job_dir / "deliverables" / "latest_run_pointer.json").write_text(
        json.dumps({"latest_run_dir": str(run_dir)}, indent=2),
        encoding="utf-8",
    )
    return job_dir, run_dir
