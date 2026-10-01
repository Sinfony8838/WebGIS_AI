# -*- coding: utf-8 -*-
"""Phase B 任务4走查：课前保存剖面测线及窗口布局 → 刷新恢复 → 发布 → 开始课堂后布局一致。

前置：后端 127.0.0.1:18643（独立数据目录），前端 127.0.0.1:5822。
"""
from __future__ import annotations

import json
import sys
from io import BytesIO
from pathlib import Path

from docx import Document
from PIL import Image
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
SHOTS = ROOT / "scratch" / "e2e" / "shots"
SHOTS.mkdir(parents=True, exist_ok=True)
FRONT = "http://127.0.0.1:5822"
BACK = "http://127.0.0.1:18643"

results: list[dict] = []


def record(step: str, ok: bool, detail: str = "") -> None:
    results.append({"step": step, "ok": ok, "detail": detail})
    print(("PASS " if ok else "FAIL ") + step + (" | " + detail if detail else ""), flush=True)


def shot(page, name: str) -> None:
    page.screenshot(path=str(SHOTS / name), full_page=False)


def sample_docx() -> bytes:
    doc = Document()
    doc.add_heading("河流水文教案", level=1)
    doc.add_paragraph("课题：河流水文特征")
    doc.add_paragraph("年级：高一")
    doc.add_paragraph("课时：40分钟")
    doc.add_paragraph("一、教学目标")
    doc.add_paragraph("描述河流水文特征")
    doc.add_paragraph("解释地形对流速的影响")
    doc.add_paragraph("四、教学过程")
    table = doc.add_table(rows=2, cols=4)
    for row, values in zip(table.rows, [["环节", "时长", "教师活动", "学生活动"], ["读图分析", "40", "展示地形图", "读图归纳"]]):
        for cell, text in zip(row.cells, values):
            cell.text = text
    image = Image.new("RGB", (120, 80), (30, 120, 60))
    buf = BytesIO()
    image.save(buf, format="PNG")
    buf.seek(0)
    doc.add_picture(buf, width=docx_inches(1))
    buf.close()
    out = BytesIO()
    doc.save(out)
    return out.getvalue()


def docx_inches(v):
    from docx.shared import Inches
    return Inches(v)


def draw_line(page, start, end) -> None:
    page.mouse.click(start[0], start[1])
    page.mouse.move((start[0] + end[0]) / 2, (start[1] + end[1]) / 2, steps=4)
    page.mouse.click(end[0], end[1])
    page.mouse.dblclick(end[0], end[1])


def window_fractions(page) -> list[dict]:
    return page.evaluate(
        """() => Array.from(document.querySelectorAll('[data-testid^=profile-window-pw_]')).map(el => {
            const r = el.getBoundingClientRect();
            return { id: el.dataset.testid.replace('profile-window-', '').split('_').slice(-2).join('_'),
                     kind: el.getAttribute('aria-label') || '',
                     x: r.x / window.innerWidth, y: r.y / window.innerHeight,
                     w: r.width / window.innerWidth, h: r.height / window.innerHeight };
        })"""
    )


def api_setup(ctx) -> tuple[str, str]:
    """导入 Word → 填必填 → 整份核对 → 定稿 → 开模拟测试。返回 (project_id, lesson_id)。"""
    login = ctx.request.post(BACK + "/auth/login", data=json.dumps({"email": "admin@example.com", "password": "admin12345"}), headers={"Content-Type": "application/json"}).json()
    csrf = login.get("csrf_token") or ""
    H = {"Content-Type": "application/json", "X-WebGIS-CSRF": csrf}
    projs = ctx.request.get(BACK + "/projects").json()["items"]
    if not projs:
        ctx.request.post(BACK + "/projects", data=json.dumps({"name": "B走查", "metadata": {"mode": "single_teacher_live_demo"}}), headers=H)
        projs = ctx.request.get(BACK + "/projects").json()["items"]
    pid = projs[0]["project_id"]

    files = {"file": ("河流水文教案.docx", sample_docx(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    imported = ctx.request.post(BACK + "/lesson-design/import-docx", params={"project_id": pid}, files=files, headers={"X-WebGIS-CSRF": csrf}).json()
    did = imported["design"]["design_id"]
    info = ctx.request.get(BACK + f"/lesson-design/sessions/{did}").json()
    stages = info["draft"]["stages"]
    for st in stages:
        st.setdefault("knowledge_conclusion", "地形与水文相互影响")
        st.setdefault("student_activities", st.get("student_activities") or ["读图讨论"])
    st[0]["minutes"] = 40

    def resolve(section, value):
        r = ctx.request.post(BACK + f"/lesson-design/sessions/{did}/sections/{section}/resolve", data=json.dumps({"decision": "edit", "value": value}), headers=H)
        assert r.ok, f"{section}: {r.text()[:200]}"

    resolve("stages", stages)
    bind = ctx.request.post(BACK + f"/lesson-design/sessions/{did}/questions/bind", data=json.dumps({
        "stage_id": stages[0]["stage_id"],
        "manual": {"text": "地形如何影响河流流速？", "answer": "坡度越大流速越快。", "explanation": "重力势能转化为动能。"},
    }), headers=H)
    assert bind.ok, bind.text()[:200]
    resolve("design_thinking", "以地形图判读为抓手，学生沿测线观察高程与流速的关系，建立地形—水文的因果链条，落实综合思维素养。")
    resolve("board_design", "地形（高程、坡度）→ 流速 → 水文特征。")
    resolve("homework", {"basic": ["课后绘制河段纵剖面"], "inquiry": ["查阅资料：水库如何改变下游水文"]})
    resolve("reflection", "预设学生难以从等高线推流速，需演示纵剖面工具辅助。")
    resolve("requirements", {"raw": "高一河流水文特征，40 分钟，含剖面工具演示。"})
    resolve("curriculum_interpretation", "课标要求运用地图与图表分析河流水文特征及其成因。")
    resolve("student_analysis", "高一学生已掌握等高线判读，但对地形与水文的因果关联缺乏直观体验。")
    resolve("textbook_analysis", "教材以河流水文要素为主线，配流域地形图，强调地形对水文的影响。")
    ctx.request.post(BACK + f"/lesson-design/sessions/{did}/sections/all/resolve", data=json.dumps({"decision": "accept"}), headers=H)
    latest = ctx.request.get(BACK + f"/lesson-design/sessions/{did}").json()
    fin = ctx.request.post(BACK + f"/lesson-design/sessions/{did}/finalize", data=json.dumps({"expected_revision": latest["revision"]}), headers=H)
    assert fin.ok, fin.text()[:300]
    lesson_id = fin.json()["lesson"]["lesson_id"]
    return pid, lesson_id


def ui_login(page) -> None:
    page.goto(FRONT, wait_until="domcontentloaded")
    page.wait_for_selector("input[type=email]", timeout=20000)
    page.fill("input[type=email]", "admin@example.com")
    page.fill("input[type=password]", "admin12345")
    page.get_by_role("button", name="登录", exact=True).last.click()
    expect(page.locator("input[type=email]")).to_have_count(0, timeout=20000)
    page.wait_for_timeout(3500)


def prepare_windows(page, n_lines=1) -> list[dict]:
    """测距模式画 n 条线并各开人口+地形窗口，拖动其中一个改变布局。"""
    page.get_by_test_id("map-tools-dock-toggle").click(timeout=10000)
    page.get_by_test_id("map-tool-measure").click(timeout=10000)
    page.wait_for_timeout(500)
    canvas = page.locator(".ol-viewport").first
    box = canvas.bounding_box()
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    draw_line(page, (cx - 200, cy - 40), (cx + 180, cy + 60))
    page.wait_for_timeout(900)
    chip_ids = page.evaluate("() => Array.from(document.querySelectorAll('[data-testid^=profile-line-chip-]')).map(el => el.dataset.testid.replace('profile-line-chip-',''))")
    for rid in chip_ids[:n_lines]:
        page.get_by_test_id(f"profile-line-open-population-{rid}").click()
        page.wait_for_timeout(250)
        page.get_by_test_id(f"profile-line-open-terrain-{rid}").click()
        page.wait_for_timeout(250)
    # 拖动人口窗口到左上角区域，形成特定布局
    pop_win = page.locator("[data-testid^=profile-window-pw_]", has_text="人口密度变化").first
    head = pop_win.locator(".profile-window-head")
    bx = pop_win.bounding_box()
    page.mouse.move(bx["x"] + bx["width"] / 2, bx["y"] + 8)
    page.mouse.down()
    for i in range(1, 9):
        page.mouse.move(bx["x"] + bx["width"] / 2 - 12 * i, bx["y"] + 8 - 4 * i)
    page.mouse.up()
    page.wait_for_timeout(300)
    return window_fractions(page)


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1600, "height": 900})
        page = ctx.new_page()

        try:
            pid, lesson_id = api_setup(ctx)
            record("API 建课（导入→核对→定稿→模拟测试就绪）", True, f"{pid}/{lesson_id}")
        except Exception as exc:  # noqa: BLE001
            record("API 建课", False, str(exc)[:300])
            return 1

        try:
            ui_login(page)
            # 进入备课工作台 → 选择目标课时 → 模拟测试
            page.get_by_test_id("class-mode-toggle").click(timeout=10000)
            page.wait_for_timeout(1500)
            panel = page.get_by_test_id("lesson-panel")
            expect(panel).to_be_visible(timeout=10000)
            # 选择目标课时
            select = panel.locator("select").first
            options = select.locator("option").all_text_contents()
            target_idx = next((i for i, t in enumerate(options) if lesson_id[:12] in t or "河流" in t), None)
            if target_idx is None:
                # 回退：从课时列表点击包含“河流”的卡片
                page.get_by_text("河流水文特征", exact=False).first.click()
            else:
                select.select_option(index=target_idx)
            page.wait_for_timeout(800)
            page.get_by_test_id("start-rehearsal").click()
            expect(page.get_by_test_id("rehearsal-panel")).to_be_visible(timeout=20000)
            page.wait_for_timeout(1200)
            record("进入模拟测试面板", True)
        except Exception as exc:  # noqa: BLE001
            record("进入模拟测试面板", False, str(exc)[:300])
            shot(page, "b4-01-rehearsal-fail.png")
            return 1

        # ---- 模拟测试：画线开窗并保存预设 ----
        saved_fractions = None
        try:
            saved_fractions = prepare_windows(page, 1)
            expect(page.locator("[data-testid^=profile-window-pw_]")).to_have_count(2, timeout=10000)
            shot(page, "b4-02-rehearsal-windows.png")
            save_btn = page.locator("[data-testid^=rehearsal-save-profile-]").first
            save_btn.click()
            expect(save_btn).to_contain_text("✓ 预设已存", timeout=15000)
            record("模拟测试保存剖面预设（测线+窗口布局）", True, f"{len(saved_fractions)} 窗")
        except Exception as exc:  # noqa: BLE001
            record("保存剖面预设", False, str(exc)[:300])
            shot(page, "b4-02-save-fail.png")

        # ---- 刷新 → 恢复模拟测试 → 预览场景恢复窗口 ----
        try:
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(3500)
            page.get_by_test_id("class-mode-toggle").click(timeout=10000)
            page.wait_for_timeout(1500)
            page.get_by_test_id("start-rehearsal").click()
            expect(page.get_by_test_id("rehearsal-panel")).to_be_visible(timeout=20000)
            page.wait_for_timeout(1000)
            preview = page.locator("[data-testid^=rehearsal-preview-]").first
            preview.click()
            page.wait_for_timeout(1500)
            expect(page.locator("[data-testid^=profile-window-pw_]")).to_have_count(2, timeout=15000)
            restored = window_fractions(page)
            if saved_fractions and len(restored) == len(saved_fractions):
                drift = max(max(abs(a[k] - b[k]) for k in ("x", "y", "w", "h"))
                            for a, b in zip(sorted(restored, key=lambda i: i["x"]), sorted(saved_fractions, key=lambda i: i["x"])))
            else:
                drift = 1.0
            record("刷新后恢复模拟测试并还原预设窗口", len(restored) == 2 and drift < 0.05, f"drift={drift:.3f}")
            shot(page, "b4-03-restored.png")
        except Exception as exc:  # noqa: BLE001
            record("刷新恢复预设", False, str(exc)[:300])
            shot(page, "b4-03-restore-fail.png")

        # ---- 完成并发布 → 开课 → 布局一致 ----
        try:
            page.get_by_test_id("rehearsal-complete-button").click()
            expect(page.get_by_test_id("rehearsal-complete")).to_be_visible(timeout=30000)
            record("完成模拟测试并发布新版本", True)
            page.get_by_role("button", name="返回备课工作台").click()
            page.wait_for_timeout(1200)
            page.get_by_test_id("start-class").click()
            page.wait_for_timeout(2500)
            expect(page.locator("[data-testid^=profile-window-pw_]")).to_have_count(2, timeout=20000)
            class_fractions = window_fractions(page)
            if saved_fractions and len(class_fractions) == len(saved_fractions):
                drift = max(max(abs(a[k] - b[k]) for k in ("x", "y", "w", "h"))
                            for a, b in zip(sorted(class_fractions, key=lambda i: i["x"]), sorted(saved_fractions, key=lambda i: i["x"])))
            else:
                drift = 1.0
            record("开课后自动加载课前预设且布局一致", len(class_fractions) == 2 and drift < 0.05, f"drift={drift:.3f}")
            shot(page, "b4-04-class-loaded.png")
        except Exception as exc:  # noqa: BLE001
            record("开课加载预设", False, str(exc)[:300])
            shot(page, "b4-04-class-fail.png")

        ctx.close()
        browser.close()

    (ROOT / "scratch" / "e2e" / "phase_b_preset_result.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    ok = all(r["ok"] for r in results)
    print("ALL-PASS" if ok else "HAS-FAILURES")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
