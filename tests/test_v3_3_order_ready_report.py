from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "01_tools" / "write_v3_3_order_ready_report.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("write_v3_3_order_ready_report", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_tsv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def _write_rehearsal_job(root: Path, job_id: str, module: str) -> Path:
    job_dir = root / "jobs" / job_id
    (job_dir / "deliverables").mkdir(parents=True)
    (job_dir / "job_manifest.json").write_text(json.dumps({"job_id": job_id}), encoding="utf-8")
    run_dir = job_dir / "runs" / job_id
    run_dir.mkdir(parents=True)
    manifest = {
        "analysis_level": "production_backend",
        "delivery_allowed": True,
        "modules": [{"module": module, "analysis_level": "production_backend", "delivery_allowed": True}],
        "production_approval": {
            "approved": True,
            "project_id": job_id,
            "delivery_scope": "internal_rehearsal",
        },
        "delivery_gate": {
            "status": "ready",
            "delivery_allowed": True,
            "delivery_scope": "internal_rehearsal",
        },
    }
    path = run_dir / "run_manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    (job_dir / "deliverables" / "latest_delivery_check.json").write_text(
        json.dumps({"status": "ready", "delivery_allowed": True, "blockers": []}),
        encoding="utf-8",
    )
    return path


def test_write_v3_3_order_ready_report_buckets_presets(tmp_path: Path) -> None:
    module = _load_module()
    root = tmp_path / "ultimate"
    root.mkdir()
    audit_dir = root / "audits" / "production_latest"
    backend_path = audit_dir / "backend_maturity_table.tsv"
    order_path = audit_dir / "order_readiness_checklist.tsv"
    capability_path = audit_dir / "production_capability_matrix.tsv"
    audit_path = audit_dir / "production_audit.json"

    _write_tsv(
        backend_path,
        [
            {
                "module": "rnaseq",
                "backend_id": "rnaseq.matrix.python_mvp",
                "preset": "standard",
                "tool": "pandas",
                "backend_status": "fully_automatic_validated_entrypoint",
                "production_allowed": "true",
                "requires_license": "false",
                "skip_reason": "",
                "next_required_evidence": "",
            },
            {
                "module": "scrna",
                "backend_id": "scrna.cellchat.handoff",
                "preset": "communication",
                "tool": "CellChat",
                "backend_status": "handoff_ready",
                "production_allowed": "false",
                "requires_license": "false",
                "skip_reason": "handoff_only",
                "next_required_evidence": "manual handoff",
            },
            {
                "module": "spatial",
                "backend_id": "spatial.spaceranger",
                "preset": "standard",
                "tool": "Space Ranger",
                "backend_status": "licensed_path_detection",
                "production_allowed": "false",
                "requires_license": "true",
                "skip_reason": "license_required",
                "next_required_evidence": "license path",
            },
            {
                "module": "multiome",
                "backend_id": "multiome.h5mu.mvp",
                "preset": "standard",
                "tool": "muon",
                "backend_status": "fully_automatic_validated_entrypoint",
                "production_allowed": "true",
                "requires_license": "false",
                "skip_reason": "",
                "next_required_evidence": "",
            },
        ],
    )
    _write_tsv(
        order_path,
        [
            {"module": "rnaseq", "ready_for_basic_order": "yes", "remaining_gap": ""},
            {"module": "scrna", "ready_for_basic_order": "partial", "remaining_gap": "handoff required"},
            {"module": "spatial", "ready_for_basic_order": "partial", "remaining_gap": "license required"},
            {"module": "multiome", "ready_for_basic_order": "partial", "remaining_gap": "rehearsal missing"},
        ],
    )
    _write_tsv(
        capability_path,
        [
            {"module": "rnaseq", "production_status": "ready_basic", "validation": "available", "next_action": ""},
            {"module": "scrna", "production_status": "partial:needs_handoff", "validation": "available", "next_action": ""},
            {"module": "spatial", "production_status": "partial:needs_license", "validation": "available", "next_action": ""},
            {"module": "multiome", "production_status": "partial:needs_modality_validation", "validation": "available", "next_action": ""},
        ],
    )
    audit_path.write_text(
        json.dumps(
            {
                "summary": {"ready_basic": 1, "partial": 3},
                "backend_maturity_table": str(backend_path),
                "order_readiness_checklist": str(order_path),
                "capability_matrix": str(capability_path),
            }
        ),
        encoding="utf-8",
    )
    _write_tsv(
        root / "reports" / "validation_index" / "validation_index.tsv",
        [
            {
                "run_name": "rnaseq_public",
                "run_kind": "validation",
                "module": "rnaseq",
                "module_names": "",
                "guard_status": "ready",
                "evidence_status": "ready_real_evidence",
                "order_readiness_status": "ready_for_validation_evidence",
                "production_approval_status": "",
                "delivery_gate_status": "",
                "delivery_gate_allowed": "",
                "delivery_scope": "not_applicable",
                "manifest_path": "",
            },
            {
                "run_name": "multiome_public",
                "run_kind": "validation",
                "module": "multiome",
                "module_names": "",
                "guard_status": "ready",
                "evidence_status": "ready_real_evidence",
                "order_readiness_status": "ready_for_validation_evidence",
                "production_approval_status": "",
                "delivery_gate_status": "",
                "delivery_gate_allowed": "",
                "delivery_scope": "not_applicable",
                "manifest_path": "",
            },
        ],
    )
    _write_rehearsal_job(root, "rnaseq_rehearsal", "rnaseq")

    report_path = module.write_v3_3_order_ready_report(root=root)
    text = report_path.read_text(encoding="utf-8")

    assert report_path == root / "reports" / "v3_3_order_ready_report.md"
    assert "Ultimate V3.3 Order-Ready Report" in text
    assert "## Order-ready presets" in text
    assert "`rnaseq` / `standard`: order_ready" in text
    assert "## Presets needing handoff" in text
    assert "`scrna` / `communication`: needs_handoff" in text
    assert "## Presets needing license" in text
    assert "`spatial` / `standard`: needs_license" in text
    assert "## Presets needing manual review" in text
    assert "`multiome` / `standard`:" in text
    assert "delivery_rehearsal_evidence_missing" in text
    assert '"order_ready": 1' in text


def test_write_v3_3_order_ready_report_cli_handles_missing_inputs(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    root.mkdir()

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (root / "reports" / "v3_3_order_ready_report.md").exists()
    assert "v3_3_order_ready_report" in result.stdout


def test_write_v3_3_order_ready_report_falls_back_to_standard_presets(tmp_path: Path) -> None:
    module = _load_module()
    root = tmp_path / "ultimate"
    root.mkdir()
    audit_dir = root / "audits" / "local_production_check"
    order_path = audit_dir / "order_readiness_checklist.tsv"
    capability_path = audit_dir / "production_capability_matrix.tsv"
    audit_path = audit_dir / "production_audit.json"

    _write_tsv(order_path, [{"module": "rnaseq", "ready_for_basic_order": "yes", "remaining_gap": ""}])
    _write_tsv(capability_path, [{"module": "rnaseq", "production_status": "ready_basic", "validation": "missing"}])
    audit_path.write_text(
        json.dumps({"order_readiness_checklist": str(order_path), "capability_matrix": str(capability_path)}),
        encoding="utf-8",
    )

    report_path = module.write_v3_3_order_ready_report(root=root)
    text = report_path.read_text(encoding="utf-8")

    assert "backend_source: `audit_standard_fallback`" in text
    assert "`rnaseq` / `standard`:" in text
    assert "missing_backend_maturity_table" in text
    assert "validation_index_evidence_missing" in text


def test_write_v3_3_order_ready_report_requires_delivery_check(tmp_path: Path) -> None:
    module = _load_module()
    root = tmp_path / "ultimate"
    root.mkdir()
    audit_dir = root / "audits" / "production_latest"
    backend_path = audit_dir / "backend_maturity_table.tsv"
    order_path = audit_dir / "order_readiness_checklist.tsv"
    capability_path = audit_dir / "production_capability_matrix.tsv"
    audit_path = audit_dir / "production_audit.json"

    _write_tsv(
        backend_path,
        [
            {
                "module": "rnaseq",
                "backend_id": "rnaseq.matrix.python_mvp",
                "preset": "standard",
                "tool": "pandas",
                "backend_status": "fully_automatic_validated_entrypoint",
                "production_allowed": "true",
                "requires_license": "false",
                "skip_reason": "",
                "next_required_evidence": "",
            }
        ],
    )
    _write_tsv(order_path, [{"module": "rnaseq", "ready_for_basic_order": "yes", "remaining_gap": ""}])
    _write_tsv(
        capability_path,
        [{"module": "rnaseq", "production_status": "ready_basic", "validation": "available", "next_action": ""}],
    )
    audit_path.write_text(
        json.dumps(
            {
                "backend_maturity_table": str(backend_path),
                "order_readiness_checklist": str(order_path),
                "capability_matrix": str(capability_path),
            }
        ),
        encoding="utf-8",
    )
    _write_tsv(
        root / "reports" / "validation_index" / "validation_index.tsv",
        [
            {
                "run_name": "rnaseq_public",
                "run_kind": "validation",
                "module": "rnaseq",
                "module_names": "",
                "guard_status": "ready",
                "evidence_status": "ready_real_evidence",
                "order_readiness_status": "ready_for_validation_evidence",
                "production_approval_status": "",
                "delivery_gate_status": "",
                "delivery_gate_allowed": "",
                "delivery_scope": "not_applicable",
                "manifest_path": "",
            },
        ],
    )
    manifest_path = _write_rehearsal_job(root, "rnaseq_rehearsal", "rnaseq")
    (manifest_path.parents[2] / "deliverables" / "latest_delivery_check.json").unlink()

    report_path = module.write_v3_3_order_ready_report(root=root)
    text = report_path.read_text(encoding="utf-8")

    assert "`rnaseq` / `standard`:" in text
    assert "delivery_rehearsal_evidence_missing" in text
    assert "delivery_check_status=missing" in text
