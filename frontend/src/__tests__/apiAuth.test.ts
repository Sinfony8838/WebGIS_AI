import { describe, expect, it, beforeEach } from "vitest";
import { buildAuthenticatedUrl, buildJobStreamUrl, setStoredApiToken } from "../api";

describe("api auth helpers", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("does not add access_token when no token is configured", () => {
    const url = new URL(buildJobStreamUrl("job_1"));

    expect(url.pathname).toBe("/jobs/job_1/stream");
    expect(url.searchParams.has("access_token")).toBe(false);
  });

  it("adds access_token for EventSource and file links", () => {
    setStoredApiToken("secret-token");

    const streamUrl = new URL(buildJobStreamUrl("job_1"));
    const fileUrl = new URL(buildAuthenticatedUrl("/files/outputs/project_demo/report.md?download=1"));

    expect(streamUrl.searchParams.get("access_token")).toBe("secret-token");
    expect(fileUrl.searchParams.get("access_token")).toBe("secret-token");
    expect(fileUrl.searchParams.get("download")).toBe("1");
  });
});
