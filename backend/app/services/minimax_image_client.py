from __future__ import annotations

import base64
import binascii
import json
import urllib.error
import urllib.request
from typing import Any, Dict

from ..config import AppConfig


ALLOWED_IMAGE_MODELS = {"image-01", "image-01-live"}
ALLOWED_ASPECT_RATIOS = {"1:1", "16:9", "4:3", "3:2", "2:3", "3:4", "9:16", "21:9"}


class MiniMaxImageError(RuntimeError):
    """A safe, user-facing failure from the MiniMax image API."""


class MiniMaxImageClient:
    def __init__(self, config: AppConfig):
        self.config = config

    def status(self) -> Dict[str, Any]:
        return self.config.image_generation_status()

    def generate(
        self,
        prompt: str,
        *,
        model: str = "",
        aspect_ratio: str = "16:9",
        prompt_optimizer: bool = True,
        timeout: float = 120.0,
    ) -> Dict[str, Any]:
        if not self.config.image_generation_enabled():
            raise MiniMaxImageError("MiniMax 图片生成尚未配置，请先设置 WEBGIS_AI_MINIMAX_API_KEY。")

        normalized_prompt = str(prompt or "").strip()
        if not normalized_prompt:
            raise ValueError("请输入图片生成描述。")
        if len(normalized_prompt) > 1500:
            raise ValueError("图片生成描述不能超过 1500 个字符。")

        selected_model = str(model or self.config.minimax_image_model).strip()
        if selected_model not in ALLOWED_IMAGE_MODELS:
            raise ValueError("图片模型仅支持 image-01 或 image-01-live。")
        selected_ratio = str(aspect_ratio or "16:9").strip()
        if selected_ratio not in ALLOWED_ASPECT_RATIOS:
            raise ValueError("不支持该图片比例。")
        if selected_model == "image-01-live" and selected_ratio == "21:9":
            raise ValueError("image-01-live 暂不支持 21:9，请改用其他比例。")

        payload = {
            "model": selected_model,
            "prompt": normalized_prompt,
            "aspect_ratio": selected_ratio,
            "response_format": "base64",
            "n": 1,
            "prompt_optimizer": bool(prompt_optimizer),
            "aigc_watermark": True,
        }
        endpoint = self._endpoint()
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.minimax_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise MiniMaxImageError(self._http_error_message(exc.code, detail)) from exc
        except urllib.error.URLError as exc:
            raise MiniMaxImageError(f"MiniMax 图片服务连接失败：{exc.reason}") from exc
        except TimeoutError as exc:
            raise MiniMaxImageError("MiniMax 图片生成超时，请稍后重试。") from exc

        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise MiniMaxImageError("MiniMax 图片服务返回了无法解析的响应。") from exc

        base_resp = parsed.get("base_resp") if isinstance(parsed, dict) else None
        if isinstance(base_resp, dict) and int(base_resp.get("status_code") or 0) != 0:
            message = str(base_resp.get("status_msg") or "请求未成功")
            raise MiniMaxImageError(f"MiniMax 图片生成失败：{message}")

        data = parsed.get("data") if isinstance(parsed, dict) else None
        encoded_images = data.get("image_base64") if isinstance(data, dict) else None
        if not isinstance(encoded_images, list) or not encoded_images:
            raise MiniMaxImageError("MiniMax 图片服务没有返回图片内容。")
        encoded = str(encoded_images[0] or "")
        if encoded.startswith("data:") and "," in encoded:
            encoded = encoded.split(",", 1)[1]
        try:
            raw_bytes = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise MiniMaxImageError("MiniMax 图片服务返回的图片数据无效。") from exc

        mime_type, suffix = self._detect_format(raw_bytes)
        if not mime_type:
            raise MiniMaxImageError("MiniMax 图片服务返回了不受支持的图片格式。")
        return {
            "raw_bytes": raw_bytes,
            "mime_type": mime_type,
            "suffix": suffix,
            "model": selected_model,
            "aspect_ratio": selected_ratio,
            "request_id": str(parsed.get("id") or parsed.get("request_id") or ""),
        }

    def _endpoint(self) -> str:
        base = self.config.minimax_image_base_url.rstrip("/")
        if base.endswith("/v1"):
            return f"{base}/image_generation"
        return f"{base}/v1/image_generation"

    @staticmethod
    def _detect_format(raw_bytes: bytes) -> tuple[str, str]:
        if raw_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png", ".png"
        if raw_bytes.startswith(b"\xff\xd8\xff"):
            return "image/jpeg", ".jpg"
        if len(raw_bytes) >= 12 and raw_bytes[:4] == b"RIFF" and raw_bytes[8:12] == b"WEBP":
            return "image/webp", ".webp"
        return "", ""

    @staticmethod
    def _http_error_message(status_code: int, detail: str) -> str:
        message = ""
        try:
            payload = json.loads(detail)
            base_resp = payload.get("base_resp") if isinstance(payload, dict) else None
            if isinstance(base_resp, dict):
                message = str(base_resp.get("status_msg") or "")
            if not message and isinstance(payload, dict):
                message = str(payload.get("message") or payload.get("error") or "")
        except json.JSONDecodeError:
            message = ""
        suffix = f"：{message[:300]}" if message else ""
        return f"MiniMax 图片服务请求失败（HTTP {status_code}）{suffix}"
