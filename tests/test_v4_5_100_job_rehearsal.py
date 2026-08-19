from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import subprocess

import yaml


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "large_scale_100_job_rehearsal.yaml"
DOC_PATH = ROOT / "docs" / "V4_5_100_JOB_REHEARSAL_SCOPE.md"


EXPECTED_DISTRIBUTION = {
    "rnaseq": 20,
    "scrna": 15,
    "proteomics": 15,
    "methylation": 10,
    "scatac": 10,
    "spatial": 10,
    "multiome": 8,
    "cite_seq": 5,
    "vdj": 4,
    "functional_state": 3,
}


def _config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def test_v4_5_config_declares_exact_100_runnable_jobs_and_distribution() -> None:
    config = _config()
    jobs = config["rehearsal_jobs"]

    assert config["project"]["delivery_scope"] == "internal_rehearsal"
    assert config["project"]["delivery_mode"] == "customer_delivery_rehearsal"
    assert config["project"]["controlled_rehearsal"] is True
    assert config["project"]["customer_delivery_actual"] is False
    assert config["project"]["real_customer_delivery"] is False
    assert config["batch"]["total_runnable_jobs"] == 100
    assert len(jobs) == 100
    assert all(job["runnable"] is True for job in jobs)
    assert Counter(job["module"] for job in jobs) == EXPECTED_DISTRIBUTION
    assert config["requested_distribution"] == EXPECTED_DISTRIBUTION


def test_v4_5_job_ids_are_unique_and_chunked_by_tens() -> None:
    config = _config()
    jobs = config["rehearsal_jobs"]
    chunk_size = config["batch"]["chunk_size"]

    job_ids = [job["job_id"] for job in jobs]
    assert len(job_ids) == len(set(job_ids))
    assert all(job_id.startswith("v4_5_") for job_id in job_ids)
    assert chunk_size == 10
    assert config["batch"]["chunk_count"] == 10

    chunks: dict[str, list[int]] = defaultdict(list)
    for job in jobs:
        chunks[job["chunk_id"]].append(job["chunk_local_index"])

    assert sorted(chunks) == [f"chunk_{index:02d}" for index in range(1, 11)]
    for local_indexes in chunks.values():
        assert len(local_indexes) == chunk_size
        assert sorted(local_indexes) == list(range(1, chunk_size + 1))


def test_v4_5_negative_controls_are_separate_from_100_jobs() -> None:
    config = _config()
    jobs = config["rehearsal_jobs"]
    controls = config["negative_controls"]

    job_ids = {job["job_id"] for job in jobs}
    control_ids = [control["control_id"] for control in controls]

    assert len(controls) == 10
    assert len(control_ids) == len(set(control_ids))
    assert job_ids.isdisjoint(control_ids)
    assert all(control["counts_toward_100"] is False for control in controls)
    assert config["delivery_policy"]["negative_controls_counted_as_runnable_jobs"] is False


def test_v4_5_shell_scripts_pass_syntax_if_present() -> None:
    scripts = sorted(
        path
        for folder in (ROOT / "slurm", ROOT / "scripts")
        if folder.exists()
        for path in folder.glob("*v4_5*")
        if path.is_file() and path.suffix in {".sbatch", ".sh"}
    )

    for script in scripts:
        text = script.read_text(encoding="utf-8")
        assert "set -euo pipefail" in text
        subprocess.run(["bash", "-n", str(script)], check=True)

    finalize = (ROOT / "slurm" / "v4_5_100_job_finalize.sbatch").read_text(encoding="utf-8")
    assert "Unable to infer V4.5 stamp" in finalize
    assert "ULTIMATE_V45_100_JOB_STAMP:?" not in finalize
    assert "reports/batch_status_v4_5_100_job" in finalize
    assert "audits/storage_v4_5_100_job_latest" in finalize
    assert "audits/order_readiness_v4_5_100_job_latest" in finalize
    assert "negative_control_preflight_matrix.tsv" in finalize
    assert "ultimate.cli order-readiness" in finalize


def test_v4_5_batch_array_dispatches_all_declared_modules() -> None:
    script = (ROOT / "slurm" / "v4_5_100_job_batch_array.sbatch").read_text(encoding="utf-8")

    assert "CHUNK_SIZE=10" in script
    assert "TOTAL_CHUNKS=10" in script
    assert "SLURM_ARRAY_JOB_ID" in script
    assert "elif (( global_index <= 100 )); then echo \"functional_state\"" in script
    assert "(global_index - 1) % 3" not in script
    for module in EXPECTED_DISTRIBUTION:
        assert f"echo \"{module}\"" in script or f"module == \"{module}\"" in script or f"elif module == \"{module}\"" in script


def test_v4_5_scope_doc_excludes_heavy_algorithms_and_raw_upstream() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")

    for token in (
        "controlled rehearsal",
        "not real customer delivery",
        "raw upstream production",
        "heavy algorithms",
        "Negative controls are declared separately",
        "not counted in the 100 runnable jobs",
        "handoff-only",
        "manual_review_required",
        "FASTQ/BCL processing",
        "CellChat/NicheNet",
        "inferCNV/CopyKAT",
        "RNA velocity",
        "Full WNN or multiVI",
        "Clinical survival or risk-model",
        "internal_rehearsal",
        "separate approval gate",
    ):
        assert token in text
