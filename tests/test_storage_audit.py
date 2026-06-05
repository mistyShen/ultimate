from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


TOOLS_DIR = Path(__file__).parents[1] / "01_tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from storage_audit import run_storage_audit


def test_storage_audit_writes_outputs_and_categories(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    _write(root / ".conda" / "envs" / "core" / "python", "env")
    _write(root / "public_data" / "manifest.tsv", "public")
    _write(root / "validation_runs" / "run1" / "run_manifest.json", "{}")
    _write(root / "references" / "human" / "README.txt", "ref")
    _write(root / "raw_links" / "customer_a.txt", "/data/customer_a")

    manifest = run_storage_audit(root=root, output_dir=tmp_path / "audit", budget_gb=1)

    audit_path = Path(manifest["storage_audit"])
    summary_path = Path(manifest["storage_audit_summary"])
    cleanup_path = Path(manifest["cleanup_plan"])
    assert audit_path.exists()
    assert summary_path.exists()
    assert cleanup_path.exists()

    rows = _read_tsv(audit_path)
    categories = {row["category"] for row in rows}
    assert {"environments", "public_data", "validation_runs", "references", "raw_links"} <= categories
    assert all("cleanup_action" in row for row in rows)

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["root"] == str(root.resolve())
    assert summary["budget_gb"] == 1
    assert summary["under_budget"] is True
    assert summary["category_totals"]["environments"]["bytes"] > 0
    assert summary["cleanup_candidate_total_bytes"] == 0
    assert _read_tsv(cleanup_path) == []


def test_storage_audit_over_budget_writes_cleanup_candidates(tmp_path: Path) -> None:
    root = tmp_path / "ultimate"
    _write(root / "jobs" / "job1" / "work.bin", "job-output")
    _write(root / ".apptainer" / "cache" / "image.sif", "container")
    _write(root / "references" / "hg38" / "genome.fa", "protected-reference")
    _write(root / "raw_links" / "raw.txt", "protected-raw")

    manifest = run_storage_audit(root=root, output_dir=tmp_path / "audit", budget_gb=0)
    summary = manifest["summary"]
    assert summary["under_budget"] is False
    assert summary["cleanup_candidate_total_bytes"] > 0

    cleanup_rows = _read_tsv(Path(manifest["cleanup_plan"]))
    cleanup_categories = {row["category"] for row in cleanup_rows}
    assert {"jobs", "containers/cache"} <= cleanup_categories
    assert "references" not in cleanup_categories
    assert "raw_links" not in cleanup_categories


def test_storage_audit_cli(tmp_path: Path, capsys) -> None:
    root = tmp_path / "ultimate"
    _write(root / "logs" / "run.log", "log")
    output_dir = tmp_path / "audit"

    from storage_audit import main

    old_argv = sys.argv
    sys.argv = ["storage_audit.py", "--root", str(root), "--output-dir", str(output_dir), "--budget-gb", "1"]
    try:
        main()
    finally:
        sys.argv = old_argv

    captured = capsys.readouterr()
    assert "storage_audit_summary" in captured.out
    assert (output_dir / "storage_audit.tsv").exists()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))
