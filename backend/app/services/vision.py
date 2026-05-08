from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any, Dict, Optional

from ..config import AppConfig
from ..models import ProjectRecord
from .minimax_mcp_client import MiniMaxMcpClient, MiniMaxMcpError


DATA_URL_RE = re.compile(r"^data:image/(png|jpeg|jpg|webp);base64,", re.IGNORECASE)


class MapVisionService:
    """Saves map screenshots and delegates visual reading to MiniMax Token Plan MCP."""

    def __init__(self, config: AppConfig, mcp_client: Optional[MiniMaxMcpClient] = None):
        self.config = config
        self.mcp_client = mcp_client or MiniMaxMcpClient(config)

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
                "reason": "未配置 MiniMax Token Plan MCP 图片理解，已回退到结构化地图上下文读图。",
            }

        prompt = self._build_prompt(project, map_context, focus)
        try:
            result = self.mcp_client.understand_image(prompt=prompt, image_url=str(snapshot_path))
            return {
                "used_vision": True,
                "snapshot_path": str(snapshot_path),
                "provider": "minimax_mcp",
                "summary": result.get("text", ""),
                "raw": result.get("raw", {}),
            }
        except MiniMaxMcpError as exc:
            return {
                "used_vision": False,
                "snapshot_path": str(snapshot_path),
                "reason": f"MiniMax Token Plan MCP 图片理解调用失败，已回退到结构化地图上下文读图：{exc}",
            }

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
