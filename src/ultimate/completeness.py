from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ultimate.backend_registry import BACKEND_REGISTRY, backend_registry_rows
from ultimate.constants import MODULE_ORDER
from ultimate.tool_registry import (
    DECISION_TO_V2_DISPOSITION,
    DECISIONS,
    TOOL_REGISTRY,
    _audit_row,
    _collect_checks,
    _env_paths,
)
from ultimate.validation_index import build_validation_index


READINESS_TIERS = (
    "order_ready_customer_rehearsed",
    "validated_backend_only",
    "handoff_required",
    "licensed_required",
    "needs_algorithm_backend",
    "needs_raw_upstream",
)


def run_tool_completeness(root: Path, output_dir: Path | None = None) -> dict[str, Any]:
    """Write the V4.1 tool completeness matrix.

    The matrix is intentionally registry-first: every tool in AGENTS-driven
    `TOOL_REGISTRY` must receive an explicit disposition, even if it is only a
    handoff, license path, reference, or rejected/cleaned decision.
    """
    root = root.resolve()
    output_dir = (output_dir or root / "audits" / "tool_completeness_latest").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    checks = _collect_checks(_env_paths(root), TOOL_REGISTRY)
    validation_rows = _latest_validation_rows(root, output_dir / "_validation_index_snapshot")
    backend_by_tool = _backend_index_by_tool()
    validation_by_module = _validation_index_by_module(validation_rows)
    customer_ready_modules = {
        row["module"]
        for row in validation_rows
        if row.get("run_kind") in {"customer_delivery_rehearsal", "customer_delivery"}
        and row.get("order_readiness_status") == "ready_for_delivery"
    }

    rows: list[dict[str, Any]] = []
    for tool in TOOL_REGISTRY:
        audit = _audit_row(tool, checks)
        backends = backend_by_tool.get(_norm(tool.name), [])
        disposition = DECISION_TO_V2_DISPOSITION.get(tool.decision, "missing_review")
        missing_review, review_reason = _tool_review_status(tool, disposition)
        module_validation = validation_by_module.get(tool.module, {})
        rows.append(
            {
                "tool_name": tool.name,
                "module": tool.module,
                "url": tool.url,
                "decision": tool.decision,
                "disposition": disposition,
                "install_method": tool.install_method,
                "environment": tool.env,
                "check_kind": audit["check_kind"],
                "check_key": audit["check_key"],
                "check_passed": str(bool(audit["check_passed"])).lower(),
                "status": audit["status"],
                "estimated_gb": audit["estimated_gb"],
                "backend_ids": ",".join(backend["backend_id"] for backend in backends),
                "backend_statuses": ",".join(sorted({backend["backend_status"] for backend in backends})),
                "validation_status": module_validation.get("best_order_readiness_status", "not_seen_in_validation_index"),
                "validation_run_kinds": module_validation.get("run_kinds", ""),
                "customer_package_eligible": str(tool.module in customer_ready_modules and disposition in {"default_backend", "optional_backend", "handoff_adapter"}).lower(),
                "missing_review": str(missing_review).lower(),
                "review_reason": review_reason,
                "reason_cn": tool.reason_cn,
            }
        )

    matrix_tsv = output_dir / "tool_completeness_matrix.tsv"
    matrix_json = output_dir / "tool_completeness_matrix.json"
    raw_upstream = output_dir / "raw_upstream_readiness_matrix.tsv"
    customer_package = output_dir / "customer_package_matrix.tsv"
    report_md = output_dir / "v4_1_tool_completeness_report.md"
    _write_tsv(matrix_tsv, rows)
    matrix_json.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_tsv(raw_upstream, _raw_upstream_rows(validation_rows))
    _write_tsv(customer_package, _customer_package_rows(validation_rows))

    summary = _count_by(rows, "disposition")
    missing_review_count = sum(1 for row in rows if row["missing_review"] == "true")
    manifest = {
        "generated_at": _now(),
        "root": str(root),
        "output_dir": str(output_dir),
        "tool_count": len(rows),
        "missing_review_count": missing_review_count,
        "summary": summary,
        "tool_completeness_matrix_tsv": str(matrix_tsv),
        "tool_completeness_matrix_json": str(matrix_json),
        "raw_upstream_readiness_matrix": str(raw_upstream),
        "customer_package_matrix": str(customer_package),
        "report_md": str(report_md),
    }
    _write_tool_completeness_report(report_md, manifest, rows)
    manifest_path = output_dir / "run_manifest.json"
    manifest["manifest_path"] = str(manifest_path)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def run_module_order_readiness(root: Path, output_dir: Path | None = None) -> dict[str, Any]:
    """Write the V4.1 module order-readiness matrix for all Ultimate modules."""
    root = root.resolve()
    output_dir = (output_dir or root / "audits" / "order_readiness_latest").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    validation_rows = _latest_validation_rows(root, output_dir / "_validation_index_snapshot")
    validation_by_module = _validation_index_by_module(validation_rows)
    backend_by_module = _backend_index_by_module()
    rows: list[dict[str, Any]] = []
    for module in MODULE_ORDER:
        validation = validation_by_module.get(module, {})
        backends = backend_by_module.get(module, [])
        tier, next_action = _readiness_tier(module, validation, backends)
        rows.append(
            {
                "module": module,
                "readiness_tier": tier,
                "customer_rehearsal_status": validation.get("customer_rehearsal_status", "not_seen"),
                "validation_status": validation.get("best_order_readiness_status", "not_seen_in_validation_index"),
                "backend_ids": ",".join(backend["backend_id"] for backend in backends),
                "backend_statuses": ",".join(sorted({backend["backend_status"] for backend in backends})),
                "raw_upstream_status": _raw_upstream_status(module, validation, backends),
                "next_action": next_action,
                "evidence_run": validation.get("best_run_name", ""),
                "slurm_job_id": validation.get("best_slurm_job_id", ""),
                "run_kinds": validation.get("run_kinds", ""),
            }
        )

    matrix_tsv = output_dir / "module_order_readiness_matrix.tsv"
    matrix_json = output_dir / "module_order_readiness_matrix.json"
    report_md = output_dir / "module_order_readiness_report.md"
    _write_tsv(matrix_tsv, rows)
    matrix_json.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    summary = _count_by(rows, "readiness_tier")
    manifest = {
        "generated_at": _now(),
        "root": str(root),
        "output_dir": str(output_dir),
        "module_count": len(rows),
        "summary": summary,
        "module_order_readiness_matrix": str(matrix_tsv),
        "module_order_readiness_json": str(matrix_json),
        "report_md": str(report_md),
    }
    _write_module_readiness_report(report_md, manifest, rows)
    manifest_path = output_dir / "run_manifest.json"
    manifest["manifest_path"] = str(manifest_path)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def _latest_validation_rows(root: Path, output_dir: Path) -> list[dict[str, str]]:
    manifest = build_validation_index(root=root, output_dir=output_dir)
    index_path = Path(str(manifest["validation_index_tsv"]))
    if not index_path.exists():
        return []
    with index_path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _tool_review_status(tool: Any, disposition: str) -> tuple[bool, str]:
    if tool.decision not in DECISIONS:
        return True, f"unknown_decision:{tool.decision}"
    if disposition == "missing_review":
        return True, "missing_disposition_mapping"
    if not tool.reason_cn.strip():
        return True, "missing_reason"
    return False, "reviewed"


def _backend_index_by_tool() -> dict[str, list[dict[str, Any]]]:
    indexed: dict[str, list[dict[str, Any]]] = {}
    for row in backend_registry_rows():
        for token in {row.get("tool", ""), row.get("label", ""), row.get("backend_id", "")}:
            normalized = _norm(str(token))
            if normalized:
                indexed.setdefault(normalized, []).append(row)
    return indexed


def _backend_index_by_module() -> dict[str, list[dict[str, Any]]]:
    indexed: dict[str, list[dict[str, Any]]] = {}
    for row in backend_registry_rows():
        indexed.setdefault(str(row["module"]), []).append(row)
    return indexed


def _validation_index_by_module(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    ranked = {
        "ready_for_delivery": 5,
        "ready_for_validation_evidence": 4,
        "needs_delivery_check": 3,
        "needs_slurm_or_artifact_evidence": 2,
        "blocked_or_partial": 1,
        "not_seen_in_validation_index": 0,
    }
    indexed: dict[str, dict[str, str]] = {}
    for row in rows:
        modules = [value.strip() for value in str(row.get("module", "")).split(",") if value.strip()]
        for module in modules:
            current = indexed.setdefault(
                module,
                {
                    "best_order_readiness_status": "not_seen_in_validation_index",
                    "best_run_name": "",
                    "best_slurm_job_id": "",
                    "run_kinds": "",
                    "customer_rehearsal_status": "not_seen",
                },
            )
            status = row.get("order_readiness_status", "") or "blocked_or_partial"
            if ranked.get(status, 0) > ranked.get(current["best_order_readiness_status"], 0):
                current["best_order_readiness_status"] = status
                current["best_run_name"] = row.get("run_name", "")
                current["best_slurm_job_id"] = row.get("slurm_job_id", "")
            run_kinds = set(filter(None, current["run_kinds"].split(",")))
            if row.get("run_kind"):
                run_kinds.add(str(row["run_kind"]))
            current["run_kinds"] = ",".join(sorted(run_kinds))
            if row.get("run_kind") in {"production_rehearsal", "customer_delivery_rehearsal", "customer_delivery"}:
                if row.get("order_readiness_status") == "ready_for_delivery":
                    current["customer_rehearsal_status"] = "ready_for_delivery"
                elif current["customer_rehearsal_status"] == "not_seen":
                    current["customer_rehearsal_status"] = "seen_but_not_ready"
    return indexed


def _readiness_tier(module: str, validation: dict[str, str], backends: list[dict[str, Any]]) -> tuple[str, str]:
    if validation.get("customer_rehearsal_status") == "ready_for_delivery":
        return "order_ready_customer_rehearsed", "Keep customer package QA and Slurm rehearsal evidence current."
    if validation.get("best_order_readiness_status") == "ready_for_validation_evidence":
        return "validated_backend_only", "Run production-style rehearsal with approval gate and delivery-check."
    statuses = {str(backend.get("backend_status")) for backend in backends}
    roles = {str(backend.get("backend_role")) for backend in backends}
    if "licensed_path_detection" in statuses or "licensed_backend" in roles:
        return "licensed_required", "User must provide licensed tool path before production execution."
    if "handoff_ready" in statuses or "handoff_backend" in roles:
        return "handoff_required", "Validate handoff route or provide upstream matrix/object before running module."
    if module in {"rnaseq", "scrna", "scatac", "multiome", "spatial", "methylation", "scepi"}:
        return "needs_raw_upstream", "Add or refresh raw/semi-raw upstream evidence for production intake."
    return "needs_algorithm_backend", "Add algorithm backend validation or explicit blocked reason."


def _raw_upstream_status(module: str, validation: dict[str, str], backends: list[dict[str, Any]]) -> str:
    if module == "rnaseq":
        return "lightweight_ready_next_production_tiny_chain"
    if module == "scrna":
        return "tenx_mtx_lightweight_ready_fastq_handoff_required"
    if module in {"proteomics", "spatial"}:
        return "controlled_matrix_only"
    if any(str(backend.get("backend_status")) == "handoff_ready" for backend in backends):
        return "handoff_required"
    return validation.get("best_order_readiness_status", "not_seen")


def _raw_upstream_rows(validation_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [
        {
            "route": "rnaseq FASTQ",
            "status": "lightweight_ready",
            "next_step": "Run production tiny chain: FASTQ to Salmon/featureCounts-like count import through Slurm.",
            "evidence_hint": _first_run(validation_rows, "rnaseq"),
        },
        {
            "route": "scrna 10x MTX",
            "status": "lightweight_ready",
            "next_step": "Keep matrix/object import ready; scRNA FASTQ remains handoff/licensed adapter.",
            "evidence_hint": _first_run(validation_rows, "scrna"),
        },
        {
            "route": "scrna FASTQ",
            "status": "handoff_or_adapter_required",
            "next_step": "Use nf-core/scrnaseq, Cell Ranger path detection, STARsolo, or alevin-fry adapter before downstream run.",
            "evidence_hint": "",
        },
        {
            "route": "spatial raw",
            "status": "controlled_matrix_only",
            "next_step": "Space Ranger remains licensed path detection; SpatialData/SOPA handoff for non-Visium modalities.",
            "evidence_hint": _first_run(validation_rows, "spatial"),
        },
        {
            "route": "proteomics raw",
            "status": "controlled_matrix_only",
            "next_step": "Use MaxQuant/PD/generic abundance table import; raw MS search is outside current core.",
            "evidence_hint": _first_run(validation_rows, "proteomics"),
        },
    ]


def _customer_package_rows(validation_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows = []
    for row in validation_rows:
        if row.get("run_kind") not in {"customer_delivery_rehearsal", "customer_delivery", "production_rehearsal"}:
            continue
        rows.append(
            {
                "run_name": row.get("run_name", ""),
                "module": row.get("module", ""),
                "run_kind": row.get("run_kind", ""),
                "delivery_scope": row.get("delivery_scope", ""),
                "order_readiness_status": row.get("order_readiness_status", ""),
                "customer_package_expected_files": "report.html,methods.md,delivery_index.tsv,sanitization.tsv,customer_delivery_sanitization.tsv,customer_package_manifest.tsv,readme_for_customer.md,figures/,tables/",
                "customer_visible_internal_paths_allowed": "false",
                "customer_package_eligible": str(row.get("order_readiness_status") == "ready_for_delivery").lower(),
            }
        )
    return rows


def _first_run(rows: list[dict[str, str]], module: str) -> str:
    for row in rows:
        if module in str(row.get("module", "")).split(","):
            return row.get("run_name", "")
    return ""


def _write_tool_completeness_report(path: Path, manifest: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    missing = [row for row in rows if row["missing_review"] == "true"]
    lines = [
        "# Ultimate V4.1 Tool Completeness Report",
        "",
        f"- Generated at: {manifest['generated_at']}",
        f"- Tool count: {manifest['tool_count']}",
        f"- Missing review count: {manifest['missing_review_count']}",
        "",
        "## Disposition Summary",
        "",
    ]
    for key, value in sorted(manifest["summary"].items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Missing Reviews", ""])
    if missing:
        lines.extend(f"- {row['tool_name']}: {row['review_reason']}" for row in missing)
    else:
        lines.append("- None. Every registered tool has an explicit disposition.")
    lines.extend(
        [
            "",
            "## Customer Package Boundary",
            "",
            "Customer packages must expose only sanitized delivery artifacts. Internal manifests, Slurm identifiers, approval JSON, raw paths, home paths and `/shared` paths stay out of the customer-facing package.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_module_readiness_report(path: Path, manifest: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    lines = [
        "# Ultimate V4.1 Module Order Readiness Report",
        "",
        f"- Generated at: {manifest['generated_at']}",
        f"- Module count: {manifest['module_count']}",
        "",
        "## Readiness Summary",
        "",
    ]
    for key, value in sorted(manifest["summary"].items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Module Matrix", ""])
    for row in rows:
        lines.append(f"- {row['module']}: {row['readiness_tier']} ({row['next_action']})")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "")
        counts[value] = counts.get(value, 0) + 1
    return counts


def _write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row}) if rows else ["empty"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _norm(value: str) -> str:
    return value.lower().replace("-", "_").replace(" ", "_").replace("/", "_")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
