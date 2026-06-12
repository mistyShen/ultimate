from pathlib import Path


def _script_text() -> str:
    script = Path(__file__).resolve().parents[1] / "slurm" / "v4_pilot_realistic_suite.sbatch"
    return script.read_text(encoding="utf-8")


def test_v4_pilot_suite_runs_deep_and_breadth_layers() -> None:
    text = _script_text()

    assert "set -euo pipefail" in text
    assert "v4_2_raw_to_customer_trial.sbatch" in text
    assert "v3_8_multiomics_publication_rehearsal.sbatch" in text
    assert "v4_1_order_readiness_rehearsal.sbatch" in text
    assert "ULTIMATE_SKIP_STORAGE_AUDIT=1" in text
    assert "v4_pilot_realistic_report.md" in text


def test_v4_pilot_suite_refreshes_audits_and_scoped_batch_status() -> None:
    text = _script_text()

    assert "validation-index" in text
    assert "audit-production" in text
    assert "audit-backends" in text
    assert "tool-completeness" in text
    assert "order-readiness" in text
    assert "storage_v4_pilot_latest" in text
    assert "batch-status" in text
    assert '--job-glob "v*_*$STAMP"' in text


def test_v4_pilot_report_names_required_status_buckets() -> None:
    text = _script_text()

    for token in (
        "ready:",
        "blocked:",
        "handoff-required:",
        "license-required:",
        "raw-upstream-validated:",
        "customer-package-ready:",
        "delivery-check-ready:",
        "under_500G=",
    ):
        assert token in text
