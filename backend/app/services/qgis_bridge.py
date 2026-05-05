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

    def fallback_plan(self, message: str, qgis_layers: "List[Dict[str, Any]] | None" = None) -> Dict[str, Any]:
        lowered = (message or "").lower()

        # --- Specific: 上海人口密度 heatmap + export ---
        if "上海" in lowered and "人口密度" in lowered and any(token in lowered for token in ["制作", "生成", "创建", "存储", "导出"]):
            output_dir = self.config.outputs_dir / "qgis_preclass"
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / "shanghai_population_density.png"
            return {
                "assistant_message": "我将按 QGIS 专业模式生成上海人口密度热力图并导出为课前材料；请确保 QGIS 中已加载上海人口点或人口密度图层。",
                "target": "qgis",
                "actions": [
                    {"tool_name": "get_layers", "tool_params": {}},
                    {"tool_name": "create_heatmap", "tool_params": {"layer_name": "上海人口密度"}},
                    {"tool_name": "export_map", "tool_params": {"file_path": str(output_path), "layout_name": "上海人口密度分布图"}},
                ],
            }

        # --- Generic: map creation / visualization requests ---
        create_tokens = ("制作", "生成", "创建", "绘制", "建立", "渲染", "create", "generate", "render", "draw")
        viz_tokens = ("热力图", "流向图", "分布图", "专题图", "heatmap", "flow")
        has_create = any(token in lowered for token in create_tokens)
        has_viz = any(token in lowered for token in viz_tokens)
        if has_create or has_viz:
            # Try to match an actual QGIS layer first, then fall back to text extraction
            matched_layer = self._match_qgis_layer(lowered, qgis_layers)
            layer_hint = matched_layer or self._extract_layer_hint(lowered)

            actions: List[Dict[str, Any]] = []
            if self._is_population_distribution_request(lowered):
                actions = self._build_population_distribution_actions(qgis_layers, layer_hint)
            if "热力图" in lowered or "heatmap" in lowered:
                params: Dict[str, Any] = {"layer_name": layer_hint} if layer_hint else {}
                actions.append({"tool_name": "create_heatmap", "tool_params": params})
            elif "流向" in lowered or "流线" in lowered or "flow" in lowered:
                params = {"layer_name": layer_hint} if layer_hint else {}
                actions.append({"tool_name": "create_flow_arrows", "tool_params": params})
            elif not actions:
                # General map creation: activate layer + set style + zoom
                if layer_hint:
                    actions.append({"tool_name": "set_layer_visibility", "tool_params": {"layer_name": layer_hint, "visible": True}})
                    actions.append({"tool_name": "set_active_layer", "tool_params": {"layer_name": layer_hint}})
                    actions.append({"tool_name": "zoom_to_layer", "tool_params": {"layer_name": layer_hint}})
                else:
                    output_dir = self.config.outputs_dir / "qgis_exports"
                    output_dir.mkdir(parents=True, exist_ok=True)
                    output_path = output_dir / "map_export.png"
                    actions.append({"tool_name": "export_map", "tool_params": {"file_path": str(output_path)}})

            if matched_layer:
                assistant_msg = f"已在 QGIS 中找到图层「{matched_layer}」，将对其执行可视化操作。"
            elif layer_hint:
                assistant_msg = f"将尝试对图层「{layer_hint}」执行可视化操作。请确认 QGIS 中已加载该图层。"
            else:
                assistant_msg = "将执行可视化操作。请确认 QGIS 中已加载相关数据图层。"

            return {
                "assistant_message": assistant_msg,
                "target": "qgis",
                "actions": actions,
            }

        # --- Export / map ---
        if any(token in lowered for token in ["导出", "export"]):
            return {
                "assistant_message": "QGIS 专业模式当前未配置 MiniMax，已为你准备地图导出提示；请在专业页手动填写导出路径后执行。",
                "target": "qgis",
                "actions": [{"tool_name": "get_layers", "tool_params": {}}],
            }

        # --- Default fallback ---
        return {
            "assistant_message": "QGIS 专业模式当前使用规则兜底。我先读取 QGIS 图层状态，复杂自然语言规划需要配置 MiniMax API。",
            "target": "qgis",
            "actions": [{"tool_name": "get_layers", "tool_params": {}}],
        }

    @staticmethod
    def _match_qgis_layer(message_lower: str, qgis_layers: "List[Dict[str, Any]] | None") -> str:
        """Match the user's request to an actual QGIS layer by keyword overlap."""
        if not qgis_layers:
            return ""

        # Extract topic keywords from the user message
        topic_keywords: List[str] = []
        bilingual_topics = (
            ("人口", "population"),
            ("密度", "density"),
            ("气温", "temperature"),
            ("降水", "precipitation"),
            ("地形", "terrain"),
            ("土壤", "soil"),
            ("迁移", "migration"),
            ("经济", "gdp"),
            ("交通", "transport"),
        )
        for zh_token, en_token in bilingual_topics:
            if zh_token in message_lower or en_token in message_lower:
                topic_keywords.extend([zh_token, en_token])
        if "gdp" in message_lower:
            topic_keywords.append("gdp")

        if not topic_keywords:
            return ""

        has_migration_intent = "迁移" in message_lower or "migration" in message_lower or "流向" in message_lower or "flow" in message_lower
        best_layer = ""
        best_score = 0
        for layer_info in qgis_layers:
            layer_name = str(layer_info.get("name") or layer_info.get("layer_name") or "").lower()
            if not layer_name:
                continue
            score = sum(1 for kw in topic_keywords if kw in layer_name)
            if has_migration_intent:
                if "migration" in layer_name or "flow" in layer_name:
                    score += 4
                elif "population" in layer_name:
                    score -= 2
            if score > best_score:
                best_score = score
                # Return the original (non-lowered) name
                best_layer = str(layer_info.get("name") or layer_info.get("layer_name") or "")
        return best_layer

    @staticmethod
    def _extract_layer_hint(lowered: str) -> str:
        """Try to extract a plausible layer name from a Chinese natural language request."""
        import re as _re

        # Pattern: "中国人口分布图" → "中国人口"; "上海GDP图" → "上海GDP"
        match = _re.search(r"([一-鿿A-Za-z0-9]{2,}?)(?:分布)?(?:地图|图)", lowered)
        if match:
            candidate = match.group(1)
            skip = {"制作", "生成", "创建", "绘制", "建立", "导出", "一张", "一个", "一幅"}
            if candidate not in skip and len(candidate) >= 2:
                return candidate
        return ""

    @staticmethod
    def _is_population_distribution_request(lowered: str) -> bool:
        has_population_topic = any(token in lowered for token in ("人口", "population", "density", "pd_"))
        has_distribution_intent = any(token in lowered for token in ("分布", "密度", "分布图", "专题图", "choropleth"))
        has_map_create_intent = any(token in lowered for token in ("制作", "生成", "创建", "绘制", "渲染", "create", "generate", "draw", "render"))
        return bool(has_population_topic and (has_distribution_intent or has_map_create_intent))

    def _build_population_distribution_actions(
        self,
        qgis_layers: "List[Dict[str, Any]] | None",
        layer_hint: str,
    ) -> List[Dict[str, Any]]:
        actions: List[Dict[str, Any]] = []
        export_path = r"C:\Users\Public\qgis_export_map.png"
        primary_layer = self._pick_population_primary_layer(qgis_layers, layer_hint)
        boundary_layer = self._pick_boundary_layer(qgis_layers)

        if primary_layer:
            ref_params = self._layer_ref_params(primary_layer)
            actions.append({"tool_name": "set_layer_visibility", "tool_params": {**ref_params, "visible": True}})
            actions.append({"tool_name": "set_active_layer", "tool_params": dict(ref_params)})
            actions.append({"tool_name": "zoom_to_layer", "tool_params": dict(ref_params)})
        elif layer_hint:
            actions.append({"tool_name": "set_layer_visibility", "tool_params": {"layer_name": layer_hint, "visible": True}})
            actions.append({"tool_name": "set_active_layer", "tool_params": {"layer_name": layer_hint}})
            actions.append({"tool_name": "zoom_to_layer", "tool_params": {"layer_name": layer_hint}})

        if primary_layer and boundary_layer:
            primary_id = str(primary_layer.get("id") or primary_layer.get("layer_id") or "")
            boundary_id = str(boundary_layer.get("id") or boundary_layer.get("layer_id") or "")
            primary_name = str(primary_layer.get("name") or primary_layer.get("layer_name") or "")
            boundary_name = str(boundary_layer.get("name") or boundary_layer.get("layer_name") or "")
            if not (primary_id and primary_id == boundary_id) and not (primary_name and primary_name == boundary_name):
                boundary_ref = self._layer_ref_params(boundary_layer)
                actions.append({"tool_name": "set_layer_visibility", "tool_params": {**boundary_ref, "visible": True}})
                actions.append({"tool_name": "set_layer_z_order", "tool_params": {**boundary_ref, "position": "top"}})

        if not actions:
            actions.append({"tool_name": "get_layers", "tool_params": {}})
        else:
            actions.append({"tool_name": "export_map", "tool_params": {"file_path": export_path}})
        return actions

    @staticmethod
    def _layer_ref_params(layer_info: Dict[str, Any]) -> Dict[str, Any]:
        layer_id = str(layer_info.get("id") or layer_info.get("layer_id") or "").strip()
        layer_name = str(layer_info.get("name") or layer_info.get("layer_name") or "").strip()
        if layer_id:
            return {"layer_id": layer_id}
        if layer_name:
            return {"layer_name": layer_name}
        return {}

    def _pick_population_primary_layer(
        self,
        qgis_layers: "List[Dict[str, Any]] | None",
        layer_hint: str = "",
    ) -> "Dict[str, Any] | None":
        if not qgis_layers:
            return None

        hint = (layer_hint or "").lower()
        best_layer: Dict[str, Any] | None = None
        best_score = -10**9
        for layer_info in qgis_layers:
            layer_name = str(layer_info.get("name") or layer_info.get("layer_name") or "").lower()
            if not layer_name:
                continue

            geometry_type = str(layer_info.get("geometry_type") or "").lower()
            raw_type = str(layer_info.get("type") or "").lower()
            is_raster = "raster" in geometry_type or raw_type in {"1", "raster"}

            score = 0
            if "migration" in layer_name or "迁移" in layer_name:
                score -= 120
            if "population" in layer_name or "人口" in layer_name:
                score += 120
            if "density" in layer_name or "密度" in layer_name:
                score += 90
            if "_pd_" in layer_name or layer_name.startswith("pd_") or "population_density" in layer_name:
                score += 120
            if "province_population" in layer_name:
                score += 40
            if "sample" in layer_name:
                score -= 25
            if is_raster:
                score += 60
            if hint and hint in layer_name:
                score += 45

            if score > best_score:
                best_score = score
                best_layer = layer_info
        return best_layer if best_score > 0 else None

    @staticmethod
    def _pick_boundary_layer(qgis_layers: "List[Dict[str, Any]] | None") -> "Dict[str, Any] | None":
        if not qgis_layers:
            return None

        best_layer: Dict[str, Any] | None = None
        best_score = -10**9
        for layer_info in qgis_layers:
            layer_name = str(layer_info.get("name") or layer_info.get("layer_name") or "").lower()
            if not layer_name:
                continue
            score = 0
            if "china_provinces" in layer_name:
                score += 150
            if "province" in layer_name or "boundary" in layer_name or "省界" in layer_name:
                score += 100
            if "population" in layer_name:
                score -= 40
            if score > best_score:
                best_score = score
                best_layer = layer_info
        return best_layer if best_score > 0 else None

    @staticmethod
    def schema_for_prompt() -> List[Dict[str, Any]]:
        return QGIS_TOOL_SCHEMA
