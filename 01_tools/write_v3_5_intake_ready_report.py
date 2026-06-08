#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def _load_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"manifest_path": str(path), "status": "unreadable"}
    payload.setdefault("manifest_path", str(path))
    return payload


def build_report(root: Path, output_dir: Path) -> dict:
    root = root.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    triage_manifests = [_load_json(path) for path in sorted(root.glob("**/triage_manifest.json")) if ".conda" not in path.parts]
    status_counts = Counter(str(item.get("status", "unknown")) for item in triage_manifests)
    handoff_required = sum(1 for item in triage_manifests if (item.get("input_summary") or {}).get("handoff_required") is True)
    ready_to_run = [item for item in triage_manifests if item.get("status") == "ready_to_run"]
    needs_action = [item for item in triage_manifests if item.get("status") != "ready_to_run"]

    lines = [
        "# Ultimate V3.5 intake readiness report",
        "",
        f"- generated_at: `{datetime.now(timezone.utc).isoformat()}`",
        f"- root: `{root}`",
        f"- triage_manifest_count: `{len(triage_manifests)}`",
        f"- handoff_required_count: `{handoff_required}`",
        "",
        "## Status summary",
        "",
        "| status | count |",
        "|---|---:|",
    ]
    for status, count in sorted(status_counts.items()):
        lines.append(f"| {status} | {count} |")

    lines.extend(["", "## Ready to run", ""])
    if ready_to_run:
        for item in ready_to_run:
            lines.append(f"- `{item.get('request_path', '')}` -> `{item.get('suggested_project_yaml', '')}`")
    else:
        lines.append("- none")

    lines.extend(["", "## Needs action", ""])
    if needs_action:
        for item in needs_action:
            summary = item.get("input_summary") or {}
            lines.append(
                f"- `{item.get('status', 'unknown')}` `{item.get('request_path', '')}` "
                f"handoff_required=`{str(summary.get('handoff_required', False)).lower()}` "
                f"missing=`{item.get('missing_requirements', '')}`"
            )
    else:
        lines.append("- none")

    lines.extend(
        [
            "",
            "## Boundaries",
            "",
            "- This report summarizes triage evidence only.",
            "- Triage does not create production evidence, does not start Slurm jobs, and does not allow delivery.",
            "- Customer delivery still requires `production_backend`, approval JSON, Slurm execution, and `delivery-check`.",
        ]
    )
    report_path = output_dir / "v3_5_intake_ready_report.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "output_dir": str(output_dir),
        "triage_manifest_count": len(triage_manifests),
        "status_counts": dict(sorted(status_counts.items())),
        "handoff_required_count": handoff_required,
        "report": str(report_path),
    }
    manifest_path = output_dir / "v3_5_intake_ready_manifest.json"
    manifest["manifest_path"] = str(manifest_path)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Write Ultimate V3.5 intake readiness report.")
    parser.add_argument("--root", type=Path, default=Path("/shared/shen/2026/ultimate"))
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    output_dir = args.output_dir or args.root / "reports"
    print(json.dumps(build_report(args.root, output_dir), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
