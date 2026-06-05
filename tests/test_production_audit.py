from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from ultimate.cli import main
from ultimate.constants import MODULE_ORDER
from ultimate.modules.common import module_mvp_table_schemas
from ultimate.production_audit import _delivery_gate_gaps, _final_acceptance_rows, _manifest_artifact_status, run_production_audit
from ultimate.validation_index import build_validation_index


def _write_scoped_prepared_job(root: Path, job_id: str) -> None:
    job_dir = root / "jobs" / job_id
    run_dir = job_dir / "runs" / job_id
    (job_dir / "deliverables").mkdir(parents=True)
    (job_dir / "reproducible_code").mkdir(parents=True)
    (run_dir / "results" / "figures" / "rnaseq").mkdir(parents=True)
    (run_dir / "results" / "tables" / "rnaseq").mkdir(parents=True)
    (run_dir / "objects" / "rnaseq").mkdir(parents=True)
    (run_dir / "reports").mkdir(parents=True)
    (run_dir / "reproducible_code").mkdir(parents=True)
    figure_path = run_dir / "results" / "figures" / "rnaseq" / "pca.png"
    table_path = run_dir / "results" / "tables" / "rnaseq" / "sample_qc.tsv"
    object_path = run_dir / "objects" / "rnaseq" / "rnaseq_mvp_object.rds"
    report_path = run_dir / "reports" / "report.html"
    methods_path = run_dir / "reports" / "methods.md"
    rerun_path = run_dir / "reproducible_code" / "rerun.sh"
    for path, text in {
        figure_path: "png",
        table_path: "sample_id\tqc\nS1\tok\n",
        object_path: "object",
        report_path: "<html>report</html>",
        methods_path: "methods",
        rerun_path: "#!/usr/bin/env bash\n",
    }.items():
        path.write_text(text, encoding="utf-8")
    run_manifest = {
        "status": "ready",
        "analysis_level": "production_backend",
        "is_demo": False,
        "is_stub": False,
        "delivery_allowed": True,
        "validation_evidence_allowed": True,
        "non_delivery_reason": "",
        "slurm_job_id": f"pytest-{job_id}",
        "slurm": {"slurm_job_id": f"pytest-{job_id}", "slurm_job_name": "pytest_rehearsal"},
        "modules": [
            {
                "module": "rnaseq",
                "status": "complete_python_bulk_backend",
                "analysis_level": "production_backend",
                "is_demo": False,
                "is_stub": False,
                "delivery_allowed": True,
                "validation_evidence_allowed": False,
                "non_delivery_reason": "",
                "artifacts": {
                    "figures": {"pca": str(figure_path)},
                    "tables": {"sample_qc": str(table_path)},
                    "objects": {"mvp_object": str(object_path)},
                },
            }
        ],
        "production_approval": {
            "approved": True,
            "approved_by": "pytest",
            "approved_at": "2026-06-05T00:00:00Z",
            "project_id": job_id,
            "input_path": str(root / "projects" / job_id),
            "output_dir": str(run_dir),
            "reason": "internal rehearsal test",
            "delivery_scope": "internal_rehearsal",
        },
        "delivery_gate": {
            "status": "ready",
            "delivery_allowed": True,
            "validation_evidence_allowed": False,
            "approval_status": "approved",
            "delivery_scope": "internal_rehearsal",
            "blocked_modules": [],
        },
    }
    (job_dir / "job_manifest.json").write_text(json.dumps({"job_id": job_id}), encoding="utf-8")
    (run_dir / "run_manifest.json").write_text(json.dumps(run_manifest), encoding="utf-8")
    delivery_index = "\n".join(
        [
            "category\tpath\tsize_bytes",
            f"figure\t{figure_path}\t{figure_path.stat().st_size}",
            f"table\t{table_path}\t{table_path.stat().st_size}",
            f"object\t{object_path}\t{object_path.stat().st_size}",
            f"report\t{report_path}\t{report_path.stat().st_size}",
            f"report\t{methods_path}\t{methods_path.stat().st_size}",
            f"reproducible_code\t{rerun_path}\t{rerun_path.stat().st_size}",
        ]
    ) + "\n"
    required = {
        job_dir / "deliverables" / "latest_run_manifest.json": json.dumps(run_manifest),
        job_dir / "deliverables" / "latest_report.html": report_path.read_text(encoding="utf-8"),
        job_dir / "deliverables" / "latest_methods.md": methods_path.read_text(encoding="utf-8"),
        job_dir / "deliverables" / "latest_delivery_index.tsv": delivery_index,
        job_dir / "reproducible_code" / "rerun.sh": rerun_path.read_text(encoding="utf-8"),
        job_dir / "reproducible_code" / "software_versions.tsv": "name\tversion\nultimate\ttest\n",
        job_dir / "reproducible_code" / "input_checksums.tsv": "path\tsha256\npytest\t0\n",
        job_dir / "reproducible_code" / "latest_repro_manifest.json": '{"run_dir": "test"}',
        run_dir / "reproducible_code" / "repro_manifest.json": '{"run_dir": "test"}',
    }
    for path, text in required.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (job_dir / "deliverables" / "latest_run_pointer.json").write_text(
        json.dumps(
            {
                "latest_run_dir": str(run_dir),
                "run_manifest": str(run_dir / "run_manifest.json"),
                "copied_artifacts": {
                    "run_manifest": str(job_dir / "deliverables" / "latest_run_manifest.json"),
                    "report_html": str(job_dir / "deliverables" / "latest_report.html"),
                    "methods_md": str(job_dir / "deliverables" / "latest_methods.md"),
                    "delivery_index": str(job_dir / "deliverables" / "latest_delivery_index.tsv"),
                },
                "policy": "job-level files are small latest-run mirrors; large result objects remain referenced from the run directory",
            }
        ),
        encoding="utf-8",
    )


def test_production_audit_writes_readiness_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    (root / ".conda" / "envs" / "ultimate-core").mkdir(parents=True)
    manifest = run_production_audit(root=root, output_dir=tmp_path / "audit")
    assert Path(manifest["capability_matrix"]).exists()
    assert Path(manifest["organism_support"]).exists()
    assert Path(manifest["style_options"]).exists()
    assert Path(manifest["order_readiness_checklist"]).exists()
    assert Path(manifest["validation_evidence_matrix"]).exists()
    assert Path(manifest["validation_gap_plan"]).exists()
    assert Path(manifest["validation_gap_plan_json"]).exists()
    assert Path(manifest["production_audit_tsv"]).exists()
    assert Path(manifest["final_acceptance_checklist"]).exists()
    assert Path(manifest["backend_maturity_table"]).exists()
    assert Path(manifest["backend_registry"]).exists()
    assert Path(manifest["module_maturity_table"]).exists()
    assert Path(manifest["module_standardization_matrix"]).exists()
    assert Path(manifest["tool_coverage_by_module"]).exists()
    assert "final_acceptance_summary" in manifest
    assert "backend_registry_summary" in manifest
    assert "validation_gap_summary" in manifest
    assert manifest["module_standardization_summary"]["ready"] == len(MODULE_ORDER)
    assert Path(manifest["next_steps"]).exists()
    assert sum(manifest["summary"].values()) == len(MODULE_ORDER)


def test_production_audit_layers_v2_core_separately_from_v3_partial(tmp_path: Path) -> None:
    core = {"rnaseq", "scrna", "vdj", "cite_seq", "functional_state"}
    capability_rows = [
        {
            "module": module,
            "validation": "available" if module in core else "partial:data_required",
            "production_status": "ready_basic" if module in core else "partial:data_required",
            "next_action": "blocked reason visible for pytest",
        }
        for module in MODULE_ORDER
    ]

    rows = _final_acceptance_rows(tmp_path / "ultimate", capability_rows, [])

    by_requirement = {row["requirement"]: row for row in rows}
    assert by_requirement["v2_core_modules_validated"]["status"] == "pass"
    assert by_requirement["v3_specialty_modules_tracked_not_blocking_v2"]["status"] == "pass"
    assert by_requirement["v3_backend_registry_ready"]["status"] == "pass"
    assert by_requirement["v3_fully_automatic_backends_gated"]["status"] == "pass"
    assert "blocked_reason=blocked reason visible for pytest" in by_requirement["v3_specialty_modules_tracked_not_blocking_v2"]["evidence"]


def test_delivery_gate_audit_keeps_legacy_manifests_optional_and_flags_inconsistent_gate() -> None:
    assert _delivery_gate_gaps({"status": "ready", "modules": []}) == []
    gaps = _delivery_gate_gaps(
        {
            "status": "ready",
            "modules": [
                {
                    "module": "rnaseq",
                    "analysis_level": "production_backend",
                    "delivery_allowed": True,
                }
            ],
            "delivery_gate": {
                "status": "ready",
                "delivery_allowed": True,
                "validation_evidence_allowed": True,
                "approval_status": "approved",
                "blocked_modules": [{"module": "rnaseq"}],
            },
        }
    )
    assert "delivery_gate:blocked_modules_present" in gaps


def test_production_audit_validation_gap_plan_maps_missing_runs_to_slurm_commands(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    (root / "slurm").mkdir(parents=True)
    (root / "slurm" / "scrna_mvp_validation.sbatch").write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    manifest = run_production_audit(root=root, output_dir=tmp_path / "audit")

    gap_plan = Path(manifest["validation_gap_plan"]).read_text(encoding="utf-8")
    row = next(line for line in gap_plan.splitlines() if line.startswith("scrna_mvp_10x_mtx\t"))
    assert f"hpc-sbatch {root.resolve()}/slurm/scrna_mvp_validation.sbatch" in row
    assert "\tpresent\t" in row
    assert "manifest_status=missing" in row
    assert "验证命令" in row
    assert manifest["validation_gap_summary"]["partial"] >= 1


def test_singlecell_validation_suite_skip_manifest_has_guard_fields() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "slurm" / "singlecell_validation_suite.sbatch"
    text = script.read_text(encoding="utf-8")
    assert '"analysis_level": "smoke_backend"' in text
    assert '"delivery_allowed": False' in text
    assert '"validation_evidence_allowed": False' in text
    assert 'validation_not_completed:' in text


def test_readiness_refresh_slurm_wrapper_runs_index_audit_and_guard_check() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "slurm" / "readiness_refresh.sbatch"
    text = script.read_text(encoding="utf-8")
    assert "ultimate.cli validation-index" in text
    assert "ultimate.cli audit-production" in text
    assert "check_validation_manifests.py" in text
    assert "set -euo pipefail" in text


def test_ultimate_run_slurm_wrapper_uses_portable_conda_discovery() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "slurm" / "ultimate_run.sbatch"
    text = script.read_text(encoding="utf-8")
    assert 'CONDA_SH="${CONDA_SH:-}"' in text
    assert "for candidate in" in text
    assert 'export PATH="$ENV_PREFIX/bin:$PATH"' in text
    assert "Unable to locate conda.sh or Python env" in text
    assert "/share/home/nshen" not in text


def test_high_impact_handoff_templates_exist() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    handoffs = repo_root / "templates" / "handoffs"
    required = {
        "nfcore_rnaseq": ("README.md", "samplesheet.csv", "params.yaml", "nextflow.config"),
        "nfcore_airrflow": ("README.md", "samplesheet.csv", "params.yaml", "nextflow.config"),
        "nfcore_sarek": ("README.md", "samplesheet.csv", "params.yaml", "nextflow.config"),
        "nfcore_atacseq": ("README.md", "samplesheet.csv", "params.yaml", "nextflow.config"),
        "nfcore_rnafusion": ("README.md", "samplesheet.csv", "params.yaml", "nextflow.config"),
        "bcl_convert": ("README.md",),
        "bcl2fastq": ("README.md",),
        "parse_biosciences": ("README.md",),
        "bd_rhapsody": ("README.md",),
        "mixcr": ("README.md",),
        "cellranger_count": ("README.md", "samplesheet.csv"),
        "cellranger_multi": ("README.md", "cellranger_multi_config.csv"),
        "cellranger_vdj": ("README.md",),
        "cellranger_atac": ("README.md",),
        "cellranger_arc": ("README.md", "libraries.csv"),
        "spaceranger": ("README.md",),
        "nfcore_spatialvi": ("README.md", "samplesheet.csv", "params.yaml", "nextflow.config"),
        "nfcore_sopa": ("README.md", "samplesheet.csv", "params.yaml", "nextflow.config"),
    }
    for directory, filenames in required.items():
        for filename in filenames:
            path = handoffs / directory / filename
            assert path.exists(), str(path)
            assert path.stat().st_size > 0, str(path)


def test_cli_styles_generates_review(tmp_path: Path) -> None:
    runner = CliRunner()
    out_dir = tmp_path / "style"
    result = runner.invoke(main, ["styles", "--style", "warm_academic", "--output-dir", str(out_dir)])
    assert result.exit_code == 0, result.output
    assert (out_dir / "style_review_manifest.json").exists()
    assert (out_dir / "qc_bar_review.png").exists()


def test_cli_audit_modules_generates_standardization_matrix(tmp_path: Path) -> None:
    runner = CliRunner()
    out_dir = tmp_path / "module_audit"
    repo_root = Path(__file__).resolve().parents[1]
    result = runner.invoke(main, ["audit-modules", "--root", str(repo_root), "--output-dir", str(out_dir)])
    assert result.exit_code == 0, result.output
    assert (out_dir / "run_manifest.json").exists()
    matrix = out_dir / "module_standardization_matrix.tsv"
    assert matrix.exists()
    text = matrix.read_text(encoding="utf-8")
    assert "demo_manifest_status" in text
    assert "overall_status" in text


def test_production_audit_rejects_demo_scrna_mvp_as_real_evidence(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    run_dir = root / "validation_runs" / "scrna_mvp_validation" / "10x_mtx"
    (run_dir / "results" / "tables").mkdir(parents=True)
    (run_dir / "results" / "figures").mkdir(parents=True)
    (run_dir / "objects").mkdir(parents=True)
    (run_dir / "reports").mkdir(parents=True)
    (run_dir / "run_manifest.json").write_text(
        """
{
  "status": "ready",
  "analysis_level": "demo_result",
  "is_demo": true,
  "is_stub": false,
  "delivery_allowed": false
}
""",
        encoding="utf-8",
    )
    for idx in range(8):
        (run_dir / "results" / "tables" / f"table_{idx}.tsv").write_text("a\\n1\\n", encoding="utf-8")
    for idx in range(3):
        (run_dir / "results" / "figures" / f"fig_{idx}.png").write_text("png", encoding="utf-8")
    (run_dir / "objects" / "scrna_mvp.h5ad").write_text("object", encoding="utf-8")
    (run_dir / "reports" / "report.md").write_text("report", encoding="utf-8")
    (run_dir / "reports" / "report.html").write_text("report", encoding="utf-8")

    manifest = run_production_audit(root=root, output_dir=tmp_path / "audit")
    evidence = Path(manifest["validation_evidence_matrix"]).read_text(encoding="utf-8")
    assert "scrna_mvp_10x_mtx" in evidence
    assert "analysis_level=demo_result" in evidence
    assert "guard_status=missing_guard_fields" in evidence


def test_production_capability_requires_guarded_validation_evidence(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    run_dir = root / "validations" / "slurm_tumor_sc_maynard_raw_counts"
    run_dir.mkdir(parents=True)
    (run_dir / "run_manifest.json").write_text('{"status": "ready"}', encoding="utf-8")

    manifest = run_production_audit(root=root, output_dir=tmp_path / "audit")

    matrix = Path(manifest["capability_matrix"]).read_text(encoding="utf-8")
    tumor_row = next(line for line in matrix.splitlines() if line.startswith("tumor_sc\t"))
    assert "partial:validation_manifest_not_ready" in tumor_row


def test_production_capability_rejects_contradictory_demo_validation_manifest(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    run_dir = root / "validations" / "slurm_vdj_10x_pbmc_unified"
    run_dir.mkdir(parents=True)
    (run_dir / "run_manifest.json").write_text(
        json.dumps(
            {
                "status": "ready",
                "analysis_level": "validated_backend",
                "is_demo": True,
                "is_stub": False,
                "delivery_allowed": False,
                "validation_evidence_allowed": True,
                "non_delivery_reason": "generated_demo_data_not_customer_delivery",
            }
        ),
        encoding="utf-8",
    )

    manifest = run_production_audit(root=root, output_dir=tmp_path / "audit")

    matrix = Path(manifest["capability_matrix"]).read_text(encoding="utf-8")
    vdj_row = next(line for line in matrix.splitlines() if line.startswith("vdj\t"))
    assert "partial:validation_manifest_not_ready" in vdj_row
    assert "ready_basic" not in vdj_row


def test_production_audit_accepts_perturb_public_validation_path(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    run_dir = root / "validations" / "slurm_perturb_seq_adamson_public"
    (run_dir / "results" / "tables").mkdir(parents=True)
    (run_dir / "results" / "figures").mkdir(parents=True)
    (run_dir / "objects").mkdir(parents=True)
    (run_dir / "reports").mkdir(parents=True)
    (run_dir / "run_manifest.json").write_text(
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
    table_names = (
        "guide_qc.tsv",
        "guide_assignment.tsv",
        "perturbation_summary.tsv",
        "perturbation_expression_effect.tsv",
        "pseudobulk_by_perturbation.tsv",
        "target_response.tsv",
    )
    schemas = module_mvp_table_schemas("perturb_seq")
    for table_name in table_names:
        table_path = run_dir / "results" / "tables" / table_name
        columns = schemas[table_name]
        values = ["perturb_seq" if column == "module" else "validated_backend" if column == "analysis_level" else "False" if column == "delivery_allowed" else f"{column}_value" for column in columns]
        table_path.write_text("\t".join(columns) + "\n" + "\t".join(values) + "\n", encoding="utf-8")
    figure_names = ("guide_distribution.png", "perturbation_umap_placeholder.png", "extra_qc.png")
    for figure_name in figure_names:
        fig_path = run_dir / "results" / "figures" / figure_name
        fig_path.write_text("png", encoding="utf-8")
    object_path = run_dir / "objects" / "perturb_seq_mvp_object.rds"
    object_path.write_text("{}", encoding="utf-8")
    (run_dir / "reports" / "report.md").write_text("report", encoding="utf-8")
    (run_dir / "reports" / "report.html").write_text("report", encoding="utf-8")
    manifest_payload = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    manifest_payload["tables"] = [f"results/tables/{table_name}" for table_name in table_names]
    manifest_payload["figures"] = [f"results/figures/{figure_name}" for figure_name in figure_names]
    manifest_payload["objects"] = {"mvp_object": "objects/perturb_seq_mvp_object.rds"}
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest_payload), encoding="utf-8")

    manifest = run_production_audit(root=root, output_dir=tmp_path / "audit")

    evidence = Path(manifest["validation_evidence_matrix"]).read_text(encoding="utf-8")
    assert "slurm_perturb_seq_adamson_public" in evidence
    perturb_evidence_row = next(line for line in evidence.splitlines() if line.startswith("slurm_perturb_seq\t"))
    assert "\tready\t" in perturb_evidence_row
    matrix = Path(manifest["capability_matrix"]).read_text(encoding="utf-8")
    perturb_row = next(line for line in matrix.splitlines() if line.startswith("perturb_seq\t"))
    assert "ready:public_or_existing_data_validation" in perturb_row
    assert "ready_basic" in perturb_row


def test_production_audit_rejects_perturb_validation_without_mvp_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    run_dir = root / "validations" / "slurm_perturb_seq_adamson_public"
    (run_dir / "results" / "tables").mkdir(parents=True)
    (run_dir / "results" / "figures").mkdir(parents=True)
    (run_dir / "objects").mkdir(parents=True)
    (run_dir / "reports").mkdir(parents=True)
    for idx in range(6):
        (run_dir / "results" / "tables" / f"table_{idx}.tsv").write_text("a\n1\n", encoding="utf-8")
    for idx in range(3):
        (run_dir / "results" / "figures" / f"fig_{idx}.png").write_text("png", encoding="utf-8")
    (run_dir / "objects" / "generic.json").write_text("{}", encoding="utf-8")
    (run_dir / "reports" / "report.html").write_text("report", encoding="utf-8")
    (run_dir / "reports" / "methods.md").write_text("methods", encoding="utf-8")
    (run_dir / "run_manifest.json").write_text(
        json.dumps(
            {
                "status": "ready",
                "analysis_level": "validated_backend",
                "is_demo": False,
                "is_stub": False,
                "delivery_allowed": False,
                "validation_evidence_allowed": True,
                "non_delivery_reason": "validation_evidence_only_not_customer_delivery",
                "tables": [f"results/tables/table_{idx}.tsv" for idx in range(6)],
                "figures": [f"results/figures/fig_{idx}.png" for idx in range(3)],
                "objects": {"json": "objects/generic.json"},
            }
        ),
        encoding="utf-8",
    )

    manifest = run_production_audit(root=root, output_dir=tmp_path / "audit")

    evidence = Path(manifest["validation_evidence_matrix"]).read_text(encoding="utf-8")
    row = next(line for line in evidence.splitlines() if line.startswith("slurm_perturb_seq\t"))
    assert "\tpartial\t" in row
    assert "missing_mvp_table:guide_qc.tsv" in row


def test_production_audit_rejects_validation_with_old_mvp_table_schema(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    run_dir = root / "validations" / "slurm_perturb_seq_adamson_public"
    (run_dir / "results" / "tables").mkdir(parents=True)
    (run_dir / "results" / "figures").mkdir(parents=True)
    (run_dir / "objects").mkdir(parents=True)
    (run_dir / "reports").mkdir(parents=True)
    for table_name in (
        "guide_qc.tsv",
        "guide_assignment.tsv",
        "perturbation_summary.tsv",
        "perturbation_expression_effect.tsv",
        "pseudobulk_by_perturbation.tsv",
        "target_response.tsv",
    ):
        (run_dir / "results" / "tables" / table_name).write_text(
            "module\tcell_id\tguide_id\ttarget_gene\tstatus\nperturb_seq\tCELL_1\tgRNA_1\tTP53\tmvp\n",
            encoding="utf-8",
        )
    for figure_name in ("guide_distribution.png", "perturbation_umap_placeholder.png"):
        (run_dir / "results" / "figures" / figure_name).write_text("png", encoding="utf-8")
    (run_dir / "objects" / "perturb_seq_mvp_object.rds").write_text("{}", encoding="utf-8")
    (run_dir / "reports" / "report.html").write_text("report", encoding="utf-8")
    (run_dir / "reports" / "methods.md").write_text("methods", encoding="utf-8")
    (run_dir / "run_manifest.json").write_text(
        json.dumps(
            {
                "status": "ready",
                "analysis_level": "validated_backend",
                "is_demo": False,
                "is_stub": False,
                "delivery_allowed": False,
                "validation_evidence_allowed": True,
                "non_delivery_reason": "validation_evidence_only_not_customer_delivery",
                "tables": [
                    "results/tables/guide_qc.tsv",
                    "results/tables/guide_assignment.tsv",
                    "results/tables/perturbation_summary.tsv",
                    "results/tables/perturbation_expression_effect.tsv",
                    "results/tables/pseudobulk_by_perturbation.tsv",
                    "results/tables/target_response.tsv",
                ],
                "figures": [
                    "results/figures/guide_distribution.png",
                    "results/figures/perturbation_umap_placeholder.png",
                ],
                "objects": {"mvp_object": "objects/perturb_seq_mvp_object.rds"},
            }
        ),
        encoding="utf-8",
    )

    manifest = run_production_audit(root=root, output_dir=tmp_path / "audit")

    evidence = Path(manifest["validation_evidence_matrix"]).read_text(encoding="utf-8")
    row = next(line for line in evidence.splitlines() if line.startswith("slurm_perturb_seq\t"))
    assert "\tpartial\t" in row
    assert "mvp_table_schema_missing:guide_qc.tsv:run_id" in row


def test_manifest_artifact_status_checks_declared_module_reports(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    report_path = run_dir / "reports" / "rnaseq" / "report.html"
    methods_path = run_dir / "reports" / "rnaseq" / "methods.md"
    report_path.parent.mkdir(parents=True)
    report_path.write_text("<html>module report</html>", encoding="utf-8")
    methods_path.write_text("module methods", encoding="utf-8")
    manifest = {
        "modules": [
            {
                "module": "rnaseq",
                "artifacts": {
                    "reports": {
                        "report_html": "reports/rnaseq/report.html",
                        "methods_md": "reports/rnaseq/methods.md",
                        "run_manifest": "reports/rnaseq/run_manifest.json",
                    }
                },
            }
        ]
    }

    status, gaps = _manifest_artifact_status(manifest, run_dir)

    assert status == "missing_or_empty_artifacts"
    assert "missing_module_reports:rnaseq:run_manifest" in gaps


def test_production_audit_rejects_validation_with_unrelated_artifact_files(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    run_dir = root / "validations" / "slurm_vdj_10x_pbmc_unified"
    (run_dir / "results" / "tables").mkdir(parents=True)
    (run_dir / "results" / "figures").mkdir(parents=True)
    (run_dir / "objects").mkdir(parents=True)
    (run_dir / "reports").mkdir(parents=True)
    (run_dir / "run_manifest.json").write_text(
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
    for idx in range(3):
        (run_dir / "results" / "tables" / f"unrelated_{idx}.tsv").write_text("a\n1\n", encoding="utf-8")
        (run_dir / "results" / "figures" / f"unrelated_{idx}.png").write_text("png", encoding="utf-8")
    (run_dir / "objects" / "unrelated.h5ad").write_text("object", encoding="utf-8")
    (run_dir / "reports" / "report.html").write_text("<html>report</html>", encoding="utf-8")
    (run_dir / "reports" / "methods.md").write_text("methods", encoding="utf-8")

    manifest = run_production_audit(root=root, output_dir=tmp_path / "audit")

    evidence = Path(manifest["validation_evidence_matrix"]).read_text(encoding="utf-8")
    row = next(line for line in evidence.splitlines() if line.startswith("slurm_vdj\t"))
    assert "\tpartial\t" in row
    assert "artifact_status=not_declared" in row


def test_production_audit_accepts_bulk_demo_as_smoke_not_validation_evidence(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    run_dir = root / "validations" / "bulk_demo_python" / "project" / "runs" / "project"
    (run_dir / "results" / "tables" / "rnaseq").mkdir(parents=True)
    (run_dir / "results" / "figures" / "rnaseq").mkdir(parents=True)
    (run_dir / "objects" / "rnaseq").mkdir(parents=True)
    (run_dir / "reports").mkdir(parents=True)
    (run_dir / "raw_qc" / "rnaseq").mkdir(parents=True)
    table_paths = []
    figure_paths = []
    object_paths = []
    for idx in range(30):
        path = run_dir / "results" / "tables" / "rnaseq" / f"table_{idx}.tsv"
        path.write_text("a\n1\n", encoding="utf-8")
        table_paths.append(path)
    for idx in range(25):
        path = run_dir / "results" / "figures" / "rnaseq" / f"figure_{idx}.png"
        path.write_text("png", encoding="utf-8")
        figure_paths.append(path)
    for idx in range(7):
        path = run_dir / "objects" / "rnaseq" / f"object_{idx}.rds"
        path.write_text("object", encoding="utf-8")
        object_paths.append(path)
    for idx, module in enumerate(MODULE_ORDER):
        raw_qc = run_dir / "raw_qc" / module / "raw_qc_manifest.json"
        raw_qc.parent.mkdir(parents=True, exist_ok=True)
        raw_qc.write_text('{"status": "ready"}', encoding="utf-8")
    (run_dir / "reports" / "report.html").write_text("<html>report</html>", encoding="utf-8")
    (run_dir / "reports" / "methods.md").write_text("methods", encoding="utf-8")
    run_manifest = {
        "status": "ready",
        "analysis_level": "demo_result",
        "is_demo": True,
        "is_stub": False,
        "delivery_allowed": False,
        "validation_evidence_allowed": False,
        "non_delivery_reason": "generated_demo_data_not_customer_delivery",
        "summary": {"module_count": len(MODULE_ORDER), "ready_module_count": len(MODULE_ORDER)},
        "modules": [
            {
                "module": "rnaseq",
                "artifacts": {
                    "tables": {f"table_{idx}": str(path) for idx, path in enumerate(table_paths)},
                    "figures": {f"figure_{idx}": str(path) for idx, path in enumerate(figure_paths)},
                    "objects": {f"object_{idx}": str(path) for idx, path in enumerate(object_paths)},
                },
            }
        ],
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(run_manifest), encoding="utf-8")

    manifest = run_production_audit(root=root, output_dir=tmp_path / "audit")

    evidence = Path(manifest["validation_evidence_matrix"]).read_text(encoding="utf-8")
    row = next(line for line in evidence.splitlines() if line.startswith("bulk_all_demo\t"))
    assert "\tready\t" in row
    assert "ready_smoke_or_real_run" in row


def test_production_audit_rejects_demo_slurm_validation_even_with_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    run_dir = root / "validations" / "slurm_vdj_10x_pbmc_unified"
    (run_dir / "results" / "tables").mkdir(parents=True)
    (run_dir / "results" / "figures").mkdir(parents=True)
    (run_dir / "objects").mkdir(parents=True)
    (run_dir / "reports").mkdir(parents=True)
    (run_dir / "run_manifest.json").write_text(
        json.dumps(
            {
                "status": "ready",
                "analysis_level": "demo_result",
                "is_demo": True,
                "is_stub": False,
                "delivery_allowed": False,
                "validation_evidence_allowed": False,
                "non_delivery_reason": "generated_demo_data_not_customer_delivery",
            }
        ),
        encoding="utf-8",
    )
    for idx in range(3):
        (run_dir / "results" / "tables" / f"table_{idx}.tsv").write_text("a\n1\n", encoding="utf-8")
        (run_dir / "results" / "figures" / f"fig_{idx}.png").write_text("png", encoding="utf-8")
    (run_dir / "objects" / "vdj_mvp.h5ad").write_text("object", encoding="utf-8")
    (run_dir / "reports" / "report.html").write_text("<html>report</html>", encoding="utf-8")
    (run_dir / "reports" / "methods.md").write_text("methods", encoding="utf-8")

    manifest = run_production_audit(root=root, output_dir=tmp_path / "audit")

    evidence = Path(manifest["validation_evidence_matrix"]).read_text(encoding="utf-8")
    row = next(line for line in evidence.splitlines() if line.startswith("slurm_vdj\t"))
    assert "\tpartial\t" in row
    assert "analysis_level=demo_result" in row


def test_production_audit_accepts_airway_tabular_public_validation_for_bulk_modules(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    run_dir = root / "validations" / "slurm_tabular_airway_public"
    (run_dir / "results" / "tables").mkdir(parents=True)
    (run_dir / "results" / "figures").mkdir(parents=True)
    (run_dir / "objects").mkdir(parents=True)
    (run_dir / "reports").mkdir(parents=True)
    for idx in range(20):
        (run_dir / "results" / "tables" / f"table_{idx}.tsv").write_text("a\n1\n", encoding="utf-8")
    for idx in range(12):
        (run_dir / "results" / "figures" / f"figure_{idx}.png").write_text("png", encoding="utf-8")
    for idx in range(4):
        (run_dir / "objects" / f"object_{idx}.json").write_text("object", encoding="utf-8")
    (run_dir / "reports" / "report.html").write_text("<html>report</html>", encoding="utf-8")
    (run_dir / "reports" / "methods.md").write_text("methods", encoding="utf-8")
    (run_dir / "run_manifest.json").write_text(
        json.dumps(
            {
                "status": "ready",
                "module": "tabular_public",
                "modules_validated": ["clinical_assoc", "publicdb", "wgcna", "single_gene"],
                "analysis_level": "validated_backend",
                "is_demo": False,
                "is_stub": False,
                "delivery_allowed": False,
                "validation_evidence_allowed": True,
                "non_delivery_reason": "validation_evidence_only_not_customer_delivery",
                "slurm_job_id": "12345",
            }
        ),
        encoding="utf-8",
    )

    manifest = run_production_audit(root=root, output_dir=tmp_path / "audit")

    evidence = Path(manifest["validation_evidence_matrix"]).read_text(encoding="utf-8")
    row = next(line for line in evidence.splitlines() if line.startswith("slurm_tabular_public\t"))
    assert "\tready\t" in row
    maturity = Path(manifest["module_maturity_table"]).read_text(encoding="utf-8")
    for module in ("clinical_assoc", "publicdb", "wgcna", "single_gene"):
        module_row = next(line for line in maturity.splitlines() if line.startswith(f"{module}\t"))
        assert "\t3_public_validated\t" in module_row
        assert "\tvalidated_backend\t" in module_row


def test_production_audit_accepts_arrmdata_methylation_public_validation(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    run_dir = root / "validations" / "slurm_methylation_arrmdata_public"
    (run_dir / "results" / "tables").mkdir(parents=True)
    (run_dir / "results" / "figures").mkdir(parents=True)
    (run_dir / "objects").mkdir(parents=True)
    (run_dir / "reports").mkdir(parents=True)
    for idx in range(8):
        (run_dir / "results" / "tables" / f"table_{idx}.tsv").write_text("a\n1\n", encoding="utf-8")
    for idx in range(4):
        (run_dir / "results" / "figures" / f"figure_{idx}.png").write_text("png", encoding="utf-8")
    (run_dir / "objects" / "methylation_mvp_object.rds").write_text("object", encoding="utf-8")
    (run_dir / "reports" / "report.html").write_text("<html>report</html>", encoding="utf-8")
    (run_dir / "reports" / "methods.md").write_text("methods", encoding="utf-8")
    (run_dir / "run_manifest.json").write_text(
        json.dumps(
            {
                "status": "ready",
                "module": "methylation",
                "dataset": "ARRmData",
                "analysis_level": "validated_backend",
                "is_demo": False,
                "is_stub": False,
                "delivery_allowed": False,
                "validation_evidence_allowed": True,
                "non_delivery_reason": "validation_evidence_only_not_customer_delivery",
                "slurm_job_id": "12345",
            }
        ),
        encoding="utf-8",
    )

    manifest = run_production_audit(root=root, output_dir=tmp_path / "audit")

    evidence = Path(manifest["validation_evidence_matrix"]).read_text(encoding="utf-8")
    row = next(line for line in evidence.splitlines() if line.startswith("slurm_methylation_public\t"))
    assert "\tready\t" in row
    maturity = Path(manifest["module_maturity_table"]).read_text(encoding="utf-8")
    module_row = next(line for line in maturity.splitlines() if line.startswith("methylation\t"))
    assert "\t3_public_validated\t" in module_row
    assert "\tvalidated_backend\t" in module_row


def test_production_audit_validation_index_detects_stale_underlying_manifest(tmp_path: Path) -> None:
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
    ready_manifest = {
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
    (run / "run_manifest.json").write_text(json.dumps(ready_manifest), encoding="utf-8")
    build_validation_index(root=root, output_dir=root / "reports" / "validation_index")
    ready_manifest.update(
        {
            "analysis_level": "demo_result",
            "is_demo": True,
            "validation_evidence_allowed": False,
            "non_delivery_reason": "generated_demo_data_not_customer_delivery",
        }
    )
    (run / "run_manifest.json").write_text(json.dumps(ready_manifest), encoding="utf-8")

    manifest = run_production_audit(root=root, output_dir=tmp_path / "audit")

    final = Path(manifest["final_acceptance_checklist"]).read_text(encoding="utf-8")
    row = next(line for line in final.splitlines() if line.startswith("validation_index_summary_ready\t"))
    assert "\tpartial\t" in row
    assert "stale_rows=scrna_public:analysis_level_changed" in row


def test_production_audit_final_acceptance_requires_prepared_job_delivery_mirror(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    job_dir = root / "jobs" / "JOB001"
    run_dir = job_dir / "runs" / "JOB001"
    run_dir.mkdir(parents=True)
    (job_dir / "job_manifest.json").write_text('{"job_id": "JOB001"}', encoding="utf-8")
    (run_dir / "run_manifest.json").write_text('{"status": "ready"}', encoding="utf-8")

    manifest = run_production_audit(root=root, output_dir=tmp_path / "audit")

    final = Path(manifest["final_acceptance_checklist"]).read_text(encoding="utf-8")
    row = next(line for line in final.splitlines() if line.startswith("prepared_job_delivery_mirror_ready\t"))
    assert "\tpartial\t" in row
    assert "checked_jobs=1" in row
    assert "latest_run_pointer" in row


def test_production_audit_requires_prepared_job_input_checksums_mirror(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    _write_scoped_prepared_job(root, "JOB001")
    (root / "jobs" / "JOB001" / "reproducible_code" / "input_checksums.tsv").unlink()

    manifest = run_production_audit(root=root, output_dir=tmp_path / "audit")

    final = Path(manifest["final_acceptance_checklist"]).read_text(encoding="utf-8")
    row = next(line for line in final.splitlines() if line.startswith("prepared_job_delivery_mirror_ready\t"))
    assert "\tpartial\t" in row
    assert "input_checksums" in row


def test_production_audit_final_acceptance_accepts_prepared_job_delivery_mirror(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    _write_scoped_prepared_job(root, "JOB001")
    _write_scoped_prepared_job(root, "JOB002")

    manifest = run_production_audit(root=root, output_dir=tmp_path / "audit")

    final = Path(manifest["final_acceptance_checklist"]).read_text(encoding="utf-8")
    row = next(line for line in final.splitlines() if line.startswith("prepared_job_delivery_mirror_ready\t"))
    assert "\tpass\t" in row
    assert "checked_jobs=2 ready_jobs=2 scoped_ready_jobs=2" in row


def test_production_audit_requires_module_report_job_mirrors_when_declared(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    job_dir = root / "jobs" / "JOB001"
    run_dir = job_dir / "runs" / "JOB001"
    (job_dir / "deliverables").mkdir(parents=True)
    (job_dir / "reproducible_code").mkdir(parents=True)
    (run_dir / "results" / "figures" / "rnaseq").mkdir(parents=True)
    (run_dir / "results" / "tables" / "rnaseq").mkdir(parents=True)
    (run_dir / "objects" / "rnaseq").mkdir(parents=True)
    (run_dir / "reports" / "rnaseq").mkdir(parents=True)
    (run_dir / "reports").mkdir(parents=True, exist_ok=True)
    (run_dir / "reproducible_code").mkdir(parents=True)
    figure_path = run_dir / "results" / "figures" / "rnaseq" / "pca.png"
    table_path = run_dir / "results" / "tables" / "rnaseq" / "sample_qc.tsv"
    object_path = run_dir / "objects" / "rnaseq" / "rnaseq_mvp_object.rds"
    report_path = run_dir / "reports" / "report.html"
    methods_path = run_dir / "reports" / "methods.md"
    module_report = run_dir / "reports" / "rnaseq" / "report.html"
    module_methods = run_dir / "reports" / "rnaseq" / "methods.md"
    module_manifest = run_dir / "reports" / "rnaseq" / "run_manifest.json"
    rerun_path = run_dir / "reproducible_code" / "rerun.sh"
    for path, text in {
        figure_path: "png",
        table_path: "sample_id\tqc\nS1\tok\n",
        object_path: "object",
        report_path: "<html>report</html>",
        methods_path: "methods",
        module_report: "<html>module report</html>",
        module_methods: "module methods",
        module_manifest: '{"module": "rnaseq"}',
        rerun_path: "#!/usr/bin/env bash\n",
        run_dir / "reproducible_code" / "repro_manifest.json": '{"run_dir": "test"}',
    }.items():
        path.write_text(text, encoding="utf-8")
    (job_dir / "job_manifest.json").write_text('{"job_id": "JOB001"}', encoding="utf-8")
    run_manifest = {
        "status": "ready",
        "modules": [
            {
                "module": "rnaseq",
                "status": "complete_python_bulk_backend",
                "analysis_level": "demo_result",
                "is_demo": True,
                "is_stub": False,
                "delivery_allowed": False,
                "validation_evidence_allowed": False,
                "non_delivery_reason": "demo_result_not_customer_delivery",
                "artifacts": {
                    "figures": {"pca": str(figure_path)},
                    "tables": {"sample_qc": str(table_path)},
                    "objects": {"mvp_object": str(object_path)},
                    "reports": {
                        "report_html": str(module_report),
                        "methods_md": str(module_methods),
                        "run_manifest": str(module_manifest),
                    },
                },
            }
        ],
        "production_approval": {},
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(run_manifest), encoding="utf-8")
    required = {
        job_dir / "deliverables" / "latest_run_manifest.json": json.dumps(run_manifest),
        job_dir / "deliverables" / "latest_report.html": report_path.read_text(encoding="utf-8"),
        job_dir / "deliverables" / "latest_methods.md": methods_path.read_text(encoding="utf-8"),
        job_dir
        / "deliverables"
        / "latest_delivery_index.tsv": "\n".join(
            [
                "category\tpath\tsize_bytes\tmodule\tartifact_key\tartifact_scope",
                f"figure\t{figure_path}\t{figure_path.stat().st_size}\trnaseq\tpca\tmodule",
                f"table\t{table_path}\t{table_path.stat().st_size}\trnaseq\tsample_qc\tmodule",
                f"object\t{object_path}\t{object_path.stat().st_size}\trnaseq\trnaseq_mvp_object\tmodule",
                f"report\t{report_path}\t{report_path.stat().st_size}\t\treport\trun",
                f"report\t{methods_path}\t{methods_path.stat().st_size}\t\tmethods\trun",
                f"module_report\t{module_report}\t{module_report.stat().st_size}\trnaseq\treport\tmodule",
                f"module_report\t{module_methods}\t{module_methods.stat().st_size}\trnaseq\tmethods\tmodule",
                f"module_report\t{module_manifest}\t{module_manifest.stat().st_size}\trnaseq\trun_manifest\tmodule",
                f"reproducible_code\t{rerun_path}\t{rerun_path.stat().st_size}\t\trerun\trun",
            ]
        )
        + "\n",
        job_dir / "reproducible_code" / "rerun.sh": rerun_path.read_text(encoding="utf-8"),
        job_dir / "reproducible_code" / "software_versions.tsv": "name\tversion\nultimate\ttest\n",
        job_dir / "reproducible_code" / "latest_repro_manifest.json": '{"run_dir": "test"}',
    }
    for path, text in required.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (job_dir / "deliverables" / "latest_run_pointer.json").write_text(
        json.dumps(
            {
                "latest_run_dir": str(run_dir),
                "run_manifest": str(run_dir / "run_manifest.json"),
                "copied_artifacts": {
                    "run_manifest": str(job_dir / "deliverables" / "latest_run_manifest.json"),
                    "report_html": str(job_dir / "deliverables" / "latest_report.html"),
                    "methods_md": str(job_dir / "deliverables" / "latest_methods.md"),
                    "delivery_index": str(job_dir / "deliverables" / "latest_delivery_index.tsv"),
                },
                "policy": "job-level files are small latest-run mirrors; large result objects remain referenced from the run directory",
            }
        ),
        encoding="utf-8",
    )

    manifest = run_production_audit(root=root, output_dir=tmp_path / "audit")

    final = Path(manifest["final_acceptance_checklist"]).read_text(encoding="utf-8")
    row = next(line for line in final.splitlines() if line.startswith("prepared_job_delivery_mirror_ready\t"))
    assert "\tpartial\t" in row
    assert "module_report_mirror_missing:rnaseq:report_html" in row


def test_production_audit_rejects_delivery_index_without_result_categories(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    job_dir = root / "jobs" / "JOB001"
    run_dir = job_dir / "runs" / "JOB001"
    (job_dir / "deliverables").mkdir(parents=True)
    (job_dir / "reproducible_code").mkdir(parents=True)
    (run_dir / "reports").mkdir(parents=True)
    (run_dir / "reproducible_code").mkdir(parents=True)
    (job_dir / "job_manifest.json").write_text('{"job_id": "JOB001"}', encoding="utf-8")
    run_manifest = {
        "status": "ready",
        "modules": [
            {
                "module": "rnaseq",
                "status": "complete_python_bulk_backend",
                "analysis_level": "demo_result",
                "is_demo": True,
                "is_stub": False,
                "delivery_allowed": False,
                "validation_evidence_allowed": False,
                "non_delivery_reason": "demo_result_not_customer_delivery",
            }
        ],
        "production_approval": {},
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(run_manifest), encoding="utf-8")
    report_path = run_dir / "reports" / "report.html"
    methods_path = run_dir / "reports" / "methods.md"
    rerun_path = run_dir / "reproducible_code" / "rerun.sh"
    for path, text in {
        report_path: "<html>report</html>",
        methods_path: "methods",
        rerun_path: "#!/usr/bin/env bash\n",
        run_dir / "reproducible_code" / "repro_manifest.json": '{"run_dir": "test"}',
    }.items():
        path.write_text(text, encoding="utf-8")
    required = {
        job_dir / "deliverables" / "latest_run_manifest.json": json.dumps(run_manifest),
        job_dir / "deliverables" / "latest_report.html": report_path.read_text(encoding="utf-8"),
        job_dir / "deliverables" / "latest_methods.md": methods_path.read_text(encoding="utf-8"),
        job_dir
        / "deliverables"
        / "latest_delivery_index.tsv": "\n".join(
            [
                "category\tpath\tsize_bytes",
                f"report\t{report_path}\t{report_path.stat().st_size}",
                f"report\t{methods_path}\t{methods_path.stat().st_size}",
                f"reproducible_code\t{rerun_path}\t{rerun_path.stat().st_size}",
            ]
        )
        + "\n",
        job_dir / "reproducible_code" / "rerun.sh": rerun_path.read_text(encoding="utf-8"),
        job_dir / "reproducible_code" / "software_versions.tsv": "name\tversion\nultimate\ttest\n",
        job_dir / "reproducible_code" / "latest_repro_manifest.json": '{"run_dir": "test"}',
    }
    for path, text in required.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (job_dir / "deliverables" / "latest_run_pointer.json").write_text(
        json.dumps(
            {
                "latest_run_dir": str(run_dir),
                "run_manifest": str(run_dir / "run_manifest.json"),
                "copied_artifacts": {
                    "run_manifest": str(job_dir / "deliverables" / "latest_run_manifest.json"),
                    "report_html": str(job_dir / "deliverables" / "latest_report.html"),
                    "methods_md": str(job_dir / "deliverables" / "latest_methods.md"),
                    "delivery_index": str(job_dir / "deliverables" / "latest_delivery_index.tsv"),
                },
                "policy": "job-level files are small latest-run mirrors; large result objects remain referenced from the run directory",
            }
        ),
        encoding="utf-8",
    )

    manifest = run_production_audit(root=root, output_dir=tmp_path / "audit")

    final = Path(manifest["final_acceptance_checklist"]).read_text(encoding="utf-8")
    row = next(line for line in final.splitlines() if line.startswith("prepared_job_delivery_mirror_ready\t"))
    assert "\tpartial\t" in row
    assert "delivery_index_missing_categories:figure,object,table" in row


def test_production_audit_final_acceptance_requires_validation_index_summary(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"

    manifest = run_production_audit(root=root, output_dir=tmp_path / "audit")

    final = Path(manifest["final_acceptance_checklist"]).read_text(encoding="utf-8")
    row = next(line for line in final.splitlines() if line.startswith("validation_index_summary_ready\t"))
    assert "\tpartial\t" in row
    assert "manifest_missing=" in row


def test_production_audit_final_acceptance_accepts_validation_index_summary(tmp_path: Path) -> None:
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
    build_validation_index(root=root, output_dir=root / "reports" / "validation_index")

    manifest = run_production_audit(root=root, output_dir=tmp_path / "audit")

    final = Path(manifest["final_acceptance_checklist"]).read_text(encoding="utf-8")
    row = next(line for line in final.splitlines() if line.startswith("validation_index_summary_ready\t"))
    assert "\tpass\t" in row
    assert "n_runs=1" in row
    assert "ready_validation_evidence=1" in row
