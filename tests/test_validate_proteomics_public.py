from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

from ultimate.production_audit import run_production_audit


TOOLS_DIR = Path(__file__).resolve().parents[1] / "01_tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))


def _write_protein_groups(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "Protein IDs\tMajority protein IDs\tProtein names\tGene names\tOnly identified by site\tReverse\tPotential contaminant\tLFQ intensity H1\tLFQ intensity H2\tLFQ intensity L1\tLFQ intensity L2\tLFQ intensity N1\tLFQ intensity N2",
                "P001\tP001\tProtein A\tGENEA\t\t\t\t100000\t120000\t30000\t28000\t50000\t52000",
                "P002\tP002\tProtein B\tGENEB\t\t\t\t20000\t18000\t70000\t76000\t30000\t31000",
                "P003\tP003\tProtein C\tGENEC\t\t\t\t40000\t39000\t42000\t41000\t41000\t40500",
                "P004\tP004\tProtein D\tGENED\t\t+\t\t90000\t88000\t10000\t12000\t25000\t24000",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_design(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "label\tcondition\treplicate",
                "H1\tCD34High\t1",
                "H2\tCD34High\t2",
                "L1\tCD34Low\t1",
                "L2\tCD34Low\t2",
                "N1\tCD34Neg\t1",
                "N2\tCD34Neg\t2",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_validate_proteomics_public_prepares_maxquant_lfq_backend_outputs(tmp_path: Path) -> None:
    from validate_proteomics_public import run_validation

    protein_groups = tmp_path / "proteinGroups.txt"
    design = tmp_path / "design.txt"
    _write_protein_groups(protein_groups)
    _write_design(design)

    manifest = run_validation(
        output_dir=tmp_path / "out",
        public_data_dir=tmp_path / "public",
        protein_groups=protein_groups,
        design_table=design,
        protein_groups_url="file://proteinGroups.txt",
        design_url="file://design.txt",
        max_features=10,
    )

    run_dir = Path(manifest["output_dir"])
    assert manifest["module"] == "proteomics"
    assert manifest["status"] == "ready"
    assert manifest["analysis_level"] == "validated_backend"
    assert manifest["delivery_allowed"] is False
    assert manifest["validation_evidence_allowed"] is True
    assert manifest["backend_id"] == "proteomics.default.abundance_python_mvp"
    assert manifest["backend_status"] == "fully_automatic_validated_entrypoint"
    assert manifest["n_samples"] == 6
    assert manifest["n_features"] == 3
    for key in ("abundance_qc", "missingness_summary", "differential_proteins", "enrichment_handoff", "ppi_export"):
        path = run_dir / "results" / "tables" / "proteomics" / f"{key}.tsv"
        assert path.exists() and path.stat().st_size > 0
    diff = pd.read_csv(run_dir / "results" / "tables" / "proteomics" / "differential_proteins.tsv", sep="\t")
    assert "backend_note" in diff.columns
    methods = (run_dir / "reports" / "proteomics" / "methods.md").read_text(encoding="utf-8")
    assert "analysis_level" in methods
    assert "蛋白" in methods or "proteomics" in methods.lower()


def test_production_audit_accepts_proteomics_public_validation(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    run_dir = root / "validations" / "slurm_proteomics_lfq_analyst_public"
    (run_dir / "results" / "tables").mkdir(parents=True)
    (run_dir / "results" / "figures").mkdir(parents=True)
    (run_dir / "objects").mkdir(parents=True)
    (run_dir / "reports").mkdir(parents=True)
    for idx in range(8):
        (run_dir / "results" / "tables" / f"table_{idx}.tsv").write_text("a\n1\n", encoding="utf-8")
    for idx in range(4):
        (run_dir / "results" / "figures" / f"figure_{idx}.png").write_text("png", encoding="utf-8")
    (run_dir / "objects" / "proteomics_mvp_object.rds").write_text("object", encoding="utf-8")
    (run_dir / "reports" / "report.html").write_text("<html>report</html>", encoding="utf-8")
    (run_dir / "reports" / "methods.md").write_text("methods", encoding="utf-8")
    (run_dir / "run_manifest.json").write_text(
        json.dumps(
            {
                "status": "ready",
                "module": "proteomics",
                "dataset": "LFQ-Analyst",
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
    row = next(line for line in evidence.splitlines() if line.startswith("slurm_proteomics_public\t"))
    assert "\tready\t" in row
    maturity = Path(manifest["module_maturity_table"]).read_text(encoding="utf-8")
    module_row = next(line for line in maturity.splitlines() if line.startswith("proteomics\t"))
    assert "\t3_public_validated\t" in module_row
    assert "\tvalidated_backend\t" in module_row
