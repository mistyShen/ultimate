from pathlib import Path


def _script_text() -> str:
    script = Path(__file__).resolve().parents[1] / "slurm" / "v4_alpha_customer_delivery_rehearsal.sbatch"
    return script.read_text(encoding="utf-8")


def test_v4_alpha_customer_delivery_rehearsal_script_presence_and_scope() -> None:
    text = _script_text()

    assert "set -euo pipefail" in text
    assert "/shared/shen/2026/ultimate" in text
    assert "/share/home" not in text
    assert 'job_id="v4_alpha_${module}_${preset}_customer_delivery_rehearsal_${STAMP}"' in text
    assert "v4_alpha_scrna_standard_customer_delivery_rehearsal" in text
    assert "v4_alpha_spatial_standard_customer_delivery_rehearsal" in text
    assert "write_tabular_job rnaseq standard" in text
    assert "write_scrna_job" in text
    assert "write_tabular_job proteomics standard" in text
    assert "write_spatial_job" in text
    assert "delivery_scope: customer_delivery" in text
    assert '"delivery_scope": "customer_delivery"' in text
    assert "delivery_mode: customer_delivery_rehearsal" in text
    assert '"delivery_mode": "customer_delivery_rehearsal"' in text
    assert "internal_rehearsal" not in text


def test_v4_alpha_customer_delivery_rehearsal_runs_delivery_check_and_report() -> None:
    text = _script_text()

    assert "production_approval.json" in text
    assert "delivery-check --run-dir" in text
    assert "/shared/shen/2026/ultimate/reports/v4_alpha_customer_delivery_report.md" in text
    assert "validation-index" in text
    assert "audit-production" in text
    assert "audit-backends" in text


def test_v4_alpha_rehearsal_records_controlled_inputs_and_raw_blockers() -> None:
    text = _script_text()

    assert "controlled small data" in text
    assert "no real customer raw data" in text
    assert "raw_upstream_evidence.tsv" in text
    assert "execution_status" in text
    assert "not_executed" in text
    assert "blocked_reason" in text
    assert "input_matrix: $job_dir/samples/${module}_matrix.tsv" in text
    assert "tenx_mtx: $job_dir/samples/scrna_controlled_10x/controlled_10x_mtx" in text
    assert "expression_matrix: $job_dir/samples/spatial_expression.tsv" in text
    assert "coordinates: $job_dir/samples/spatial_coordinates.tsv" in text
