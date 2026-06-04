from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from ultimate.cli import main
from ultimate.constants import MODULE_ORDER
from ultimate.production_audit import run_production_audit


def test_production_audit_writes_readiness_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    (root / ".conda" / "envs" / "ultimate-core").mkdir(parents=True)
    manifest = run_production_audit(root=root, output_dir=tmp_path / "audit")
    assert Path(manifest["capability_matrix"]).exists()
    assert Path(manifest["organism_support"]).exists()
    assert Path(manifest["style_options"]).exists()
    assert Path(manifest["order_readiness_checklist"]).exists()
    assert Path(manifest["validation_evidence_matrix"]).exists()
    assert Path(manifest["final_acceptance_checklist"]).exists()
    assert Path(manifest["module_maturity_table"]).exists()
    assert Path(manifest["module_standardization_matrix"]).exists()
    assert Path(manifest["tool_coverage_by_module"]).exists()
    assert "final_acceptance_summary" in manifest
    assert manifest["module_standardization_summary"]["ready"] == len(MODULE_ORDER)
    assert Path(manifest["next_steps"]).exists()
    assert sum(manifest["summary"].values()) == len(MODULE_ORDER)


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
    for idx in range(6):
        (run_dir / "results" / "tables" / f"table_{idx}.tsv").write_text("a\n1\n", encoding="utf-8")
    for idx in range(3):
        (run_dir / "results" / "figures" / f"fig_{idx}.png").write_text("png", encoding="utf-8")
    (run_dir / "objects" / "perturb_seq_public_fixture_object.json").write_text("{}", encoding="utf-8")
    (run_dir / "reports" / "report.md").write_text("report", encoding="utf-8")
    (run_dir / "reports" / "report.html").write_text("report", encoding="utf-8")

    manifest = run_production_audit(root=root, output_dir=tmp_path / "audit")

    evidence = Path(manifest["validation_evidence_matrix"]).read_text(encoding="utf-8")
    assert "slurm_perturb_seq_adamson_public" in evidence
    perturb_evidence_row = next(line for line in evidence.splitlines() if line.startswith("slurm_perturb_seq\t"))
    assert "\tready\t" in perturb_evidence_row
    matrix = Path(manifest["capability_matrix"]).read_text(encoding="utf-8")
    perturb_row = next(line for line in matrix.splitlines() if line.startswith("perturb_seq\t"))
    assert "ready:public_or_existing_data_validation" in perturb_row
    assert "ready_basic" in perturb_row
