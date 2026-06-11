from __future__ import annotations

import csv
import json
from pathlib import Path

from click.testing import CliRunner

from ultimate.cli import main
from ultimate.completeness import run_module_order_readiness, run_tool_completeness
from ultimate.constants import MODULE_ORDER
from ultimate.tool_registry import TOOL_REGISTRY


def test_tool_completeness_covers_registry_without_missing_review(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    root.mkdir()
    manifest = run_tool_completeness(root=root, output_dir=tmp_path / "tool_completeness")

    assert manifest["tool_count"] == len(TOOL_REGISTRY)
    assert manifest["missing_review_count"] == 0
    rows = _read_tsv(Path(manifest["tool_completeness_matrix_tsv"]))
    names = {row["tool_name"] for row in rows}
    for expected in {
        "scanpy",
        "nf-core/scrnaseq",
        "CellChat",
        "Space Ranger",
        "WGCNA",
        "GEOquery",
        "TCGAbiolinks",
        "cellxgene",
    }:
        assert expected in names
    assert {row["missing_review"] for row in rows} == {"false"}


def test_module_order_readiness_has_all_modules_and_valid_tiers(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    root.mkdir()
    manifest = run_module_order_readiness(root=root, output_dir=tmp_path / "order_readiness")

    rows = _read_tsv(Path(manifest["module_order_readiness_matrix"]))
    assert {row["module"] for row in rows} == set(MODULE_ORDER)
    assert len(rows) == 22
    allowed = {
        "order_ready_customer_rehearsed",
        "validated_backend_only",
        "handoff_required",
        "licensed_required",
        "needs_algorithm_backend",
        "needs_raw_upstream",
    }
    assert {row["readiness_tier"] for row in rows} <= allowed


def test_order_readiness_does_not_treat_validated_only_as_customer_delivery(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    run = root / "validations" / "scrna_public"
    (run / "reports").mkdir(parents=True)
    (run / "reports" / "report.html").write_text("<html></html>", encoding="utf-8")
    (run / "reports" / "methods.md").write_text("methods", encoding="utf-8")
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
                "figures": [],
                "tables": [],
                "objects": {},
            }
        ),
        encoding="utf-8",
    )

    manifest = run_module_order_readiness(root=root, output_dir=tmp_path / "order_readiness")
    rows = {row["module"]: row for row in _read_tsv(Path(manifest["module_order_readiness_matrix"]))}

    assert rows["scrna"]["readiness_tier"] != "order_ready_customer_rehearsed"


def test_order_readiness_counts_ready_internal_rehearsal_as_order_ready(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    run = root / "jobs" / "v4_1_vdj_standard_internal_rehearsal" / "runs" / "v4_1_vdj_standard_internal_rehearsal"
    (run / "reports").mkdir(parents=True)
    (run / "logs").mkdir(parents=True)
    (run / "results" / "figures").mkdir(parents=True)
    (run / "results" / "tables").mkdir(parents=True)
    (run / "objects").mkdir(parents=True)
    (run / "reports" / "report.html").write_text("<html></html>", encoding="utf-8")
    (run / "reports" / "methods.md").write_text("methods", encoding="utf-8")
    (run / "results" / "figures" / "clone.png").write_text("png", encoding="utf-8")
    (run / "results" / "tables" / "clones.tsv").write_text("a\n1\n", encoding="utf-8")
    (run / "objects" / "vdj.h5ad").write_text("object", encoding="utf-8")
    (run / "logs" / "vdj.log").write_text("ok", encoding="utf-8")
    (run / "run_manifest.json").write_text(
        json.dumps(
            {
                "module": "vdj",
                "status": "ready",
                "analysis_level": "production_backend",
                "is_demo": False,
                "is_stub": False,
                "delivery_allowed": True,
                "validation_evidence_allowed": True,
                "non_delivery_reason": "",
                "delivery_scope": "internal_rehearsal",
                "slurm_job_id": "888",
                "production_approval": {
                    "approved": True,
                    "approved_by": "pytest",
                    "approved_at": "2026-06-11T00:00:00Z",
                    "project_id": "v4_1_vdj_standard_internal_rehearsal",
                    "input_path": str(run / "config" / "project.yaml"),
                    "output_dir": str(run),
                    "delivery_scope": "internal_rehearsal",
                    "reason": "pytest internal rehearsal",
                },
                "delivery_gate": {"status": "ready", "delivery_allowed": True, "approval_status": "approved", "delivery_scope": "internal_rehearsal", "blockers": []},
                "figures": ["results/figures/clone.png"],
                "tables": ["results/tables/clones.tsv"],
                "objects": {"h5ad": "objects/vdj.h5ad"},
            }
        ),
        encoding="utf-8",
    )

    manifest = run_module_order_readiness(root=root, output_dir=tmp_path / "order_readiness")
    rows = {row["module"]: row for row in _read_tsv(Path(manifest["module_order_readiness_matrix"]))}

    assert rows["vdj"]["readiness_tier"] == "order_ready_customer_rehearsed"


def test_cli_tool_completeness_and_order_readiness(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    root.mkdir()
    runner = CliRunner()

    tool_result = runner.invoke(main, ["tool-completeness", "--root", str(root), "--output-dir", str(tmp_path / "tools")])
    order_result = runner.invoke(main, ["order-readiness", "--root", str(root), "--output-dir", str(tmp_path / "order")])

    assert tool_result.exit_code == 0, tool_result.output
    assert order_result.exit_code == 0, order_result.output
    assert "tool_completeness_matrix_tsv" in tool_result.output
    assert "module_order_readiness_matrix" in order_result.output


def _read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))
