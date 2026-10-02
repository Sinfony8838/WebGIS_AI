# -*- coding: utf-8 -*-
"""Phase B 真实交互走查：剖面独立窗口（任务3）+ 课前剖面预设（任务4）。

前置：后端 127.0.0.1:18643（独立数据目录），前端 127.0.0.1:5822。
真实鼠标拖动/缩放剖面窗口（dispatchEvent 合成 pointer 事件序列 + 数值断言）。
"""
from __future__ import annotations

import os
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
SHOTS = ROOT / "scratch" / "e2e" / "shots"
SHOTS.mkdir(parents=True, exist_ok=True)
FRONT = os.getenv("WEBGIS_QA_FRONT", "http://127.0.0.1:5822")
BACK = os.getenv("WEBGIS_QA_BACK", "http://127.0.0.1:18643")

results: list[dict] = []


def record(step: str, ok: bool, detail: str = "") -> None:
    results.append({"step": step, "ok": ok, "detail": detail})
    print(("PASS " if ok else "FAIL ") + step + (" | " + detail if detail else ""), flush=True)


def shot(page, name: str) -> None:
    page.screenshot(path=str(SHOTS / name), full_page=False)


def drag(page, locator, dx: int, dy: int) -> None:
    """真实指针序列拖动（pointerdown → pointermove 序列 → pointerup）。"""
    box = locator.bounding_box()
    assert box, "locator not visible"
    sx, sy = box["x"] + box["width"] / 2, box["y"] + 8
    page.mouse.move(sx, sy)
    page.mouse.down()
    steps = 8
    for i in range(1, steps + 1):
        page.mouse.move(sx + dx * i / steps, sy + dy * i / steps)
    page.mouse.up()


def resize(page, handle_locator, dx: int, dy: int) -> None:
    box = handle_locator.bounding_box()
    assert box, "handle not visible"
    sx, sy = box["x"] + 4, box["y"] + 4
    page.mouse.move(sx, sy)
    page.mouse.down()
    steps = 6
    for i in range(1, steps + 1):
        page.mouse.move(sx + dx * i / steps, sy + dy * i / steps)
    page.mouse.up()


def draw_measure_line(page, start: tuple[float, float], end: tuple[float, float]) -> None:
    """在 2D 地图画布上真实画一条测线（click 起点→ move → click 终点 → dblclick 结束）。"""
    page.mouse.click(start[0], start[1])
    page.mouse.move((start[0] + end[0]) / 2, (start[1] + end[1]) / 2, steps=5)
    page.mouse.click(end[0], end[1])
    page.mouse.dblclick(end[0], end[1])


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1600, "height": 900})
        page = ctx.new_page()

        # ---- 0. 登录 ----
        try:
            page.goto(FRONT, wait_until="domcontentloaded")
            page.wait_for_selector("input[type=email]", timeout=20000)
            page.fill("input[type=email]", "admin@example.com")
            page.fill("input[type=password]", "admin12345")
            page.get_by_role("button", name="登录", exact=True).last.click()
            expect(page.locator("input[type=email]")).to_have_count(0, timeout=20000)
            page.wait_for_timeout(4000)
            record("登录", True)
        except Exception as exc:  # noqa: BLE001
            record("登录", False, str(exc)[:200])
            return 1

        # ---- 1. 展开地图工具并进入测距模式 ----
        try:
            page.get_by_role("button", name="展开地图工具与可视化地图").click(timeout=10000)
            # 默认 3D 地球：先切到 2D 平面地图（测距/剖面仅 2D）
            mode_toggle = page.get_by_test_id("map-mode-toggle")
            if mode_toggle.get_attribute("aria-pressed") == "true":
                mode_toggle.click()
                page.wait_for_timeout(2500)
            page.get_by_role("button", name="测距模式 · 快捷键 M").click(timeout=10000)
            page.wait_for_timeout(600)
            record("进入测距模式", True)
        except Exception as exc:  # noqa: BLE001
            record("进入测距模式", False, str(exc)[:200])
            shot(page, "b01-measure-mode-fail.png")
            return 1

        # ---- 1b. 放大到城市级视野，保证测线长度落在 1m–2000km 有效区间 ----
        try:
            canvas = page.locator(".ol-viewport").first
            box = canvas.bounding_box()
            cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
            for _ in range(5):
                page.mouse.move(cx, cy)
                page.mouse.wheel(0, -300)
                page.wait_for_timeout(220)
            record("滚轮放大到城市级视野", True)
        except Exception as exc:  # noqa: BLE001
            record("滚轮放大", False, str(exc)[:200])

        # ---- 2. 真实画两条测线（地图画布坐标） ----
        try:
            canvas = page.locator(".ol-viewport").first
            box = canvas.bounding_box()
            assert box
            cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
            draw_measure_line(page, (cx - 220, cy - 60), (cx + 160, cy + 40))
            page.wait_for_timeout(800)
            # 画完一条自动回到浏览模式：重新进入测距再画第二条
            page.get_by_role("button", name="测距模式 · 快捷键 M").click()
            page.wait_for_timeout(500)
            draw_measure_line(page, (cx - 120, cy + 140), (cx + 240, cy - 120))
            page.wait_for_timeout(1200)
            bar = page.get_by_test_id("profile-windows-bar")
            expect(bar).to_be_visible(timeout=10000)
            chips = page.locator("[data-testid^=profile-line-chip-]").count()
            record("真实绘制两条测线", chips >= 2, f"{chips} 条测线芯片")
        except Exception as exc:  # noqa: BLE001
            record("真实绘制两条测线", False, str(exc)[:200])
            shot(page, "b02-lines-fail.png")
            return 1

        # ---- 3. 打开四个窗口：两条线 × 人口 + 地形 ----
        try:
            chip_ids = page.evaluate(
                "() => Array.from(document.querySelectorAll('[data-testid^=profile-line-chip-]'))"
                ".map(el => el.dataset.testid.replace('profile-line-chip-', ''))"
            )
            assert len(chip_ids) >= 2, chip_ids
            for rid in chip_ids[:2]:
                page.get_by_test_id(f"profile-line-open-population-{rid}").click()
                page.wait_for_timeout(300)
                page.get_by_test_id(f"profile-line-open-terrain-{rid}").click()
                page.wait_for_timeout(300)
            windows = page.locator("[data-testid^=profile-window-pw_]")
            expect(windows).to_have_count(4, timeout=10000)
            record("两条测线同时打开人口+地形共四个窗口", True, f"{windows.count()} 窗")
            shot(page, "b03-four-windows.png")
        except Exception as exc:  # noqa: BLE001
            record("打开四窗口", False, str(exc)[:200])
            shot(page, "b03-windows-fail.png")

        # ---- 4. 剖面数据真实加载（人口源 + 地形） ----
        try:
            # 每个独立窗口异步采样；等待四个完成，不能把首个本地结果当成地形也已完成。
            expect(page.locator(".profile-window-meta")).to_have_count(4, timeout=60000)
            pop_meta = page.locator(".profile-window-meta", has_text="人口密度").count()
            terrain_meta = page.locator(".profile-window-meta", has_text="高程").count()
            footnotes = page.locator(".profile-window-footnote").count()
            errs = page.locator(".profile-window-error").all_text_contents()
            record("窗口内数据与来源/分辨率/无数据标注", pop_meta >= 1 and terrain_meta >= 1 and footnotes >= 1,
                   f"人口 {pop_meta} · 地形 {terrain_meta} · 脚注 {footnotes} · 错误: {errs}")
        except Exception as exc:  # noqa: BLE001
            record("窗口数据加载", False, str(exc)[:200])

        # ---- 5. 真实鼠标拖动第一个窗口 + 数值断言 ----
        try:
            first = page.locator("[data-testid^=profile-window-pw_]").first
            before = first.bounding_box()
            head = first.locator(".profile-window-head")
            drag(page, head, 180, 90)
            page.wait_for_timeout(400)
            after = first.bounding_box()
            moved = abs(after["x"] - before["x"] - 180) < 40 and abs(after["y"] - before["y"] - 90) < 40
            record("真实拖动窗口（±180,+90）", moved, f"({before['x']:.0f},{before['y']:.0f})→({after['x']:.0f},{after['y']:.0f})")
            shot(page, "b05-dragged.png")
        except Exception as exc:  # noqa: BLE001
            record("拖动窗口", False, str(exc)[:200])

        # ---- 6. 真实缩放窗口 ----
        try:
            first = page.locator("[data-testid^=profile-window-pw_]").first
            before = first.bounding_box()
            handle = first.locator(".profile-window-resize")
            resize(page, handle, 160, 80)
            page.wait_for_timeout(400)
            after = first.bounding_box()
            grown = (after["width"] - before["width"]) > 80 and (after["height"] - before["height"]) > 30
            record("真实缩放窗口", grown, f"{before['width']:.0f}x{before['height']:.0f}→{after['width']:.0f}x{after['height']:.0f}")
        except Exception as exc:  # noqa: BLE001
            record("缩放窗口", False, str(exc)[:200])

        # ---- 7. 单独关闭某线的一个窗口，另一窗口保留 ----
        try:
            windows_before = page.locator("[data-testid^=profile-window-pw_]").count()
            target = page.locator("[data-testid^=profile-window-pw_][data-testid*='_terrain']").first
            wid = target.get_attribute("data-testid").replace("profile-window-", "")
            page.get_by_test_id(f"profile-window-close-{wid}").click()
            page.wait_for_timeout(400)
            after_count = page.locator("[data-testid^=profile-window-pw_]").count()
            record("关闭单线地形窗口后其余窗口保留", after_count == windows_before - 1,
                   f"{windows_before}→{after_count}")
        except Exception as exc:  # noqa: BLE001
            record("关闭单窗口", False, str(exc)[:200])

        # ---- 8. 一键暂收 / 恢复（保留图表、位置与尺寸） ----
        try:
            first = page.locator("[data-testid^=profile-window-pw_]").first
            geom_before = first.bounding_box()
            page.get_by_test_id("profiles-collapse-all").click()
            page.wait_for_timeout(300)
            hidden_count = page.locator(".profile-window.is-hidden").count()
            page.get_by_test_id("profiles-collapse-all").click()
            page.wait_for_timeout(300)
            geom_after = first.bounding_box()
            restored = (abs(geom_after["x"] - geom_before["x"]) < 2 and abs(geom_after["y"] - geom_before["y"]) < 2
                        and abs(geom_after["width"] - geom_before["width"]) < 2)
            record("一键暂收→恢复保留位置尺寸", hidden_count >= 1 and restored,
                   f"hidden={hidden_count}, 位置偏差 {abs(geom_after['x'] - geom_before['x']):.1f}px")
        except Exception as exc:  # noqa: BLE001
            record("暂收/恢复", False, str(exc)[:200])

        # ---- 9. 清除一条测线同步清理其窗口 ----
        try:
            chip_ids = page.evaluate(
                "() => Array.from(document.querySelectorAll('[data-testid^=profile-line-chip-]'))"
                ".map(el => el.dataset.testid.replace('profile-line-chip-', ''))"
            )
            before_windows = page.locator("[data-testid^=profile-window-pw_]").count()
            page.get_by_test_id(f"profile-line-clear-{chip_ids[0]}").click()
            page.wait_for_timeout(500)
            after_windows = page.locator("[data-testid^=profile-window-pw_]").count()
            record("清除测线同步清理其窗口", after_windows < before_windows, f"{before_windows}→{after_windows}")
            shot(page, "b09-after-clear-line.png")
        except Exception as exc:  # noqa: BLE001
            record("清除测线", False, str(exc)[:200])

        ctx.close()
        browser.close()

    (ROOT / "scratch" / "e2e" / "phase_b_result.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    ok = all(r["ok"] for r in results)
    print("ALL-PASS" if ok else "HAS-FAILURES")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
