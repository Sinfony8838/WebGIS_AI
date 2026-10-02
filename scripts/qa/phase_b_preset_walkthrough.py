# -*- coding: utf-8 -*-
"""Phase B 任务4走查：课前保存剖面测线及窗口布局 → 刷新恢复 → 发布 → 开始课堂后布局一致。

前置：后端 127.0.0.1:18643（独立数据目录），前端 127.0.0.1:5822。
"""
from __future__ import annotations

import os
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
FRONT = os.getenv("WEBGIS_QA_FRONT", "http://127.0.0.1:5822")
BACK = os.getenv("WEBGIS_QA_BACK", "http://127.0.0.1:18643")

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
    import uuid
    project_response = ctx.request.post(BACK + "/projects", data=json.dumps({"name": "B预设走查-" + uuid.uuid4().hex[:8], "metadata": {"mode": "single_teacher_live_demo"}}), headers=H)
    assert project_response.ok, project_response.text()[:200]
    pid = project_response.json()["project_id"]
    user_id = login["user"]["user_id"]
    ctx.add_init_script("localStorage.setItem(" + json.dumps("webgis_ai_project_id:" + user_id) + "," + json.dumps(pid) + ");")

    # ctx.request 不支持 multipart files：走 multipart/form-data 手工编码
    import uuid as _uuid
    boundary = _uuid.uuid4().hex
    crlf = "\r\n"
    payload = sample_docx()
    parts = [
        f"--{boundary}" + crlf,
        f'Content-Disposition: form-data; name="project_id"' + crlf + crlf,
        pid + crlf,
        f"--{boundary}" + crlf,
        'Content-Disposition: form-data; name="file"; filename="lesson.docx"' + crlf,
        "Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document" + crlf + crlf,
    ]
    body = "".join(parts).encode() + payload + (crlf + f"--{boundary}--" + crlf).encode()
    resp = ctx.request.post(
        BACK + "/lesson-design/import-docx",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "X-WebGIS-CSRF": csrf},
    )
    assert resp.ok, resp.text()[:300]
    imported = resp.json()
    did = imported["design"]["design_id"]
    info = ctx.request.get(BACK + f"/lesson-design/sessions/{did}").json()
    stages = info["draft"]["stages"]
    for st in stages:
        st.setdefault("knowledge_conclusion", "地形与水文相互影响")
        st.setdefault("student_activities", st.get("student_activities") or ["读图讨论"])
    stages[0]["minutes"] = 40

    def resolve(section, value):
        r = ctx.request.post(BACK + f"/lesson-design/sessions/{did}/sections/{section}/resolve", data=json.dumps({"decision": "edit", "value": value}), headers=H)
        assert r.ok, f"{section}: {r.text()[:200]}"

    resolve("stages", stages)
    bind = ctx.request.post(BACK + f"/lesson-design/sessions/{did}/questions/bind", data=json.dumps({
        "stage_id": stages[0]["stage_id"],
        "manual": {"text": "地形如何影响河流流速？", "answer": "坡度越大流速越快。", "explanation": "重力势能转化为动能。"},
    }), headers=H)
    assert bind.ok, bind.text()[:200]
    resolve("key_difficulties", {"key": ["地形对流速的影响"], "difficult": ["从等高线推断流速变化"]})
    resolve("methods", ["讲授法", "读图分析法"])
    resolve("objectives", ["描述河流水文特征", "解释地形对流速的影响"])
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
    # ctx.request 登录已带会话 cookie：应用可能直接进入主界面
    try:
        page.wait_for_selector("input[type=email]", timeout=8000)
    except Exception:
        return
    page.fill("input[type=email]", "admin@example.com")
    page.fill("input[type=password]", "admin12345")
    page.get_by_role("button", name="登录", exact=True).last.click()
    expect(page.locator("input[type=email]")).to_have_count(0, timeout=20000)
    page.wait_for_timeout(3500)


def prepare_windows(page, n_lines=1) -> list[dict]:
    """测距模式画 n 条线并各开人口+地形窗口，拖动其中一个改变布局。"""
    page.get_by_role("button", name="展开地图工具与可视化地图").click(timeout=10000)
    mode_toggle = page.get_by_test_id("map-mode-toggle")
    if mode_toggle.get_attribute("aria-pressed") == "true":
        mode_toggle.click()
        page.wait_for_timeout(2500)
    page.get_by_role("button", name="测距模式 · 快捷键 M").click(timeout=10000)
    page.wait_for_timeout(500)
    canvas = page.locator(".ol-viewport").first
    box = canvas.bounding_box()
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    for _ in range(5):
        page.mouse.move(cx, cy)
        page.mouse.wheel(0, -300)
        page.wait_for_timeout(220)
    draw_line(page, (cx - 200, cy - 40), (cx + 180, cy + 60))
    page.wait_for_timeout(900)
    chip_ids = page.evaluate("() => Array.from(document.querySelectorAll('[data-testid^=profile-line-chip-]')).map(el => el.dataset.testid.replace('profile-line-chip-',''))")
    for rid in chip_ids[:n_lines]:
        if page.get_by_test_id("profile-manager-toggle").get_attribute("aria-expanded") != "true":
            page.get_by_test_id("profile-manager-toggle").click()
        page.get_by_test_id(f"profile-line-open-population-{rid}").click()
        page.wait_for_timeout(250)
        if page.get_by_test_id("profile-manager-toggle").get_attribute("aria-expanded") != "true":
            page.get_by_test_id("profile-manager-toggle").click()
        page.get_by_test_id(f"profile-line-open-terrain-{rid}").click()
        page.wait_for_timeout(250)
    # 拖动人口窗口到左上角区域，形成特定布局
    pop_win = page.locator("[data-testid^=profile-window-pw_]", has_text="人口密度变化").first
    head = pop_win.locator(".profile-window-head")
    bx = pop_win.bounding_box()
    page.mouse.move(bx["x"] + bx["width"] / 2, bx["y"] + 8)
    page.mouse.down()
    for i in range(1, 9):
        page.mouse.move(bx["x"] + bx["width"] / 2 + 10 * i, bx["y"] + 8 - 4 * i)
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
            import traceback; record("API 建课", False, traceback.format_exc()[-600:])
            return 1

        try:
            ui_login(page)
            # 进入备课工作台 → 选择目标课时 → 模拟测试
            page.get_by_test_id("class-mode-toggle").click(timeout=10000)
            page.wait_for_timeout(1500)
            panel = page.get_by_test_id("lesson-panel")
            expect(panel).to_be_visible(timeout=10000)
            # 选择目标课时（lesson-select 的 option value 即 lesson_id），重试至模拟测试按钮可用
            selected = False
            for _ in range(3):
                panel.get_by_test_id("lesson-select").select_option(lesson_id)
                page.wait_for_timeout(1200)
                try:
                    expect(page.get_by_test_id("start-rehearsal")).to_be_enabled(timeout=8000)
                    selected = True
                    break
                except Exception:
                    continue
            diag = page.evaluate("""() => {
                const sels = Array.from(document.querySelectorAll('[data-testid=lesson-select]'));
                const btn = document.querySelector('[data-testid=start-rehearsal]');
                return {
                    selCount: sels.length,
                    values: sels.map(s => s.value),
                    optionCounts: sels.map(s => s.options.length),
                    disabled: btn ? btn.disabled : null,
                    title: btn ? btn.title : null,
                    panels: document.querySelectorAll('[data-testid=lesson-panel]').length,
                };
            }""")
            assert selected, f"课时选择后模拟测试按钮仍不可用: {json.dumps(diag, ensure_ascii=False)}"
            page.get_by_test_id("start-rehearsal").click()
            expect(page.get_by_test_id("rehearsal-panel")).to_be_visible(timeout=20000)
            page.wait_for_timeout(1200)
            expect(page.get_by_test_id("rehearsal-error")).to_have_count(0)
            expect(page.locator(".lesson-stage-row").first).to_be_visible()
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
            # 展开第一个环节，环节操作按钮（预览/存场景/存剖面预设）才渲染
            diag = page.evaluate("""() => ({
                panel: !!document.querySelector('[data-testid=rehearsal-panel]'),
                stageList: document.querySelectorAll('.lesson-stage-list').length,
                stageRows: document.querySelectorAll('.lesson-stage-row').length,
                panelText: (document.querySelector('[data-testid=rehearsal-panel]')||{innerText:''}).innerText.slice(0, 120),
            })""")
            print("DIAG:", diag, flush=True)
            page.locator(".lesson-stage-row").first.click()
            page.wait_for_timeout(500)
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
            page.get_by_test_id("lesson-select").select_option(lesson_id)
            expect(page.get_by_test_id("start-rehearsal")).to_be_enabled()
            page.get_by_test_id("start-rehearsal").click()
            expect(page.get_by_test_id("rehearsal-panel")).to_be_visible(timeout=20000)
            page.wait_for_timeout(1000)
            page.locator(".lesson-stage-row").first.click()
            page.wait_for_timeout(500)
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
            page.set_viewport_size({"width": 1366, "height": 768})
            page.wait_for_timeout(500)
            bounds = window_fractions(page)
            record("1366x768 窗口完整可见", all(0 <= w['x'] and 0 <= w['y'] and w['x']+w['w'] <= 1.001 and w['y']+w['h'] <= 1.001 for w in bounds))
            win = page.locator("[data-testid^=profile-window-pw_]").first
            before = win.bounding_box()
            page.mouse.move(before['x']+80, before['y']+12)
            page.mouse.down()
            page.mouse.move(before['x']+120, before['y']+35, steps=8)
            page.mouse.up()
            after = win.bounding_box()
            record("1366x768 实际拖动", abs(after['x'] - before['x']) > 20)
            shot(page, "b4-05-small-viewport.png")
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
