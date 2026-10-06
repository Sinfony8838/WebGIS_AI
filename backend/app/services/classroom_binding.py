"""Read-only guards for assistant references to classroom resources."""
from typing import Any, Dict, Optional

from ..models import ClassSessionRecord
from ..store import RuntimeStore


def require_project_session(
    store: RuntimeStore, project_id: str, session_id: str,
) -> ClassSessionRecord:
    session = store.get_class_session(session_id)
    if session is None:
        raise KeyError(f"Unknown class session: {session_id}")
    if session.project_id != project_id:
        raise ValueError("Class session does not belong to the requested project")
    return session


def require_classroom_context(
    store: RuntimeStore, project_id: str, map_context: Optional[Dict[str, Any]],
) -> Optional[ClassSessionRecord]:
    context = (map_context or {}).get("teaching_context")
    if not isinstance(context, dict):
        return None
    context_project = str(context.get("project_id") or "").strip()
    if context_project and context_project != project_id:
        raise ValueError("Teaching context does not belong to the requested project")
    session_id = str(context.get("session_id") or "").strip()
    if not session_id:
        return None
    session = require_project_session(store, project_id, session_id)
    lesson_id = str(context.get("lesson_id") or "").strip()
    if lesson_id and lesson_id != session.lesson_id:
        raise ValueError("Teaching context lesson does not match the class session")
    # Ended sessions remain valid for reflection; callers that mutate a live
    # class retain their existing status checks. Historical snapshots need not
    # have a corresponding lesson still present in the global lesson registry.
    return session


def require_confirmation_classroom(
    store: RuntimeStore, project_id: str, payload: Dict[str, Any],
) -> None:
    require_classroom_context(store, project_id, payload.get("map_context"))
    frozen = payload.get("frozen_plan")
    if isinstance(frozen, dict):
        require_classroom_context(store, project_id, frozen.get("map_context"))
