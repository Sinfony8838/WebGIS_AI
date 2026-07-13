"""PyQGIS handlers — one module per workflow operation.

Each module exposes ``execute(params, workspace) -> dict``. Handlers are
responsible for resolving ``${stepId.key}`` references via
``workspace.resolve_reference``.

All handlers run inside the worker subprocess. They may import ``qgis.core``
and ``processing`` freely.
"""
