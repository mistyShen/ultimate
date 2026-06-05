#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser(description="Write an Ultimate v3 backend-readiness status report.")
    parser.add_argument("--root", type=Path, required=True, help="Ultimate project root.")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory for v3_status_report.md.")
    parser.add_argument(
        "--production-audit",
        type=Path,
        default=None,
        help="Optional production_audit.json. Defaults to <root>/audits/production_latest/production_audit.json.",
    )
    args = parser.parse_args()
    report_path = write_v3_status_report(
        root=args.root,
        output_dir=args.output_dir,
        production_audit=args.production_audit,
    )
    print(json.dumps({"v3_status_report": str(report_path)}, indent=2, ensure_ascii=False))


def write_v3_status_report(*, root: Path, output_dir: Path, production_audit: Path | None = None) -> Path:
    root = root.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    audit_path = production_audit or root / "audits" / "production_latest" / "production_audit.json"
    audit = _read_json(audit_path)
    backend_rows = _read_tsv(Path(str(audit.get("backend_maturity_table") or output_dir / "missing.tsv")))
    module_rows = _read_tsv(Path(str(audit.get("module_maturity_table") or output_dir / "missing.tsv")))
    final_rows = _read_tsv(Path(str(audit.get("final_acceptance_checklist") or output_dir / "missing.tsv")))

    backend_summary = _count_by(backend_rows, "backend_status")
    maturity_summary = _count_by(backend_rows, "maturity_level")
    automatic = [row for row in backend_rows if str(row.get("backend_status") or "").startswith("fully_automatic")]
    planned = [row for row in backend_rows if str(row.get("backend_status") or "").startswith("planned")]
    handoff = [row for row in backend_rows if str(row.get("backend_status") or "") == "handoff_ready"]
    licensed = [row for row in backend_rows if str(row.get("backend_status") or "") == "licensed_path_detection"]
    report_path = output_dir / "v3_status_report.md"
    report_path.write_text(
        "\n".join(
            [
                "# Ultimate V3 Backend Status Report",
                "",
                f"- 生成时间：`{datetime.now(timezone.utc).isoformat()}`",
                f"- 项目根目录：`{root}`",
                f"- production audit：`{audit_path}`",
                "",
                "## 总览",
                "",
                f"- backend 总数：`{len(backend_rows)}`",
                f"- fully automatic / validated entrypoint：`{len(automatic)}`",
                f"- planned fully automatic：`{len(planned)}`",
                f"- handoff backend：`{len(handoff)}`",
                f"- licensed path detection：`{len(licensed)}`",
                f"- backend_status 汇总：`{json.dumps(backend_summary, ensure_ascii=False, sort_keys=True)}`",
                f"- maturity_level 汇总：`{json.dumps(maturity_summary, ensure_ascii=False, sort_keys=True)}`",
                "",
                "## 已可自动运行的 MVP/入口",
                "",
                _backend_list(automatic),
                "",
                "## V3 planned 后端缺口",
                "",
                _backend_gap_list(planned),
                "",
                "## Handoff / Licensed",
                "",
                _backend_list(handoff + licensed),
                "",
                "## 模块成熟度摘要",
                "",
                _module_list(module_rows),
                "",
                "## acceptance gate",
                "",
                _final_list(final_rows),
                "",
                "## V3 声明边界",
                "",
                "- `fully_automatic_mvp` 只代表当前 MVP 输入契约可自动跑，不代表所有高级算法已接入。",
                "- `planned_fully_automatic` 不能作为正式后端宣传，必须补 runner、pytest、Slurm validation、report warning 后才可升级。",
                "- `licensed_path_detection` 只能检测/调用用户提供路径，不能伪装成开源自动后端。",
                "- `production_backend` 仍必须经过 approval gate；validated_backend 只代表验证证据。",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return report_path


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _read_tsv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _count_by(rows: list[dict[str, str]], column: str) -> dict[str, int]:
    summary: dict[str, int] = {}
    for row in rows:
        key = row.get(column) or "missing"
        summary[key] = summary.get(key, 0) + 1
    return summary


def _backend_list(rows: list[dict[str, str]]) -> str:
    if not rows:
        return "- none"
    return "\n".join(
        f"- `{row.get('backend_id')}`：{row.get('backend_status')}；module=`{row.get('module')}`；preset=`{row.get('preset')}`；tool=`{row.get('tool')}`"
        for row in rows
    )


def _backend_gap_list(rows: list[dict[str, str]]) -> str:
    if not rows:
        return "- none"
    return "\n".join(
        f"- `{row.get('backend_id')}`：{row.get('skip_reason') or row.get('next_required_evidence') or 'next evidence not recorded'}"
        for row in rows
    )


def _module_list(rows: list[dict[str, str]]) -> str:
    if not rows:
        return "- module maturity table missing"
    return "\n".join(
        f"- `{row.get('module_name')}`：{row.get('maturity_level')}；validation={row.get('public_validation_status')}；next={row.get('next_required_backend')}"
        for row in rows
    )


def _final_list(rows: list[dict[str, str]]) -> str:
    if not rows:
        return "- final acceptance checklist missing"
    selected = [row for row in rows if str(row.get("requirement") or "").startswith("v3_")]
    if not selected:
        selected = rows
    return "\n".join(f"- `{row.get('requirement')}`：{row.get('status')}；{row.get('evidence')}" for row in selected)


if __name__ == "__main__":
    main()
