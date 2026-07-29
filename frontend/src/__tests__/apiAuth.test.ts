import { afterEach, describe, expect, it, vi } from "vitest";
import {
  buildAuthenticatedUrl,
  getApiBase,
  setCsrfToken,
  setUnauthorizedHandler,
  updateAdminUser
} from "../api";

// 注：合并后的前端暂不携带访问令牌（旧版 setStoredApiToken/buildJobStreamUrl 已移除）。
// 若后端启用 WEBGIS_AI_AUTH_TOKEN 公网鉴权，需要先恢复前端令牌支持。
describe("api url helpers", () => {
  afterEach(() => {
    setCsrfToken("");
    setUnauthorizedHandler(null);
    vi.restoreAllMocks();
  });
  it("prefixes relative paths with the API base", () => {
    const url = new URL(buildAuthenticatedUrl("/files/outputs/project_demo/report.md?download=1"));

    expect(url.origin).toBe(new URL(getApiBase()).origin);
    expect(url.pathname).toBe("/files/outputs/project_demo/report.md");
    expect(url.searchParams.get("download")).toBe("1");
  });

  it("keeps absolute URLs untouched and empty paths empty", () => {
    expect(buildAuthenticatedUrl("https://example.com/a.png")).toBe("https://example.com/a.png");
    expect(buildAuthenticatedUrl("")).toBe("");
  });

  it("sends cookies and the in-memory CSRF token for mutations", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ status: "success", user: {} }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );
    setCsrfToken("csrf-only-in-memory");

    await updateAdminUser("user_1", { display_name: "王老师" });

    const [, init] = fetchMock.mock.calls[0];
    expect(init?.credentials).toBe("include");
    expect(new Headers(init?.headers).get("X-WebGIS-CSRF")).toBe("csrf-only-in-memory");
  });

  it("invokes the centralized sign-out handler on any 401", async () => {
    const unauthorized = vi.fn();
    setUnauthorizedHandler(unauthorized);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: { message: "登录已失效" } }), {
        status: 401,
        headers: { "Content-Type": "application/json" }
      })
    );

    await expect(updateAdminUser("user_1", { display_name: "王老师" })).rejects.toThrow("登录已失效");
    expect(unauthorized).toHaveBeenCalledTimes(1);
  });
});
