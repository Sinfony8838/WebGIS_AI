"""Real Phase D classroom clicks against an isolated backend, never production.

Run with WEBGIS_QA_PASSWORD set. The script creates a new project and explicit QA
lesson per viewport. API calls only seed fixtures/read evidence; classroom actions
use visible UI buttons. No route interception or API response mocking is used.
Results/screenshots are saved under scratch/phase-d/<run timestamp>, never staged.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
CONCLUSION = "QA结论：先观察证据，再解释人口差异。"
ANSWER = "QA官方答案：地形与交通条件共同影响人口分布。"
TAIL = "选项末尾可达标记"


def fixture(project_id: str, suffix: str, media_url: str = "") -> dict:
    question = {
        "question_id": "qa_long_question", "type": "choice", "source": "teacher_manual",
        "text": "读图后分析人口分布。" + "比较沿海平原、内陆高原和河谷地区，先描述密度变化，再结合地形、气候和交通解释差异。" * 12,
        "options": ["甲：" + "请从地图上寻找相应证据，并描述空间分布特点。" * 5,
                    "乙：" + "请区分人口总量和人口密度，说明推理使用的指标。" * 5,
                    "丙：" + "请分析图例与比例尺，避免用局部现象代替整体规律。" * 5,
                    "丁：" + "请完整阅读本选项并用一条证据支持你的判断。" * 10 + TAIL],
        "answer": ANSWER, "answer_letter": "A", "answer_index": 0,
        "explanation": "QA解释：密度是单位面积人口数量，比较时要使用同一空间尺度。",
        "expected_points": [], "misconceptions": [], "suggested_seconds": 120,
    }
    scene = {"basemap_id": "amap_light", "templates": [], "layer_visibility": {},
             "view": {"center": [121.47, 31.23], "zoom": 8}, "annotations": [], "visual_query": None,
             "globe": {"enabled": False}}
    stages = []
    for index, title in enumerate(["观察地图", "解释差异"]):
        stages.append({
            "stage_id": f"qa_stage_{index + 1}", "title": title, "minutes": 5,
            "scene": scene, "script": ["QA教师内部口令，不向学生展示"],
            "teacher_guidance": {"teacher_talk": "QA教师内部提示"},
            "assistant_prompts": ["QA内部AI提示"], "questions": [question] if index == 0 else [],
            "knowledge_conclusion": CONCLUSION,
            "presentation": {"aspect_ratio": "16:9", "blocks": [
                {"id": "title", "type": "text", "text": title, "x": 0.02, "y": 0.02, "w": 0.96, "h": 0.13, "order": 1, "z": 1},
                {"id": "question", "type": "question", "text": "", "asset": {"question_id": "qa_long_question"},
                 "x": 0.02, "y": 0.18, "w": 0.96, "h": 0.6, "order": 2, "z": 1},
                {"id": "conclusion", "type": "text", "text": CONCLUSION, "teacher_reveal": True,
                 "x": 0.02, "y": 0.81, "w": 0.96, "h": 0.17, "order": 3, "z": 1},
            ]},
        })
        if index == 1 and media_url:
            stages[-1]["presentation"]["blocks"][1] = {
                "id": "native_video", "type": "video", "text": "", "asset": {"url": media_url, "mime_type": "video/webm", "name": "本地课堂视频"},
                "x": 0.02, "y": 0.18, "w": 0.96, "h": 0.60, "order": 2, "z": 1,
            }
    return {"title": f"Phase D 浏览器验收 {suffix}", "subject": "地理", "grade": "高一", "objectives": ["观察与解释"],
            "stages": stages, "metadata": {"project_id": project_id, "qa_fixture": "phase_d_walkthrough"}}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--front", default="http://127.0.0.1:5827")
    parser.add_argument("--back", default="http://127.0.0.1:18645")
    parser.add_argument("--email", default="admin@example.com")
    parser.add_argument("--viewports", default="1366x768,1920x1080")
    parser.add_argument("--media-url", default="", help="Existing same-backend uploaded video; only native controls are clicked.")
    args = parser.parse_args()
    for value in (args.front, args.back):
        if urlparse(value).hostname not in {"localhost", "127.0.0.1"}:
            raise SystemExit("This acceptance script only permits local isolated servers.")
    password = os.environ.get("WEBGIS_QA_PASSWORD")
    if args.media_url and not args.media_url.startswith(args.back + "/files/uploads/"):
        raise SystemExit("Media must be an uploaded asset from the same isolated backend.")
    if not password:
        raise SystemExit("Set WEBGIS_QA_PASSWORD; credentials are not saved in this script or evidence.")
    output = ROOT / "scratch" / "phase-d" / time.strftime("%Y%m%d-%H%M%S")
    output.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []

    def record(step: str, detail=None):
        results.append({"step": step, "ok": True, "detail": detail})
        (output / "result.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print("PASS " + step, flush=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for size in args.viewports.split(","):
            width, height = map(int, size.split("x"))
            context = browser.new_context(viewport={"width": width, "height": height})
            page = context.new_page()
            page.set_default_timeout(15000)
            errors, requests = [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("request", lambda request: requests.append({"method": request.method, "path": urlparse(request.url).path})
                    if request.url.startswith(args.back) and "/class-sessions" in request.url else None)
            current_step = size + " setup"
            try:
                login_response = context.request.post(args.back + "/auth/login", data={"email": args.email, "password": password})
                assert login_response.ok, f"login status {login_response.status}"
                login = login_response.json()
                headers = {"X-WebGIS-CSRF": login["csrf_token"]}

                def post(path, payload):
                    response = context.request.post(args.back + path, data=payload, headers=headers)
                    assert response.ok, f"{path}: {response.status} {response.text()[:240]}"
                    return response.json()

                project = post("/projects", {"name": f"Phase D QA {size} {output.name}", "metadata": {"mode": "single_teacher_live_demo", "qa_fixture": True}})
                project_id = project["project_id"]
                lesson = post("/lessons", fixture(project_id, size, args.media_url))
                lesson_id = lesson["lesson_id"]
                binding = json.dumps([args.front, "webgis_ai_project_id:" + login["user"]["user_id"], project_id])
                context.add_init_script(f"const [origin,key,value] = {binding}; if(location.origin === origin) localStorage.setItem(key,value);")
                page.goto(args.front, wait_until="domcontentloaded")
                expect(page.get_by_test_id("class-mode-toggle")).to_be_visible(timeout=30000)
                page.get_by_test_id("class-mode-toggle").click()
                page.get_by_test_id("lesson-select").select_option(lesson_id)
                page.get_by_test_id("start-class").click()
                expect(page.get_by_test_id("class-run-panel")).to_be_visible(timeout=30000)

                def session():
                    response = context.request.get(args.back + "/class-sessions", params={"project_id": project_id})
                    assert response.ok
                    matches = [item for item in response.json()["items"] if item["lesson_id"] == lesson_id]
                    assert len(matches) == 1
                    return matches[0]

                current = session()
                assert current["current_stage_id"] == "qa_stage_1"
                record(size + " 实际点击开始课堂", {"project_id": project_id, "lesson_id": lesson_id, "session_id": current["session_id"]})
                page.screenshot(path=str(output / f"{size}-01-teacher.png"))

                current_step = size + " 环节切换与学生模式"
                page.get_by_test_id("class-next-stage").click()
                expect(page.locator(".classroom-stage-progress")).to_contain_text("2/2")
                page.get_by_test_id("class-prev-stage").click()
                expect(page.locator(".classroom-stage-progress")).to_contain_text("1/2")
                page.get_by_test_id("student-display-toggle").click()
                expect(page.get_by_test_id("student-stage-navigation")).to_be_visible()
                for selector in (".class-run-panel", ".basic-knowledge-launcher", ".copilot-widget", ".copilot-orb", "[data-testid=quick-record]"):
                    assert page.locator(selector).count() == 0, selector
                assert "QA教师内部提示" not in page.locator("body").text_content()
                controls = page.get_by_test_id("classroom-teacher-controls")
                controls.locator("summary").click()
                page.get_by_test_id("class-toggle-presentation").click()
                surface = page.get_by_test_id("stage-presentation-surface")
                expect(surface).to_be_visible()
                assert surface.get_by_text(CONCLUSION, exact=True).count() == 0
                slider = page.get_by_role("slider", name="展示字号")
                slider.focus()
                slider.press("End")
                expect(slider).to_have_value("44")
                assert surface.evaluate("el => getComputedStyle(el).getPropertyValue('--sps-font-size').trim()") == "44px"
                page.get_by_test_id("reveal-stage-conclusions").click()
                expect(surface.get_by_text(CONCLUSION, exact=True)).to_be_visible()
                page.get_by_test_id("class-next-stage").click()
                expect(page.locator(".classroom-stage-progress")).to_contain_text("2/2")
                assert surface.get_by_text(CONCLUSION, exact=True).count() == 0
                if args.media_url:
                    current_step = size + " 课堂视频原生播放"
                    video = surface.locator("video")
                    expect(video).to_be_visible()
                    page.wait_for_function("() => document.querySelector('.sps video')?.readyState >= 2")
                    video.evaluate("el => { window.qaVideoEvents=[]; ['play','playing','timeupdate'].forEach(type => el.addEventListener(type, () => window.qaVideoEvents.push({type,time:el.currentTime}))); }")
                    bounds = video.bounding_box()
                    assert bounds
                    # Chromium puts playback controls above the bottom seek bar.
                    video.click(position={"x": 24, "y": bounds["height"] - 48})
                    page.wait_for_function("() => document.querySelector('.sps video')?.currentTime > 0.15")
                    media = video.evaluate("el => ({duration:el.duration,currentTime:el.currentTime,events:window.qaVideoEvents})")
                    assert any(event["type"] == "playing" for event in media["events"])
                    page.screenshot(path=str(output / f"{size}-02b-native-video.png"))
                    record(size + " 课堂本地视频原生播放", media)
                current_step = size + " 环节切换与学生模式"
                page.get_by_test_id("class-prev-stage").click()
                expect(page.locator(".classroom-stage-progress")).to_contain_text("1/2")
                assert surface.get_by_text(CONCLUSION, exact=True).count() == 0
                slider.focus()
                slider.press("Home")
                for _ in range(3):
                    slider.press("ArrowRight")
                expect(slider).to_have_value("30")
                record(current_step, "教师内容不挂载；字号24–44可调；跨环节后结论重新隐藏")

                current_step = size + " 长题展开与末尾阅读"
                surface.get_by_role("button", name="展开问题 2", exact=True).click()
                reading = page.get_by_role("region", name="完整内容", exact=True)
                reading.focus()
                reading.press("Control+End")
                page.wait_for_timeout(250)
                assert reading.evaluate("el => el.scrollHeight > el.clientHeight && el.scrollTop > 0")
                page.screenshot(path=str(output / f"{size}-02-long-reader.png"))
                reading.get_by_role("button", name="投屏答题", exact=True).click()
                modal = page.get_by_test_id("question-practice-modal")
                expect(modal).to_be_visible()
                assert modal.get_by_test_id("qpm-answer").count() == 0
                assert modal.get_by_test_id("qpm-note-correct").count() == 0
                body = modal.get_by_role("region", name="题目与讲解", exact=True)
                body.focus()
                body.press("Control+End")
                page.wait_for_timeout(250)
                tail = modal.locator(".qpm-options li").last.locator("span").last
                geometry = tail.evaluate("""el => {
                  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT); let node,last;
                  while(node=walker.nextNode()) last=node;
                  const range=document.createRange(); range.setStart(last,Math.max(0,last.length-8)); range.setEnd(last,last.length);
                  const rect=range.getBoundingClientRect(), area=el.closest('.qpm-body').getBoundingClientRect();
                  return {tail:rect.toJSON(),area:area.toJSON(),visible:rect.bottom<=area.bottom+1 && rect.top>=area.top-1};
                }""")
                assert geometry["visible"], geometry
                page.screenshot(path=str(output / f"{size}-03-question-tail.png"))
                record(current_step, geometry)

                current_step = size + " 投屏题与地图工具同时可用"
                page.get_by_role("button", name="展开地图工具与可视化地图", exact=True).click()
                mode = page.get_by_test_id("map-mode-toggle")
                mode.click()
                expect(mode).to_have_attribute("aria-pressed", "true")
                mode.click()
                expect(mode).to_have_attribute("aria-pressed", "false")
                page.screenshot(path=str(output / f"{size}-03b-question-tools.png"))
                page.get_by_role("button", name="收起地图工具与可视化地图", exact=True).click()
                record(current_step, "题目保持打开时真实切换2D/3D后返回；外网3D瓦片不在此断言")

                current_step = size + " 服务端计时与刷新"
                page.get_by_test_id("teacher-question-timer").click()
                expect(page.get_by_test_id("teacher-question-timer")).to_have_text("暂停计时")
                page.wait_for_timeout(1200)
                before = session()
                stage_events = sum(event["type"] == "stage_enter" for event in before["events"])
                request_boundary = len(requests)
                page.reload(wait_until="domcontentloaded")
                expect(page.get_by_test_id("student-stage-navigation")).to_be_visible(timeout=30000)
                expect(page.get_by_test_id("question-practice-modal")).to_be_visible()
                after = session()
                assert sum(event["type"] == "stage_enter" for event in after["events"]) == stage_events
                assert after["active_question"]["timer"]["running_since"] == before["active_question"]["timer"]["running_since"]
                assert not any(request["method"] == "POST" and (request["path"].endswith("/stage") or request["path"].endswith("/timer")) for request in requests[request_boundary:])
                assert page.locator(".class-run-panel").count() == 0
                controls = page.get_by_test_id("classroom-teacher-controls")
                controls.locator("summary").click()
                page.get_by_test_id("teacher-question-timer").click()
                expect(page.get_by_test_id("teacher-question-timer")).to_have_text("继续计时")
                page.get_by_test_id("teacher-question-reveal").click()
                expect(page.get_by_test_id("qpm-answer")).to_be_visible(timeout=30000)
                assert ANSWER in page.get_by_test_id("qpm-answer").text_content()
                page.screenshot(path=str(output / f"{size}-04-answer.png"))
                record(current_step, {"stage_enter_count": stage_events, "running_since_preserved": True})

                current_step = size + " 导航与地图工具可点"
                page.get_by_test_id("teacher-question-close").click()
                expect(page.get_by_test_id("question-practice-modal")).to_have_count(0)
                page.get_by_role("button", name="展开地图工具与可视化地图", exact=True).click()
                mode = page.get_by_test_id("map-mode-toggle")
                expect(mode).to_be_visible()
                assert page.get_by_test_id("map-3d-globe").count() == 1
                boxes = {}
                for name, locator in {"previous": page.get_by_test_id("class-prev-stage"), "next": page.get_by_test_id("class-next-stage"),
                                      "tools": mode, "display": page.get_by_test_id("student-display-toggle")}.items():
                    bounds = locator.bounding_box()
                    assert bounds and bounds["x"] >= 0 and bounds["y"] >= 0 and bounds["x"] + bounds["width"] <= width and bounds["y"] + bounds["height"] <= height, (name, bounds)
                    assert locator.evaluate("el => {const r=el.getBoundingClientRect();const hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return el===hit || el.contains(hit);}"), name + " covered"
                    boxes[name] = bounds
                page.screenshot(path=str(output / f"{size}-05-map-tools.png"))
                record(current_step, {"bounds": boxes, "globe": "component and visible mode control verified; external 3D tiles not asserted"})

                current_step = size + " 结束课堂与复盘"
                page.get_by_test_id("student-display-toggle").click()
                expect(page.get_by_test_id("class-run-panel")).to_be_visible()
                page.get_by_role("button", name="结束上课", exact=True).click()
                expect(page.get_by_test_id("report-panel")).to_be_visible(timeout=30000)
                expect(page.get_by_test_id("generate-report")).to_be_enabled(timeout=20000)
                page.get_by_test_id("generate-report").click()
                expect(page.get_by_test_id("report-diagnosis")).to_be_visible(timeout=45000)
                assert session()["status"] == "ended"
                page.screenshot(path=str(output / f"{size}-06-report.png"))
                record(current_step, "结束与生成报告均真实点击；未伪造学生作答数据")
                record(size + " pageerror", errors)
                assert not errors, errors
            except Exception as exc:
                results.append({"step": current_step, "ok": False, "detail": str(exc)[:3000], "pageerrors": errors})
                page.screenshot(path=str(output / f"{size}-FAIL.png"))
                print("FAIL " + current_step + ": " + str(exc)[:600], flush=True)
            finally:
                (output / "result.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
                (output / f"{size}-requests.json").write_text(json.dumps(requests, ensure_ascii=False, indent=2), encoding="utf-8")
                context.close()
        browser.close()
    print("Evidence: " + str(output), flush=True)
    return 0 if results and all(item["ok"] for item in results) else 1


if __name__ == "__main__":
    sys.exit(main())
