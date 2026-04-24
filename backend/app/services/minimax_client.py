from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, List

from ..config import AppConfig


class MiniMaxClient:
    def __init__(self, config: AppConfig):
        self.config = config

    def status(self) -> Dict[str, Any]:
        return {
            **self.config.llm_status(),
            "configured": self.config.minimax_enabled(),
        }

    def chat_completion(self, messages: List[Dict[str, str]], temperature: float = 0.2) -> str:
        if not self.config.minimax_enabled():
            raise RuntimeError("MiniMax API key is not configured")

        endpoint = f"{self.config.minimax_base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": self.config.minimax_model,
            "messages": messages,
            "temperature": temperature,
        }
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
            with urllib.request.urlopen(request, timeout=45) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"MiniMax API error {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"MiniMax API request failed: {exc.reason}") from exc

        parsed = json.loads(body)
        choices = parsed.get("choices") or []
        if not choices:
            raise RuntimeError("MiniMax API returned no choices")
        content = choices[0].get("message", {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("MiniMax API returned empty content")
        return content
