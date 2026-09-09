import { expect, it, vi } from "vitest";
import { JobActivity } from "../lib/jobActivity";

it("keeps a concurrent map task locked when a read-only answer finishes", () => {
  const jobs = new JobActivity<string>();
  jobs.add("answer", true);
  expect(jobs.busy).toBe(true);
  expect(jobs.mapBusy).toBe(false);
  jobs.add("map");
  expect(jobs.mapBusy).toBe(true);
  expect(jobs.delete("answer")).toBe(true);
  expect(jobs.delete("answer")).toBe(false);
  expect(jobs.mapBusy).toBe(true);
  jobs.delete("map");
  expect(jobs.busy).toBe(false);
});
it("unlocks the map while a remaining answer continues and closes all streams on unmount", () => {
  const jobs = new JobActivity<string>();
  jobs.add("map", false); jobs.add("answer", true);
  jobs.delete("map");
  expect(jobs.mapBusy).toBe(false);
  expect(jobs.busy).toBe(true);
  const close = vi.fn(); jobs.closeAll(close);
  expect(close).toHaveBeenCalledWith("answer");
  expect(jobs.has("answer")).toBe(false);
  expect(jobs.busy).toBe(false);
});
