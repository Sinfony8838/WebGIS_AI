from __future__ import annotations

import json
import socket
import subprocess
from typing import Any, Dict, List

from ..config import AppConfig


QGIS_TOOL_SCHEMA = [
    {"name": "get_layers", "description": "读取 QGIS 当前项目图层。", "parameters": {}},
    {"name": "set_layer_visibility", "description": "显示或隐藏 QGIS 图层。", "parameters": {"layer_id": "string?", "layer_name": "string?", "visible": "boolean"}},
    {"name": "set_active_layer", "description": "设置 QGIS 当前活动图层。", "parameters": {"layer_id": "string?", "layer_name": "string?"}},
    {"name": "set_layer_z_order", "description": "调整 QGIS 图层顺序。", "parameters": {"layer_id": "string?", "layer_name": "string?", "position": "string"}},
    {"name": "fly_to", "description": "飞到指定经纬度。", "parameters": {"lat": "number", "lon": "number", "scale": "number"}},
    {"name": "zoom_to_layer", "description": "缩放到 QGIS 图层。", "parameters": {"layer_id": "string?", "layer_name": "string?"}},
    {"name": "set_style", "description": "设置 QGIS 图层样式。", "parameters": {"layer_id": "string?", "layer_name": "string?", "style_type": "string"}},
    {"name": "query_attributes", "description": "查询 QGIS 图层属性。", "parameters": {"layer_id": "string?", "layer_name": "string?", "filters": "string?", "limit": "number?"}},
    {"name": "add_layer_from_path", "description": "从本地路径添加 QGIS 图层。", "parameters": {"file_path": "string", "layer_name": "string?"}},
    {"name": "export_layer_to_file", "description": "导出 QGIS 图层到文件。", "parameters": {"layer_id": "string?", "layer_name": "string?", "file_path": "string"}},
    {"name": "run_algorithm", "description": "执行 QGIS processing 算法。", "parameters": {"algorithm_id": "string", "params": "object"}},
    {"name": "create_heatmap", "description": "创建热力图。", "parameters": {"layer_id": "string?", "layer_name": "string?"}},
    {"name": "create_flow_arrows", "description": "创建流线或流向箭头。", "parameters": {"layer_id": "string?", "layer_name": "string?"}},
    {"name": "clip_raster_by_mask", "description": "按矢量掩膜裁剪栅格。", "parameters": {"raster_layer": "string", "mask_layer": "string"}},
    {"name": "export_map", "description": "导出 QGIS 地图。", "parameters": {"file_path": "string", "layout_name": "string?"}},
]

QGIS_ALLOWED_TOOLS = {item["name"] for item in QGIS_TOOL_SCHEMA}
QGIS_MAX_MESSAGE_BYTES = 5 * 1024 * 1024


class QgisBridgeClient:
    def __init__(self, config: AppConfig, timeout: int = 30):
        self.config = config
        self.timeout = timeout

    def _recv_exact(self, sock: socket.socket, size: int) -> bytes:
        buffer = b""
        while len(buffer) < size:
            chunk = sock.recv(size - len(buffer))
            if not chunk:
                raise ConnectionError("Socket closed before full response was received")
            buffer += chunk
        return buffer

    def call(self, tool_name: str, **tool_params: Any) -> Dict[str, Any]:
        if tool_name not in QGIS_ALLOWED_TOOLS and tool_name != "ping":
            raise ValueError(f"QGIS tool is not allowed: {tool_name}")

        payload = json.dumps({"tool_name": tool_name, "tool_params": tool_params}, ensure_ascii=False).encode("utf-8")
        with socket.create_connection((self.config.qgis_host, self.config.qgis_port), timeout=self.timeout) as sock:
            sock.sendall(len(payload).to_bytes(4, "big") + payload)
            message_length = int.from_bytes(self._recv_exact(sock, 4), "big")
            if message_length <= 0 or message_length > QGIS_MAX_MESSAGE_BYTES:
                raise ValueError(f"Unexpected QGIS response size: {message_length}")
            return json.loads(self._recv_exact(sock, message_length).decode("utf-8"))

    def status(self) -> Dict[str, Any]:
        payload = self.config.qgis_status_config()
        try:
            response = self.call("ping")
            if response.get("status") == "success":
                return {**payload, "reachable": True, "health_mode": "ping", "response": response}
            message = str(response.get("message", ""))
            if "Unknown tool: ping" in message:
                fallback = self.call("get_layers")
                return {**payload, "reachable": True, "health_mode": "fallback:get_layers", "response": fallback}
            return {**payload, "reachable": False, "health_mode": "ping", "response": response}
        except Exception as exc:
            return {**payload, "reachable": False, "error": str(exc)}

    def layers(self) -> Dict[str, Any]:
        return self.call("get_layers")

    def execute(self, tool_name: str, tool_params: Dict[str, Any] | None = None) -> Dict[str, Any]:
        return self.call(tool_name, **(tool_params or {}))

    def focus_window(self) -> Dict[str, Any]:
        command = """
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class WinApi {
  [DllImport("user32.dll")]
  public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);
  [DllImport("user32.dll")]
  public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")]
  public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")]
  public static extern bool BringWindowToTop(IntPtr hWnd);
  [DllImport("user32.dll")]
  public static extern IntPtr SetFocus(IntPtr hWnd);
  [DllImport("user32.dll")]
  public static extern uint GetWindowThreadProcessId(IntPtr hWnd, IntPtr lpdwProcessId);
  [DllImport("user32.dll")]
  public static extern bool AttachThreadInput(uint idAttach, uint idAttachTo, bool fAttach);
  [DllImport("kernel32.dll")]
  public static extern uint GetCurrentThreadId();
}
'@;
$process = Get-Process | Where-Object {
  $_.MainWindowHandle -ne 0 -and ($_.ProcessName -like 'qgis*' -or $_.MainWindowTitle -like '*QGIS*')
} | Select-Object -First 1;
if (-not $process) {
  throw 'QGIS window not found';
}
$handle = [IntPtr]$process.MainWindowHandle;
[WinApi]::ShowWindowAsync($handle, 9) | Out-Null;
Start-Sleep -Milliseconds 120;

$focused = $false;
$method = @();

if ([WinApi]::SetForegroundWindow($handle)) {
  $focused = $true;
  $method += 'SetForegroundWindow';
}

if (-not $focused) {
  try {
    $shell = New-Object -ComObject WScript.Shell;
    if ($shell.AppActivate([int]$process.Id)) {
      $method += 'AppActivatePid';
    } elseif ($process.MainWindowTitle -and $shell.AppActivate($process.MainWindowTitle)) {
      $method += 'AppActivateTitle';
    }
    Start-Sleep -Milliseconds 80;
    if ([WinApi]::GetForegroundWindow() -eq $handle) {
      $focused = $true;
    }
  } catch {
    $method += 'AppActivateUnavailable';
  }
}

if (-not $focused) {
  $currentThread = [WinApi]::GetCurrentThreadId();
  $foregroundWindow = [WinApi]::GetForegroundWindow();
  $foregroundThread = 0;
  if ($foregroundWindow -ne [IntPtr]::Zero) {
    $foregroundThread = [WinApi]::GetWindowThreadProcessId($foregroundWindow, [IntPtr]::Zero);
  }
  $targetThread = [WinApi]::GetWindowThreadProcessId($handle, [IntPtr]::Zero);
  if ($foregroundThread -ne 0 -and $targetThread -ne 0) {
    [WinApi]::AttachThreadInput($currentThread, $foregroundThread, $true) | Out-Null;
    [WinApi]::AttachThreadInput($currentThread, $targetThread, $true) | Out-Null;
    [WinApi]::BringWindowToTop($handle) | Out-Null;
    [WinApi]::SetForegroundWindow($handle) | Out-Null;
    [WinApi]::SetFocus($handle) | Out-Null;
    [WinApi]::AttachThreadInput($currentThread, $targetThread, $false) | Out-Null;
    [WinApi]::AttachThreadInput($currentThread, $foregroundThread, $false) | Out-Null;
    $method += 'AttachThreadInput';
    Start-Sleep -Milliseconds 60;
    if ([WinApi]::GetForegroundWindow() -eq $handle) {
      $focused = $true;
    }
  }
}

if ($focused) {
  @{ ok = $true; message = 'QGIS window focused'; method = ($method -join ',') } | ConvertTo-Json -Compress;
} else {
  @{
    ok = $true;
    message = 'QGIS window restored, but Windows blocked foreground focus. Please click QGIS once.';
    warning = 'focus_blocked_by_windows_policy';
    method = ($method -join ',');
  } | ConvertTo-Json -Compress;
}
""".strip()
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if completed.returncode != 0:
            raw_message = completed.stderr.strip() or completed.stdout.strip() or "Failed to focus QGIS"
            return {"ok": False, "message": raw_message}
        raw_output = completed.stdout.strip()
        if raw_output:
            try:
                parsed = json.loads(raw_output)
                if isinstance(parsed, dict):
                    if "ok" in parsed:
                        return parsed
                    return {"ok": True, "message": str(parsed.get("message") or "QGIS window focused")}
            except json.JSONDecodeError:
                return {"ok": True, "message": raw_output}
        return {"ok": True, "message": "QGIS window focused"}

    def fallback_plan(self, message: str) -> Dict[str, Any]:
        lowered = (message or "").lower()
        if any(token in lowered for token in ["导出", "export", "地图"]):
            return {
                "assistant_message": "QGIS 专业模式当前未配置 MiniMax，已为你准备地图导出提示；请在专业页手动填写导出路径后执行。",
                "target": "qgis",
                "actions": [{"tool_name": "get_layers", "tool_params": {}}],
            }
        return {
            "assistant_message": "QGIS 专业模式当前使用规则兜底。我先读取 QGIS 图层状态，复杂自然语言规划需要配置 MiniMax API。",
            "target": "qgis",
            "actions": [{"tool_name": "get_layers", "tool_params": {}}],
        }

    @staticmethod
    def schema_for_prompt() -> List[Dict[str, Any]]:
        return QGIS_TOOL_SCHEMA
