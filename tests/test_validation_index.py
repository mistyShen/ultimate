from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from ultimate.cli import main
from ultimate.validation_index import build_validation_index


def test_build_validation_index_reads_run_manifests(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    run = root / "validations" / "demo_run"
    (run / "reports").mkdir(parents=True)
    (run / "reports" / "report.html").write_text("<html></html>", encoding="utf-8")
    manifest = {
        "status": "ready",
        "analysis_level": "validated_backend",
        "is_demo": False,
        "is_stub": False,
        "delivery_allowed": False,
        "validation_evidence_allowed": True,
        "non_delivery_reason": "validation_evidence_only_not_customer_delivery",
        "slurm_job_id": "123",
        "input_h5": "/data/input.h5",
        "n_cells": 12,
        "figures": ["a.png", "b.png"],
        "tables": ["a.tsv"],
        "objects": {"h5ad": "obj.h5ad"},
        "backend_id": "vdj.default.scirpy_mvp",
        "backend_status": "fully_automatic_mvp",
    }
    (run / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = build_validation_index(root=root, output_dir=tmp_path / "index")

    assert result["n_runs"] == 1
    assert Path(result["validation_index_tsv"]).exists()
    assert Path(result["validation_index_json"]).exists()
    assert Path(result["report_html"]).exists()
    text = Path(result["validation_index_tsv"]).read_text(encoding="utf-8")
    assert "guard_status" in text
    assert "validated_backend" in text
    assert "123" in text
    assert "delivery_gate_status" in text
    assert "backend_ids" in text
    assert "vdj.default.scirpy_mvp" in text


def test_cli_validation_index(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    run = root / "validations" / "demo_run"
    run.mkdir(parents=True)
    (run / "run_manifest.json").write_text(json.dumps({"status": "ready"}), encoding="utf-8")

    result = CliRunner().invoke(main, ["validation-index", "--root", str(root), "--output-dir", str(tmp_path / "index")])

    assert result.exit_code == 0, result.output
    assert "validation_index_tsv" in result.output
    text = (tmp_path / "index" / "validation_index.tsv").read_text(encoding="utf-8")
    assert "missing_guard_fields" in text


def test_validation_index_includes_nested_validation_roots(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    for run in (
        root / "validations" / "direct_run",
        root / "validation_runs" / "scrna_mvp_validation" / "h5ad",
        root / "validations" / "bulk_demo_python" / "project" / "runs" / "bulk_demo",
    ):
        run.mkdir(parents=True)
        (run / "run_manifest.json").write_text(
            json.dumps(
                {
                    "status": "ready",
                    "analysis_level": "validated_backend",
                    "is_demo": False,
                    "is_stub": False,
                    "delivery_allowed": False,
                    "validation_evidence_allowed": True,
                    "non_delivery_reason": "validation_evidence_only_not_customer_delivery",
                }
            ),
            encoding="utf-8",
        )

    result = build_validation_index(root=root, output_dir=tmp_path / "index")

    assert result["n_runs"] == 3
    text = (tmp_path / "index" / "validation_index.tsv").read_text(encoding="utf-8")
    assert "direct_run" in text
    assert "h5ad" in text
    assert "bulk_demo" in text


def test_validation_index_infers_module_from_standard_validation_run_names(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    runs = {
        root / "validations" / "slurm_cite_seq_10x_pbmc_unified": "cite_seq",
        root / "validations" / "slurm_tumor_sc_maynard_raw_counts": "tumor_sc",
        root / "validation_runs" / "scrna_mvp_validation" / "h5ad": "scrna",
        root / "validations" / "bulk_demo_python" / "project" / "runs" / "project": "rnaseq,scrna,scatac,multiome,vdj,scdna,mtdna,scepi,cite_seq,spatial,perturb_seq,hto_demux,genotype_demux,functional_state,tumor_sc,clinical_assoc,method_tools,methylation,proteomics,publicdb,wgcna,single_gene",
    }
    for run in runs:
        run.mkdir(parents=True)
        (run / "run_manifest.json").write_text(
            json.dumps(
                {
                    "status": "ready",
                    "analysis_level": "smoke_backend",
                    "is_demo": False,
                    "is_stub": False,
                    "delivery_allowed": False,
                    "validation_evidence_allowed": False,
                    "non_delivery_reason": "backend_smoke_check_not_customer_delivery",
                }
            ),
            encoding="utf-8",
        )

    result = build_validation_index(root=root, output_dir=tmp_path / "index")

    rows = {
        line.split("\t")[0]: line.split("\t")[2]
        for line in Path(result["validation_index_tsv"]).read_text(encoding="utf-8").splitlines()[1:]
    }
    assert rows["slurm_cite_seq_10x_pbmc_unified"] == "cite_seq"
    assert rows["slurm_tumor_sc_maynard_raw_counts"] == "tumor_sc"
    assert rows["h5ad"] == "scrna"
    assert rows["project"].startswith("rnaseq,scrna,scatac")


def test_validation_index_adds_module_and_order_readiness_fields(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    run = root / "validations" / "scrna_public"
    (run / "reports").mkdir(parents=True)
    (run / "logs").mkdir(parents=True)
    (run / "results" / "figures").mkdir(parents=True)
    (run / "results" / "tables").mkdir(parents=True)
    (run / "objects").mkdir(parents=True)
    (run / "reports" / "report.html").write_text("<html></html>", encoding="utf-8")
    (run / "reports" / "methods.md").write_text("methods", encoding="utf-8")
    (run / "logs" / "run.log").write_text("ok", encoding="utf-8")
    (run / "results" / "figures" / "umap.png").write_text("png", encoding="utf-8")
    (run / "results" / "tables" / "qc.tsv").write_text("a\n1\n", encoding="utf-8")
    (run / "objects" / "scrna_mvp.h5ad").write_text("object", encoding="utf-8")
    (run / "run_manifest.json").write_text(
        json.dumps(
            {
                "module": "scrna",
                "status": "ready",
                "analysis_level": "validated_backend",
                "is_demo": False,
                "is_stub": False,
                "delivery_allowed": False,
                "validation_evidence_allowed": True,
                "non_delivery_reason": "validation_evidence_only_not_customer_delivery",
                "slurm_job_id": "777",
                "figures": ["results/figures/umap.png"],
                "tables": ["results/tables/qc.tsv"],
                "objects": {"h5ad": "objects/scrna_mvp.h5ad"},
            }
        ),
        encoding="utf-8",
    )

    result = build_validation_index(root=root, output_dir=tmp_path / "index")

    text = Path(result["validation_index_tsv"]).read_text(encoding="utf-8")
    assert "module" in text
    assert "evidence_status" in text
    assert "order_readiness_status" in text
    assert "missing_or_gap" in text
    row = next(line for line in text.splitlines() if line.startswith("scrna_public\t"))
    assert "scrna" in row
    assert "ready_real_evidence" in row
    assert "ready_for_validation_evidence" in row
    assert result["summary"]["ready_for_validation_evidence"] == 1
    assert result["summary"]["module_counts"]["scrna"] == 1
    assert result["summary"]["delivery_gate_status_counts"]["not_recorded"] == 1


def test_validation_index_reads_nested_slurm_job_id(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    run = root / "validations" / "nested_slurm_public"
    (run / "reports").mkdir(parents=True)
    (run / "logs").mkdir(parents=True)
    (run / "results" / "figures").mkdir(parents=True)
    (run / "results" / "tables").mkdir(parents=True)
    (run / "objects").mkdir(parents=True)
    (run / "reports" / "report.html").write_text("<html></html>", encoding="utf-8")
    (run / "reports" / "methods.md").write_text("methods", encoding="utf-8")
    (run / "logs" / "run.log").write_text("ok", encoding="utf-8")
    (run / "results" / "figures" / "plot.png").write_text("png", encoding="utf-8")
    (run / "results" / "tables" / "table.tsv").write_text("a\n1\n", encoding="utf-8")
    (run / "objects" / "object.h5ad").write_text("object", encoding="utf-8")
    (run / "run_manifest.json").write_text(
        json.dumps(
            {
                "module": "scrna",
                "status": "ready",
                "analysis_level": "validated_backend",
                "is_demo": False,
                "is_stub": False,
                "delivery_allowed": False,
                "validation_evidence_allowed": True,
                "non_delivery_reason": "validation_evidence_only_not_customer_delivery",
                "slurm": {"slurm_job_id": "999"},
                "figures": ["results/figures/plot.png"],
                "tables": ["results/tables/table.tsv"],
                "objects": {"h5ad": "objects/object.h5ad"},
            }
        ),
        encoding="utf-8",
    )

    result = build_validation_index(root=root, output_dir=tmp_path / "index")

    rows = json.loads(Path(result["validation_index_json"]).read_text(encoding="utf-8"))
    assert rows[0]["slurm_job_id"] == "999"
    assert rows[0]["has_slurm_evidence"] == "true"
    assert rows[0]["order_readiness_status"] == "ready_for_validation_evidence"


def test_validation_index_checks_module_level_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    run = root / "validations" / "slurm_vdj_10x_pbmc_unified"
    (run / "results" / "tables" / "vdj").mkdir(parents=True)
    (run / "results" / "figures" / "vdj").mkdir(parents=True)
    (run / "objects" / "vdj").mkdir(parents=True)
    (run / "reports").mkdir(parents=True)
    (run / "logs").mkdir(parents=True)
    table = run / "results" / "tables" / "vdj" / "clonotype_summary.tsv"
    figure = run / "results" / "figures" / "vdj" / "clone_size_distribution.png"
    obj = run / "objects" / "vdj" / "vdj_mvp.h5ad"
    table.write_text("clonotype_id\nc1\n", encoding="utf-8")
    figure.write_text("png", encoding="utf-8")
    obj.write_text("object", encoding="utf-8")
    (run / "reports" / "report.html").write_text("<html></html>", encoding="utf-8")
    (run / "reports" / "methods.md").write_text("methods", encoding="utf-8")
    (run / "logs" / "run.log").write_text("ok", encoding="utf-8")
    (run / "run_manifest.json").write_text(
        json.dumps(
            {
                "status": "ready",
                "analysis_level": "validated_backend",
                "is_demo": False,
                "is_stub": False,
                "delivery_allowed": False,
                "validation_evidence_allowed": True,
                "non_delivery_reason": "validation_evidence_only_not_customer_delivery",
                "slurm_job_id": "9381151",
                "modules": [
                    {
                        "module": "vdj",
                        "status": "complete_vdj_10x_backend",
                        "backend_id": "vdj.default.scirpy_mvp",
                        "backend_status": "fully_automatic_validated_entrypoint",
                        "artifacts": {
                            "tables": {"clonotype_summary": str(table)},
                            "figures": {"clone_size_distribution": str(figure)},
                            "objects": {"mvp_object": str(obj)},
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = build_validation_index(root=root, output_dir=tmp_path / "index")
    rows = json.loads(Path(result["validation_index_json"]).read_text(encoding="utf-8"))
    row = next(item for item in rows if item["run_name"] == "slurm_vdj_10x_pbmc_unified")

    assert row["artifact_status"] == "ready"
    assert row["order_readiness_status"] == "ready_for_validation_evidence"
    assert row["backend_ids"] == "vdj.default.scirpy_mvp"
    assert row["backend_statuses"] == "fully_automatic_validated_entrypoint"


def test_validation_index_includes_module_backend_execution_rows(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    run = root / "validations" / "slurm_rnaseq_airway_public"
    (run / "results" / "tables" / "rnaseq").mkdir(parents=True)
    (run / "results" / "figures" / "rnaseq").mkdir(parents=True)
    (run / "objects" / "rnaseq").mkdir(parents=True)
    (run / "reports").mkdir(parents=True)
    (run / "logs").mkdir(parents=True)
    table = run / "results" / "tables" / "rnaseq" / "de_results.tsv"
    figure = run / "results" / "figures" / "rnaseq" / "deseq2_edgeR_volcano.png"
    obj = run / "objects" / "rnaseq" / "rnaseq_de_backend.rds"
    table.write_text("feature_id\tpadj\nGENE_A\t0.01\n", encoding="utf-8")
    figure.write_text("png", encoding="utf-8")
    obj.write_text("object", encoding="utf-8")
    (run / "reports" / "report.html").write_text("<html></html>", encoding="utf-8")
    (run / "reports" / "methods.md").write_text("methods", encoding="utf-8")
    (run / "logs" / "run.log").write_text("ok", encoding="utf-8")
    (run / "run_manifest.json").write_text(
        json.dumps(
            {
                "status": "ready",
                "analysis_level": "validated_backend",
                "is_demo": False,
                "is_stub": False,
                "delivery_allowed": False,
                "validation_evidence_allowed": True,
                "non_delivery_reason": "validation_evidence_only_not_customer_delivery",
                "slurm_job_id": "9381178",
                "modules": [
                    {
                        "module": "rnaseq",
                        "status": "complete_python_bulk_backend",
                        "backend_id": "rnaseq.matrix.python_mvp",
                        "backend_status": "fully_automatic_validated_entrypoint",
                        "backend_execution": [
                            {
                                "backend_id": "rnaseq.de.deseq2_edger",
                                "status": "ready",
                                "analysis_level": "validated_backend",
                                "skip_reason": "",
                            }
                        ],
                        "artifacts": {
                            "tables": {"de_results": str(table)},
                            "figures": {"de_backend_volcano": str(figure)},
                            "objects": {"rnaseq_de_backend_rds": str(obj)},
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = build_validation_index(root=root, output_dir=tmp_path / "index")
    rows = json.loads(Path(result["validation_index_json"]).read_text(encoding="utf-8"))
    row = next(item for item in rows if item["run_name"] == "slurm_rnaseq_airway_public")

    assert "rnaseq.matrix.python_mvp" in row["backend_ids"]
    assert "rnaseq.de.deseq2_edger" in row["backend_ids"]
    assert "fully_automatic_validated_entrypoint" in row["backend_statuses"]
    assert "ready" in row["backend_statuses"]


def test_validation_index_includes_prepared_jobs_and_delivery_scope_priority(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    run = root / "jobs" / "JOB001" / "runs" / "RUN001"
    (run / "reports").mkdir(parents=True)
    (run / "logs").mkdir(parents=True)
    (run / "results" / "figures").mkdir(parents=True)
    (run / "results" / "tables").mkdir(parents=True)
    (run / "objects").mkdir(parents=True)
    (run / "reports" / "report.html").write_text("<html></html>", encoding="utf-8")
    (run / "reports" / "methods.md").write_text("methods", encoding="utf-8")
    (run / "logs" / "run.log").write_text("ok", encoding="utf-8")
    (run / "results" / "figures" / "pca.png").write_text("png", encoding="utf-8")
    (run / "results" / "tables" / "qc.tsv").write_text("a\n1\n", encoding="utf-8")
    (run / "objects" / "object.rds").write_text("object", encoding="utf-8")
    (run / "run_manifest.json").write_text(
        json.dumps(
            {
                "module": "rnaseq",
                "status": "ready",
                "analysis_level": "production_backend",
                "is_demo": False,
                "is_stub": False,
                "delivery_allowed": True,
                "validation_evidence_allowed": True,
                "non_delivery_reason": "",
                "slurm_job_id": "123",
                "delivery_scope": "customer_delivery",
                "production_approval": {
                    "approved": True,
                    "approved_by": "pytest",
                    "approved_at": "2026-06-05T00:00:00Z",
                    "project_id": "JOB001",
                    "input_path": str(run / "config.yaml"),
                    "output_dir": str(run),
                    "delivery_scope": "customer_delivery",
                    "reason": "pytest",
                },
                "delivery_gate": {
                    "status": "ready",
                    "delivery_allowed": True,
                    "validation_evidence_allowed": True,
                    "approval_status": "approved",
                    "delivery_scope": "internal_rehearsal",
                },
                "figures": ["results/figures/pca.png"],
                "tables": ["results/tables/qc.tsv"],
                "objects": {"rds": "objects/object.rds"},
            }
        ),
        encoding="utf-8",
    )

    result = build_validation_index(root=root, output_dir=tmp_path / "index")

    rows = json.loads(Path(result["validation_index_json"]).read_text(encoding="utf-8"))
    row = rows[0]
    assert row["run_kind"] == "production_rehearsal"
    assert row["delivery_scope"] == "internal_rehearsal"
    assert row["delivery_gate_validation_allowed"] == "true"
    assert row["production_approval_status"] == "approved"
    assert row["has_slurm_evidence"] == "true"


def test_validation_index_distinguishes_customer_delivery_rehearsal(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    run = root / "jobs" / "V4_ALPHA" / "runs" / "V4_ALPHA"
    (run / "reports").mkdir(parents=True)
    (run / "logs").mkdir(parents=True)
    (run / "results" / "figures").mkdir(parents=True)
    (run / "results" / "tables").mkdir(parents=True)
    (run / "objects").mkdir(parents=True)
    (run / "reports" / "report.html").write_text("<html></html>", encoding="utf-8")
    (run / "reports" / "methods.md").write_text("methods", encoding="utf-8")
    (run / "logs" / "run.log").write_text("ok", encoding="utf-8")
    (run / "results" / "figures" / "pca.png").write_text("png", encoding="utf-8")
    (run / "results" / "tables" / "qc.tsv").write_text("a\n1\n", encoding="utf-8")
    (run / "objects" / "object.rds").write_text("object", encoding="utf-8")
    (run / "run_manifest.json").write_text(
        json.dumps(
            {
                "module": "rnaseq",
                "status": "ready",
                "analysis_level": "production_backend",
                "is_demo": False,
                "is_stub": False,
                "delivery_allowed": True,
                "validation_evidence_allowed": True,
                "slurm_job_id": "456",
                "production_approval": {
                    "approved": True,
                    "approved_by": "pytest",
                    "approved_at": "2026-06-11T00:00:00Z",
                    "project_id": "V4_ALPHA",
                    "input_path": str(run / "config.yaml"),
                    "output_dir": str(run),
                    "delivery_scope": "customer_delivery",
                    "delivery_mode": "customer_delivery_rehearsal",
                    "reason": "pytest",
                },
                "delivery_gate": {
                    "status": "ready",
                    "delivery_allowed": True,
                    "approval_status": "approved",
                    "delivery_scope": "customer_delivery",
                    "delivery_mode": "customer_delivery_rehearsal",
                },
                "figures": ["results/figures/pca.png"],
                "tables": ["results/tables/qc.tsv"],
                "objects": {"rds": "objects/object.rds"},
            }
        ),
        encoding="utf-8",
    )

    result = build_validation_index(root=root, output_dir=tmp_path / "index")

    rows = json.loads(Path(result["validation_index_json"]).read_text(encoding="utf-8"))
    assert rows[0]["run_kind"] == "customer_delivery_rehearsal"
    assert rows[0]["delivery_scope"] == "customer_delivery"


def test_validation_index_demo_or_smoke_cannot_be_ready_for_delivery(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    for name, level in {"demo": "demo_result", "smoke": "smoke_backend"}.items():
        run = root / "validations" / name
        (run / "reports").mkdir(parents=True)
        (run / "reports" / "report.html").write_text("<html></html>", encoding="utf-8")
        (run / "reports" / "methods.md").write_text("methods", encoding="utf-8")
        (run / "run_manifest.json").write_text(
            json.dumps(
                {
                    "status": "ready",
                    "analysis_level": level,
                    "is_demo": level == "demo_result",
                    "is_stub": False,
                    "delivery_allowed": False,
                    "validation_evidence_allowed": False,
                    "non_delivery_reason": "not_delivery",
                }
            ),
            encoding="utf-8",
        )

    result = build_validation_index(root=root, output_dir=tmp_path / "index")

    rows = json.loads(Path(result["validation_index_json"]).read_text(encoding="utf-8"))
    assert {row["order_readiness_status"] for row in rows} == {"not_ready"}


def test_validation_index_indexes_delivery_gate_when_present(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    run = root / "validations" / "unified_demo_run"
    (run / "reports").mkdir(parents=True)
    (run / "logs").mkdir(parents=True)
    (run / "results" / "figures").mkdir(parents=True)
    (run / "results" / "tables").mkdir(parents=True)
    (run / "objects").mkdir(parents=True)
    (run / "reports" / "report.html").write_text("<html></html>", encoding="utf-8")
    (run / "reports" / "methods.md").write_text("methods", encoding="utf-8")
    (run / "logs" / "run.log").write_text("ok", encoding="utf-8")
    (run / "results" / "figures" / "plot.png").write_text("png", encoding="utf-8")
    (run / "results" / "tables" / "table.tsv").write_text("a\n1\n", encoding="utf-8")
    (run / "objects" / "object.rds").write_text("object", encoding="utf-8")
    (run / "run_manifest.json").write_text(
        json.dumps(
            {
                "module": "rnaseq",
                "status": "ready",
                "analysis_level": "demo_result",
                "is_demo": True,
                "is_stub": False,
                "delivery_allowed": False,
                "validation_evidence_allowed": False,
                "non_delivery_reason": "demo_result_not_customer_delivery",
                "figures": ["results/figures/plot.png"],
                "tables": ["results/tables/table.tsv"],
                "objects": {"mvp": "objects/object.rds"},
                "delivery_gate": {
                    "status": "blocked",
                    "run_status": "ready",
                    "delivery_allowed": False,
                    "validation_evidence_allowed": False,
                    "approval_status": "not_required",
                    "blockers": ["demo_modules=rnaseq", "no_production_backend_modules"],
                    "blocked_modules": [{"module": "rnaseq", "analysis_level": "demo_result"}],
                },
            }
        ),
        encoding="utf-8",
    )

    result = build_validation_index(root=root, output_dir=tmp_path / "index")

    rows = json.loads(Path(result["validation_index_json"]).read_text(encoding="utf-8"))
    assert rows[0]["delivery_gate_status"] == "blocked"
    assert rows[0]["delivery_gate_allowed"] == "false"
    assert rows[0]["delivery_gate_approval_status"] == "not_required"
    assert rows[0]["delivery_gate_blockers"] == "demo_modules=rnaseq;no_production_backend_modules"
    assert result["summary"]["delivery_gate_status_counts"]["blocked"] == 1
    report = Path(result["report_md"]).read_text(encoding="utf-8")
    assert "delivery gate blocked: 1" in report


def test_validation_index_adds_functional_state_derived_row_from_scrna_signature_validation(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    run = root / "validations" / "slurm_scrna_nsclc_lambrechts"
    (run / "reports").mkdir(parents=True)
    (run / "logs").mkdir(parents=True)
    (run / "results" / "figures").mkdir(parents=True)
    (run / "results" / "tables").mkdir(parents=True)
    (run / "objects").mkdir(parents=True)
    (run / "reports" / "report.html").write_text("<html></html>", encoding="utf-8")
    (run / "reports" / "methods.md").write_text("methods", encoding="utf-8")
    (run / "logs" / "run.log").write_text("ok", encoding="utf-8")
    (run / "results" / "figures" / "signature_score_heatmap.png").write_text("png", encoding="utf-8")
    (run / "results" / "tables" / "signature_scores_by_cell_type.tsv").write_text("cell_type\tscore\nT\t1\n", encoding="utf-8")
    (run / "objects" / "scrna_mvp.h5ad").write_text("object", encoding="utf-8")
    (run / "run_manifest.json").write_text(
        json.dumps(
            {
                "module": "scrna",
                "status": "ready",
                "analysis_level": "validated_backend",
                "is_demo": False,
                "is_stub": False,
                "delivery_allowed": False,
                "validation_evidence_allowed": True,
                "non_delivery_reason": "validation_evidence_only_not_customer_delivery",
                "slurm_job_id": "12345",
                "backend_status": [
                    {
                        "backend_id": "functional_state.default.signature_scoring",
                        "backend_status": "fully_automatic_validated_entrypoint",
                        "status": "ready",
                        "backend_slurm_job_id": "12345",
                    }
                ],
                "figures": ["results/figures/signature_score_heatmap.png"],
                "tables": ["results/tables/signature_scores_by_cell_type.tsv"],
                "objects": {"h5ad": "objects/scrna_mvp.h5ad"},
            }
        ),
        encoding="utf-8",
    )

    result = build_validation_index(root=root, output_dir=tmp_path / "index")

    rows = json.loads(Path(result["validation_index_json"]).read_text(encoding="utf-8"))
    by_module = {row["module"]: row for row in rows}
    assert {"scrna", "functional_state"} <= set(by_module)
    derived = by_module["functional_state"]
    assert derived["run_name"] == "slurm_scrna_nsclc_lambrechts__functional_state"
    assert derived["analysis_level"] == "validated_backend"
    assert derived["validation_evidence_allowed"] == "true"
    assert derived["artifact_status"] == "ready"
    assert "derived_from_scrna_signature_validation" in derived["missing_or_gap"]
    assert "blocked_reason=source_slurm_job_id_not_recorded" not in derived["missing_or_gap"]
    assert derived["slurm_job_id"] == "12345"
    assert derived["backend_ids"] == "functional_state.default.signature_scoring"
    assert derived["backend_statuses"] == "fully_automatic_validated_entrypoint"
    assert derived["backend_slurm_job_ids"] == "12345"


def test_validation_index_flags_delivery_without_approval(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    run = root / "validations" / "customer_like_run"
    (run / "reports").mkdir(parents=True)
    (run / "reports" / "report.html").write_text("<html></html>", encoding="utf-8")
    (run / "reports" / "methods.md").write_text("methods", encoding="utf-8")
    (run / "run_manifest.json").write_text(
        json.dumps(
            {
                "module": "rnaseq",
                "status": "ready",
                "analysis_level": "production_backend",
                "is_demo": False,
                "is_stub": False,
                "delivery_allowed": True,
                "validation_evidence_allowed": True,
                "non_delivery_reason": "",
            }
        ),
        encoding="utf-8",
    )

    result = build_validation_index(root=root, output_dir=tmp_path / "index")

    text = Path(result["validation_index_tsv"]).read_text(encoding="utf-8")
    row = next(line for line in text.splitlines() if line.startswith("customer_like_run\t"))
    assert "production_backend" in row
    assert "missing" in row
    assert "ready_for_delivery" not in row
    assert "production_approval=missing" in row


def test_validation_index_rejects_delivery_without_declared_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    run = root / "validations" / "no_artifacts"
    (run / "reports").mkdir(parents=True)
    (run / "reports" / "report.html").write_text("<html></html>", encoding="utf-8")
    (run / "reports" / "methods.md").write_text("methods", encoding="utf-8")
    (run / "run_manifest.json").write_text(
        json.dumps(
            {
                "module": "rnaseq",
                "status": "ready",
                "analysis_level": "production_backend",
                "is_demo": False,
                "is_stub": False,
                "delivery_allowed": True,
                "validation_evidence_allowed": True,
                "non_delivery_reason": "",
                "production_approval": {
                    "approved": True,
                    "approved_by": "pytest",
                    "approved_at": "2026-06-04T00:00:00Z",
                    "project_id": "no_artifacts",
                    "input_path": str(run / "config" / "project.yaml"),
                    "output_dir": str(run),
                    "delivery_scope": "internal_rehearsal",
                "reason": "pytest approval",
                },
            }
        ),
        encoding="utf-8",
    )

    result = build_validation_index(root=root, output_dir=tmp_path / "index")

    text = Path(result["validation_index_tsv"]).read_text(encoding="utf-8")
    row = next(line for line in text.splitlines() if line.startswith("no_artifacts\t"))
    assert "artifact_status=not_checked" in row
    assert "ready_for_delivery" not in row


def test_validation_index_rejects_incomplete_production_approval(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    run = root / "validations" / "bad_approval"
    (run / "reports").mkdir(parents=True)
    (run / "results" / "figures").mkdir(parents=True)
    (run / "results" / "tables").mkdir(parents=True)
    (run / "objects").mkdir(parents=True)
    (run / "reports" / "report.html").write_text("<html></html>", encoding="utf-8")
    (run / "reports" / "methods.md").write_text("methods", encoding="utf-8")
    (run / "results" / "figures" / "plot.png").write_text("png", encoding="utf-8")
    (run / "results" / "tables" / "table.tsv").write_text("a\n1\n", encoding="utf-8")
    (run / "objects" / "object.rds").write_text("object", encoding="utf-8")
    (run / "run_manifest.json").write_text(
        json.dumps(
            {
                "module": "rnaseq",
                "status": "ready",
                "analysis_level": "production_backend",
                "is_demo": False,
                "is_stub": False,
                "delivery_allowed": True,
                "validation_evidence_allowed": True,
                "non_delivery_reason": "",
                "production_approval": {"approved": True},
                "figures": ["results/figures/plot.png"],
                "tables": ["results/tables/table.tsv"],
                "objects": {"rds": "objects/object.rds"},
            }
        ),
        encoding="utf-8",
    )

    result = build_validation_index(root=root, output_dir=tmp_path / "index")

    text = Path(result["validation_index_tsv"]).read_text(encoding="utf-8")
    row = next(line for line in text.splitlines() if line.startswith("bad_approval\t"))
    assert "invalid_missing_fields:" in row
    assert "ready_for_delivery" not in row


def test_validation_index_checks_required_delivery_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    run = root / "validations" / "artifact_gap"
    (run / "reports").mkdir(parents=True)
    (run / "reports" / "report.html").write_text("<html></html>", encoding="utf-8")
    (run / "reports" / "methods.md").write_text("methods", encoding="utf-8")
    (run / "run_manifest.json").write_text(
        json.dumps(
            {
                "module": "vdj",
                "status": "ready",
                "analysis_level": "validated_backend",
                "is_demo": False,
                "is_stub": False,
                "delivery_allowed": False,
                "validation_evidence_allowed": True,
                "non_delivery_reason": "validation_evidence_only_not_customer_delivery",
                "slurm_job_id": "888",
                "figures": ["results/figures/missing.png"],
                "tables": ["results/tables/missing.tsv"],
                "objects": {"h5ad": "objects/missing.h5ad"},
            }
        ),
        encoding="utf-8",
    )

    result = build_validation_index(root=root, output_dir=tmp_path / "index")

    text = Path(result["validation_index_tsv"]).read_text(encoding="utf-8")
    row = next(line for line in text.splitlines() if line.startswith("artifact_gap\t"))
    assert "missing_or_empty_artifacts" in row
    assert "missing_figures:results/figures/missing.png" in row
    assert result["summary"]["artifact_status_counts"]["missing_or_empty_artifacts"] == 1


def test_validation_index_summary_counts_readiness(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    fixtures = {
        "ready_evidence": {
            "status": "ready",
            "analysis_level": "validated_backend",
            "is_demo": False,
            "is_stub": False,
            "delivery_allowed": False,
            "validation_evidence_allowed": True,
            "non_delivery_reason": "validation_evidence_only_not_customer_delivery",
            "slurm_job_id": "1",
        },
        "missing_guard": {"status": "ready"},
        "approval_missing": {
            "status": "ready",
            "analysis_level": "production_backend",
            "is_demo": False,
            "is_stub": False,
            "delivery_allowed": True,
            "validation_evidence_allowed": True,
            "non_delivery_reason": "",
        },
    }
    for name, manifest in fixtures.items():
        run = root / "validations" / name
        (run / "reports").mkdir(parents=True)
        (run / "results" / "figures").mkdir(parents=True)
        (run / "results" / "tables").mkdir(parents=True)
        (run / "objects").mkdir(parents=True)
        (run / "reports" / "report.html").write_text("<html></html>", encoding="utf-8")
        (run / "reports" / "methods.md").write_text("methods", encoding="utf-8")
        if name == "ready_evidence":
            (run / "results" / "figures" / "plot.png").write_text("png", encoding="utf-8")
            (run / "results" / "tables" / "table.tsv").write_text("a\n1\n", encoding="utf-8")
            (run / "objects" / "object.h5ad").write_text("object", encoding="utf-8")
            manifest["figures"] = ["results/figures/plot.png"]
            manifest["tables"] = ["results/tables/table.tsv"]
            manifest["objects"] = {"h5ad": "objects/object.h5ad"}
        (run / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = build_validation_index(root=root, output_dir=tmp_path / "index")

    assert result["summary"]["guard_status_counts"]["ready"] == 2
    assert result["summary"]["guard_status_counts"]["missing_guard_fields"] == 1
    assert result["summary"]["order_readiness_status_counts"]["ready_for_validation_evidence"] == 1
    assert result["summary"]["order_readiness_status_counts"]["needs_manual_review"] == 1
    assert result["summary"]["order_readiness_status_counts"]["not_ready"] == 1
    summary_text = Path(result["validation_summary_tsv"]).read_text(encoding="utf-8")
    assert "order_readiness_status_counts.ready_for_validation_evidence\t1" in summary_text
