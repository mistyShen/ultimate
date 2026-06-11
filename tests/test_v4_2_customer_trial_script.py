from pathlib import Path


def _script_text() -> str:
    script = Path(__file__).resolve().parents[1] / "slurm" / "v4_2_raw_to_customer_trial.sbatch"
    return script.read_text(encoding="utf-8")


def test_v4_2_customer_trial_script_scope_and_entries() -> None:
    text = _script_text()

    assert "set -euo pipefail" in text
    assert "/shared/shen/2026/ultimate" in text
    assert "/share/home" not in text
    assert "v4_2_rnaseq_raw_customer_trial" in text
    assert "v4_2_scrna_mtx_customer_trial" in text
    assert "delivery_scope: customer_delivery" in text
    assert "delivery_mode: customer_delivery_rehearsal" in text
    assert "v4_2_customer_trial_report.md" in text
    assert "raw-upstream-validated" in text
    assert "license-required" in text
    assert "handoff-required" in text


def test_v4_2_customer_trial_uses_formal_customer_package_and_batch_status() -> None:
    text = _script_text()

    assert "customer-package --run-dir" in text
    assert "delivery-check --run-dir" in text
    assert "batch-status" in text
    assert '--job-glob "v4_2_*_${STAMP}"' in text
    assert "tool-completeness" in text
    assert "order-readiness" in text
    assert "storage_v4_2_latest" in text


def test_v4_2_customer_trial_runs_explicit_tiny_rnaseq_raw_stage() -> None:
    text = _script_text()

    assert "--stage rnaseq_fastq_tiny_counts" in text
    assert "--tiny-reference" in text
    assert "--quant-tool salmon" in text
    assert "raw_upstream_manifest.json" in text
    assert "blocked" in text
