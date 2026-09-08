import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { TeachingMaterialViewer } from "../components/TeachingMaterialViewer";

describe("TeachingMaterialViewer", () => {
  const originals = ["showModal", "close"].map(key => [key, Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, key)] as const);
  beforeEach(() => {
    // jsdom has no top layer; browser acceptance checks stacking and focus.
    Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value: vi.fn(function (this: HTMLDialogElement) { this.setAttribute("open", ""); }) });
    Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value: vi.fn(function (this: HTMLDialogElement) { this.removeAttribute("open"); }) });
  });
  afterEach(() => {
    cleanup();
    originals.forEach(([key, descriptor]) => {
      if (descriptor) Object.defineProperty(HTMLDialogElement.prototype, key, descriptor);
      else Reflect.deleteProperty(HTMLDialogElement.prototype, key);
    });
  });

  it("opens modally and keeps Escape from closing the underlying database", () => {
    const onClose = vi.fn();
    const behind = vi.fn();
    window.addEventListener("keydown", behind);
    try {
      const view = render(<TeachingMaterialViewer open title="课堂截图" materials={[]} onClose={onClose} />);
      const dialog = screen.getByRole("dialog", { name: "课堂截图" });
      expect(HTMLDialogElement.prototype.showModal).toHaveBeenCalledOnce();
      fireEvent.keyDown(screen.getByRole("button", { name: "关闭资料预览" }), { key: "Escape" });
      expect(behind).not.toHaveBeenCalled();
      fireEvent(dialog, new Event("cancel", { cancelable: true }));
      expect(onClose).toHaveBeenCalledOnce();
      view.rerender(<TeachingMaterialViewer open={false} title="课堂截图" materials={[]} onClose={onClose} />);
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    } finally { window.removeEventListener("keydown", behind); }
  });

  it("embeds bilibili video links with the player iframe", () => {
    render(
      <TeachingMaterialViewer
        open
        title="胡焕庸线视频"
        onClose={() => undefined}
        materials={[
          {
            id: "hu_huanyong_bilibili_video",
            title: "胡焕庸线科普视频",
            type: "video",
            source: "bilibili",
            url: "https://www.bilibili.com/video/BV13p4y1X7Lu/?share_source=copy_web",
            thumbnail_url: "",
            description: "",
            region_binding: { name: "china" },
            sort_order: 1,
            created_at: "2026-05-05T00:00:00+08:00"
          }
        ]}
      />
    );

    const frame = screen.getByTitle("胡焕庸线科普视频");
    expect(frame).toHaveAttribute("src", expect.stringContaining("player.bilibili.com"));
    expect(frame).toHaveAttribute("src", expect.stringContaining("BV13p4y1X7Lu"));
  });
});
