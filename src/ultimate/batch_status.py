from __future__ import annotations

import csv
import fnmatch
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BATCH_STATUS_COLUMNS = (
    "job_id",
    "module",
    "preset",
    "input_type",
    "sample_count",
    "cell_count",
    "feature_count",
    "slurm_job_id",
    "storage_gb",
    "job_dir",
    "scaffold_status",
    "raw_upstream_status",
    "run_status",
    "customer_package_status",
    "delivery_check_status",
    "overall_status",
    "failure_stage",
    "failure_recovery_file",
    "next_action",
    "failure_recovery",
)


def build_batch_status(*, batch_dir: Path, output_dir: Path | None = None, job_glob: str | None = None) -> dict[str, Any]:
    batch_dir = batch_dir.expanduser().resolve()
    output_dir = (output_dir or batch_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = [_status_row(job) for job in _job_dirs(batch_dir, job_glob=job_glob)]
    if not rows and (batch_dir / "batch_manifest.json").exists():
        rows = [
            _manifest_row(row)
            for row in _batch_manifest_rows(batch_dir / "batch_manifest.json")
            if _matches_job_glob(Path(str(row.get("job_dir") or row.get("job_id") or "")), job_glob)
        ]
    table = output_dir / "batch_status.tsv"
    report = output_dir / "batch_status_report.md"
    _write_tsv(table, rows, BATCH_STATUS_COLUMNS)
    _write_report(report, rows=rows, batch_dir=batch_dir)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "batch_dir": str(batch_dir),
        "output_dir": str(output_dir),
        "job_glob": job_glob or "",
        "job_count": len(rows),
        "status_counts": {status: sum(1 for row in rows if row["overall_status"] == status) for status in sorted({row["overall_status"] for row in rows})},
        "delivery_allowed": False,
        "non_delivery_reason": "batch_status_report_only_not_delivery",
        "artifacts": {"batch_status_tsv": str(table), "batch_status_report": str(report)},
        "rows": rows,
    }
    manifest_path = output_dir / "batch_status_manifest.json"
    manifest["manifest_path"] = str(manifest_path)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def _job_dirs(batch_dir: Path, *, job_glob: str | None = None) -> list[Path]:
    if (batch_dir / "jobs").is_dir():
        return _filter_job_dirs(sorted(path for path in (batch_dir / "jobs").iterdir() if path.is_dir()), job_glob)
    if (batch_dir / "batch_manifest.json").exists():
        return _filter_job_dirs(
            [Path(str(row.get("job_dir"))) for row in _batch_manifest_rows(batch_dir / "batch_manifest.json") if row.get("job_dir")],
            job_glob,
        )
    return (
        _filter_job_dirs(sorted(path for path in batch_dir.iterdir() if path.is_dir() and (path / "job_manifest.json").exists()), job_glob)
        if batch_dir.is_dir()
        else []
    )


def _filter_job_dirs(paths: list[Path], job_glob: str | None) -> list[Path]:
    return [path for path in paths if _matches_job_glob(path, job_glob)]


def _matches_job_glob(path: Path, job_glob: str | None) -> bool:
    if not job_glob:
        return True
    name = path.name or str(path)
    return fnmatch.fnmatch(name, job_glob)


def _status_row(job_dir: Path) -> dict[str, str]:
    job_id = job_dir.name
    job_manifest = _read_json(job_dir / "job_manifest.json")
    job_id = str(job_manifest.get("job_id") or job_id)
    project_config = _read_project_config(job_dir)
    run_manifest = _latest_run_manifest(job_dir)
    raw_status = _raw_upstream_status(job_dir)
    run_status = _run_status(job_dir)
    customer_status = _customer_package_status(job_dir)
    delivery_status = _delivery_check_status(job_dir)
    overall, stage, action = _overall(raw_status, run_status, customer_status, delivery_status)
    recovery = _ensure_failure_recovery(job_dir, job_id=job_id, overall=overall, stage=stage, action=action)
    module = _infer_module(job_id=job_id, config=project_config, run_manifest=run_manifest)
    sample_count = _sample_count(job_dir=job_dir, config=project_config)
    cell_count, feature_count = _data_shape_counts(job_dir=job_dir, config=project_config, module=module)
    return {
        "job_id": job_id,
        "module": module,
        "preset": _infer_preset(job_id=job_id, config=project_config, module=module),
        "input_type": _infer_input_type(config=project_config, module=module, raw_status=raw_status),
        "sample_count": sample_count,
        "cell_count": cell_count,
        "feature_count": feature_count,
        "slurm_job_id": _slurm_job_id(job_dir=job_dir, run_manifest=run_manifest),
        "storage_gb": _storage_gb(job_dir),
        "job_dir": str(job_dir),
        "scaffold_status": "scaffolded" if job_manifest else "unknown",
        "raw_upstream_status": raw_status,
        "run_status": run_status,
        "customer_package_status": customer_status,
        "delivery_check_status": delivery_status,
        "overall_status": overall,
        "failure_stage": stage,
        "failure_recovery_file": str(recovery),
        "next_action": action,
        "failure_recovery": str(recovery),
    }


def _manifest_row(row: dict[str, Any]) -> dict[str, str]:
    job_dir = Path(str(row.get("job_dir") or ""))
    if job_dir.exists():
        return _status_row(job_dir)
    return {
        "job_id": str(row.get("job_id") or ""),
        "module": str(row.get("module") or ""),
        "preset": str(row.get("preset") or ""),
        "input_type": str(row.get("input_type") or ""),
        "sample_count": str(row.get("sample_count") or ""),
        "cell_count": str(row.get("cell_count") or ""),
        "feature_count": str(row.get("feature_count") or ""),
        "slurm_job_id": str(row.get("slurm_job_id") or ""),
        "storage_gb": str(row.get("storage_gb") or ""),
        "job_dir": str(job_dir),
        "scaffold_status": str(row.get("scaffold_status") or "not_scaffolded"),
        "raw_upstream_status": "not_checked",
        "run_status": "missing",
        "customer_package_status": "missing",
        "delivery_check_status": "missing",
        "overall_status": str(row.get("status") or "blocked"),
        "failure_stage": "prepare_batch",
        "failure_recovery_file": str(row.get("failure_recovery") or ""),
        "next_action": str(row.get("next_action") or "fix_scaffold_blocker"),
        "failure_recovery": str(row.get("failure_recovery") or ""),
    }


def _batch_manifest_rows(path: Path) -> list[dict[str, Any]]:
    payload = _read_json(path)
    rows = payload.get("rows")
    return rows if isinstance(rows, list) else []


def _raw_upstream_status(job_dir: Path) -> str:
    manifests = sorted((job_dir / "raw_upstream").glob("*/raw_upstream_manifest.json")) if (job_dir / "raw_upstream").is_dir() else []
    if manifests:
        statuses = [_read_json(path).get("status", "unknown") for path in manifests]
        if "blocked" in statuses:
            return "blocked"
        if all(status == "ready" for status in statuses):
            return "ready"
        return "partial"
    evidence = job_dir / "raw_links" / "raw_upstream_evidence.tsv"
    if evidence.exists():
        rows = _read_tsv(evidence)
        statuses = {row.get("execution_status", "") for row in rows}
        if "blocked" in statuses:
            return "blocked"
        if "ready" in statuses:
            return "ready"
        return "handoff_or_not_executed"
    return "not_recorded"


def _run_status(job_dir: Path) -> str:
    pointer = job_dir / "deliverables" / "latest_run_pointer.json"
    if pointer.exists():
        payload = _read_json(pointer)
        run_dir = Path(str(payload.get("latest_run_dir") or ""))
        run_manifest = _read_json(run_dir / "run_manifest.json") if run_dir.exists() else {}
        return str(run_manifest.get("status") or "ready_pointer_without_manifest")
    latest = job_dir / "deliverables" / "latest_run_manifest.json"
    if latest.exists():
        return str(_read_json(latest).get("status") or "unknown")
    return "missing"


def _latest_run_manifest(job_dir: Path) -> dict[str, Any]:
    pointer = job_dir / "deliverables" / "latest_run_pointer.json"
    if pointer.exists():
        payload = _read_json(pointer)
        run_dir = Path(str(payload.get("latest_run_dir") or ""))
        if run_dir.exists():
            return _read_json(run_dir / "run_manifest.json")
    latest = job_dir / "deliverables" / "latest_run_manifest.json"
    if latest.exists():
        return _read_json(latest)
    run_manifests = sorted((job_dir / "runs").glob("*/run_manifest.json")) if (job_dir / "runs").is_dir() else []
    return _read_json(run_manifests[-1]) if run_manifests else {}


def _read_project_config(job_dir: Path) -> dict[str, Any]:
    config_path = job_dir / "config" / "project.yaml"
    if not config_path.exists():
        return {}
    try:
        import yaml

        payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _infer_module(*, job_id: str, config: dict[str, Any], run_manifest: dict[str, Any]) -> str:
    modules = run_manifest.get("modules")
    if isinstance(modules, dict):
        enabled = [name for name, payload in modules.items() if isinstance(payload, dict)]
        if enabled:
            return str(enabled[0])
    config_modules = config.get("modules")
    if isinstance(config_modules, dict):
        enabled = [name for name, payload in config_modules.items() if isinstance(payload, dict) and payload.get("enabled", True)]
        if enabled:
            return str(enabled[0])
    known = (
        "functional_state",
        "single_gene",
        "methylation",
        "proteomics",
        "multiome",
        "rnaseq",
        "scrna",
        "scatac",
        "spatial",
        "cite_seq",
        "vdj",
        "scepi",
        "publicdb",
    )
    for name in known:
        if name in job_id:
            return name
    return ""


def _infer_preset(*, job_id: str, config: dict[str, Any], module: str) -> str:
    module_config = _module_config(config, module)
    if module_config.get("preset"):
        return str(module_config.get("preset"))
    for token in ("publication", "standard", "basic", "communication", "tumor"):
        if token in job_id:
            return token
    return ""


def _infer_input_type(*, config: dict[str, Any], module: str, raw_status: str) -> str:
    module_config = _module_config(config, module)
    if raw_status == "ready":
        return "raw_or_semiraw_import"
    key_map = (
        ("h5ad", "h5ad"),
        ("tenx_mtx", "10x_mtx"),
        ("tenx_h5", "10x_h5"),
        ("abundance_table", "abundance_table"),
        ("beta_matrix", "beta_matrix"),
        ("peak_matrix", "peak_matrix"),
        ("rna_matrix", "rna_matrix"),
        ("atac_matrix", "atac_matrix"),
        ("input_matrix", "matrix"),
    )
    for key, value in key_map:
        if module_config.get(key):
            return value
    if module_config:
        return "configured"
    return ""


def _module_config(config: dict[str, Any], module: str) -> dict[str, Any]:
    modules = config.get("modules")
    if isinstance(modules, dict):
        payload = modules.get(module)
        if isinstance(payload, dict):
            return payload
        for value in modules.values():
            if isinstance(value, dict) and value.get("enabled", True):
                return value
    return {}


def _sample_count(*, job_dir: Path, config: dict[str, Any]) -> str:
    samples = config.get("samples") if isinstance(config.get("samples"), dict) else {}
    candidates = [
        Path(str(samples.get("samplesheet"))) if samples.get("samplesheet") else None,
        job_dir / "samples" / "samples.tsv",
    ]
    for candidate in candidates:
        if candidate and candidate.exists():
            try:
                rows = _read_tsv(candidate)
                sample_ids = {row.get("sample_id", "") for row in rows if row.get("sample_id")}
                return str(len(sample_ids) if sample_ids else len(rows))
            except Exception:
                return ""
    return ""


def _data_shape_counts(*, job_dir: Path, config: dict[str, Any], module: str) -> tuple[str, str]:
    module_config = _module_config(config, module)
    matrix_keys = ("input_matrix", "abundance_table", "beta_matrix", "peak_matrix", "rna_matrix", "atac_matrix")
    for key in matrix_keys:
        value = module_config.get(key)
        if value:
            rows, columns = _matrix_shape(Path(str(value)))
            if rows:
                if module in {"scrna", "scatac", "multiome"}:
                    return str(max(columns - 1, 0)) if columns else "", str(rows)
                return "", str(rows)
    tenx = module_config.get("tenx_mtx")
    if tenx:
        return _tenx_shape(Path(str(tenx)))
    h5ad = module_config.get("h5ad")
    if h5ad:
        return _h5ad_shape(Path(str(h5ad)))
    raw_matrix = job_dir / "raw_links" / "raw_import_matrix.tsv"
    if raw_matrix.exists():
        rows, columns = _matrix_shape(raw_matrix)
        return "", str(rows) if rows else str(max(columns - 1, 0))
    return "", ""


def _matrix_shape(path: Path) -> tuple[int, int]:
    if not path.exists():
        return 0, 0
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle, delimiter="\t")
            header = next(reader, [])
            rows = sum(1 for _ in reader)
        return rows, len(header)
    except Exception:
        return 0, 0


def _tenx_shape(path: Path) -> tuple[str, str]:
    try:
        import gzip

        matrix = path / "matrix.mtx.gz"
        opener = gzip.open if matrix.exists() else open
        if not matrix.exists():
            matrix = path / "matrix.mtx"
        with opener(matrix, "rt", encoding="utf-8") as handle:  # type: ignore[arg-type]
            for line in handle:
                if not line.startswith("%"):
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        return parts[1], parts[0]
    except Exception:
        pass
    return "", ""


def _h5ad_shape(path: Path) -> tuple[str, str]:
    try:
        import h5py

        with h5py.File(path, "r") as handle:
            shape = handle["X"].shape
            return str(shape[0]), str(shape[1])
    except Exception:
        return "", ""


def _slurm_job_id(*, job_dir: Path, run_manifest: dict[str, Any]) -> str:
    for key in ("slurm_job_id", "SLURM_JOB_ID"):
        if run_manifest.get(key):
            return str(run_manifest.get(key))
    raw_manifests = sorted((job_dir / "raw_upstream").glob("*/raw_upstream_manifest.json")) if (job_dir / "raw_upstream").is_dir() else []
    for manifest in raw_manifests:
        payload = _read_json(manifest)
        if payload.get("slurm_job_id"):
            return str(payload.get("slurm_job_id"))
    return ""


def _storage_gb(path: Path) -> str:
    total = 0
    try:
        for item in path.rglob("*"):
            if item.is_file() and not item.is_symlink():
                total += item.stat().st_size
    except Exception:
        return ""
    return f"{total / 1024**3:.6f}"


def _customer_package_status(job_dir: Path) -> str:
    package_dir = job_dir / "deliverables" / "customer"
    required = ("report.html", "methods.md", "delivery_index.tsv", "sanitization.tsv", "customer_package_manifest.tsv", "readme_for_customer.md")
    if not package_dir.exists():
        return "missing"
    missing = [name for name in required if not (package_dir / name).exists() or (package_dir / name).stat().st_size == 0]
    return "ready" if not missing else "partial"


def _delivery_check_status(job_dir: Path) -> str:
    path = job_dir / "deliverables" / "latest_delivery_check.json"
    if not path.exists():
        return "missing"
    return str(_read_json(path).get("status") or "unknown")


def _overall(raw_status: str, run_status: str, customer_status: str, delivery_status: str) -> tuple[str, str, str]:
    if delivery_status == "ready":
        return "ready", "complete", "keep_evidence_current"
    if raw_status == "blocked":
        if "license" in raw_status:
            return "needs_license", "raw_upstream", "provide_licensed_tool_path_or_use_handoff"
        if "handoff" in raw_status:
            return "handoff_required", "raw_upstream", "complete_upstream_handoff_then_rerun_slurm"
        return "blocked", "raw_upstream", "fix_raw_upstream_then_rerun_slurm"
    if "license" in raw_status:
        return "needs_license", "raw_upstream", "provide_licensed_tool_path_or_use_handoff"
    if "handoff" in raw_status:
        return "handoff_required", "raw_upstream", "complete_upstream_handoff_then_rerun_slurm"
    if run_status in {"missing", "partial", "failed"}:
        return "failed" if run_status == "failed" else "blocked", "analysis_run", "rerun_or_recover_analysis_job"
    if customer_status in {"missing", "partial"}:
        return "blocked", "customer_package", "run_ultimate_customer_package"
    if delivery_status in {"missing", "blocked"}:
        return "blocked", "delivery_check", "run_or_fix_delivery_check"
    return "needs_manual_review", "unknown", "inspect_job_artifacts"


def _ensure_failure_recovery(job_dir: Path, *, job_id: str, overall: str, stage: str, action: str) -> Path:
    path = job_dir / "failure_recovery.md"
    if path.exists() and path.stat().st_size > 0:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "# Failure recovery",
                "",
                f"- job_id: `{job_id}`",
                f"- status: `{overall}`",
                f"- failure_stage: `{stage}`",
                "- reusable_artifacts: `prepared job directory, run manifest if present, customer package if present`",
                f"- rerun_required: `{str(overall != 'ready').lower()}`",
                f"- slurm_required: `{str(stage in {'raw_upstream', 'analysis_run'}).lower()}`",
                f"- minimal_fix_command: `{action}`",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _write_tsv(path: Path, rows: list[dict[str, Any]], fieldnames: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_report(path: Path, *, rows: list[dict[str, str]], batch_dir: Path) -> None:
    lines = [
        "# Ultimate batch status report",
        "",
        f"- batch_dir: `{batch_dir}`",
        f"- jobs_total: {len(rows)}",
        f"- ready: {sum(1 for row in rows if row['overall_status'] == 'ready')}",
        f"- blocked: {sum(1 for row in rows if row['overall_status'] == 'blocked')}",
        f"- failed: {sum(1 for row in rows if row['overall_status'] == 'failed')}",
        f"- needs_manual_review: {sum(1 for row in rows if row['overall_status'] == 'needs_manual_review')}",
        f"- needs_license: {sum(1 for row in rows if row['overall_status'] == 'needs_license')}",
        f"- handoff_required: {sum(1 for row in rows if row['overall_status'] == 'handoff_required')}",
        "",
        "| job_id | module | preset | input_type | sample_count | cell_count | feature_count | slurm_job_id | storage_gb | overall_status | raw_upstream | run | customer_package | delivery_check | next_action |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['job_id']} | {row.get('module', '')} | {row.get('preset', '')} | {row.get('input_type', '')} | "
            f"{row.get('sample_count', '')} | {row.get('cell_count', '')} | {row.get('feature_count', '')} | "
            f"{row.get('slurm_job_id', '')} | {row.get('storage_gb', '')} | {row['overall_status']} | "
            f"{row['raw_upstream_status']} | {row['run_status']} | {row['customer_package_status']} | "
            f"{row['delivery_check_status']} | {row['next_action']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
