"""Structured error types for the PyQGIS worker.

These error codes are stable strings exposed to the frontend so it can
render localized, user-friendly messages.  Always include a ``user_friendly``
field on errors that originate inside the worker so the frontend has
something safe to display.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


WORKFLOW_ERROR_CODES = (
    "AI_PARSE_FAILED",
    "VALIDATION_FAILED",
    "QGIS_ENV_NOT_READY",
    "DATASET_NOT_FOUND",
    "FIELD_NOT_FOUND",
    "FIELD_TYPE_MISMATCH",
    "GEOMETRY_INVALID",
    "CRS_NOT_SUPPORTED",
    "PROCESSING_FAILED",
    "WORKER_CRASHED",
    "EXPORT_FAILED",
    "UNKNOWN_OP",
    "REFERENCE_NOT_RESOLVED",
    "INTERNAL_ERROR",
)

#: Default user-friendly messages keyed by error code.  Worker handlers
#: should override ``user_friendly`` whenever they have richer context.
DEFAULT_USER_FRIENDLY = {
    "AI_PARSE_FAILED": "AI 输出无法解析为有效 workflow，请重新描述需求。",
    "VALIDATION_FAILED": "工作流校验未通过，请查看错误详情。",
    "QGIS_ENV_NOT_READY": "当前未检测到可用 QGIS 环境，请检查 QGIS_ROOT、GDAL_DATA、PROJ_LIB 和 PATH。",
    "DATASET_NOT_FOUND": "找不到指定的数据集，请确认数据已上传或选择其他数据。",
    "FIELD_NOT_FOUND": "图层中找不到所需字段。",
    "FIELD_TYPE_MISMATCH": "字段类型不符合操作要求。",
    "GEOMETRY_INVALID": "图层几何无效，请先执行 fix_geometries 修复。",
    "CRS_NOT_SUPPORTED": "图层坐标系不适合该操作，请重投影后再试。",
    "PROCESSING_FAILED": "QGIS Processing 算法执行失败，请查看日志。",
    "WORKER_CRASHED": "PyQGIS Worker 进程异常退出，请重新提交任务。",
    "EXPORT_FAILED": "导出文件失败。",
    "UNKNOWN_OP": "尚未实现的工作流操作。",
    "REFERENCE_NOT_RESOLVED": "上游步骤未提供所需输出。",
    "INTERNAL_ERROR": "系统内部错误，请重试。",
}


class WorkflowExecutionError(Exception):
    """Raised by handlers / executor to signal a structured workflow failure."""

    def __init__(
        self,
        code: str,
        message: str = "",
        user_friendly: str = "",
        step_id: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message or DEFAULT_USER_FRIENDLY.get(code, code))
        self.code = code
        self.message = message or str(self)
        self.user_friendly = user_friendly or DEFAULT_USER_FRIENDLY.get(code, self.message)
        self.step_id = step_id
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "user_friendly": self.user_friendly,
            "step_id": self.step_id,
            "details": dict(self.details),
        }


def make_error(
    code: str,
    message: str = "",
    user_friendly: str = "",
    step_id: str = "",
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Helper that builds the standardized error payload as a plain dict."""
    if code not in WORKFLOW_ERROR_CODES:
        code = "INTERNAL_ERROR"
    return {
        "code": code,
        "message": message or DEFAULT_USER_FRIENDLY.get(code, code),
        "user_friendly": user_friendly or DEFAULT_USER_FRIENDLY.get(code, message or code),
        "step_id": step_id,
        "details": dict(details or {}),
    }
