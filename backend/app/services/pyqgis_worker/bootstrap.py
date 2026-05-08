"""Bootstrap a headless QGIS environment inside the worker subprocess.

This module is *only* imported from the PyQGIS worker subprocess. The FastAPI
main process must never import it (and never import ``qgis.core``).

It performs the following steps before any ``import qgis`` call:

1. Reads ``QGIS_ROOT`` (preferring the env variable; the manager forwards
   :attr:`AppConfig.qgis_root` if set).
2. Adjusts ``sys.path`` so that ``qgis`` and the bundled ``processing``
   plugin can be imported.
3. Sets ``GDAL_DATA``, ``PROJ_LIB``, ``QT_QPA_PLATFORM=offscreen`` and
   prepends QGIS bin to ``PATH``.
4. Calls ``QgsApplication.setPrefixPath`` and ``initQgis``.
5. Initializes the QGIS Processing framework so ``processing.run`` works.

If any step fails the function raises :class:`WorkflowExecutionError` with
``QGIS_ENV_NOT_READY``.  This way the worker can return a clean error to the
main process instead of crashing.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from .errors import WorkflowExecutionError


def _candidate_subdirs() -> list[str]:
    """Common QGIS Python plugin folders on Windows installations."""
    return [
        "apps/qgis-ltr/python",
        "apps/qgis-ltr/python/plugins",
        "apps/qgis/python",
        "apps/qgis/python/plugins",
    ]


def _detect_prefix(root: Path) -> Path:
    """Pick a sensible ``QgsApplication.setPrefixPath`` value."""
    for candidate in ("apps/qgis-ltr", "apps/qgis"):
        prefix = root / candidate
        if prefix.exists():
            return prefix
    return root


def init_qgis_env(qgis_root: Optional[str] = None) -> Path:
    """Configure environment variables and ``sys.path`` for headless QGIS.

    Returns the resolved root path. Raises :class:`WorkflowExecutionError` on
    misconfiguration so callers can convert to a structured error response.
    """
    root_value = qgis_root or os.environ.get("QGIS_ROOT") or os.environ.get("WEBGIS_AI_QGIS_ROOT", "")
    root_value = (root_value or "").strip()
    if not root_value:
        raise WorkflowExecutionError(
            code="QGIS_ENV_NOT_READY",
            message="QGIS_ROOT is empty",
            user_friendly="未设置 QGIS_ROOT 环境变量，无法启动 PyQGIS Worker。",
            details={"hint": "在系统环境变量中设置 QGIS_ROOT 指向 QGIS 安装目录"},
        )
    root_path = Path(root_value)
    if not root_path.exists():
        raise WorkflowExecutionError(
            code="QGIS_ENV_NOT_READY",
            message=f"QGIS_ROOT does not exist: {root_path}",
            user_friendly=f"QGIS_ROOT 路径不存在：{root_path}",
            details={"qgis_root": str(root_path)},
        )

    # Add Python plugin paths
    for sub in _candidate_subdirs():
        candidate = (root_path / sub).resolve()
        if candidate.exists():
            sys.path.insert(0, str(candidate))

    # Environment variables
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    for env_key, sub in (
        ("GDAL_DATA", "share/gdal"),
        ("PROJ_LIB", "share/proj"),
    ):
        candidate = root_path / sub
        if candidate.exists() and not os.environ.get(env_key):
            os.environ[env_key] = str(candidate)

    bin_dir = root_path / "bin"
    if bin_dir.exists():
        os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")

    # Avoid Qt asking for a display
    os.environ.setdefault("QGIS_PREFIX_PATH", str(_detect_prefix(root_path)))
    return root_path


def start_qgis(qgis_root: Optional[str] = None):
    """Initialize ``QgsApplication`` and the Processing framework.

    Returns the live :class:`qgis.core.QgsApplication` instance. Raises
    :class:`WorkflowExecutionError` on any failure.
    """
    root = init_qgis_env(qgis_root)
    try:  # pragma: no cover - requires real QGIS
        from qgis.core import QgsApplication  # type: ignore
    except Exception as exc:  # ImportError or runtime ABI mismatch
        raise WorkflowExecutionError(
            code="QGIS_ENV_NOT_READY",
            message=f"failed to import qgis.core: {exc}",
            user_friendly="无法导入 qgis.core，请确认 QGIS_ROOT 指向正确的 QGIS 安装并使用 QGIS 自带的 Python。",
            details={"reason": repr(exc)},
        ) from exc

    prefix = _detect_prefix(root)
    QgsApplication.setPrefixPath(str(prefix), True)
    app = QgsApplication([], False)
    try:
        app.initQgis()
    except Exception as exc:  # pragma: no cover - requires real QGIS
        raise WorkflowExecutionError(
            code="QGIS_ENV_NOT_READY",
            message=f"QgsApplication.initQgis failed: {exc}",
            user_friendly="QgsApplication 初始化失败。",
            details={"reason": repr(exc)},
        ) from exc

    try:  # pragma: no cover
        from processing.core.Processing import Processing  # type: ignore

        Processing.initialize()
    except Exception as exc:  # pragma: no cover
        # Processing failure is fatal for most ops; report it but let app keep going
        raise WorkflowExecutionError(
            code="QGIS_ENV_NOT_READY",
            message=f"Processing.initialize failed: {exc}",
            user_friendly="QGIS Processing 框架初始化失败。",
            details={"reason": repr(exc)},
        ) from exc

    return app
