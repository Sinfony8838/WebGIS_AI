"""MiniMax LLM client (v1.3 — the retired Xiaomi MiMo provider is removed).

Default path: MiniMax **Anthropic-compatible** Messages API
(``https://api.minimaxi.com/anthropic`` → ``/v1/messages``). If the
configured base URL does not contain ``/anthropic`` (legacy ``/v1``
deployments), the client falls back to the OpenAI Chat Completions format.

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

    #: Default output-token budget. Reasoning-capable models (MiniMax M2 系列)
    #: spend part of the budget on thinking before the visible answer; without
    #: generous headroom the response ends at the length limit with empty
    #: visible content.
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

        if self._uses_anthropic_format():
            return self._anthropic_chat_completion(
                messages,
                temperature,
                model=model,
                extra_payload=extra_payload,
                timeout=timeout,
            )

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
    # Anthropic-compatible path (MiniMax /anthropic endpoint)
    # ------------------------------------------------------------------

    def _uses_anthropic_format(self) -> bool:
        """MiniMax's recommended endpoint speaks the Anthropic Messages API.

        Detection is URL-based so legacy deployments that point
        ``WEBGIS_AI_MINIMAX_BASE_URL`` at an OpenAI-style ``/v1`` endpoint
        keep the old Chat Completions behaviour unchanged.
        """
        return "/anthropic" in self.config.active_llm_base_url()

    @staticmethod
    def _content_to_text(content: Any) -> str:
        """Flatten OpenAI-style message content (str or block list) to text."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                str(block.get("text", ""))
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
        return str(content or "")

    def _anthropic_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        temperature: float,
        *,
        model: Optional[str],
        extra_payload: Optional[Dict[str, Any]],
        timeout: float,
    ) -> str:
        system_parts: List[str] = []
        converted: List[Dict[str, Any]] = []
        for message in messages:
            role = str(message.get("role") or "user")
            text = self._content_to_text(message.get("content"))
            if role == "system":
                if text.strip():
                    system_parts.append(text)
                continue
            mapped_role = "assistant" if role == "assistant" else "user"
            if converted and converted[-1]["role"] == mapped_role:
                # Anthropic 要求 user/assistant 交替，同角色消息合并。
                converted[-1]["content"] += f"\n\n{text}"
            else:
                converted.append({"role": mapped_role, "content": text})
        if not converted or converted[0]["role"] != "user":
            converted.insert(0, {"role": "user", "content": "（继续）"})

        extra = dict(extra_payload or {})
        max_tokens = extra.pop("max_tokens", None) or extra.pop("max_completion_tokens", None)
        payload: Dict[str, Any] = {
            "model": model or self.config.active_llm_model(),
            "messages": converted,
            "temperature": temperature,
            "max_tokens": int(max_tokens) if max_tokens else self.DEFAULT_MAX_COMPLETION_TOKENS,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        payload.update(extra)

        endpoint = f"{self.config.active_llm_base_url().rstrip('/')}/v1/messages"
        key = self.config.active_llm_api_key()
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                # Anthropic 风格 x-api-key 与 Bearer 双发，兼容两种鉴权。
                "x-api-key": key,
                "Authorization": f"Bearer {key}",
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"MiniMax API error {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"MiniMax API request failed: {exc.reason}") from exc

        parsed = json.loads(body)
        blocks = parsed.get("content") or []
        text = "".join(
            str(block.get("text", ""))
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        )
        if text.strip():
            return text
        stop_reason = str(parsed.get("stop_reason") or "")
        if stop_reason == "max_tokens":
            raise RuntimeError(
                "MiniMax returned empty content: max_tokens budget exhausted before the "
                "final answer. Increase max_tokens via extra_payload."
            )
        raise RuntimeError("MiniMax API returned empty content")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _auth_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.active_llm_api_key()}",
            "Content-Type": "application/json",
        }

    def _provider_label(self) -> str:
        return "MiniMax"

    def _provider_unconfigured_message(self) -> str:
        return "MiniMax API key is not configured (set WEBGIS_AI_MINIMAX_API_KEY)"


# ---------------------------------------------------------------------------
# Backwards-compat alias.
#
# All historical call sites (llm_planner.py, session_engine.py, assistant.py,
# vision.py, runtime.py, ...) import ``MiniMaxClient`` from this module. The
# v1.2 refactor keeps that import working by aliasing the new class; no
# downstream source change required.
# ---------------------------------------------------------------------------

MiniMaxClient = LLMClient


def build_llm_client(config: AppConfig) -> LLMClient:
    """Single construction seam for the chat-completion LLM client.

    The runtime builds its client exclusively through this factory so a
    future multi-provider switch (config.llm_provider routing to a
    different vendor's client class) is a one-function change. Today the
    only provider is MiniMax, so the factory simply returns
    :class:`LLMClient`.
    """
    provider = (getattr(config, "llm_provider", "") or "").strip().lower()
    del provider  # single-provider era; kept for the future routing switch
    return LLMClient(config)
