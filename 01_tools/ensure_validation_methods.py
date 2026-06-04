#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from check_validation_manifests import iter_validation_manifests


def main() -> None:
    parser = argparse.ArgumentParser(description="Create transparent methods.md files for validation runs that lack them.")
    parser.add_argument("--root", type=Path, default=Path("/shared/shen/2026/ultimate"))
    parser.add_argument("--validations-dir", type=Path, default=Path("/shared/shen/2026/ultimate/validations"))
    parser.add_argument("--output-tsv", type=Path, required=True)
    args = parser.parse_args()
    rows = ensure_validation_methods(root=args.root, validations_dir=args.validations_dir)
    write_tsv(args.output_tsv, rows)
    summary: dict[str, int] = {}
    for row in rows:
        summary[row["action"]] = summary.get(row["action"], 0) + 1
    print(json.dumps({"summary": summary, "output_tsv": str(args.output_tsv)}, indent=2, ensure_ascii=False))


def ensure_validation_methods(*, root: Path, validations_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for manifest_path in iter_validation_manifests(validations_dir=validations_dir, root=root):
        rows.append(_ensure_one(manifest_path))
    return rows


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ("run_name", "manifest_path", "methods_path", "action", "analysis_level", "status", "module", "note")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _ensure_one(manifest_path: Path) -> dict[str, Any]:
    run_dir = manifest_path.parent
    methods_path = run_dir / "reports" / "methods.md"
    row = {
        "run_name": run_dir.name,
        "manifest_path": str(manifest_path),
        "methods_path": str(methods_path),
        "action": "unchanged" if methods_path.exists() and methods_path.stat().st_size > 0 else "created",
        "analysis_level": "",
        "status": "",
        "module": "",
        "note": "",
    }
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        row["action"] = "skipped"
        row["note"] = f"manifest_unreadable:{type(exc).__name__}"
        return row

    row["analysis_level"] = str(manifest.get("analysis_level", ""))
    row["status"] = str(manifest.get("status", ""))
    row["module"] = _module_name(manifest, run_dir)
    if row["action"] == "unchanged":
        row["note"] = "methods_exists"
        return row

    methods_path.parent.mkdir(parents=True, exist_ok=True)
    methods_path.write_text(_methods_text(manifest, run_dir), encoding="utf-8")
    row["note"] = "created_from_run_manifest_and_artifact_index"
    return row


def _module_name(manifest: dict[str, Any], run_dir: Path) -> str:
    module = manifest.get("module") or manifest.get("module_name")
    if module:
        return str(module)
    name = run_dir.name
    for prefix in ("slurm_", "scrna_mvp_"):
        if name.startswith(prefix):
            return name.removeprefix(prefix)
    return name


def _methods_text(manifest: dict[str, Any], run_dir: Path) -> str:
    tables = manifest.get("tables") if isinstance(manifest.get("tables"), list) else []
    figures = manifest.get("figures") if isinstance(manifest.get("figures"), list) else []
    objects = manifest.get("objects") if isinstance(manifest.get("objects"), dict) else {}
    lines = [
        "# 验证运行方法说明",
        "",
        f"生成时间：{datetime.now(timezone.utc).isoformat()}",
        f"运行目录：`{run_dir}`",
        f"模块/范围：`{_module_name(manifest, run_dir)}`",
        f"状态：`{manifest.get('status', '')}`",
        f"analysis_level：`{manifest.get('analysis_level', '')}`",
        f"delivery_allowed：`{manifest.get('delivery_allowed', '')}`",
        f"validation_evidence_allowed：`{manifest.get('validation_evidence_allowed', '')}`",
        "",
        "## 方法来源",
        "该文件由 `ensure_validation_methods.py` 根据已有 `run_manifest.json` 和产物索引补齐。",
        "它用于补全验证 run 的交付结构，不新增分析结论，不改变原始数据、对象、表格或图。",
        "",
        "## 输入与命令记录",
        f"- 输入：`{manifest.get('input_path') or manifest.get('input_h5') or manifest.get('input_h5ad') or manifest.get('source_root') or manifest.get('input_dir') or 'see run_manifest.json'}`",
        f"- Slurm job id：`{manifest.get('slurm_job_id') or (manifest.get('slurm') or {}).get('job_id') or ''}`",
        f"- 非交付原因：`{manifest.get('non_delivery_reason', '')}`",
        "",
        "## 产物摘要",
        f"- 表格数量：{len(tables)}",
        f"- 图数量：{len(figures)}",
        f"- 对象数量：{len(objects)}",
        "",
        "## 限制",
        "该 methods 文件只说明已经完成的验证运行及其产物索引。",
        "若 manifest 标记为 demo_result 或 smoke_backend，则结果不得作为正式交付或验证证据。",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
