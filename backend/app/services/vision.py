"""Map screenshot → AI lecture-script via an LLM vision backend.

v1.3 唯一后端：``vision_provider = "minimax_mcp"`` —— 通过 MiniMax Token
Plan MCP 子进程调用 ``understand_image``（Token Plan Key 默认复用 MiniMax
API Key）。图片识别不可用时返回明确错误，不用地图状态冒充识图结果。

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
from .minimax_mcp_client import MiniMaxMcpClient, MiniMaxMcpError


DATA_URL_RE = re.compile(r"^data:image/(png|jpeg|jpg|webp);base64,", re.IGNORECASE)


class MapVisionService:
    """Saves map screenshots and delegates visual reading to the configured backend."""

    def __init__(
        self,
        config: AppConfig,
        mcp_client: Optional[MiniMaxMcpClient] = None,
    ):
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

    def understand_image(
        self,
        image_path: str,
        question: str,
        supplemental_context: str = "",
    ) -> Dict[str, Any]:
        """Ask the configured vision backend about a persisted project image.

        The user's question is sent with the real image path. Structured map
        state is intentionally excluded: it must never masquerade as visual
        evidence when image understanding is unavailable.
        """
        path = Path(image_path).resolve()
        if not path.is_file():
            return {
                "used_vision": False,
                "snapshot_path": str(path),
                "reason": "图片文件不存在，暂时无法识别。",
            }
        status = self.status()
        provider = self.config.vision_provider
        if not status.get("configured"):
            return {
                "used_vision": False,
                "snapshot_path": str(path),
                "reason": "图片识别服务尚未配置，暂时无法读取这张图片。",
            }
        if provider != "minimax_mcp":
            return {
                "used_vision": False,
                "snapshot_path": str(path),
                "reason": f"当前图片识别后端不受支持（{provider}）。",
            }

        prompt = self._build_image_prompt(question, supplemental_context)
        return self._understand_via_mcp(
            path,
            prompt,
            allow_structured_fallback=False,
            include_coordinates=self._asks_for_coordinates(question),
        )

    # ------------------------------------------------------------------
    # Provider backends
    # ------------------------------------------------------------------

    def _understand_via_mcp(
        self,
        snapshot_path: Path,
        prompt: str,
        allow_structured_fallback: bool = True,
        include_coordinates: bool = False,
    ) -> Dict[str, Any]:
        try:
            result = self.mcp_client.understand_image(prompt=prompt, image_url=str(snapshot_path))
        except MiniMaxMcpError as exc:
            return {
                "used_vision": False,
                "snapshot_path": str(snapshot_path),
                "reason": (
                    f"MiniMax Token Plan MCP 图片理解调用失败，已回退到结构化地图上下文读图：{exc}"
                    if allow_structured_fallback
                    else f"图片识别服务暂时不可用：{exc}"
                ),
            }
        return {
            "used_vision": True,
            "snapshot_path": str(snapshot_path),
            "provider": "minimax_mcp",
            "summary": self._sanitize_vision_summary(
                str(result.get("text") or ""),
                include_coordinates=include_coordinates,
            ),
            "raw": result.get("raw", {}),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _not_configured_message(self, provider: str) -> str:
        if provider == "minimax_mcp":
            return "未配置 MiniMax Token Plan MCP 图片理解，已回退到结构化地图上下文读图。"
        return f"未配置受支持的视觉读图后端（vision_provider={provider}），已回退到结构化地图上下文读图。"

    @staticmethod
    def _sanitize_vision_summary(text: str, include_coordinates: bool = False) -> str:
        """Keep useful visual evidence and discard transport/OCR noise.

        Some Windows releases of the upstream MCP package corrupt OCR-only
        Chinese labels before returning JSON. The image model's English visual
        description remains intact, so remove damaged label lines and viewport
        coordinate sections before the text model composes the Chinese answer.
        """
        cleaned: list[str] = []
        skip_coordinate_section = False
        for raw_line in text.splitlines():
            line = raw_line.replace("�C", "–").strip()
            lowered = line.lower()
            if line.startswith("#"):
                skip_coordinate_section = any(
                    token in lowered for token in ("coordinate", "graticule", "latitude", "longitude")
                )
                if skip_coordinate_section:
                    continue
            elif skip_coordinate_section:
                if not line:
                    continue
                if line.startswith("#"):
                    skip_coordinate_section = False
                else:
                    continue
            coordinate_line = any(
                token in lowered
                for token in (
                    "zoom level",
                    "viewport coordinate",
                    "latitude lines",
                    "longitude lines",
                    "degrees north",
                    "degrees south",
                    "degrees east",
                    "degrees west",
                )
            ) or bool(re.search(r"\b\d{1,3}(?:\.\d+)?\s*°\s*[NSEW]\b", line, re.IGNORECASE))
            if not include_coordinates and coordinate_line:
                continue
            if line.count("�") >= 2:
                continue
            cleaned.append(line)
        return "\n".join(cleaned).strip()

    def _build_prompt(self, project: ProjectRecord, map_context: Dict[str, Any], focus: str = "") -> str:
        visible_layers = map_context.get("visible_layers") or []
        if not visible_layers:
            visible_layers = [layer.name for layer in project.layers if layer.visible][:6]
        return "\n".join(
            [
                "Read this classroom geography map directly and return the visual findings in clear English only.",
                "Identify the map theme, legend, visible spatial patterns, high/low areas, and plausible geographic explanations.",
                "Separate direct observations from inference. State uncertainty when labels, values, or boundaries are unclear.",
                "Do not report viewport coordinates or zoom level, and do not claim to see anything that is not visible.",
                f"The user's focus is: {focus or 'geography map interpretation'}",
                f"Project name: {project.name}",
                f"Visible layer names are optional context only, never a substitute for the image: {visible_layers}",
            ]
        )

    @staticmethod
    def _asks_for_coordinates(question: str) -> bool:
        return any(
            token in question.lower()
            for token in ("经纬度", "经度", "纬度", "坐标", "经线", "纬线", "比例尺", "尺度", "coordinate", "latitude", "longitude")
        )

    def _build_image_prompt(self, question: str, supplemental_context: str = "") -> str:
        asks_for_coordinates = self._asks_for_coordinates(question)
        parts = [
            "Analyze this real image for a geography teacher. Inspect the image before answering.",
            "Return the visual analysis in clear English only; the application will produce the final Simplified Chinese response.",
            "Describe directly visible objects, text, legends, colors, textures, and spatial relationships before geographic inference.",
            "Clearly separate observation from inference. If labels, values, or boundaries are unclear, state the uncertainty and never invent them.",
            (
                "The user explicitly asked about coordinates or scale, so include only coordinate values that are legible in the image."
                if asks_for_coordinates
                else "Do not report viewport or geographic coordinates, graticule values, scale, or zoom level."
            ),
            f"User's original question: {question.strip() or 'Identify and analyze the geographic information in this image.'}",
        ]
        if "人口" in question:
            parts.extend(
                [
                    "This is a population-geography task. First identify whether the mapped variable is population total, population density, migration flow, or another indicator; never substitute one for another.",
                    "Read the map title, printed data year, legend unit, and every visible class boundary exactly. Treat a printed year as the data time point and never describe it as current data unless the image explicitly says so.",
                    "Do not derive population counts, percentages, rankings, or present-day claims from colors. Do not merge legend classes or change inequality signs and numeric ranges.",
                    "Answer only the spatial pattern the user asked about. Do not add causes, extra regions, or unlabelled places unless the question explicitly asks for inference.",
                ]
            )
        if supplemental_context.strip():
            parts.append(f"Optional context for explanation only, never a substitute for image evidence: {supplemental_context.strip()}")
        return "\n".join(parts)
