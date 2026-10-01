# -*- coding: utf-8 -*-
"""Phase A 真实交互走查：教案表格素材入口 + Word 导入人工归类。

前置：
- 后端 127.0.0.1:18642（WEBGIS_AI_DATA_DIR 指向独立数据目录，先 POST /auth/bootstrap 管理员）
- 前端 127.0.0.1:5821（vite dev，VITE_API_BASE_URL=http://127.0.0.1:18642）
- scratch/e2e/季风教案_合并单元格样本.docx 由 scratch/e2e/make_sample_docx.py 生成

产物：scratch/e2e/shots/*.png、scratch/e2e/walkthrough_result.json、真实 webm 视频。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
SHOTS = ROOT / "scratch" / "e2e" / "shots"
SHOTS.mkdir(parents=True, exist_ok=True)
SAMPLE_DOCX = ROOT / "scratch" / "e2e" / "季风教案_合并单元格样本.docx"
FRONT = "http://127.0.0.1:5821"
BACK = "http://127.0.0.1:18642"

results: list[dict] = []


def record(step: str, ok: bool, detail: str = "") -> None:
    results.append({"step": step, "ok": ok, "detail": detail})
    print(("PASS " if ok else "FAIL ") + step + (" | " + detail if detail else ""), flush=True)


def shot(page, name: str) -> str:
    path = SHOTS / name
    page.screenshot(path=str(path), full_page=False)
    return str(path)


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = ctx.new_page()

        # ---- 0. 登录 ----
        try:
            page.goto(FRONT, wait_until="domcontentloaded")
            page.wait_for_selector("input[type=email]", timeout=20000)
            page.fill("input[type=email]", "admin@example.com")
            page.fill("input[type=password]", "admin12345")
            page.get_by_role("button", name="登录", exact=True).click()
            expect(page.locator("input[type=email]")).to_have_count(0, timeout=20000)
            record("登录", True)
        except Exception as exc:  # noqa: BLE001
            record("登录", False, str(exc)[:200])
            shot(page, "00-login-fail.png")
            return 1

        # ---- 1. 确保有项目 → 打开教案设计 ----
        try:
            page.wait_for_timeout(4000)
            projs = ctx.request.get(BACK + "/projects").json()
            items = projs.get("items") or []
            if not items:
                ctx.request.post(
                    BACK + "/projects",
                    data=json.dumps({"name": "走查项目", "metadata": {"mode": "single_teacher_live_demo"}}),
                    headers={"Content-Type": "application/json"},
                )
                page.reload(wait_until="domcontentloaded")
                page.wait_for_timeout(4000)
            page.get_by_test_id("lesson-design-launcher").click()
            page.wait_for_selector("[data-testid=lesson-design-workspace]", timeout=20000)
            page.wait_for_timeout(2500)
            record("打开教案设计工作台", True)
        except Exception as exc:  # noqa: BLE001
            record("打开教案设计工作台", False, str(exc)[:200])
            shot(page, "01-open-fail.png")
            return 1

        # ---- 2. Word 导入（真实上传）----
        try:
            page.get_by_test_id("ldw-import-docx").click()
            inp = page.locator("input[accept='.docx']:not([multiple])")
            inp.set_input_files(str(SAMPLE_DOCX))
            page.wait_for_selector("[data-testid=docx-import-review]", timeout=30000)
            page.wait_for_timeout(1500)
            count = page.locator("[data-testid^=dir-item-]").count()
            page.screenshot(path=str(shot(page, "02-import-review.png")), full_page=True)
            record("Word 真实上传并出现校对清单", count >= 2, f"{count} 条待归类")
        except Exception as exc:  # noqa: BLE001
            record("Word 真实上传", False, str(exc)[:200])
            shot(page, "02-import-fail.png")
            return 1

        # ---- 3. 人工归类：未知文字 → 教学目标（追加）----
        try:
            items = page.locator("[data-testid^=dir-item-]")
            text_idx = -1
            for i in range(items.count()):
                if "无法识别" in (items.nth(i).text_content() or ""):
                    text_idx = i
                    break
            assert text_idx >= 0, "未找到未知文字条目"
            item = items.nth(text_idx)
            item.locator("select").nth(1).select_option("objectives")
            item.get_by_role("button", name="采用").click()
            expect(item.get_by_test_id(f"dir-result-{text_idx}")).to_contain_text("教学目标", timeout=15000)
            page.screenshot(path=str(shot(page, "03-assign-section.png")), full_page=True)
            record("未知文字归类到教学目标（追加）", True)
        except Exception as exc:  # noqa: BLE001
            record("未知文字归类", False, str(exc)[:200])
            shot(page, "03-assign-fail.png")

        # ---- 4. 人工归类：图片 → 环节素材（绑定到环节2）----
        try:
            items = page.locator("[data-testid^=dir-item-]")
            img_idx = -1
            for i in range(items.count()):
                if items.nth(i).locator("img.dir-image").count():
                    img_idx = i
                    break
            assert img_idx >= 0, "未找到图片条目"
            item = items.nth(img_idx)
            item.locator("select").first.select_option(index=0)
            item.get_by_role("button", name="绑定到环节素材").click()
            expect(item.get_by_test_id(f"dir-result-{img_idx}")).to_contain_text("素材列表", timeout=15000)
            page.screenshot(path=str(shot(page, "04-bind-image.png")), full_page=True)
            record("导入图片绑定到环节素材列表", True)
        except Exception as exc:  # noqa: BLE001
            record("图片绑定", False, str(exc)[:200])
            shot(page, "04-bind-fail.png")

        # ---- 5. 环节1 素材：展示编排（含导入图）、绑定场景、文字区块 ----
        try:
            row0 = page.get_by_test_id("lpt-row-0")
            row0.get_by_text("本环节素材").click()
            ple = page.locator("[data-testid^=ple-]:not([data-testid=ple-canvas])").first
            expect(ple).to_be_visible(timeout=10000)
            image_blocks = ple.locator(".ple-block").count()
            has_img_block = ple.locator(".ple-block img").count()
            record("环节1 展示编排可见（含导入图片区块）", has_img_block >= 1, f"{image_blocks} 个区块, 图片 {has_img_block}")
            page.get_by_test_id("lpt-bind-scene-0").click()
            expect(page.locator(".lpt-material-note")).to_contain_text("已把当前地图场景绑定到本环节", timeout=10000)
            ple.get_by_role("button", name="插入文字区块").click()
            block = ple.locator(".ple-block").last
            block.locator("input").fill("观看季风风向示意")
            page.screenshot(path=str(shot(page, "05-materials.png")), full_page=True)
            record("环节1 绑定场景 + 文字区块", True)
        except Exception as exc:  # noqa: BLE001
            record("环节1 素材操作", False, str(exc)[:200])
            shot(page, "05-material-fail.png")

        # ---- 6. 真实视频上传（Playwright 录制的真实 webm）----
        try:
            vctx = browser.new_context(
                viewport={"width": 400, "height": 300},
                record_video_dir=str(SHOTS / "vrec"),
                record_video_size={"width": 320, "height": 240},
            )
            vpage = vctx.new_page()
            vpage.goto("about:blank")
            vpage.wait_for_timeout(1800)
            vpath = vpage.video.path()
            vctx.close()
            webm = SHOTS / "sample.webm"
            webm.write_bytes(Path(vpath).read_bytes())
            record("生成真实 webm 视频", webm.stat().st_size > 1000, f"{webm.stat().st_size} bytes")

            ple = page.locator("[data-testid^=ple-]:not([data-testid=ple-canvas])").first
            ple.get_by_role("button", name="插入视频区块").click()
            vinput = ple.locator("input[accept='.mp4,.webm']")
            vinput.set_input_files(str(webm))
            expect(ple.get_by_role("status")).to_contain_text("正在上传", timeout=5000)
            expect(ple.locator(".ple-block video")).to_have_count(1, timeout=30000)
            page.screenshot(path=str(shot(page, "06-video-block.png")), full_page=True)
            record("本地视频真实上传并挂为视频区块", True)
        except Exception as exc:  # noqa: BLE001
            record("视频上传", False, str(exc)[:200])
            shot(page, "06-video-fail.png")

        # ---- 7. 环节2 题目：手动录入（题干/答案/解析）----
        try:
            row1 = page.get_by_test_id("lpt-row-1")
            row1.get_by_text("添加题目").click()
            row1.get_by_role("button", name="录入手动题目").click()
            form = row1.locator(".lpt-manual-form")
            form.locator("textarea").nth(0).fill("冬季风和夏季风的方向有什么不同？")
            form.locator("textarea").nth(1).fill("冬季风从陆地吹向海洋，夏季风从海洋吹向陆地。")
            form.locator("textarea").nth(2).fill("海陆热力性质差异决定了风向的季节反转。")
            row1.get_by_role("button", name="加入本环节").click()
            expect(row1.locator(".lpt-question-list li")).to_have_count(1, timeout=15000)
            page.screenshot(path=str(shot(page, "07-question.png")), full_page=True)
            record("环节2 手动录入题目", True)
        except Exception as exc:  # noqa: BLE001
            record("环节2 手动录入题目", False, str(exc)[:200])
            shot(page, "07-question-fail.png")

        # ---- 8. 保存展示编排 → 刷新 → 恢复 ----
        try:
            ple = page.locator("[data-testid^=ple-]:not([data-testid=ple-canvas])").first
            ple.get_by_test_id("ple-save").click()
            page.wait_for_timeout(2500)
            page.reload(wait_until="domcontentloaded")
            page.wait_for_selector("[data-testid=docx-import-review]", timeout=30000)
            page.wait_for_timeout(1500)
            assigned_ok = page.locator("[data-status=assigned]").count()
            record("刷新后归类进度恢复", assigned_ok >= 2, f"{assigned_ok} 条已归类")
            row0 = page.get_by_test_id("lpt-row-0")
            row0.get_by_text("本环节素材").click(force=True)
            ple = page.locator("[data-testid^=ple-]:not([data-testid=ple-canvas])").first
            expect(ple).to_be_visible(timeout=10000)
            n_blocks = ple.locator(".ple-block").count()
            has_video = ple.locator(".ple-block video").count()
            page.screenshot(path=str(shot(page, "08-after-reload.png")), full_page=True)
            record("刷新后环节1素材保留（图/文/视频）", n_blocks >= 3 and has_video == 1, f"{n_blocks} 区块, 视频 {has_video}")
        except Exception as exc:  # noqa: BLE001
            record("保存+刷新恢复", False, str(exc)[:200])
            shot(page, "08-reload-fail.png")

        # ---- 9. 数据层核对：design API（同一会话 cookie）----
        try:
            design_id = page.evaluate("new URLSearchParams(location.search).get('design_id')")
            info = ctx.request.get(BACK + f"/lesson-design/sessions/{design_id}").json()
            draft = info.get("draft") or {}
            stages = draft.get("stages") or []
            s1 = stages[0] if stages else {}
            pres = (s1.get("presentation") or {}).get("blocks") or []
            types = [b.get("type") for b in pres]
            scene = s1.get("scene") or {}
            q2 = (stages[1].get("questions") if len(stages) > 1 else []) or []
            img_assigned = any(
                (i.get("assignment") or {}).get("kind") == "stage_material"
                for i in (draft.get("import_review", {}).get("unclassified") or [])
            )
            record(
                "草稿数据：场景绑定+素材区块+题目+图片归类状态",
                bool(scene) and "image" in types and "video" in types and q2 and img_assigned,
                f"blocks={types} scene={list(scene)[:4]} q2={len(q2)}",
            )
        except Exception as exc:  # noqa: BLE001
            record("草稿数据核对", False, str(exc)[:200])

        ctx.close()
        browser.close()

    (ROOT / "scratch" / "e2e" / "walkthrough_result.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    ok = all(r["ok"] for r in results)
    print("ALL-PASS" if ok else "HAS-FAILURES")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
