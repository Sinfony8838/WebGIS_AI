import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { TeachingMaterialViewer } from "../components/TeachingMaterialViewer";
import { getApiBase } from "../api";
import type { TeachingMaterial } from "../types";

vi.mock("../api", () => ({ getApiBase: vi.fn(() => "http://127.0.0.1:18999") }));

function material(url: string, type: TeachingMaterial["type"] = "animation"): TeachingMaterial {
  return {
    id: "fixture", title: "教学素材", type, source: "teacher_upload", url,
    thumbnail_url: "", description: "", region_binding: {}, sort_order: 1, created_at: "",
  };
}

describe("TeachingMaterialViewer", () => {
  const originals = ["showModal", "close"].map(key => [key, Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, key)] as const);
  beforeEach(() => {
    vi.mocked(getApiBase).mockReturnValue("http://127.0.0.1:18999");
    // jsdom has no top layer; browser acceptance checks stacking and focus.
    Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value: vi.fn(function (this: HTMLDialogElement) { this.setAttribute("open", ""); }) });
    Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value: vi.fn(function (this: HTMLDialogElement) { this.removeAttribute("open"); }) });
  });

  it.each([
    "/files/uploads/interactive.html",
    "/workflow-files/workflow_fixture/interactive.HTM?version=1#activity",
    "http://127.0.0.1:18999/files/uploads/interactive.html",
  ])("previews local HTML with scripts but without app-origin access: %s", (url) => {
    render(<TeachingMaterialViewer open title="资料" onClose={() => undefined} materials={[material(url)]} />);
    const frame = screen.getByTitle("教学素材");
    expect(frame.tagName).toBe("IFRAME");
    expect(frame).toHaveAttribute("sandbox", "allow-scripts");
    expect(frame).toHaveAttribute("src", url.startsWith("/") ? `http://127.0.0.1:18999${url}` : url);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it.each(["/", "/api", "http://127.0.0.1:18999/api/"])("supports API base %s for file previews", (base) => {
    vi.mocked(getApiBase).mockReturnValue(base);
    render(<TeachingMaterialViewer open title="资料" onClose={() => undefined}
      materials={[material("/files/uploads/interactive.html", "document")]} />);
    expect(screen.getByTitle("教学素材")).toHaveAttribute("sandbox", "allow-scripts");
  });

  it.each([
    ["/files/uploads/animation.gif", "animation"],
    ["/files/uploads/map.svg", "image"],
  ] as const)("keeps %s as an image", (url, type) => {
    render(<TeachingMaterialViewer open title="资料" onClose={() => undefined} materials={[material(url, type)]} />);
    expect(screen.getByRole("img", { name: "教学素材" })).toHaveAttribute("src", `http://127.0.0.1:18999${url}`);
    expect(screen.queryByTitle("教学素材")).not.toBeInTheDocument();
  });

  it.each([
    "https://example.com/files/uploads/interactive.html",
    "//example.com/workflow-files/workflow_fixture/interactive.html",
    "http://127.0.0.1:18999/other/interactive.html",
    "/files/../../other/interactive.html",
  ])("opens HTML outside authorized file routes as a link: %s", (url) => {
    render(<TeachingMaterialViewer open title="资料" onClose={() => undefined} materials={[material(url)]} />);
    expect(screen.getByRole("link", { name: "打开资料" })).toHaveAttribute("target", "_blank");
    expect(screen.queryByTitle("教学素材")).not.toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
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
