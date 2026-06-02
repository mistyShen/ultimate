from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape


TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


def build_report(run_dir: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    manifest_path = run_dir / "run_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing run manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    reports_dir = run_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    context = {
        "manifest": manifest,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "modules": manifest.get("modules", []),
        "preflight": manifest.get("preflight", {}),
    }
    html = _render("report.html.j2", context)
    methods = _render("methods.md.j2", context)
    html_path = reports_dir / "report.html"
    methods_path = reports_dir / "methods.md"
    report_manifest_path = reports_dir / "report_manifest.json"
    html_path.write_text(html, encoding="utf-8")
    methods_path.write_text(methods, encoding="utf-8")
    report_manifest = {
        "generated_at": context["generated_at"],
        "html_report": str(html_path),
        "methods_md": str(methods_path),
        "source_manifest": str(manifest_path),
    }
    report_manifest_path.write_text(json.dumps(report_manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    report_manifest["manifest_path"] = str(report_manifest_path)
    return report_manifest


def _render(template_name: str, context: dict[str, Any]) -> str:
    environment = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(enabled_extensions=("html", "xml")),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return environment.get_template(template_name).render(**context)
