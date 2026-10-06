"""Read-only guards for assistant references to classroom resources."""
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Dict, Optional

from ..models import ClassSessionRecord, LessonRecord
from ..store import RuntimeStore


_assistant_role: ContextVar[str] = ContextVar("assistant_server_role", default="")


@contextmanager
def assistant_actor_scope(role: str):
    """Carry the server-authenticated role through synchronous tool callbacks.

    The value is never read from map context or a persisted plan. ContextVar
    keeps simultaneous workers isolated; reset also runs on failed turns.
    """
    token = _assistant_role.set(role)
    try:
        yield
    finally:
        _assistant_role.reset(token)


def require_project_lesson(
    store: RuntimeStore, project_id: str, lesson_id: str, *, actor_role: Optional[str] = None,
) -> LessonRecord:
    project = store.get_project(project_id)
    if project is None:
        raise KeyError(f"Unknown project: {project_id}")
    lesson = store.get_lesson(lesson_id)
    role = _assistant_role.get() if actor_role is None else actor_role
    if lesson is None or (
        lesson.source != "builtin" and role != "admin"
        and lesson.owner_user_id != project.owner_user_id
    ):
        # Match the HTTP lesson policy without disclosing another teacher's ID.
        raise KeyError(f"Unknown lesson: {lesson_id}")
    return lesson


def require_context_lesson(
    store: RuntimeStore, project_id: str, map_context: Optional[Dict[str, Any]],
    *, actor_role: Optional[str] = None,
) -> None:
    session = require_classroom_context(store, project_id, map_context)
    context = (map_context or {}).get("teaching_context")
    lesson_id = str(context.get("lesson_id") or "").strip() if isinstance(context, dict) else ""
    if lesson_id and session is None:
        require_project_lesson(store, project_id, lesson_id, actor_role=actor_role)


def require_confirmation_lessons(
    store: RuntimeStore, project_id: str, payload: Dict[str, Any],
    *, actor_role: Optional[str] = None,
) -> None:
    plans = [payload]
    if isinstance(payload.get("frozen_plan"), dict):
        plans.append(payload["frozen_plan"])
    for plan in plans:
        require_context_lesson(store, project_id, plan.get("map_context"), actor_role=actor_role)
        for action in plan.get("actions") or []:
            if action.get("tool_name") == "start_class_session":
                lesson_id = str((action.get("tool_params") or {}).get("lesson_id") or "").strip()
                if lesson_id:
                    require_project_lesson(store, project_id, lesson_id, actor_role=actor_role)


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
