import { afterEach, describe, expect, it, vi } from "vitest";
import {
  fetchProject, fetchLayers, fetchOutputs, fetchLessonResources, fetchActiveTeachingMaps,
  setCsrfToken, setUnauthorizedHandler, updateAdminUser
} from "../api";

function response(status = 200) {
  return new Response(JSON.stringify(status === 401 ? { detail: "synthetic expired session" } : { items: [] }),
    { status, headers: { "Content-Type": "application/json" } });
}
function deferred() {
  let resolve!: (value: Response) => void;
  const promise = new Promise<Response>(yes => { resolve = yes; });
  return { promise, resolve };
}
const readers = [fetchProject, fetchLayers, fetchOutputs, fetchLessonResources, fetchActiveTeachingMaps];

describe("snapshot request cancellation and auth ownership", () => {
  afterEach(() => { setCsrfToken(""); setUnauthorizedHandler(null); vi.restoreAllMocks(); });

  it.each(readers)("forwards optional signal through %s while keeping cookie authentication", async read => {
    const mock = vi.spyOn(globalThis, "fetch").mockImplementation(async () => response());
    const controller = new AbortController();
    await read("project-a", controller.signal);
    await read("project-a");
    expect(mock.mock.calls[0][1]?.signal).toBe(controller.signal);
    expect(mock.mock.calls[0][1]?.credentials).toBe("include");
    expect(mock.mock.calls[1][0]).toBe(mock.mock.calls[0][0]);
    expect(mock.mock.calls[1][1]?.signal).toBeUndefined();
  });

  it("preserves AbortError instead of presenting cancellation as a network failure", async () => {
    const controller = new AbortController();
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => { controller.abort(); throw new TypeError("cancelled transport"); });
    await expect(fetchProject("project-a", controller.signal)).rejects.toMatchObject({ name: "AbortError" });
  });

  it("an aborted transport's late 401 cannot sign out the current actor", async () => {
    const batch = deferred();
    const unauthorized = vi.fn();
    setUnauthorizedHandler(unauthorized);
    setCsrfToken("synthetic-session-a");
    vi.spyOn(globalThis, "fetch").mockReturnValue(batch.promise);
    const controller = new AbortController();
    const pending = fetchProject("project-a", controller.signal);
    const checked = expect(pending).rejects.toMatchObject({ name: "AbortError" });
    controller.abort();
    batch.resolve(response(401));
    await checked;
    expect(unauthorized).not.toHaveBeenCalled();
  });

  it("an old auth generation's 401 reports failure but preserves the newer session", async () => {
    const batch = deferred();
    const unauthorized = vi.fn();
    setUnauthorizedHandler(unauthorized);
    setCsrfToken("synthetic-session-a");
    const mock = vi.spyOn(globalThis, "fetch").mockReturnValueOnce(batch.promise).mockImplementation(async () => response());
    const pending = fetchProject("project-a");
    const checked = expect(pending).rejects.toMatchObject({ status: 401 });
    setCsrfToken("synthetic-session-b");
    batch.resolve(response(401));
    await checked;
    expect(unauthorized).not.toHaveBeenCalled();
    await updateAdminUser("synthetic-user", { nickname: "synthetic" });
    expect(new Headers(mock.mock.calls[1][1]?.headers).get("X-WebGIS-CSRF")).toBe("synthetic-session-b");
  });

  it("a current session's 401 still signs out and removes its CSRF token", async () => {
    const unauthorized = vi.fn();
    setUnauthorizedHandler(unauthorized);
    setCsrfToken("synthetic-current-session");
    const mock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(response(401)).mockResolvedValueOnce(response());
    await expect(fetchProject("project-a")).rejects.toMatchObject({ status: 401 });
    expect(unauthorized).toHaveBeenCalledTimes(1);
    await updateAdminUser("synthetic-user", { nickname: "synthetic" });
    expect(new Headers(mock.mock.calls[1][1]?.headers).has("X-WebGIS-CSRF")).toBe(false);
  });
});
