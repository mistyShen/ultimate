from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from ultimate.backend_registry import (
    BACKEND_REGISTRY,
    BACKEND_ROLES,
    backend_maturity_rows,
    build_backend_plan,
    modules_without_backend,
    run_audit_backends,
)
from ultimate.cli import main
from ultimate.constants import MODULE_ORDER


def test_backend_registry_covers_all_modules_and_uses_valid_roles() -> None:
    assert not modules_without_backend()
    modules = {backend.module for backend in BACKEND_REGISTRY}
    assert set(MODULE_ORDER).issubset(modules)
    assert {backend.backend_role for backend in BACKEND_REGISTRY}.issubset(set(BACKEND_ROLES))
    assert any(backend.backend_id == "scrna.mvp.validate_scrna" for backend in BACKEND_REGISTRY)
    assert any(backend.backend_id == "rnaseq.de.deseq2_edger" for backend in BACKEND_REGISTRY)
    assert any(backend.backend_status == "licensed_path_detection" for backend in BACKEND_REGISTRY)


def test_backend_plan_records_requested_and_skipped_backends() -> None:
    config = {
        "modules": {
            "scrna": {
                "preset": "tumor",
                "backends": {
                    "annotation": "celltypist",
                    "communication": "liana",
                    "unknown": "not_a_backend",
                },
            }
        }
    }

    plan = build_backend_plan("scrna", config)

    assert plan["selected_backend_id"] == "scrna.mvp.validate_scrna"
    active_ids = {row["backend_id"] for row in plan["active_backends"]}
    assert "scrna.annotation.celltypist" in active_ids
    assert "scrna.communication.liana" in active_ids
    assert plan["unknown_requested_backends"] == {"unknown": "not_a_backend"}
    assert not any("backend_not_fully_automatic:scrna.communication.liana" in warning for warning in plan["interpretation_warnings"])
    assert any("候选互作" in warning for warning in plan["interpretation_warnings"])


def test_v3_tabular_public_backends_are_evidence_gated_entrypoints() -> None:
    by_id = {backend.backend_id: backend for backend in BACKEND_REGISTRY}
    expected = {
        "rnaseq.matrix.python_mvp": "slurm/bulk_validation_suite.sbatch",
        "publicdb.cached_tables.python_mvp": "slurm/bulk_validation_suite.sbatch",
        "clinical_assoc.default.sample_level_stats": "slurm/bulk_validation_suite.sbatch",
        "wgcna.default.ready_matrix": "slurm/bulk_validation_suite.sbatch",
        "single_gene.default.gene_report_mvp": "slurm/bulk_validation_suite.sbatch",
        "methylation.default.beta_matrix_python_mvp": "slurm/bulk_validation_suite.sbatch",
        "proteomics.default.abundance_python_mvp": "slurm/proteomics_backend_validation.sbatch",
        "scrna.qc.scrublet": "slurm/scrna_mvp_validation.sbatch",
        "scrna.annotation.celltypist": "slurm/scrna_mvp_validation.sbatch",
        "scrna.functional.decoupler_gseapy": "slurm/scrna_mvp_validation.sbatch",
        "scrna.communication.liana": "slurm/scrna_mvp_validation.sbatch",
        "functional_state.default.signature_scoring": "slurm/bulk_validation_suite.sbatch",
    }

    for backend_id, slurm_profile in expected.items():
        backend = by_id[backend_id]
        assert backend.backend_status == "fully_automatic_validated_entrypoint"
        assert backend.slurm_profile == slurm_profile
        assert backend.production_allowed is True


def test_backend_audit_cli_writes_registry_and_maturity_tables(tmp_path: Path) -> None:
    manifest = run_audit_backends(root=tmp_path / "ultimate", output_dir=tmp_path / "audit")

    assert Path(manifest["backend_registry"]).exists()
    assert Path(manifest["backend_registry_json"]).exists()
    assert Path(manifest["backend_maturity_table"]).exists()
    assert manifest["backend_count"] == len(BACKEND_REGISTRY)
    maturity_rows = backend_maturity_rows(tmp_path / "ultimate")
    assert len(maturity_rows) == len(BACKEND_REGISTRY)

    runner = CliRunner()
    result = runner.invoke(main, ["audit-backends", "--root", str(tmp_path / "ultimate"), "--output-dir", str(tmp_path / "cli_audit")])
    assert result.exit_code == 0
    cli_manifest = json.loads(result.output)
    assert Path(cli_manifest["backend_registry"]).exists()
