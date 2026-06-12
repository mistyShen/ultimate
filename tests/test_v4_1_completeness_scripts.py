from pathlib import Path


def _script(name: str) -> str:
    path = Path(__file__).resolve().parents[1] / "slurm" / name
    return path.read_text(encoding="utf-8")


def test_v4_1_tool_completeness_audit_script_refreshes_all_indices() -> None:
    text = _script("v4_1_tool_completeness_audit.sbatch")

    assert "set -euo pipefail" in text
    assert "/shared/shen/2026/ultimate" in text
    assert "audit-tools" in text
    assert "validation-index" in text
    assert "audit-production" in text
    assert "audit-backends" in text
    assert "tool-completeness" in text
    assert "order-readiness" in text
    assert "storage_audit.py" in text
    assert "--budget-gb 500" in text
    assert "v4_1_tool_completeness_report.md" in text


def test_v4_1_order_readiness_rehearsal_covers_next_six_modules() -> None:
    text = _script("v4_1_order_readiness_rehearsal.sbatch")

    assert "set -euo pipefail" in text
    assert "delivery_scope: internal_rehearsal" in text
    assert "write_vdj_job" in text
    assert "write_cite_job" in text
    assert "write_matrix_job methylation" in text
    assert "write_peak_job scatac" in text
    assert "write_peak_job multiome" in text
    assert "write_matrix_job functional_state" in text
    assert "delivery-check --run-dir" in text
    assert "v4_1_order_readiness_report.md" in text
    assert "storage_audit.py" in text
    assert "--budget-gb 500" in text
    assert "ULTIMATE_SKIP_STORAGE_AUDIT" in text
    assert "delivery_scope: customer_delivery" not in text


def test_v4_beta_customer_trial_writes_customer_package_manifest() -> None:
    text = _script("v4_beta_customer_trial.sbatch")

    assert "customer_package_manifest.tsv" in text
    assert "customer_visible" in text
    assert "sanitized" in text
