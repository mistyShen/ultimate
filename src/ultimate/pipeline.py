from __future__ import annotations

import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ultimate.config import dump_yaml, enabled_modules, load_config, load_samples, output_dir
from ultimate.modules import run_module
from ultimate.plot_style import generate_style_review, set_active_style_from_config
from ultimate.preflight import run_preflight
from ultimate.raw_qc import run_raw_qc
from ultimate.report import build_report


def run_pipeline_from_config(config_path: Path) -> dict[str, Any]:
    loaded = load_config(config_path)
    loaded.raw["_config_path"] = str(loaded.path)
    return run_pipeline(loaded.raw)


def run_pipeline(config: dict[str, Any]) -> dict[str, Any]:
    out_dir = output_dir(config)
    for directory in ("results/figures", "results/tables", "objects", "reports", "logs", "raw_qc"):
        (out_dir / directory).mkdir(parents=True, exist_ok=True)
    active_style = set_active_style_from_config(config)
    dump_yaml(config, out_dir / "config_snapshot.yaml")
    preflight = run_preflight(config, write=True)
    samples = load_samples(config)
    style_review = generate_style_review(out_dir / "reports" / "style_review")
    module_manifests = []
    for module_name in enabled_modules(config):
        raw_manifest = run_raw_qc(
            module_name=module_name,
            config=config,
            output_dir=out_dir,
            samples=samples,
        )
        _attach_raw_handoff(config, module_name, raw_manifest)
        module_manifest = run_module(
            module_name=module_name,
            config=config,
            output_dir=out_dir,
            samples=samples,
        )
        module_manifest["raw_qc"] = raw_manifest
        module_manifests.append(module_manifest)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project": config.get("project", {}),
        "output_dir": str(out_dir),
        "python": {
            "version": sys.version.split()[0],
            "executable": sys.executable,
            "platform": platform.platform(),
        },
        "preflight": preflight,
        "figure_style": active_style,
        "style_review": style_review,
        "modules": module_manifests,
        "artifacts_root": {
            "figures": str(out_dir / "results" / "figures"),
            "tables": str(out_dir / "results" / "tables"),
            "objects": str(out_dir / "objects"),
            "reports": str(out_dir / "reports"),
            "logs": str(out_dir / "logs"),
        },
    }
    manifest_path = out_dir / "run_manifest.json"
    manifest["run_manifest_path"] = str(manifest_path)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    report_manifest = build_report(out_dir)
    manifest["report"] = report_manifest
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def _attach_raw_handoff(config: dict[str, Any], module_name: str, raw_manifest: dict[str, Any]) -> None:
    module_cfg = (config.get("modules") or {}).setdefault(module_name, {})
    current = module_cfg.get("input_matrix")
    if current and Path(current).exists():
        return
    standard_matrix = ((raw_manifest.get("artifacts") or {}).get("objects") or {}).get("standard_matrix")
    if standard_matrix and Path(standard_matrix).exists():
        module_cfg["input_matrix"] = standard_matrix
