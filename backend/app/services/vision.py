from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any, Dict, Optional

from ..config import AppConfig
from ..models import ProjectRecord


DATA_URL_RE = re.compile(r"^data:image/(png|jpeg|jpg|webp);base64,", re.IGNORECASE)


class MapVisionService:
    """Saves map screenshots and exposes a clear fallback when image understanding is unavailable.

    MiniMax Token Plan image understanding is MCP-tool based rather than the OpenAI-compatible
    chat endpoint used by the text assistant. This service keeps the integration point explicit:
    once a Token Plan MCP bridge is available, call it here and return a vision explanation.
    """

    def __init__(self, config: AppConfig):
        self.config = config

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

        # The actual MiniMax image understanding endpoint is exposed through Token Plan MCP.
        # Without an MCP bridge in this FastAPI process, do not fake visual inference.
        if not status.get("configured"):
            return {
                "used_vision": False,
                "snapshot_path": str(snapshot_path) if snapshot_path else "",
                "reason": "未配置 MiniMax Token Plan MCP 图像理解，已回退到结构化地图上下文读图。",
            }

        return {
            "used_vision": False,
            "snapshot_path": str(snapshot_path) if snapshot_path else "",
            "reason": "已保存截图；当前服务尚未连接 Token Plan MCP 运行时，已回退到结构化地图上下文读图。",
        }
