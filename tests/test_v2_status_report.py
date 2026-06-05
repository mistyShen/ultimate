from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "01_tools" / "write_v2_status_report.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("write_v2_status_report", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_tsv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = list(rows[0].keys())
    text = "\t".join(headers) + "\n"
    for row in rows:
        text += "\t".join(str(row.get(header, "")) for header in headers) + "\n"
    path.write_text(text, encoding="utf-8")


def _write_rehearsal_job(root: Path, job_id: str, *, delivery_scope: str = "internal_rehearsal") -> Path:
    run_dir = root / "jobs" / job_id / "runs" / job_id
    run_dir.mkdir(parents=True)
    manifest = {
        "analysis_level": "production_backend",
        "delivery_allowed": True,
        "modules": [{"module": "rnaseq", "analysis_level": "production_backend", "delivery_allowed": True}],
        "production_approval": {
            "approved": True,
            "project_id": job_id,
            "delivery_scope": delivery_scope,
        },
        "delivery_gate": {
            "status": "ready",
            "delivery_allowed": True,
            "delivery_scope": delivery_scope,
        },
    }
    path = run_dir / "run_manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_write_v2_status_report_builds_required_sections(tmp_path: Path) -> None:
    module = _load_module()
    root = tmp_path / "ultimate"
    root.mkdir()
    _write_tsv(
        root / "reports" / "validation_index" / "validation_index.tsv",
        [
            {
                "run_name": "scrna_public",
                "module": "scrna",
                "analysis_level": "validated_backend",
                "evidence_status": "ready_real_evidence",
                "order_readiness_status": "ready_for_validation_evidence",
                "delivery_scope": "not_applicable",
                "missing_or_gap": "",
                "next_action": "",
                "guard_status": "ready",
            }
        ],
    )
    _write_tsv(root / "reports" / "validation_index" / "validation_summary.tsv", [{"metric": "n_runs", "value": 1}])
    (root / "audits" / "production_latest").mkdir(parents=True)
    (root / "audits" / "production_latest" / "production_audit.json").write_text(
        json.dumps({"final_acceptance_summary": {"pass": 6}, "validation_gap_summary": {"partial": 1}}),
        encoding="utf-8",
    )
    _write_tsv(
        root / "audits" / "production_latest" / "module_maturity_table.tsv",
        [
            {
                "module_name": "scrna",
                "maturity_level": "3_public_validated",
                "analysis_level": "validated_backend",
                "public_validation_status": "available",
                "known_limitations": "",
                "next_required_backend": "",
            },
            {
                "module_name": "spatial",
                "maturity_level": "1_smoke_skeleton",
                "analysis_level": "smoke_backend",
                "public_validation_status": "partial:data_required",
                "known_limitations": "Visium validation pending.",
                "next_required_backend": "Add public Visium validation.",
            },
        ],
    )
    (root / "audits" / "storage_latest").mkdir(parents=True)
    (root / "audits" / "storage_latest" / "storage_audit_summary.json").write_text(
        json.dumps({"total_gb": 123.4, "budget_gb": 500}),
        encoding="utf-8",
    )
    job_a = _write_rehearsal_job(root, "rehearsal_a")
    _write_rehearsal_job(root, "rehearsal_b")

    report_path = module.write_v2_status_report(
        root=root,
        output_dir=tmp_path / "out",
        storage_summary=None,
        pytest_status="pass",
        pytest_note="targeted pytest passed",
        rehearsal_jobs=[str(job_a), "rehearsal_b"],
    )

    text = report_path.read_text(encoding="utf-8")
    assert report_path.exists()
    for section in (
        "## 1. Pytest status",
        "## 2. Modules at validated_backend",
        "## 3. Partial or blocked modules and reasons",
        "## 4. Two production-style rehearsal jobs ready",
        "## 5. delivery_scope correctness",
        "## 6. Storage under 500G",
        "## 7. Next minimal fixes",
    ):
        assert section in text
    assert "module=scrna" in text
    assert "module=spatial" in text
    assert "delivery_scope_correct: `true`" in text
    assert "ready_for_two_rehearsals: `true`" in text
    assert "storage_status: `under_budget`" in text


def test_write_v2_status_report_handles_missing_inputs_and_bad_rehearsal_scope(tmp_path: Path) -> None:
    module = _load_module()
    root = tmp_path / "ultimate"
    root.mkdir()
    _write_rehearsal_job(root, "customer_scoped", delivery_scope="customer_delivery")

    report_path = module.write_v2_status_report(
        root=root,
        output_dir=tmp_path / "out",
        storage_summary=None,
        pytest_status="partial",
        pytest_note="fixtures only",
        rehearsal_jobs=["customer_scoped", "missing_job"],
    )

    text = report_path.read_text(encoding="utf-8")
    assert "validation_index: missing" in text
    assert "module_maturity: missing" in text
    assert "storage_status: `missing`" in text
    assert "ready_for_two_rehearsals: `false`" in text
    assert "delivery_scope_correct: `false`" in text
    assert "customer_scoped:customer_delivery" in text
    assert "requested=missing_job" in text


def test_write_v2_status_report_cli(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    root.mkdir()
    storage = tmp_path / "storage.json"
    storage.write_text(json.dumps({"total_gb": 42}), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--root",
            str(root),
            "--output-dir",
            str(tmp_path / "out"),
            "--storage-summary",
            str(storage),
            "--pytest-status",
            "not_run",
            "--pytest-note",
            "cli fixture",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "out" / "v2_status_report.md").exists()
    assert "v2_status_report" in result.stdout
