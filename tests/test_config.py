from __future__ import annotations

from pathlib import Path

from ultimate.config import enabled_modules, load_config
from ultimate.demo import init_project


def test_init_project_and_load_config(tmp_path: Path) -> None:
    manifest = init_project("rnaseq", tmp_path / "demo", demo_data=True)
    loaded = load_config(Path(manifest["config_path"]))
    assert loaded.raw["project"]["organism"] == "human"
    assert enabled_modules(loaded.raw) == ["rnaseq"]
    assert Path(loaded.raw["modules"]["rnaseq"]["input_matrix"]).exists()
