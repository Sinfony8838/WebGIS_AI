from __future__ import annotations

import json
import os
import queue
import shlex
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional

from ..config import AppConfig


class MiniMaxMcpError(RuntimeError):
    """Raised when the MiniMax Token Plan MCP bridge cannot complete a request."""


class MiniMaxMcpClient:
    """Small JSON-RPC stdio client for MiniMax Token Plan MCP tools.

    The official Token Plan guide exposes image understanding through the
    `understand_image` MCP tool. We run one short-lived MCP process per request
    so the FastAPI runtime does not need to manage a long-lived child process.
    """

    def __init__(self, config: AppConfig, timeout_seconds: float = 60.0):
        self.config = config
        self.timeout_seconds = timeout_seconds
        self._next_id = 1

    def understand_image(self, prompt: str, image_url: str) -> Dict[str, Any]:
        if not self.config.vision_status().get("configured"):
            raise MiniMaxMcpError("MiniMax Token Plan MCP is not configured")
        response = self._call_tool(
            "understand_image",
            {
                "prompt": prompt,
                "image_url": image_url,
            },
        )
        text = self._extract_text(response.get("result", {}))
        if not text:
            raise MiniMaxMcpError("MiniMax MCP returned an empty image understanding result")
        return {"used_vision": True, "text": text, "raw": response.get("result", {})}

    def _call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        process = None
        stdout_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        stderr_lines: List[str] = []
        try:
            process = subprocess.Popen(
                self._command(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(self.config.root_dir),
                env=self._environment(),
                universal_newlines=True,
                bufsize=1,
            )
        except FileNotFoundError as exc:
            raise MiniMaxMcpError(
                f"MiniMax MCP command not found: {self.config.minimax_mcp_command}. "
                "Install uv/uvx or set WEBGIS_AI_MINIMAX_MCP_COMMAND."
            ) from exc

        assert process.stdin is not None
        assert process.stdout is not None
        assert process.stderr is not None

        stdout_thread = threading.Thread(target=self._read_stdout, args=(process.stdout, stdout_queue), daemon=True)
        stderr_thread = threading.Thread(target=self._read_stderr, args=(process.stderr, stderr_lines), daemon=True)
        stdout_thread.start()
        stderr_thread.start()

        try:
            initialize_id = self._request_id()
            self._send(
                process,
                {
                    "jsonrpc": "2.0",
                    "id": initialize_id,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "WebGIS-AI", "version": "1.1.0"},
                    },
                },
            )
            self._wait_for_response(process, stdout_queue, initialize_id, stderr_lines)
            self._send(process, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

            call_id = self._request_id()
            self._send(
                process,
                {
                    "jsonrpc": "2.0",
                    "id": call_id,
                    "method": "tools/call",
                    "params": {"name": name, "arguments": arguments},
                },
            )
            response = self._wait_for_response(process, stdout_queue, call_id, stderr_lines)
            if response.get("error"):
                error = response["error"]
                raise MiniMaxMcpError(str(error.get("message") or error))
            return response
        finally:
            self._close_process(process)

    def _command(self) -> List[str]:
        command = shlex.split(self.config.minimax_mcp_command.strip())
        if not command:
            raise MiniMaxMcpError("WEBGIS_AI_MINIMAX_MCP_COMMAND is empty")
        package = self.config.minimax_mcp_package.strip()
        if package:
            command.append(package)
        command.append("-y")
        return command

    def _environment(self) -> Dict[str, str]:
        env = os.environ.copy()
        env["MINIMAX_API_KEY"] = self.config.minimax_token_plan_key.strip()
        env["MINIMAX_API_HOST"] = self.config.minimax_api_host.rstrip("/")
        if self.config.minimax_mcp_base_path.strip():
            env["MINIMAX_MCP_BASE_PATH"] = self.config.minimax_mcp_base_path.strip()
        if self.config.minimax_mcp_resource_mode.strip():
            env["MINIMAX_API_RESOURCE_MODE"] = self.config.minimax_mcp_resource_mode.strip()
        return env

    def _request_id(self) -> int:
        request_id = self._next_id
        self._next_id += 1
        return request_id

    def _send(self, process: subprocess.Popen, payload: Dict[str, Any]) -> None:
        if process.stdin is None:
            raise MiniMaxMcpError("MiniMax MCP stdin is unavailable")
        process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        process.stdin.flush()

    def _wait_for_response(
        self,
        process: subprocess.Popen,
        stdout_queue: "queue.Queue[Dict[str, Any]]",
        request_id: int,
        stderr_lines: List[str],
    ) -> Dict[str, Any]:
        deadline = time.monotonic() + self.timeout_seconds
        last_message: Optional[Dict[str, Any]] = None
        while time.monotonic() < deadline:
            if process.poll() is not None and stdout_queue.empty():
                stderr = "\n".join(stderr_lines[-8:]).strip()
                raise MiniMaxMcpError(f"MiniMax MCP exited before response {request_id}. {stderr}".strip())
            try:
                message = stdout_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            last_message = message
            if message.get("id") == request_id:
                if message.get("error"):
                    error = message["error"]
                    raise MiniMaxMcpError(str(error.get("message") or error))
                return message
        stderr = "\n".join(stderr_lines[-8:]).strip()
        detail = f" Last message: {last_message}" if last_message else ""
        raise MiniMaxMcpError(f"Timed out waiting for MiniMax MCP response {request_id}.{detail} {stderr}".strip())

    def _read_stdout(self, stream: Any, stdout_queue: "queue.Queue[Dict[str, Any]]") -> None:
        for line in iter(stream.readline, ""):
            line = line.strip()
            if not line:
                continue
            try:
                stdout_queue.put(json.loads(line))
            except json.JSONDecodeError:
                continue

    def _read_stderr(self, stream: Any, stderr_lines: List[str]) -> None:
        for line in iter(stream.readline, ""):
            line = line.strip()
            if line:
                stderr_lines.append(line)

    def _close_process(self, process: Optional[subprocess.Popen]) -> None:
        if process is None:
            return
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()

    def _extract_text(self, result: Dict[str, Any]) -> str:
        content = result.get("content")
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text") or "").strip())
            return "\n\n".join(part for part in parts if part)
        if isinstance(result.get("text"), str):
            return result["text"].strip()
        return ""
