"""Public assistant profiles. Input channel never grants tool capabilities."""
from __future__ import annotations
from .interaction_run import current_run

ALIASES = {"": "chat", "chat": "chat", "knowledge": "chat", "teaching": "chat", "operate": "operate", "tool": "operate", "interaction": "operate"}

def normalize_mode(value: str) -> str:
    try:
        return ALIASES[value]
    except (KeyError, TypeError):
        raise ValueError("assistant_mode 必须是 chat 或 operate")

def active_mode() -> str:
    run = current_run()
    return run.mode if run else ""

def tool_allowed(name: str, mode: str = "") -> bool:
    mode = mode or active_mode()
    if mode == "chat":
        return name in {"generate_image", "web_search"}
    if mode == "operate":
        return name not in {"generate_image", "draft_teaching", "web_search"}
    return True  # internal legacy services are not public profile entry points

def require_tool(name: str) -> None:
    if not tool_allowed(name):
        raise ValueError(f"{active_mode()} 模式不允许调用 {name}；请显式切换模式或打开独立教案设计。")

def bind_conversation(store, project_id: str, mode: str, conversation_id: str, actor: str):
    if conversation_id:
        conversation = store.get_conversation(conversation_id)
        if conversation is None or conversation.deleted_at:
            raise KeyError("Unknown conversation")
        if conversation.project_id != project_id or conversation.assistant_mode != mode or conversation.owner_user_id != actor:
            raise ValueError("会话的用户、项目或模式不匹配；旧混合会话仅供阅读，请新建会话。")
        return conversation
    conversation = store.create_conversation(project_id, mode)
    conversation.owner_user_id = actor
    store.save_conversation(conversation)
    return conversation
