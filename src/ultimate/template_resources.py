from __future__ import annotations

import os
import sys
from pathlib import Path


def template_root_candidates() -> list[Path]:
    """Return template roots in lookup order for source and installed runs."""

    candidates: list[Path] = []
    env_root = os.environ.get("ULTIMATE_TEMPLATE_ROOT")
    if env_root:
        candidates.append(Path(env_root).expanduser())
    package_root = Path(__file__).resolve().parent
    project_root = Path(__file__).resolve().parents[2]
    candidates.extend(
        [
            project_root / "templates",
            package_root / "templates",
            Path(sys.prefix) / "share" / "ultimate" / "templates",
        ]
    )
    seen: set[Path] = set()
    unique: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve() if candidate.exists() else candidate
        if resolved not in seen:
            seen.add(resolved)
            unique.append(candidate)
    return unique


def find_template_dir(*parts: str, required: bool = False) -> Path | None:
    """Find a template directory without assuming checkout-only paths."""

    searched = []
    for root in template_root_candidates():
        candidate = root.joinpath(*parts)
        searched.append(str(candidate))
        if candidate.exists() and candidate.is_dir():
            return candidate
    if required:
        joined = ", ".join(searched)
        raise FileNotFoundError(f"Ultimate template directory not found for {'/'.join(parts) or '<root>'}. Searched: {joined}")
    return None


def template_lookup_status(*parts: str) -> dict[str, str]:
    path = find_template_dir(*parts, required=False)
    return {
        "status": "ready" if path else "missing",
        "path": str(path or ""),
        "searched": ";".join(str(root.joinpath(*parts)) for root in template_root_candidates()),
    }
