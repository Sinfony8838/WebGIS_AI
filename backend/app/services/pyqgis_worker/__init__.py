"""PyQGIS Worker subsystem.

The package provides a sub-process that hosts QgsApplication and executes
workflow steps, plus a manager class that lives in the FastAPI main process
and talks to the worker via ``multiprocessing.Queue``.

The FastAPI main process must NEVER import ``qgis.core``.  All QGIS imports
are deferred to the worker subprocess (see :mod:`bootstrap` and
:mod:`worker_main`).
"""

from .errors import WORKFLOW_ERROR_CODES, WorkflowExecutionError  # noqa: F401
from .worker_manager import PyQgisWorkerManager  # noqa: F401
