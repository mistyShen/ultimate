from __future__ import annotations

from ultimate.modules.backend_entrypoints import validate as _validate

MODULE_NAME = "single_gene"


def validate():
    return _validate(MODULE_NAME)
