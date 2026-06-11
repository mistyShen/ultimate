from pathlib import Path


def _script_text() -> str:
    script = Path(__file__).resolve().parents[1] / "slurm" / "v4_beta_customer_trial.sbatch"
    return script.read_text(encoding="utf-8")


def test_v4_beta_customer_trial_script_presence_and_scope() -> None:
    text = _script_text()

    assert "set -euo pipefail" in text
    assert "/shared/shen/2026/ultimate" in text
    assert "/share/home" not in text
    assert 'job_id="v4_beta_${module}_${preset}_customer_delivery_rehearsal_${STAMP}"' in text
    assert "v4_beta_scrna_standard_customer_delivery_rehearsal" in text
    assert "write_tabular_job rnaseq standard" in text
    assert "write_tabular_job proteomics standard" in text
    assert "write_spatial_job" in text
    assert "delivery_scope: customer_delivery" in text
    assert "delivery_mode: customer_delivery_rehearsal" in text


def test_v4_beta_customer_trial_requires_rich_customer_package_and_delivery_check() -> None:
    text = _script_text()

    assert "readme_for_customer.md" in text
    assert "sanitization.tsv" in text
    assert 'customer_dir / "figures"' in text
    assert 'customer_dir / "tables"' in text
    assert "delivery-check --run-dir" in text
    assert "v4_beta_customer_trial_report.md" in text
    assert "validation-index_v4_beta" not in text
    assert "validation_index_v4_beta" in text
    assert "audit-production" in text
    assert "audit-backends" in text
    assert "storage_v4_beta_latest" in text


def test_v4_beta_customer_trial_runs_two_raw_upstream_evidence_paths() -> None:
    text = _script_text()

    assert "raw-upstream-evidence --module" in text
    assert 'run_raw_upstream_evidence "$job_dir" "rnaseq"' in text
    assert 'run_raw_upstream_evidence "$job_dir" "scrna"' in text
    assert "Raw upstream ready evidence rows" in text
    assert "Raw upstream blocked/handoff rows" in text
    assert "raw_upstream_not_run_controlled_matrix_input_only" in text
