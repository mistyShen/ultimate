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
    _copy_report_deliverables(run_dir, deliverables_dir)
    delivery_index = _write_delivery_index(run_dir / "delivery_index.tsv", run_dir)

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
    delivery_index = _write_delivery_index(run_dir / "delivery_index.tsv", run_dir)
    repro_manifest["delivery_index"] = str(delivery_index)
    repro_manifest_path.write_text(json.dumps(repro_manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    _copy_if_exists(delivery_index, deliverables_dir / "delivery_index.tsv")
    job_level_delivery = _write_job_level_delivery(run_dir=run_dir, repro_manifest=repro_manifest, repro_manifest_path=repro_manifest_path)
    if job_level_delivery:
        repro_manifest["job_level_delivery"] = job_level_delivery
        repro_manifest_path.write_text(json.dumps(repro_manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        _copy_if_exists(repro_manifest_path, Path(job_level_delivery["reproducible_code_dir"]) / "latest_repro_manifest.json")
    return repro_manifest


def refresh_job_level_delivery_mirrors(run_dir: Path) -> dict[str, Any]:
    """Refresh prepared-job latest mirrors after reports have been rebuilt.

    `export_reproducible_package` intentionally runs before report rendering in
    the pipeline finalize order so the report can include reproducibility
    details. This helper updates only the small job-level mirrors afterward; it
    does not recalculate checksums, software versions, or rerun scripts.
    """

    run_dir = run_dir.resolve()
    repro_manifest_path = run_dir / "reproducible_code" / "repro_manifest.json"
    if not repro_manifest_path.exists():
        return {}
    try:
        repro_manifest = json.loads(repro_manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    delivery_index = _write_delivery_index(run_dir / "delivery_index.tsv", run_dir)
    repro_manifest["delivery_index"] = str(delivery_index)
    job_level_delivery = _write_job_level_delivery(run_dir=run_dir, repro_manifest=repro_manifest, repro_manifest_path=repro_manifest_path)
    if not job_level_delivery:
        return {}
    repro_manifest["job_level_delivery"] = job_level_delivery
    repro_manifest_path.write_text(json.dumps(repro_manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    _copy_if_exists(repro_manifest_path, Path(job_level_delivery["reproducible_code_dir"]) / "latest_repro_manifest.json")
    return job_level_delivery


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
CONDA_SH="${{CONDA_SH:-}}"
MODE="${{1:-report}}"

if [ -z "$CONDA_SH" ]; then
  for candidate in \
    "$PROJECT_ROOT/.conda/etc/profile.d/conda.sh" \
    "$PROJECT_ROOT/miniconda3/etc/profile.d/conda.sh" \
    "/shared/shen/2026/ultimate/.conda/etc/profile.d/conda.sh"
  do
    if [ -f "$candidate" ]; then
      CONDA_SH="$candidate"
      break
    fi
  done
fi

if [ -n "$CONDA_SH" ] && [ -f "$CONDA_SH" ]; then
  # shellcheck disable=SC1090
  source "$CONDA_SH"
  conda activate "$ENV_PREFIX"
elif [ -x "$ENV_PREFIX/bin/python" ]; then
  export PATH="$ENV_PREFIX/bin:$PATH"
fi
if [ -d "$PROJECT_ROOT/src" ]; then
  export PYTHONPATH="$PROJECT_ROOT/src${{PYTHONPATH:+:$PYTHONPATH}}"
fi

if [ "$MODE" = "report" ]; then
  python -m ultimate.cli report --run-dir "$RUN_DIR"
  python -m ultimate.cli export-repro --run-dir "$RUN_DIR"
elif [ "$MODE" = "full" ]; then
  if [ -z "${{SLURM_JOB_ID:-}}" ]; then
    echo "Full rerun must be submitted through Slurm; report-only rebuild is allowed locally." >&2
    exit 3
  fi
  if [ "${{ULTIMATE_ALLOW_OVERWRITE:-}}" != "1" ]; then
    echo "Full rerun requires ULTIMATE_ALLOW_OVERWRITE=1 inside the Slurm job." >&2
    exit 4
  fi
  python -m ultimate.cli run --config "$CONFIG_PATH"
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
        f"- Full rerun in the same output directory: submit `{rerun_script} full` through Slurm with `ULTIMATE_ALLOW_OVERWRITE=1`.",
        "",
        "Full rerun is blocked outside Slurm to avoid heavy recomputation on a login node.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_delivery_index(path: Path, run_dir: Path) -> Path:
    rows = []
    indexed_paths: set[str] = set()
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
            if item.is_file() and item.stat().st_size > 0:
                rows.append(_delivery_index_row(category, item, run_dir))
                indexed_paths.add(str(item.expanduser().resolve()))
    for row in _declared_external_artifact_rows(run_dir, indexed_paths):
        rows.append(row)
        indexed_paths.add(str(Path(str(row["path"])).expanduser().resolve()))
    _write_tsv(path, rows, ("category", "path", "size_bytes", "module", "artifact_key", "artifact_scope"))
    return path


def _declared_external_artifact_rows(run_dir: Path, indexed_paths: set[str]) -> list[dict[str, Any]]:
    manifest_path = run_dir / "run_manifest.json"
    if not manifest_path.exists():
        return []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    modules = manifest.get("modules") if isinstance(manifest.get("modules"), list) else []
    rows: list[dict[str, Any]] = []
    category_map = {
        "figures": "figure",
        "tables": "table",
        "objects": "object",
        "reports": "module_report",
    }
    for module in modules:
        if not isinstance(module, dict):
            continue
        module_name = str(module.get("module") or "")
        artifacts = module.get("artifacts") if isinstance(module.get("artifacts"), dict) else {}
        for artifact_group, category in category_map.items():
            payload = artifacts.get(artifact_group)
            if isinstance(payload, dict):
                pairs = payload.items()
            elif isinstance(payload, list):
                pairs = ((Path(str(value)).stem, value) for value in payload)
            else:
                continue
            for key, value in pairs:
                item = Path(str(value)).expanduser()
                if not item.is_file():
                    continue
                if item.stat().st_size <= 0:
                    continue
                resolved = str(item.resolve())
                if resolved in indexed_paths:
                    continue
                rows.append(
                    {
                        "category": category,
                        "path": str(item),
                        "size_bytes": item.stat().st_size,
                        "module": module_name,
                        "artifact_key": str(key),
                        "artifact_scope": "external_declared",
                    }
                )
    return rows


def _delivery_index_row(category: str, item: Path, run_dir: Path) -> dict[str, Any]:
    module = ""
    artifact_key = item.stem
    artifact_scope = "run"
    indexed_category = category
    try:
        rel = item.relative_to(run_dir)
    except ValueError:
        rel = item
    parts = rel.parts
    if len(parts) >= 3 and parts[0] in {"results", "objects", "reports"}:
        if parts[0] == "results" and len(parts) >= 4:
            module = parts[2]
            artifact_scope = "module"
        elif parts[0] == "objects":
            module = parts[1]
            artifact_scope = "module"
        elif parts[0] == "reports" and len(parts) >= 3:
            module = parts[1]
            artifact_scope = "module"
            indexed_category = "module_report"
    return {
        "category": indexed_category,
        "path": str(item),
        "size_bytes": item.stat().st_size,
        "module": module,
        "artifact_key": artifact_key,
        "artifact_scope": artifact_scope,
    }


def _copy_report_deliverables(run_dir: Path, deliverables_dir: Path) -> None:
    for name in ("report.html", "methods.md", "report_manifest.json"):
        _copy_if_exists(run_dir / "reports" / name, deliverables_dir / name)
    _copy_if_exists(run_dir / "run_manifest.json", deliverables_dir / "run_manifest.json")
    _copy_if_exists(run_dir / "delivery_index.tsv", deliverables_dir / "delivery_index.tsv")


def _write_job_level_delivery(run_dir: Path, repro_manifest: dict[str, Any], repro_manifest_path: Path) -> dict[str, Any]:
    job_dir = _prepared_job_dir(run_dir)
    if job_dir is None:
        return {}
    deliverables_dir = job_dir / "deliverables"
    package_dir = job_dir / "reproducible_code"
    deliverables_dir.mkdir(parents=True, exist_ok=True)
    package_dir.mkdir(parents=True, exist_ok=True)

    copied = {
        "run_manifest": _copy_if_exists(run_dir / "run_manifest.json", deliverables_dir / "latest_run_manifest.json"),
        "report_html": _copy_if_exists(run_dir / "reports" / "report.html", deliverables_dir / "latest_report.html"),
        "methods_md": _copy_if_exists(run_dir / "reports" / "methods.md", deliverables_dir / "latest_methods.md"),
        "report_manifest": _copy_if_exists(run_dir / "reports" / "report_manifest.json", deliverables_dir / "latest_report_manifest.json"),
        "delivery_index": _copy_if_exists(run_dir / "delivery_index.tsv", deliverables_dir / "latest_delivery_index.tsv"),
        "rerun_script": _copy_if_exists(run_dir / "reproducible_code" / "rerun.sh", package_dir / "rerun.sh"),
        "repro_readme": _copy_if_exists(run_dir / "reproducible_code" / "README.md", package_dir / "README.md"),
        "config_snapshot": _copy_if_exists(run_dir / "reproducible_code" / "config_snapshot.yaml", package_dir / "config_snapshot.yaml"),
        "software_versions": _copy_if_exists(run_dir / "reproducible_code" / "software_versions.tsv", package_dir / "software_versions.tsv"),
        "input_checksums": _copy_if_exists(run_dir / "reproducible_code" / "input_checksums.tsv", package_dir / "input_checksums.tsv"),
        "repro_manifest": _copy_if_exists(repro_manifest_path, package_dir / "latest_repro_manifest.json"),
    }
    copied["module_reports"] = _copy_module_report_mirrors(run_dir, deliverables_dir)
    pointer = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "job_dir": str(job_dir),
        "latest_run_dir": str(run_dir),
        "run_manifest": str(run_dir / "run_manifest.json"),
        "run_reproducible_package": repro_manifest,
        "copied_artifacts": _stringify_copied_artifacts(copied),
        "policy": "job-level files are small latest-run mirrors; large result objects remain referenced from the run directory",
    }
    pointer_path = deliverables_dir / "latest_run_pointer.json"
    pointer["manifest_path"] = str(pointer_path)
    pointer_path.write_text(json.dumps(pointer, indent=2, ensure_ascii=False), encoding="utf-8")
    readme_path = deliverables_dir / "README.md"
    readme_path.write_text(
        "\n".join(
            [
                "# Ultimate job deliverables",
                "",
                f"- Latest run: `{run_dir}`",
                f"- Report: `{deliverables_dir / 'latest_report.html'}`",
                f"- Methods: `{deliverables_dir / 'latest_methods.md'}`",
                f"- Module reports: `{deliverables_dir / 'module_reports'}`",
                f"- Delivery index: `{deliverables_dir / 'latest_delivery_index.tsv'}`",
                f"- Reproducible code: `{package_dir}`",
                "",
                "Large tables, figures, and objects stay in the run directory and are indexed by `latest_delivery_index.tsv`.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return {
        "job_dir": str(job_dir),
        "deliverables_dir": str(deliverables_dir),
        "reproducible_code_dir": str(package_dir),
        "latest_run_pointer": str(pointer_path),
        "readme": str(readme_path),
    }


def _copy_module_report_mirrors(run_dir: Path, deliverables_dir: Path) -> dict[str, dict[str, Path]]:
    manifest_path = run_dir / "run_manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    mirrors: dict[str, dict[str, Path]] = {}
    modules = manifest.get("modules")
    if not isinstance(modules, list):
        return mirrors
    for module in modules:
        if not isinstance(module, dict):
            continue
        module_name = str(module.get("module") or "unknown")
        reports = (((module.get("artifacts") or {}).get("reports") or {}) if isinstance(module.get("artifacts"), dict) else {})
        if not isinstance(reports, dict):
            continue
        for key, value in reports.items():
            source = Path(str(value))
            if not source.is_absolute():
                source = run_dir / source
            target_name = {
                "report_html": "report.html",
                "methods_md": "methods.md",
                "run_manifest": "run_manifest.json",
            }.get(str(key), Path(str(value)).name)
            copied = _copy_if_exists(source, deliverables_dir / "module_reports" / module_name / target_name)
            if copied:
                mirrors.setdefault(module_name, {})[str(key)] = copied
    return mirrors


def _stringify_copied_artifacts(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _stringify_copied_artifacts(nested) for key, nested in value.items() if nested}
    return str(value) if value else ""


def _prepared_job_dir(run_dir: Path) -> Path | None:
    if run_dir.parent.name != "runs":
        return None
    job_dir = run_dir.parent.parent
    if not (job_dir / "job_manifest.json").exists():
        return None
    return job_dir


def _write_tsv(path: Path, rows: list[dict[str, Any]], fieldnames: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
