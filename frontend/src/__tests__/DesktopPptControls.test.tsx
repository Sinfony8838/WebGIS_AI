import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { DesktopPptControls } from "../components/DesktopPptControls";
import { openDesktopPowerPoint } from "../lib/desktopPowerPoint";
vi.mock("../lib/desktopPowerPoint", () => ({ openDesktopPowerPoint: vi.fn() }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });

it("offers one icon that directly requests native preview", async () => {
  const onNotice = vi.fn();
  vi.mocked(openDesktopPowerPoint).mockResolvedValue({ status: "shown" });
  render(<DesktopPptControls onNotice={onNotice} />);
  expect(screen.getAllByRole("button")).toHaveLength(1);
  const launcher = screen.getByRole("button", { name: "PPT 课件" });
  expect(launcher.textContent).toBe("");
  expect(launcher.querySelector("svg")).not.toBeNull();
  fireEvent.click(launcher);
  await waitFor(() => expect(launcher).toBeEnabled());
  expect(openDesktopPowerPoint).toHaveBeenCalledTimes(1);
  expect(openDesktopPowerPoint).toHaveBeenCalledWith("preview");
  expect(onNotice).not.toHaveBeenCalled();
});

it("reports connector failures without opening a page viewer", async () => {
  vi.mocked(openDesktopPowerPoint).mockRejectedValue(new Error("请启动本机连接器"));
  const onNotice = vi.fn();
  render(<DesktopPptControls onNotice={onNotice} />);
  fireEvent.click(screen.getByRole("button", { name: "PPT 课件" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("请启动本机连接器"));
  expect(screen.getByRole("button", { name: "关闭 PPT 连接提示" })).toHaveFocus();
  fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(onNotice).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "PPT 课件" })).toBeEnabled();
});

it("keeps cancellation quiet and reports blocked return to WebGIS", async () => {
  const onNotice = vi.fn();
  vi.mocked(openDesktopPowerPoint).mockResolvedValueOnce({ status: "cancelled" });
  render(<DesktopPptControls onNotice={onNotice} />);
  const launcher = screen.getByRole("button", { name: "PPT 课件" });
  fireEvent.click(launcher);
  await waitFor(() => expect(launcher).toBeEnabled());
  expect(onNotice).not.toHaveBeenCalled();
  vi.mocked(openDesktopPowerPoint).mockResolvedValueOnce({ status: "shown", foreground: false });
  fireEvent.click(launcher);
  await waitFor(() => expect(onNotice).toHaveBeenCalledWith(expect.stringContaining("Windows 未允许返回 WebGIS")));
});

it("does not submit twice while the picker or preview is pending", async () => {
  let complete!: (value: { status: "cancelled" }) => void;
  vi.mocked(openDesktopPowerPoint).mockReturnValue(new Promise(resolve => { complete = resolve; }));
  render(<DesktopPptControls onNotice={vi.fn()} />);
  const launcher = screen.getByRole("button", { name: "PPT 课件" });
  fireEvent.click(launcher);
  fireEvent.click(launcher);
  expect(launcher).toBeDisabled();
  expect(launcher).toHaveAttribute("aria-busy", "true");
  expect(openDesktopPowerPoint).toHaveBeenCalledTimes(1);
  complete({ status: "cancelled" });
  await waitFor(() => expect(launcher).toBeEnabled());
});
