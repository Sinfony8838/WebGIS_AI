"""Provider-pluggable LLM client.

v1.2 default provider: **Xiaomi MiMo** (https://platform.xiaomimimo.com),
OpenAI Chat Completions compatible. Authentication uses a non-standard
``api-key`` header (NOT ``Authorization: Bearer``).

Legacy provider: **MiniMax** — kept as a working fallback so projects with
``WEBGIS_AI_LLM_PROVIDER=minimax`` continue to behave exactly as before.

The historical symbol :class:`MiniMaxClient` is preserved as an alias of
:class:`LLMClient` so all existing call sites (planner, session engine,
vision, runtime) keep working without source-level changes.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from ..config import AppConfig


class LLMClient:
    """OpenAI Chat Completions client that routes by ``config.llm_provider``."""

    def __init__(self, config: AppConfig):
        self.config = config

    # ------------------------------------------------------------------
    # Status / introspection
    # ------------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        return {
            **self.config.llm_status(),
            "configured": self.config.llm_enabled(),
        }

    # ------------------------------------------------------------------
    # Text chat completions
    # ------------------------------------------------------------------

    #: Default ``max_completion_tokens`` for reasoning-capable models so the
    #: chain-of-thought tokens do not starve the visible ``content``. Mimo
    #: v2.5-pro (and other reasoning models) put their thinking into
    #: ``reasoning_content`` first; without a generous budget the response
    #: hits ``finish_reason="length"`` with ``content=""``.
    DEFAULT_MAX_COMPLETION_TOKENS = 2048

    def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.2,
        *,
        model: Optional[str] = None,
        extra_payload: Optional[Dict[str, Any]] = None,
        timeout: float = 45.0,
    ) -> str:
        """POST a chat-completions request and return the assistant's text.

        ``messages`` follows OpenAI's schema; ``content`` may be a string or
        a list of OpenAI-style content blocks (text / image_url) — the latter
        is used by the vision path on supported providers.

        A default ``max_completion_tokens`` is added when the caller did not
        supply one so reasoning models (Mimo v2.5-pro etc.) have headroom for
        both the chain-of-thought and the final answer.
        """
        if not self.config.llm_enabled():
            raise RuntimeError(self._provider_unconfigured_message())

        endpoint = f"{self.config.active_llm_base_url().rstrip('/')}/chat/completions"
        payload: Dict[str, Any] = {
            "model": model or self.config.active_llm_model(),
            "messages": messages,
            "temperature": temperature,
        }
        if extra_payload:
            payload.update(extra_payload)
        # Apply our default budget only if the caller did not specify one,
        # honouring both the new OpenAI key (``max_completion_tokens``) and
        # the legacy alias (``max_tokens``).
        if "max_completion_tokens" not in payload and "max_tokens" not in payload:
            payload["max_completion_tokens"] = self.DEFAULT_MAX_COMPLETION_TOKENS

        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=self._auth_headers(),
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{self._provider_label()} API error {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"{self._provider_label()} API request failed: {exc.reason}") from exc

        parsed = json.loads(body)
        choices = parsed.get("choices") or []
        if not choices:
            raise RuntimeError(f"{self._provider_label()} API returned no choices")
        first = choices[0]
        message = first.get("message", {}) or {}
        content = message.get("content")
        if isinstance(content, list):
            # Some providers stream a list of content blocks. Concatenate
            # the text segments so callers keep getting a string back.
            content = "".join(
                str(block.get("text", "")) for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
        if isinstance(content, str) and content.strip():
            return content
        # Empty visible content — emit a focused diagnostic so the operator
        # can tell "model unavailable" from "reasoning ate the budget".
        finish_reason = str(first.get("finish_reason") or "")
        usage = parsed.get("usage") or {}
        details = usage.get("completion_tokens_details") or {}
        reasoning_tokens = details.get("reasoning_tokens")
        reasoning_text = str(message.get("reasoning_content") or "")
        if finish_reason == "length" and reasoning_text:
            raise RuntimeError(
                f"{self._provider_label()} returned empty content: reasoning consumed the "
                f"max_completion_tokens budget (reasoning_tokens={reasoning_tokens}). "
                "Increase max_completion_tokens or pass a larger value via extra_payload."
            )
        raise RuntimeError(f"{self._provider_label()} API returned empty content")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _auth_headers(self) -> Dict[str, str]:
        provider = self.config.llm_provider
        key = self.config.active_llm_api_key()
        if provider == "mimo":
            # Xiaomi MiMo uses the custom ``api-key`` header (NOT Bearer).
            return {
                "api-key": key,
                "Content-Type": "application/json",
            }
        # MiniMax (and any future OpenAI-style provider) defaults to Bearer.
        return {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }

    def _provider_label(self) -> str:
        provider = self.config.llm_provider
        if provider == "mimo":
            return "Xiaomi MiMo"
        if provider == "minimax":
            return "MiniMax"
        return provider or "LLM"

    def _provider_unconfigured_message(self) -> str:
        provider = self.config.llm_provider
        if provider == "mimo":
            return "Xiaomi MiMo API key is not configured (set WEBGIS_AI_MIMO_API_KEY)"
        if provider == "minimax":
            return "MiniMax API key is not configured (set WEBGIS_AI_MINIMAX_API_KEY)"
        return f"LLM provider '{provider}' is not supported"


# ---------------------------------------------------------------------------
# Backwards-compat alias.
#
# All historical call sites (llm_planner.py, session_engine.py, assistant.py,
# vision.py, runtime.py, ...) import ``MiniMaxClient`` from this module. The
# v1.2 refactor keeps that import working by aliasing the new class; no
# downstream source change required.
# ---------------------------------------------------------------------------

MiniMaxClient = LLMClient
