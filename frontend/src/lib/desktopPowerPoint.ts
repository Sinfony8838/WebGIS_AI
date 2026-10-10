const DESKTOP_URL = "http://127.0.0.1:18998";

export interface DesktopPptResult {
  status: "opened" | "focused" | "cancelled";
  file_name?: string;
  foreground?: boolean;
}

async function desktopRequest(path: string, init?: RequestInit): Promise<Record<string, unknown>> {
  let response: Response;
  try {
    response = await fetch(`${DESKTOP_URL}${path}`, {
      ...init, credentials: "omit", cache: "no-store", signal: AbortSignal.timeout(5000)
    });
  } catch {
    throw new Error("本机连接中断。请检查文件选择框或 PowerPoint；操作可能已经开始，页面不会自动重复打开。");
  }
  const result = await response.json();
  if (!response.ok) throw new Error(String(result.message || "本机 PowerPoint 操作失败。"));
  return result;
}

/** No project credentials, uploads or absolute local paths cross this boundary. */
export async function openDesktopPowerPoint(action: "open" | "focus"): Promise<DesktopPptResult> {
  let connection: Record<string, unknown>;
  try {
    connection = await desktopRequest("/connection");
  } catch {
    throw new Error("未连接本机 PowerPoint。请先在这台教师电脑启动 Start-DesktopPowerPoint.ps1；若浏览器询问本地网络访问权限，请允许后重试。");
  }
  if (connection.service !== "webgis-desktop-powerpoint" || connection.protocol !== 1 || typeof connection.token !== "string") {
    throw new Error("本机连接器版本不匹配，请使用本项目提供的 PowerPoint 连接器。");
  }
  const accepted = await desktopRequest("/actions", {
    method: "POST", headers: { "Content-Type": "application/json", "X-WebGIS-Desktop": connection.token },
    body: JSON.stringify({ action })
  });
  const id = accepted.action_id;
  if (typeof id !== "string" || !/^[a-f0-9]{32}$/.test(id)) throw new Error("本机连接器返回了无效操作编号。");
  // The native picker can stay open. Never retry a POST on timeout: doing so
  // could open a second native dialog or duplicate an already opened deck.
  for (let attempt = 0; attempt < 300; attempt += 1) {
    const result = await desktopRequest(`/actions/${id}`, { headers: { "X-WebGIS-Desktop": connection.token } });
    if (result.status === "failed") throw new Error(String(result.message || "PowerPoint 未能打开课件。"));
    if (["opened", "focused", "cancelled"].includes(String(result.status))) return result as unknown as DesktopPptResult;
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
  throw new Error("本机操作仍在等待。请检查文件选择框或 PowerPoint 窗口，完成或取消后再操作；不会重复打开课件。");
}
