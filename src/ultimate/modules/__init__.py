from __future__ import annotations

def run_module(*args, **kwargs):
    from ultimate.modules.runner import run_module as _run_module

    return _run_module(*args, **kwargs)


__all__ = ["run_module"]
