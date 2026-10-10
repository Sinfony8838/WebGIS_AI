import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { DesktopPptControls } from "../components/DesktopPptControls";
import { openDesktopPowerPoint } from "../lib/desktopPowerPoint";
vi.mock("../lib/desktopPowerPoint", () => ({ openDesktopPowerPoint: vi.fn() }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });

it("opens on the teacher computer and focuses without invoking page rendering", async () => {
  const onNotice = vi.fn();
  vi.mocked(openDesktopPowerPoint).mockResolvedValue({ status: "opened", file_name: "课件.pptx", foreground: true });
  render(<DesktopPptControls onNotice={onNotice} />);
  fireEvent.click(screen.getByRole("button", { name: "打开 PPT" }));
  await waitFor(() => expect(onNotice).toHaveBeenCalledWith("课件.pptx已在本机 PowerPoint 打开。"));
  expect(openDesktopPowerPoint).toHaveBeenCalledWith("open");
  vi.mocked(openDesktopPowerPoint).mockResolvedValue({ status: "focused", foreground: true });
  fireEvent.click(screen.getByRole("button", { name: "切回 PPT" }));
  await waitFor(() => expect(openDesktopPowerPoint).toHaveBeenLastCalledWith("focus"));
});

it("reports connector failures and never silently opens the in-page viewer", async () => {
  vi.mocked(openDesktopPowerPoint).mockRejectedValue(new Error("请启动本机连接器"));
  const onNotice = vi.fn();
  render(<DesktopPptControls onNotice={onNotice} />);
  fireEvent.click(screen.getByRole("button", { name: "打开 PPT" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("请启动本机连接器"));
  expect(onNotice).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "打开 PPT" })).toBeEnabled();
});

it("does not claim cancellation or blocked foreground activation succeeded", async () => {
  const onNotice = vi.fn();
  vi.mocked(openDesktopPowerPoint).mockResolvedValueOnce({ status: "cancelled" });
  render(<DesktopPptControls onNotice={onNotice} />);
  fireEvent.click(screen.getByRole("button", { name: "打开 PPT" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "打开 PPT" })).toBeEnabled());
  expect(onNotice).not.toHaveBeenCalled();
  vi.mocked(openDesktopPowerPoint).mockResolvedValueOnce({ status: "focused", foreground: false });
  fireEvent.click(screen.getByRole("button", { name: "切回 PPT" }));
  await waitFor(() => expect(onNotice).toHaveBeenCalledWith(expect.stringContaining("Windows 未允许")));
});
