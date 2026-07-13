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


def _load_env_file(env_path: Path) -> dict[str, str]:
    """Parse the OSGeo4W ``qgis-ltr-bin.env`` style file.

    Each non-empty, non-comment line is ``KEY=VALUE``. Returns the dict so
    callers can decide which keys to apply (we generally want all of them
    except ones the parent has already customised).
    """
    result: dict[str, str] = {}
    try:
        text = env_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return result
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key:
            result[key] = value.strip()
    return result


def init_qgis_env(qgis_root: Optional[str] = None) -> Path:
    """Configure environment variables and ``sys.path`` for headless QGIS.

    Returns the resolved root path. Raises :class:`WorkflowExecutionError` on
    misconfiguration so callers can convert to a structured error response.

    On a standard OSGeo4W install the QGIS installer ships a `bin/*-bin.env`
    file (e.g. ``qgis-ltr-bin.env`` for the LTR build) that lists every
    PATH / PYTHONHOME / QT_PLUGIN_PATH / GDAL_DATA / PROJ_DATA value the
    bundled python.exe needs. We prefer to load that file verbatim because
    it's QGIS's own source of truth and survives version-to-version layout
    drift; we only synthesise the values manually if no env file is found.
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

    # Always run Qt headless inside the worker subprocess.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    # 1) Preferred path: replay the official QGIS env file. We try the LTR
    # variant first because it matches our preferred sys.path layout, then
    # fall back to the rolling release file name. PATH is treated specially
    # because we want to prepend rather than overwrite the host PATH.
    env_dir = root_path / "bin"
    env_file: Optional[Path] = None
    for candidate_name in ("qgis-ltr-bin.env", "qgis-bin.env"):
        candidate = env_dir / candidate_name
        if candidate.exists():
            env_file = candidate
            break

    applied_from_env_file = False
    if env_file is not None:
        env_pairs = _load_env_file(env_file)
        for key, value in env_pairs.items():
            if not value:
                continue
            if key == "PATH":
                os.environ["PATH"] = value + os.pathsep + os.environ.get("PATH", "")
                continue
            # The env file is authoritative for QGIS-bundled paths (PYTHONHOME,
            # QT_PLUGIN_PATH, GDAL_DATA, PROJ_DATA, …). Override anything the
            # host might have set so we don't accidentally use the system
            # Python's site-packages for PyQt5 etc.
            os.environ[key] = value
        applied_from_env_file = True

    # 2) Fallback: replicate the minimum set if no env file shipped.
    if not applied_from_env_file:
        for env_key, sub in (
            ("GDAL_DATA", "share/gdal"),
            ("PROJ_LIB", "share/proj"),
            ("PROJ_DATA", "share/proj"),
        ):
            candidate = root_path / sub
            if candidate.exists() and not os.environ.get(env_key):
                os.environ[env_key] = str(candidate)
        bin_dir = root_path / "bin"
        if bin_dir.exists():
            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")

    # Always make sure the QGIS Python plugin paths are on sys.path, even
    # when the env file already set PYTHONPATH (which only affects child
    # processes, not the live interpreter).
    for sub in _candidate_subdirs():
        candidate = (root_path / sub).resolve()
        if candidate.exists():
            sys.path.insert(0, str(candidate))

    # PYTHONHOME from the env file sets the QGIS-bundled Python prefix, but
    # the live interpreter has already cached sys.prefix. Make sure the
    # bundled site-packages is reachable via sys.path so PyQt5 imports work
    # even when this module is loaded under a non-QGIS parent Python during
    # tests.
    site_packages = root_path / "apps" / "Python312" / "Lib" / "site-packages"
    if site_packages.exists() and str(site_packages) not in sys.path:
        sys.path.insert(0, str(site_packages))

    # Standardise the prefix for QgsApplication.setPrefixPath later on.
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
