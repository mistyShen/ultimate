from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CHECKSUM_MAX_BYTES = 256 * 1024 * 1024
INPUT_PATH_KEYS = (
    "samplesheet",
    "input_matrix",
    "input_path",
    "clinical_table",
    "signature_matrix",
    "validated_run_dir",
    "validation_run_dir",
    "fastq_1",
    "fastq_2",
    "fragments",
    "peak_matrix",
    "matrix_path",
    "idat_dir",
    "visium_dir",
)


def export_reproducible_package(run_dir: Path, *, checksum_max_bytes: int = DEFAULT_CHECKSUM_MAX_BYTES) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    manifest_path = run_dir / "run_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing run manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    package_dir = run_dir / "reproducible_code"
    deliverables_dir = run_dir / "deliverables"
    package_dir.mkdir(parents=True, exist_ok=True)
    deliverables_dir.mkdir(parents=True, exist_ok=True)

    config_snapshot = _copy_if_exists(run_dir / "config_snapshot.yaml", package_dir / "config_snapshot.yaml")
    analysis_request = _copy_analysis_request(manifest, package_dir)
    samplesheet = _copy_samplesheet(manifest, package_dir)
    software_versions = _write_software_versions(package_dir / "software_versions.tsv")
    input_checksums = _write_input_checksums(manifest, package_dir / "input_checksums.tsv", checksum_max_bytes=checksum_max_bytes)
    rerun_script = _write_rerun_script(package_dir / "rerun.sh", run_dir=run_dir, config_path=config_snapshot or (run_dir / "config_snapshot.yaml"))
    readme = _write_repro_readme(
        package_dir / "README.md",
        run_dir=run_dir,
        manifest=manifest,
        rerun_script=rerun_script,
        config_snapshot=config_snapshot,
        analysis_request=analysis_request,
        samplesheet=samplesheet,
    )
    delivery_index = _write_delivery_index(run_dir / "delivery_index.tsv", run_dir)
    _copy_report_deliverables(run_dir, deliverables_dir)

    repro_manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_dir": str(run_dir),
        "package_dir": str(package_dir),
        "deliverables_dir": str(deliverables_dir),
        "readme": str(readme),
        "rerun_script": str(rerun_script),
        "config_snapshot": str(config_snapshot) if config_snapshot else "",
        "analysis_request": str(analysis_request) if analysis_request else "",
        "samplesheet_snapshot": str(samplesheet) if samplesheet else "",
        "software_versions": str(software_versions),
        "input_checksums": str(input_checksums),
        "delivery_index": str(delivery_index),
        "checksum_max_bytes": checksum_max_bytes,
    }
    repro_manifest_path = package_dir / "repro_manifest.json"
    repro_manifest["manifest_path"] = str(repro_manifest_path)
    repro_manifest_path.write_text(json.dumps(repro_manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return repro_manifest


def _copy_if_exists(source: Path, target: Path) -> Path | None:
    if not source.exists():
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target


def _copy_analysis_request(manifest: dict[str, Any], package_dir: Path) -> Path | None:
    request = manifest.get("analysis_request") or {}
    source = request.get("source") if isinstance(request, dict) else None
    if source and Path(str(source)).exists():
        return _copy_if_exists(Path(str(source)), package_dir / Path(str(source)).name)
    if request:
        target = package_dir / "analysis_request.yaml"
        target.write_text(yaml.safe_dump(request, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return target
    return None


def _copy_samplesheet(manifest: dict[str, Any], package_dir: Path) -> Path | None:
    samples = ((manifest.get("preflight") or {}).get("samples") or {})
    project = manifest.get("project") or {}
    config_path = Path(str(manifest.get("config_snapshot") or ""))
    candidates = []
    if config_path.exists():
        try:
            config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            config = {}
        sample_value = ((config.get("samples") or {}).get("samplesheet") if isinstance(config.get("samples"), dict) else None)
        if sample_value:
            candidates.append(Path(str(sample_value)))
    sample_path = samples.get("samplesheet") or project.get("samplesheet")
    if sample_path:
        candidates.append(Path(str(sample_path)))
    for candidate in candidates:
        if candidate.exists():
            return _copy_if_exists(candidate, package_dir / "samplesheet.tsv")
    return None


def _write_software_versions(path: Path) -> Path:
    rows = []
    for name in ("click", "PyYAML", "pandas", "numpy", "matplotlib", "seaborn", "jinja2", "scanpy", "anndata"):
        rows.append({"kind": "python_package", "name": name, "version": _package_version(name), "source": sys.executable})
    for command in ("python", "Rscript", "snakemake", "mamba", "conda", "nextflow", "multiqc", "quarto"):
        rows.append({"kind": "command", "name": command, "version": _command_version(command), "source": shutil.which(command) or ""})
    rows.append({"kind": "platform", "name": "python_executable", "version": sys.executable, "source": platform.platform()})
    _write_tsv(path, rows, ("kind", "name", "version", "source"))
    return path


def _package_version(name: str) -> str:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "not_installed"


def _command_version(command: str) -> str:
    exe = shutil.which(command)
    if not exe:
        return "not_found"
    for args in ((command, "--version"), (command, "-version"), (command, "-V")):
        try:
            completed = subprocess.run(args, check=False, text=True, capture_output=True, timeout=15)
        except Exception:
            continue
        text = (completed.stdout or completed.stderr).strip().splitlines()
        if text:
            return text[0][:240]
    return "available"


def _write_input_checksums(manifest: dict[str, Any], path: Path, *, checksum_max_bytes: int) -> Path:
    config = _load_config_snapshot(manifest)
    candidates = _collect_input_paths(config)
    rows = []
    seen: set[str] = set()
    for key, value in candidates:
        item = Path(str(value))
        marker = f"{key}:{item}"
        if marker in seen:
            continue
        seen.add(marker)
        rows.append(_checksum_row(key, item, checksum_max_bytes=checksum_max_bytes))
    _write_tsv(path, rows, ("key", "path", "exists", "kind", "size_bytes", "sha256", "checksum_status"))
    return path


def _load_config_snapshot(manifest: dict[str, Any]) -> dict[str, Any]:
    config_path = Path(str(manifest.get("config_snapshot") or ""))
    if not config_path.exists():
        config_path = Path(str(manifest.get("output_dir") or "")) / "config_snapshot.yaml"
    if not config_path.exists():
        return {}
    try:
        return yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}


def _collect_input_paths(config: dict[str, Any]) -> list[tuple[str, Any]]:
    rows: list[tuple[str, Any]] = []
    samples = config.get("samples")
    if isinstance(samples, dict) and samples.get("samplesheet"):
        rows.append(("samples.samplesheet", samples["samplesheet"]))
    request = config.get("analysis_request")
    if isinstance(request, str):
        rows.append(("analysis_request", request))
    for module_name, module_cfg in (config.get("modules") or {}).items():
        if not isinstance(module_cfg, dict):
            continue
        for key in INPUT_PATH_KEYS:
            if module_cfg.get(key):
                rows.append((f"modules.{module_name}.{key}", module_cfg[key]))
        raw_cfg = module_cfg.get("raw")
        if isinstance(raw_cfg, dict):
            for key in INPUT_PATH_KEYS:
                if raw_cfg.get(key):
                    rows.append((f"modules.{module_name}.raw.{key}", raw_cfg[key]))
    return rows


def _checksum_row(key: str, path: Path, *, checksum_max_bytes: int) -> dict[str, Any]:
    exists = path.exists()
    kind = "dir" if path.is_dir() else "file" if path.is_file() else ""
    size = path.stat().st_size if exists and path.is_file() else ""
    sha = ""
    status = "missing"
    if exists and path.is_dir():
        status = "directory_not_hashed"
    elif exists and path.is_file():
        if int(size) > checksum_max_bytes:
            status = "skipped_large_file"
        else:
            sha = _sha256(path)
            status = "hashed"
    return {"key": key, "path": str(path), "exists": exists, "kind": kind, "size_bytes": size, "sha256": sha, "checksum_status": status}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_rerun_script(path: Path, *, run_dir: Path, config_path: Path | None) -> Path:
    config_value = str(config_path or (run_dir / "config_snapshot.yaml"))
    code_root = Path(__file__).resolve().parents[2]
    content = f"""#!/usr/bin/env bash
set -euo pipefail

RUN_DIR="{run_dir}"
CONFIG_PATH="{config_value}"
PROJECT_ROOT="${{ULTIMATE_ROOT:-{code_root}}}"
ENV_PREFIX="${{ULTIMATE_ENV:-$PROJECT_ROOT/.conda/envs/ultimate-core}}"
CONDA_SH="${{CONDA_SH:-/share/home/nshen/miniconda3/etc/profile.d/conda.sh}}"
MODE="${{1:-report}}"

if [ -f "$CONDA_SH" ]; then
  # shellcheck disable=SC1090
  source "$CONDA_SH"
  conda activate "$ENV_PREFIX"
fi
if [ -d "$PROJECT_ROOT/src" ]; then
  export PYTHONPATH="$PROJECT_ROOT/src${{PYTHONPATH:+:$PYTHONPATH}}"
fi

if [ "$MODE" = "report" ]; then
  python -m ultimate.cli report --run-dir "$RUN_DIR"
  python -m ultimate.cli export-repro --run-dir "$RUN_DIR"
elif [ "$MODE" = "full" ]; then
  ULTIMATE_ALLOW_OVERWRITE=1 python -m ultimate.cli run --config "$CONFIG_PATH"
else
  echo "Usage: $0 [report|full]" >&2
  exit 2
fi
"""
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
    return path


def _write_repro_readme(
    path: Path,
    *,
    run_dir: Path,
    manifest: dict[str, Any],
    rerun_script: Path,
    config_snapshot: Path | None,
    analysis_request: Path | None,
    samplesheet: Path | None,
) -> Path:
    lines = [
        f"# Reproducible package: {manifest.get('run_id', run_dir.name)}",
        "",
        f"- Run directory: `{run_dir}`",
        f"- Status: `{manifest.get('status', 'unknown')}`",
        f"- Original command: `{manifest.get('reproducible_command', 'not_recorded')}`",
        f"- Config snapshot: `{config_snapshot or 'not_recorded'}`",
        f"- Analysis request: `{analysis_request or 'not_recorded'}`",
        f"- Samplesheet: `{samplesheet or 'not_recorded'}`",
        "",
        "## Rerun",
        "",
        f"- Rebuild report and reproducibility files: `{rerun_script} report`",
        f"- Full rerun in the same output directory: `{rerun_script} full`",
        "",
        "Full rerun sets `ULTIMATE_ALLOW_OVERWRITE=1` because the original run directory already contains a manifest.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_delivery_index(path: Path, run_dir: Path) -> Path:
    rows = []
    for category, directory in (
        ("figure", run_dir / "results" / "figures"),
        ("table", run_dir / "results" / "tables"),
        ("object", run_dir / "objects"),
        ("report", run_dir / "reports"),
        ("reproducible_code", run_dir / "reproducible_code"),
    ):
        if not directory.exists():
            continue
        for item in sorted(directory.rglob("*")):
            if item.is_file():
                rows.append({"category": category, "path": str(item), "size_bytes": item.stat().st_size})
    _write_tsv(path, rows, ("category", "path", "size_bytes"))
    return path


def _copy_report_deliverables(run_dir: Path, deliverables_dir: Path) -> None:
    for name in ("report.html", "methods.md", "report_manifest.json"):
        _copy_if_exists(run_dir / "reports" / name, deliverables_dir / name)
    _copy_if_exists(run_dir / "run_manifest.json", deliverables_dir / "run_manifest.json")
    _copy_if_exists(run_dir / "delivery_index.tsv", deliverables_dir / "delivery_index.tsv")


def _write_tsv(path: Path, rows: list[dict[str, Any]], fieldnames: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
