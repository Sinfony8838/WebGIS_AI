import { describe, expect, it } from "vitest";
import { buildAuthenticatedUrl, getApiBase } from "../api";

// 注：合并后的前端暂不携带访问令牌（旧版 setStoredApiToken/buildJobStreamUrl 已移除）。
// 若后端启用 WEBGIS_AI_AUTH_TOKEN 公网鉴权，需要先恢复前端令牌支持。
describe("api url helpers", () => {
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
});
