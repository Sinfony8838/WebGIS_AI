import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { TeachingMaterialViewer } from "../components/TeachingMaterialViewer";

describe("TeachingMaterialViewer", () => {
  afterEach(() => {
    cleanup();
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
