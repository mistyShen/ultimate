from __future__ import annotations

from pathlib import Path

from ultimate.config import load_config
from ultimate.demo import init_project
from ultimate.preflight import run_preflight


def test_preflight_reports_modules(tmp_path: Path) -> None:
    manifest = init_project("all", tmp_path / "demo_all", demo_data=True)
    loaded = load_config(Path(manifest["config_path"]))
    preflight = run_preflight(loaded.raw, write=True)
    assert preflight["status"] in {"ready", "ready_with_warnings"}
    assert len(preflight["modules"]) >= 13
    assert Path(preflight["manifest_path"]).exists()
