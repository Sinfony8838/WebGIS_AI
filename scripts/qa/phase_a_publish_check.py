# -*- coding: utf-8 -*-
"""Phase A 发布链路核对：教案草稿 → 整份核对 → 定稿 → 模拟测试工作副本一致。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
FRONT = "http://127.0.0.1:5821"
BACK = "http://127.0.0.1:18642"
results = []


def record(step, ok, detail=""):
    results.append({"step": step, "ok": ok, "detail": detail})
    print(("PASS " if ok else "FAIL ") + step + (" | " + detail if detail else ""), flush=True)


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1600, "height": 900})
        page = ctx.new_page()
        login = ctx.request.post(
            BACK + "/auth/login",
            data=json.dumps({"email": "admin@example.com", "password": "admin12345"}),
            headers={"Content-Type": "application/json"},
        ).json()
        csrf = login.get("csrf_token") or ""
        ctx.request.new_context_options = None  # no-op; header added per call below
        def H(extra=None):
            h = {"Content-Type": "application/json", "X-WebGIS-CSRF": csrf}
            if extra:
                h.update(extra)
            return h
        page.goto(FRONT, wait_until="domcontentloaded")
        target = None
        projects = ctx.request.get(BACK + "/projects").json().get("items") or []
        for proj in projects:
            designs = ctx.request.get(BACK + f"/lesson-design/sessions?project_id={proj['project_id']}").json()
            for item in designs.get("items") or []:
                if item.get("status") == "active" and (item.get("draft") or {}).get("import_review"):
                    target = item
                    break
            if target:
                break
        assert target, "没有可用的导入草稿"
        design_id = target["design_id"]
        record("找到导入草稿", True, design_id)

        # 逐项 API 直填必填章节（与 UI resolve 同一端点）
        def resolve(section, value):
            r = ctx.request.post(
                BACK + f"/lesson-design/sessions/{design_id}/sections/{section}/resolve",
                data=json.dumps({"decision": "edit", "value": value}),
                headers=H(),
            )
            assert r.ok, f"{section}: {r.text()[:200]}"
            return r.json()

        info = ctx.request.get(BACK + f"/lesson-design/sessions/{design_id}").json()
        stages = info["draft"]["stages"]
        for stage in stages:
            stage.setdefault("knowledge_conclusion", "海陆热力差异决定季风风向的季节变化")
            stage.setdefault("student_activities", stage.get("student_activities") or ["读图讨论"])
        # 环节时长合计 = 课时 40 分钟；环节1 补一个明确问题
        stages[0]["minutes"] = 10
        stages[1]["minutes"] = 30
        resolve("stages", stages)
        bind = ctx.request.post(
            BACK + f"/lesson-design/sessions/{design_id}/questions/bind",
            data=json.dumps({
                "stage_id": stages[0]["stage_id"],
                "manual": {"text": "冬季风和夏季风的风向有什么不同？", "answer": "冬季风从陆地吹向海洋，夏季风从海洋吹向陆地。", "explanation": "海陆热力性质差异导致风向随季节反转。"},
            }),
            headers=H(),
        )
        assert bind.ok, bind.text()[:200]
        resolve("design_thinking", "以季风气候的观察现象为切入点，学生从生活体验出发，通过读图、讨论与简图绘制，逐步建立海陆热力性质差异与季风环流的因果解释，最后落实到对区域气候特征的综合认识。")
        resolve("board_design", "季风：冬季风（陆→海）；夏季风（海→陆）；成因：海陆热力性质差异。")
        resolve("homework", {"basic": ["绘制冬夏季风风向示意图"], "inquiry": ["查阅资料：季风对家乡农业的影响"]})
        resolve("reflection", "预设学生对海陆热力差异理解困难，需借助示意图与生活实例分步搭梯。")
        resolve("requirements", {"raw": "七年级季风气候的形成，40 分钟，含读图与小组探究。"})
        resolve("curriculum_interpretation", "课标要求运用地图说明季风气候的分布与成因，理解海陆热力差异对气候的影响。")
        resolve("student_analysis", "七年级学生已认识气温与降水分布，具备初步读图能力，但对海陆性质的抽象差异理解不足，需要示意图与生活经验支持。")
        resolve("textbook_analysis", "教材以季风环流为主线，配以冬夏季风示意图，突出海陆热力性质差异这一核心成因。")
        ctx.request.post(BACK + f"/lesson-design/sessions/{design_id}/sections/all/resolve",
                         data=json.dumps({"decision": "accept"}), headers=H())
        record("填写必填章节并整份核对确认", True, design_id)

        latest = ctx.request.get(BACK + f"/lesson-design/sessions/{design_id}").json()
        fin = ctx.request.post(BACK + f"/lesson-design/sessions/{design_id}/finalize",
                               data=json.dumps({"expected_revision": latest["revision"]}), headers=H())
        ok = fin.ok
        record("定稿生成课时 v1", ok, fin.text()[:200] if not ok else "")
        lesson = fin.json().get("lesson") or {} if ok else {}
        if not lesson:
            # 已定稿过的草稿：从设计记录里取 final_lesson_id
            info2 = ctx.request.get(BACK + f"/lesson-design/sessions/{design_id}").json()
            lid = info2.get("final_lesson_id") or ""
            lesson = ctx.request.get(BACK + f"/lessons/{lid}").json().get("lesson") or {"lesson_id": lid, "metadata": {"project_id": proj["project_id"]}}

        # 模拟测试：创建工作副本并核对素材一致
        rehearsal = ctx.request.post(
            BACK + "/lesson-rehearsals",
            data=json.dumps({"lesson_id": lesson["lesson_id"], "project_id": lesson["metadata"]["project_id"]}),
            headers=H(),
        )
        assert rehearsal.ok, rehearsal.text()[:200]
        wc = rehearsal.json().get("rehearsal", rehearsal.json()).get("working_copy") or {}
        wc_stages = wc.get("stages") or []
        s1 = wc_stages[0] if wc_stages else {}
        types1 = [b.get("type") for b in ((s1.get("presentation") or {}).get("blocks") or [])]
        scene1 = s1.get("scene") or {}
        q2 = (wc_stages[1].get("questions") if len(wc_stages) > 1 else []) or []
        record(
            "模拟测试工作副本与教案素材一致",
            "image" in types1 and "video" in types1 and bool(scene1) and bool(q2),
            f"blocks={types1} scene={'有' if scene1 else '无'} q2={len(q2)}",
        )
        browser.close()
    (ROOT / "scratch" / "e2e" / "publish_check_result.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if all(r["ok"] for r in results) else 2


if __name__ == "__main__":
    sys.exit(main())
