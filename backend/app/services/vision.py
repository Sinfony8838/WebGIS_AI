"""Map screenshot → AI lecture-script via an LLM vision backend.

v1.2 supports two provider paths:

* ``vision_provider = "mimo"`` — direct OpenAI-compatible chat completion
  to Xiaomi MiMo with a multimodal ``content`` array
  (``[{type:"text"}, {type:"image_url"}]``). No subprocess; reuses
  ``LLMClient`` and the same ``WEBGIS_AI_MIMO_API_KEY``.
* ``vision_provider = "minimax_mcp"`` — legacy: spawns the MiniMax Token
  Plan MCP subprocess and calls ``understand_image``. Kept for users on
  ``WEBGIS_AI_LLM_PROVIDER=minimax``.

Selection is driven by :attr:`AppConfig.vision_provider` which auto-tracks
``llm_provider`` unless the user explicitly sets
``WEBGIS_AI_VISION_PROVIDER``.

The public contract :meth:`MapVisionService.understand_map` is unchanged:
return ``{used_vision, snapshot_path, summary?, reason?, provider?}``.
"""
from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any, Dict, Optional

from ..config import AppConfig
from ..models import ProjectRecord
from .minimax_client import LLMClient
from .minimax_mcp_client import MiniMaxMcpClient, MiniMaxMcpError


DATA_URL_RE = re.compile(r"^data:image/(png|jpeg|jpg|webp);base64,", re.IGNORECASE)

# Image-mime mapping used when re-encoding the saved snapshot back into a
# data URL for the OpenAI-style ``image_url`` content block.
_SUFFIX_TO_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


class MapVisionService:
    """Saves map screenshots and delegates visual reading to the configured backend."""

    def __init__(
        self,
        config: AppConfig,
        mcp_client: Optional[MiniMaxMcpClient] = None,
        llm_client: Optional[LLMClient] = None,
    ):
        self.config = config
        # Lazily-constructed clients: only the active provider actually runs.
        self.mcp_client = mcp_client or MiniMaxMcpClient(config)
        self.llm_client = llm_client or LLMClient(config)

    def status(self) -> Dict[str, Any]:
        return self.config.vision_status()

    def save_snapshot(self, project_id: str, screen_snapshot: Dict[str, Any]) -> Optional[Path]:
        image_data_url = str(screen_snapshot.get("image_data_url") or "")
        if not image_data_url or not DATA_URL_RE.match(image_data_url):
            return None
        _, encoded = image_data_url.split(",", 1)
        raw = base64.b64decode(encoded.encode("utf-8"))
        output_dir = self.config.project_output_dir(project_id) / "vision"
        output_dir.mkdir(parents=True, exist_ok=True)
        path = self.config.unique_path(output_dir, "map_screen.png")
        path.write_bytes(raw)
        return path

    def understand_map(
        self,
        project_id: str,
        project: ProjectRecord,
        map_context: Dict[str, Any],
        focus: str = "",
        screen_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        snapshot_path = self.save_snapshot(project_id, screen_snapshot or {})
        status = self.status()
        provider = self.config.vision_provider

        if snapshot_path is None:
            return {
                "used_vision": False,
                "snapshot_path": "",
                "reason": "未收到可用的课堂地图截图，已回退到结构化地图上下文读图。",
            }

        if not status.get("configured"):
            return {
                "used_vision": False,
                "snapshot_path": str(snapshot_path),
                "reason": self._not_configured_message(provider),
            }

        prompt = self._build_prompt(project, map_context, focus)

        if provider == "mimo":
            return self._understand_via_mimo(snapshot_path, prompt)
        if provider == "minimax_mcp":
            return self._understand_via_mcp(snapshot_path, prompt)
        return {
            "used_vision": False,
            "snapshot_path": str(snapshot_path),
            "reason": (
                f"未配置受支持的视觉读图后端（vision_provider={provider}），"
                "已回退到结构化地图上下文读图。"
            ),
        }

    # ------------------------------------------------------------------
    # Provider backends
    # ------------------------------------------------------------------

    def _understand_via_mimo(self, snapshot_path: Path, prompt: str) -> Dict[str, Any]:
        try:
            data_url = self._snapshot_to_data_url(snapshot_path)
        except OSError as exc:
            return {
                "used_vision": False,
                "snapshot_path": str(snapshot_path),
                "reason": f"读取截图失败：{exc}",
            }

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ]
        try:
            text = self.llm_client.chat_completion(
                messages,
                temperature=0.3,
                model=self.config.vision_model or "mimo-v2.5",
                timeout=60.0,
            )
        except RuntimeError as exc:
            return {
                "used_vision": False,
                "snapshot_path": str(snapshot_path),
                "reason": f"Xiaomi MiMo 多模态读图调用失败，已回退到结构化地图上下文读图：{exc}",
            }
        return {
            "used_vision": True,
            "snapshot_path": str(snapshot_path),
            "provider": "mimo",
            "summary": text,
            "raw": {},
        }

    def _understand_via_mcp(self, snapshot_path: Path, prompt: str) -> Dict[str, Any]:
        try:
            result = self.mcp_client.understand_image(prompt=prompt, image_url=str(snapshot_path))
        except MiniMaxMcpError as exc:
            return {
                "used_vision": False,
                "snapshot_path": str(snapshot_path),
                "reason": (
                    f"MiniMax Token Plan MCP 图片理解调用失败，已回退到结构化地图上下文读图：{exc}"
                ),
            }
        return {
            "used_vision": True,
            "snapshot_path": str(snapshot_path),
            "provider": "minimax_mcp",
            "summary": result.get("text", ""),
            "raw": result.get("raw", {}),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _snapshot_to_data_url(self, snapshot_path: Path) -> str:
        suffix = snapshot_path.suffix.lower()
        mime = _SUFFIX_TO_MIME.get(suffix, "image/png")
        encoded = base64.b64encode(snapshot_path.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{encoded}"

    def _not_configured_message(self, provider: str) -> str:
        if provider == "mimo":
            return (
                "未配置 Xiaomi MiMo 多模态读图（需要 WEBGIS_AI_MIMO_API_KEY + "
                "WEBGIS_AI_VISION_ENABLED=1），已回退到结构化地图上下文读图。"
            )
        if provider == "minimax_mcp":
            return "未配置 MiniMax Token Plan MCP 图片理解，已回退到结构化地图上下文读图。"
        return f"未配置受支持的视觉读图后端（vision_provider={provider}），已回退到结构化地图上下文读图。"

    def _build_prompt(self, project: ProjectRecord, map_context: Dict[str, Any], focus: str = "") -> str:
        visible_layers = map_context.get("visible_layers") or []
        if not visible_layers:
            visible_layers = [layer.name for layer in project.layers if layer.visible][:6]
        return "\n".join(
            [
                "请作为专业地理教师直接读取这张课堂地图截图。",
                "请识别地图主题、图例含义、主要空间分布、高值区/低值区、空间差异原因和课堂讲解要点。",
                "回答要面向课堂讲解，优先给出可直接朗读的中文讲解稿。",
                "不要说“我没有看到图片”，除非图片确实无法识别。",
                f"用户关注点：{focus or '读图讲解'}",
                f"当前项目：{project.name}",
                (
                    "结构化地图上下文："
                    f"zoom={map_context.get('zoom', '')}, "
                    f"center={map_context.get('center', '')}, "
                    f"visible_layers={visible_layers}"
                ),
            ]
        )
