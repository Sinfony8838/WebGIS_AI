"""Project-bound image references shared by assistant and vision boundaries."""
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import AppConfig
from ..store import RuntimeStore


SUPPORTED_IMAGE_MIME_BY_SUFFIX = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".gif": "image/gif",
}


def detect_image_mime(raw_bytes: bytes) -> str:
    if raw_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if raw_bytes.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(raw_bytes) >= 12 and raw_bytes[:4] == b"RIFF" and raw_bytes[8:12] == b"WEBP":
        return "image/webp"
    return ""


def resolve_project_image(
    config: AppConfig, store: RuntimeStore, project_id: str, reference: Dict[str, Any],
) -> Dict[str, Any]:
    if store.get_project(project_id) is None:
        raise KeyError(f"Unknown project: {project_id}")
    if any(char in project_id for char in ("/", "\\", ":")) or project_id in {".", ".."}:
        raise ValueError("Invalid project image directory")
    if not isinstance(reference, dict):
        raise ValueError("图片引用必须是包含 artifact_id 的对象。")
    artifact_id = str(reference.get("artifact_id") or "").strip()
    if not artifact_id:
        raise ValueError("图片附件缺少 artifact_id。")
    artifact = store.get_artifact(artifact_id)
    if artifact is None:
        raise KeyError(f"Unknown artifact: {artifact_id}")
    if artifact.project_id != project_id:
        raise ValueError("不能使用其他项目的图片。")
    if artifact.artifact_type not in {"map_snapshot", "uploaded_image", "generated_image"}:
        raise ValueError("该产物不是可识别的图片。")
    # Never resolve, stat or open a client-supplied path. Resolve the registry
    # path against physical data roots, then retain the project component so
    # an internal project-directory link cannot redirect to another project.
    path = Path(artifact.path).resolve()
    roots = (config.uploads_dir.resolve() / project_id, config.outputs_dir.resolve() / project_id)
    if not any(path.is_relative_to(root) for root in roots):
        raise ValueError("图片路径不在允许的项目目录中。")
    expected = SUPPORTED_IMAGE_MIME_BY_SUFFIX.get(path.suffix.lower())
    if not expected or not path.is_file():
        raise ValueError("图片文件不存在或格式不受支持。")
    with path.open("rb") as image_file:
        detected = detect_image_mime(image_file.read(32))
    if detected != expected:
        raise ValueError("图片文件内容与格式不一致。")
    return {
        "artifact_id": artifact.artifact_id, "title": artifact.title, "path": str(path),
        "public_url": str(artifact.metadata.get("public_url") or config.public_url_for_path(path)),
        "mime_type": detected,
    }


def resolve_image_list(
    config: AppConfig, store: RuntimeStore, project_id: str, references: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not isinstance(references, list) or len(references) > 1:
        raise ValueError("每条消息暂时只能附加一张图片。")
    return [resolve_project_image(config, store, project_id, item) for item in references]


def resolve_image_context(
    config: AppConfig, store: RuntimeStore, project_id: str, map_context: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    context = dict(map_context or {})
    attachments = resolve_image_list(config, store, project_id, context.get("image_attachments") or [])
    single = context.get("image_attachment")
    resolved_single = resolve_project_image(config, store, project_id, single) if single else None
    chosen = attachments[0] if attachments else resolved_single
    if chosen is not None:
        context["image_attachments"] = [chosen]
        context["image_attachment"] = chosen
        # A new provider result, rather than stale/client-provided image text,
        # supplies the visual answer. This does not alter classroom statistics.
        for key in ("vision_used", "vision_summary", "vision_result", "vision_reason",
                    "vision_provider", "vision_snapshot_path"):
            context.pop(key, None)
    return context


def require_confirmation_images(
    config: AppConfig, store: RuntimeStore, project_id: str, payload: Dict[str, Any],
) -> None:
    resolve_image_context(config, store, project_id, payload.get("map_context"))
    frozen = payload.get("frozen_plan")
    if isinstance(frozen, dict):
        resolve_image_context(config, store, project_id, frozen.get("map_context"))
