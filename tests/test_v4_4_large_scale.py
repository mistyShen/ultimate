from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

from ultimate.batch_status import BATCH_STATUS_COLUMNS


ROOT = Path(__file__).resolve().parents[1]


def test_large_scale_standard_rehearsal_config_parses() -> None:
    config = yaml.safe_load((ROOT / "config" / "large_scale_standard_rehearsal.yaml").read_text(encoding="utf-8"))

    assert config["project"]["delivery_scope"] == "internal_rehearsal"
    assert config["delivery_policy"]["production_approval_required"] is True
    assert config["delivery_policy"]["customer_package_required"] is True
    assert {job["job_class"] for job in config["rehearsal_jobs"]} >= {
        "rnaseq_50_sample_matrix",
        "scrna_multisample_10x",
        "proteomics_50_sample_abundance",
    }


def test_large_scale_samplesheet_template_has_required_columns() -> None:
    header = (ROOT / "templates" / "large_scale_samplesheet.tsv").read_text(encoding="utf-8").splitlines()[0].split("\t")

    for column in ("sample_id", "condition", "batch", "input_path", "module", "preset", "input_type"):
        assert column in header


def test_batch_status_exports_v4_4_fields() -> None:
    for column in (
        "job_id",
        "module",
        "preset",
        "input_type",
        "sample_count",
        "cell_count",
        "feature_count",
        "run_status",
        "slurm_job_id",
        "customer_package_status",
        "delivery_check_status",
        "storage_gb",
        "failure_stage",
        "failure_recovery_file",
        "next_action",
    ):
        assert column in BATCH_STATUS_COLUMNS


def test_large_scale_scope_excludes_complex_mechanism_claims() -> None:
    text = (ROOT / "docs" / "LARGE_SCALE_STANDARD_SCOPE.md").read_text(encoding="utf-8")

    for token in (
        "CellChat/NicheNet",
        "inferCNV/CopyKAT",
        "RNA velocity",
        "Complex spatial communication",
        "Clinical survival or risk model",
        "Full FASTQ/BCL upstream production",
        "manual_review_required",
    ):
        assert token in text


def test_v4_4_slurm_script_declares_required_outputs_and_passes_syntax() -> None:
    script = ROOT / "slurm" / "v4_4_large_scale_standard_rehearsal.sbatch"
    text = script.read_text(encoding="utf-8")

    assert "set -euo pipefail" in text
    assert "v4_4_rnaseq_50sample_standard_rehearsal" in text
    assert "v4_4_scrna_multisample_standard_rehearsal" in text
    assert "v4_4_proteomics_50sample_standard_rehearsal" in text
    assert "storage_v4_4_large_scale_latest" in text
    assert "batch_status_v4_4_large_scale" in text
    assert "v4_4_large_scale_standard_report.md" in text
    assert "customer-package --run-dir" in text
    assert "delivery-check --run-dir" in text
    assert "cleanup_plan.tsv" in text
    subprocess.run(["bash", "-n", str(script)], check=True)
