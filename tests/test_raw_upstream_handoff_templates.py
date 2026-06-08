from __future__ import annotations

import csv
from pathlib import Path

import yaml


def test_nfcore_rnaseq_handoff_is_import_ready_but_not_executed() -> None:
    handoff_dir = _handoff_dir("nfcore_rnaseq")

    samplesheet_header = _csv_header(handoff_dir / "samplesheet.csv")
    assert samplesheet_header[:4] == ["sample", "fastq_1", "fastq_2", "strandedness"]
    assert {"seq_platform", "seq_center"}.issubset(samplesheet_header)

    params = yaml.safe_load((handoff_dir / "params.yaml").read_text(encoding="utf-8"))
    assert params["input"].endswith("nfcore_rnaseq_samplesheet.csv")
    assert params["aligner"] == "star_salmon"
    assert params["outdir"].startswith("/shared/shen/2026/ultimate/jobs/<job_id>/runs/")

    nextflow_config = (handoff_dir / "nextflow.config").read_text(encoding="utf-8")
    assert "executor = 'slurm'" in nextflow_config
    assert "cacheDir = '/shared/shen/2026/ultimate/containers/apptainer'" in nextflow_config
    assert "pipeline_info/dag.html" in nextflow_config
    assert "/share/home" not in nextflow_config

    command_plan = (handoff_dir / "command_plan.sh").read_text(encoding="utf-8")
    assert "Ultimate does not execute nf-core/rnaseq" in command_plan
    assert "nextflow run nf-core/rnaseq" in command_plan
    assert "cat <<PLAN" in command_plan

    import_config = yaml.safe_load((handoff_dir / "expected_matrix_import.yaml").read_text(encoding="utf-8"))
    assert import_config["execution_status"] == "not_executed_by_ultimate"
    assert import_config["production_gate"]["raw_fastq_direct_import_allowed"] is False
    rnaseq_cfg = import_config["ultimate_import_config"]["modules"]["rnaseq"]
    assert rnaseq_cfg["input_matrix_kind"] == "raw_gene_counts"
    assert rnaseq_cfg["delivery_allowed"] is False

    readme = (handoff_dir / "README.md").read_text(encoding="utf-8")
    assert "FASTQ 不直接进入 Ultimate core" in readme
    assert "open-source upstream handoff" in readme
    assert "not called by Ultimate" in readme


def test_nfcore_scrnaseq_handoff_is_import_ready_but_not_executed() -> None:
    handoff_dir = _handoff_dir("nfcore_scrnaseq")

    samplesheet_header = _csv_header(handoff_dir / "samplesheet.csv")
    assert samplesheet_header[:3] == ["sample", "fastq_1", "fastq_2"]
    assert {"expected_cells", "seq_center"}.issubset(samplesheet_header)
    assert "strandedness" not in samplesheet_header

    params = yaml.safe_load((handoff_dir / "params.yaml").read_text(encoding="utf-8"))
    assert params["input"].endswith("nfcore_scrnaseq_samplesheet.csv")
    assert params["aligner"] == "star"
    assert params["protocol"] == "10XV3"
    assert params["outdir"].startswith("/shared/shen/2026/ultimate/jobs/<job_id>/runs/")

    nextflow_config = (handoff_dir / "nextflow.config").read_text(encoding="utf-8")
    assert "executor = 'slurm'" in nextflow_config
    assert "cacheDir = '/shared/shen/2026/ultimate/containers/apptainer'" in nextflow_config
    assert "pipeline_info/dag.html" in nextflow_config
    assert "/share/home" not in nextflow_config

    command_plan = (handoff_dir / "command_plan.sh").read_text(encoding="utf-8")
    assert "Ultimate does not execute nf-core/scrnaseq" in command_plan
    assert "nextflow run nf-core/scrnaseq" in command_plan
    assert "cat <<PLAN" in command_plan

    import_config = yaml.safe_load((handoff_dir / "expected_matrix_import.yaml").read_text(encoding="utf-8"))
    assert import_config["execution_status"] == "not_executed_by_ultimate"
    assert import_config["production_gate"]["raw_fastq_direct_import_allowed"] is False
    scrna_cfg = import_config["ultimate_import_config"]["modules"]["scrna"]
    assert scrna_cfg["input_type"] == "10x_h5_or_mtx"
    assert scrna_cfg["delivery_allowed"] is False

    readme = (handoff_dir / "README.md").read_text(encoding="utf-8")
    assert "FASTQ 不直接进入 Ultimate core" in readme
    assert "open-source upstream handoff" in readme
    assert "not called by Ultimate" in readme


def test_module_handoff_docs_require_upstream_fastq_handoff() -> None:
    rnaseq_readme = (_handoff_dir("rnaseq") / "README.md").read_text(encoding="utf-8")
    scrna_readme = (_handoff_dir("scrna") / "README.md").read_text(encoding="utf-8")

    assert "FASTQ 输入必须先走 upstream handoff" in rnaseq_readme
    assert "nfcore_rnaseq" in rnaseq_readme
    assert "raw count matrix" in rnaseq_readme
    assert "FASTQ 输入必须先走 upstream handoff" in scrna_readme
    assert "nfcore_scrnaseq" in scrna_readme
    assert "matrix/object" in scrna_readme


def test_v3_3_rehearsal_slurm_script_runs_delivery_check() -> None:
    script = Path(__file__).resolve().parents[1] / "slurm" / "v3_3_production_rehearsal.sbatch"
    text = script.read_text(encoding="utf-8")

    assert "set -euo pipefail" in text
    assert "v3_3_rnaseq_matrix_rehearsal" in text
    assert "v3_3_scrna_communication_rehearsal" in text
    assert "v3_3_scatac_publication_rehearsal" in text
    assert "production_approval.json" in text
    assert "job_id: $job_id" in text
    assert "delivery_scope" in text
    assert "internal_rehearsal" in text
    assert "delivery-check --run-dir" in text
    assert "write_v3_3_order_ready_report.py" in text


def _csv_header(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return next(csv.reader(handle))


def _handoff_dir(name: str) -> Path:
    return Path(__file__).resolve().parents[1] / "templates" / "handoffs" / name
