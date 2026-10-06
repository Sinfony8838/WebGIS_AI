import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../api";
import { restoreClassroomProject } from "../lib/projectRecovery";

function fixture() {
  const pointers = new Map([["teacher", "old-project"]]);
  const read = vi.fn().mockResolvedValue({ project_id: "old-project" });
  const create = vi.fn().mockResolvedValue({ project_id: "new-project" });
  const remember = vi.fn((id: string) => { pointers.set("teacher", id); });
  const isCurrent = vi.fn().mockReturnValue(true);
  return { pointers, access: { read, create, remember, isCurrent } };
}

describe("classroom project restoration", () => {
  it("reads the saved project without creating or rewriting its pointer", async () => {
    const { pointers, access } = fixture();
    expect(await restoreClassroomProject(pointers.get("teacher")!, access)).toEqual({
      project: { project_id: "old-project" }, restored: true
    });
    expect(access.read).toHaveBeenCalledWith("old-project");
    expect(access.create).not.toHaveBeenCalled();
    expect(access.remember).not.toHaveBeenCalled();
  });

  it.each([400, 401, 403, 404, 429, 500, 503])("HTTP %i keeps the old pointer and never creates", async (status) => {
    const { pointers, access } = fixture();
    const error = new ApiError(`synthetic HTTP ${status}`, status);
    access.read.mockRejectedValue(error);
    await expect(restoreClassroomProject(pointers.get("teacher")!, access)).rejects.toBe(error);
    expect(pointers.get("teacher")).toBe("old-project");
    expect(access.create).not.toHaveBeenCalled();
    expect(access.remember).not.toHaveBeenCalled();
  });

  it.each([new TypeError("synthetic network failure"), new SyntaxError("synthetic bad JSON")])(
    "%s is reported without replacement", async (error) => {
      const { pointers, access } = fixture();
      access.read.mockRejectedValue(error);
      await expect(restoreClassroomProject(pointers.get("teacher")!, access)).rejects.toBe(error);
      expect(pointers.get("teacher")).toBe("old-project");
      expect(access.create).not.toHaveBeenCalled();
      expect(access.remember).not.toHaveBeenCalled();
    }
  );

  it("a later retry reads the same old ID after temporary failure", async () => {
    const { pointers, access } = fixture();
    access.read.mockRejectedValueOnce(new Error("synthetic temporary failure"));
    await expect(restoreClassroomProject(pointers.get("teacher")!, access)).rejects.toThrow("temporary");
    expect((await restoreClassroomProject(pointers.get("teacher")!, access))?.restored).toBe(true);
    expect(access.read.mock.calls).toEqual([["old-project"], ["old-project"]]);
    expect(access.create).not.toHaveBeenCalled();
  });

  it("creates for a first visit or an explicit new-project choice and remembers only success", async () => {
    const { pointers, access } = fixture();
    expect(await restoreClassroomProject("", access)).toEqual({
      project: { project_id: "new-project" }, restored: false
    });
    expect(access.read).not.toHaveBeenCalled();
    expect(access.create).toHaveBeenCalledTimes(1);
    expect(pointers.get("teacher")).toBe("new-project");
  });

  it("failed explicit creation preserves the previous pointer", async () => {
    const { pointers, access } = fixture();
    access.create.mockRejectedValue(new Error("synthetic POST failure"));
    await expect(restoreClassroomProject("", access)).rejects.toThrow("POST failure");
    expect(pointers.get("teacher")).toBe("old-project");
    expect(access.remember).not.toHaveBeenCalled();
  });

  it("a cancelled initialization makes no request", async () => {
    const { access } = fixture();
    access.isCurrent.mockReturnValue(false);
    expect(await restoreClassroomProject("", access)).toBeNull();
    expect(access.read).not.toHaveBeenCalled();
    expect(access.create).not.toHaveBeenCalled();
  });

  it.each(["old-project", ""])("cancelled in-flight work for %s does not commit a pointer", async (id) => {
    const { pointers, access } = fixture();
    let finish!: (project: { project_id: string }) => void;
    const pending = new Promise<{ project_id: string }>(resolve => { finish = resolve; });
    access.read.mockReturnValue(pending);
    access.create.mockReturnValue(pending);
    const request = restoreClassroomProject(id, access);
    access.isCurrent.mockReturnValue(false);
    finish({ project_id: "late-project" });
    expect(await request).toBeNull();
    expect(pointers.get("teacher")).toBe("old-project");
    expect(access.remember).not.toHaveBeenCalled();
  });
});
