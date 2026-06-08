from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import tomllib

from ultimate.template_resources import find_template_dir, template_lookup_status


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_pytest_default_entrypoint_adds_src_pythonpath() -> None:
    pyproject = tomllib.loads((_root() / "pyproject.toml").read_text(encoding="utf-8"))
    pytest_options = pyproject["tool"]["pytest"]["ini_options"]

    assert pytest_options["testpaths"] == ["tests"]
    assert pytest_options["pythonpath"] == ["src"]


def test_setup_py_delegates_to_pyproject_metadata() -> None:
    setup_text = (_root() / "setup.py").read_text(encoding="utf-8")

    assert "setup()" in setup_text
    assert "install_requires" not in setup_text
    assert "package_data" not in setup_text
    assert "extras_require" not in setup_text


def test_data_files_cover_all_external_template_dirs() -> None:
    root = _root()
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    data_files = pyproject["tool"]["setuptools"]["data-files"]

    assert data_files["share/ultimate/templates/intake"] == ["templates/intake/*"]
    assert data_files["share/ultimate/templates/samples"] == ["templates/samples/*"]
    for handoff_dir in sorted((root / "templates" / "handoffs").iterdir()):
        if handoff_dir.is_dir():
            key = f"share/ultimate/templates/handoffs/{handoff_dir.name}"
            assert data_files[key] == [f"templates/handoffs/{handoff_dir.name}/*"]


def test_template_resource_lookup_finds_source_templates() -> None:
    intake = find_template_dir("intake", required=True)
    samples = find_template_dir("samples", required=True)
    handoff = find_template_dir("handoffs", "nfcore_scrnaseq", required=True)

    assert (intake / "customer_project_intake.tsv").exists()
    assert (samples / "scrna_10x.tsv").exists()
    assert (handoff / "README.md").exists()
    assert template_lookup_status("intake")["status"] == "ready"


def test_plain_pytest_collect_works_without_manual_pythonpath() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "tests/test_analysis_levels.py"],
        cwd=_root(),
        text=True,
        capture_output=True,
        timeout=60,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "test_demo_path_defaults_to_non_delivery_demo_result" in completed.stdout
