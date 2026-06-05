from __future__ import annotations

import json
import os
from pathlib import Path

import yaml

from ultimate.backend_registry import build_backend_plan
from ultimate.pipeline import run_pipeline_from_config
from ultimate.rnaseq_de_backend import rnaseq_de_backend_requested


def _write_counts_and_samples(tmp_path: Path) -> tuple[Path, Path]:
    counts = tmp_path / "inputs" / "counts.tsv"
    samples = tmp_path / "inputs" / "samples.tsv"
    counts.parent.mkdir(parents=True, exist_ok=True)
    counts.write_text(
        "\n".join(
            [
                "feature_id\tCTRL_1\tCTRL_2\tTRT_1\tTRT_2",
                "GENE_A\t40\t42\t120\t118",
                "GENE_B\t85\t81\t80\t76",
                "GENE_C\t10\t12\t31\t29",
                "GENE_D\t58\t60\t55\t56",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    samples.write_text(
        "\n".join(
            [
                "sample_id\tcondition\tbatch",
                "CTRL_1\tcontrol\tb1",
                "CTRL_2\tcontrol\tb1",
                "TRT_1\ttreated\tb2",
                "TRT_2\ttreated\tb2",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return counts, samples


def _write_config(tmp_path: Path, *, rscript: Path | None = None, request_form: str = "value") -> Path:
    counts, samples = _write_counts_and_samples(tmp_path)
    backends = {"de": "deseq2_edger"} if request_form == "value" else {"rnaseq.de.deseq2_edger": True}
    rnaseq_cfg = {
        "enabled": True,
        "analysis_level": "smoke_backend",
        "is_demo": False,
        "preset": "publication",
        "input_matrix": str(counts),
        "samplesheet": str(samples),
        "backends": backends,
        "de_backend": {"enabled": True},
    }
    if rscript is not None:
        rnaseq_cfg["de_backend"]["rscript"] = str(rscript)
    config = {
        "project": {
            "name": "pytest_rnaseq_de",
            "organism": "human",
            "output_dir": str(tmp_path / "run"),
            "run_mode": "interactive",
            "is_demo": False,
        },
        "samples": {"samplesheet": str(samples)},
        "design": {"condition_column": "condition", "control": "control", "case": "treated"},
        "modules": {"rnaseq": rnaseq_cfg},
    }
    path = tmp_path / "config" / "project.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


def _write_fake_rscript(tmp_path: Path) -> Path:
    path = tmp_path / "fake_Rscript.py"
    path.write_text(
        """#!/usr/bin/env python3
import json
import sys
from pathlib import Path

if len(sys.argv) > 1 and sys.argv[1] == "-e":
    print("DESeq2\\t1.50.2")
    print("edgeR\\t4.8.2")
    print("jsonlite\\t2.0.0")
    raise SystemExit(0)

args = sys.argv[2:]
opts = {}
i = 0
while i < len(args):
    key = args[i].lstrip("-")
    opts[key] = args[i + 1]
    i += 2
tables = Path(opts["tables-dir"])
figures = Path(opts["figures-dir"])
objects = Path(opts["objects-dir"])
for directory in (tables, figures, objects):
    directory.mkdir(parents=True, exist_ok=True)
(tables / "de_results.tsv").write_text("feature_id\\tlog2FoldChange\\tpvalue\\tpadj\\tbackend_id\\tbackend_method\\tanalysis_level\\tinterpretation_warning\\nGENE_A\\t2.1\\t0.001\\t0.01\\trnaseq.de.deseq2_edger\\tDESeq2\\tsmoke_backend\\tstatistical_only\\n")
(tables / "deseq2_edgeR_de_results.tsv").write_text((tables / "de_results.tsv").read_text())
(tables / "de_backend_status.tsv").write_text("backend_id\\tstatus\\tanalysis_level\\tbackend_method\\tcomparison\\tn_features_tested\\tn_samples\\tcontrol_replicates\\tcase_replicates\\tinterpretation_warning\\nrnaseq.de.deseq2_edger\\tready\\tsmoke_backend\\tDESeq2\\ttreated_vs_control\\t1\\t4\\t2\\t2\\tstatistical_only\\n")
(tables / "de_backend_versions.tsv").write_text("package\\tversion\\nDESeq2\\t1.50.2\\nedgeR\\t4.8.2\\njsonlite\\t2.0.0\\n")
manifest = {
    "backend_id": "rnaseq.de.deseq2_edger",
    "status": "ready",
    "analysis_level": "smoke_backend",
    "backend_method": "DESeq2",
    "skip_reason": "",
}
(tables / "de_backend_manifest.json").write_text(json.dumps(manifest))
(figures / "deseq2_edgeR_volcano.png").write_text("png")
(figures / "deseq2_edgeR_top_gene_heatmap.png").write_text("png")
(objects / "rnaseq_de_backend.rds").write_text("rds")
""",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | 0o111)
    return path


def test_rnaseq_de_backend_request_detection() -> None:
    assert rnaseq_de_backend_requested({"backends": {"de": "deseq2_edger"}})
    assert rnaseq_de_backend_requested({"backends": {"de": "rnaseq.de.deseq2_edger"}})
    assert rnaseq_de_backend_requested({"backends": {"rnaseq.de.deseq2_edger": True}})
    assert rnaseq_de_backend_requested({"de_backend": {"enabled": True}})

    plan = build_backend_plan("rnaseq", {"modules": {"rnaseq": {"backends": {"rnaseq.de.deseq2_edger": True}}}})
    active = {row["backend_id"] for row in plan["active_backends"]}
    assert "rnaseq.de.deseq2_edger" in active


def test_rnaseq_de_backend_skip_outputs_are_declared(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, rscript=tmp_path / "missing_Rscript")
    manifest = run_pipeline_from_config(config_path)
    module = manifest["modules"][0]
    tables = module["artifacts"]["tables"]

    assert module["analysis_level"] == "smoke_backend"
    assert module["delivery_allowed"] is False
    assert module["rnaseq_de_backend"]["status"] == "skipped"
    assert module["status"].startswith("partial:rnaseq_de_backend")
    for key in ("de_results", "deseq2_edgeR_de_results", "de_backend_status", "de_backend_versions", "manifest", "backend_execution"):
        assert Path(tables[key]).exists(), key
    backend_manifest = json.loads(Path(tables["manifest"]).read_text(encoding="utf-8"))
    assert backend_manifest["backend_id"] == "rnaseq.de.deseq2_edger"
    assert backend_manifest["status"] == "skipped"
    assert backend_manifest["skip_reason"].startswith("dependency_missing:Rscript")


def test_rnaseq_de_backend_ready_path_with_fake_rscript_keeps_mvp_contract(tmp_path: Path) -> None:
    fake_rscript = _write_fake_rscript(tmp_path)
    config_path = _write_config(tmp_path, rscript=fake_rscript)
    manifest = run_pipeline_from_config(config_path)
    module = manifest["modules"][0]
    tables = module["artifacts"]["tables"]
    figures = module["artifacts"]["figures"]
    objects = module["artifacts"]["objects"]

    assert module["status"] == "complete_python_bulk_backend"
    assert module["rnaseq_de_backend"]["status"] == "ready"
    assert any(row["backend_id"] == "rnaseq.de.deseq2_edger" for row in module["backend_plan"]["active_backends"])
    for key in ("counts_raw", "counts_normalized", "sample_qc", "design_check", "de_design_ready", "enrichment_handoff"):
        assert Path(tables[key]).exists(), key
    for key in ("de_results", "deseq2_edgeR_de_results", "de_backend_status", "de_backend_versions", "manifest", "backend_execution"):
        assert Path(tables[key]).exists(), key
    for key in ("pca", "sample_correlation_heatmap", "volcano", "top_gene_heatmap", "de_backend_volcano", "de_backend_top_gene_heatmap"):
        assert Path(figures[key]).exists(), key
    assert Path(objects["mvp_object"]).name == "rnaseq_mvp_object.rds"
    assert Path(objects["rnaseq_de_backend_rds"]).exists()

    status_text = Path(tables["de_backend_status"]).read_text(encoding="utf-8")
    assert "ready" in status_text
    assert "DESeq2" in status_text
