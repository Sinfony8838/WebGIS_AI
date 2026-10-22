"""Image provider bytes here are fixtures, never real-geography acceptance."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from backend.tests import test_assistant_profiles as profile_fixtures
from backend.app.runtime import TRANSPARENT_PNG
from backend.app.services.geography_image_policy import GeographyImagePolicy, image_edit_request, is_redraw
from backend.app.services.interaction_run import InteractionRun, interaction_scope, ModelBudgetExceeded, RunStopped

BRIEF = {"allowed": True, "kind": "concept", "prompt": "蒸发向大气，降水向地面，地表径流流向低处。AI生成概念示意。", "checks": ["径流流向低处"]}
class GeographyImageTests(unittest.TestCase):
    build_runtime = profile_fixtures.AssistantProfilesTests.build_runtime
    wait = profile_fixtures.AssistantProfilesTests.wait
    def setUp(self):
        self.runtime,self.store,self.pid=self.build_runtime()
        self.addCleanup(self.store.close)
        self.runtime.config.minimax_api_key="fixture"
        self.runtime.config.minimax_token_plan_key="fixture"
        self.runtime.config.vision_provider="minimax_mcp"
        self.policy=GeographyImagePolicy(self.runtime)
    def text_model(self,obj):
        self.runtime.session_engine.knowledge.minimax_client=type("FixtureModel",(),{"chat_completion":lambda _self,*args,**kwargs:json.dumps(obj,ensure_ascii=False)})()
    def mcp(self,text):
        return {"result":{"content":[{"type":"text","text":json.dumps(text,ensure_ascii=False) if isinstance(text,dict) else text}]}}
    def uploaded(self):
        return self.runtime.upload_image_asset(self.pid,"reference.png",TRANSPARENT_PNG)["artifact"]
    def test_rejects_wrong_theory_and_real_map_before_image_call(self):
        for kind,reason in [("concept","自然地表径流不能无外力从低处流向山顶"),("map","真实人口分级地图需要数据")]:
            self.text_model({"allowed":False,"kind":kind,"reason":reason})
            with patch.object(self.runtime.image_generation_service,"generate") as generate:
                with self.assertRaisesRegex(ValueError,"未生成图片"):
                    self.runtime.generate_image_asset(self.pid,"绘制图片")
                generate.assert_not_called()
    def test_bad_or_missing_preflight_cannot_fall_back_to_generation(self):
        for response in [{"allowed":"true",**{k:v for k,v in BRIEF.items() if k!="allowed"}}, {**BRIEF,"checks":[]}, {**BRIEF,"prompt":"x"*851}, {**BRIEF,"kind":"map"}]:
            self.text_model(response)
            with self.assertRaises(ValueError): self.policy.prepare(self.pid,"图片")
    def test_review_fail_unknown_and_missing_evidence_fail_closed(self):
        brief={"checks":["径流向下"]}
        cases=[({"status":"pass","checks":[{"requirement":"径流向下","status":"fail","evidence":"箭头逆坡"}]},"fail"),({"status":"pass","checks":[{"requirement":"另一项","status":"pass","evidence":"可见"}]},"unknown"), ("不是JSON","unknown")]
        for payload,status in cases:
            with patch.object(self.runtime.vision_service.mcp_client,"_call_tool",return_value=self.mcp({**payload,"visible_text":["AI生成概念示意"]} if isinstance(payload,dict) else payload)):
                result=self.policy.review(Path("fixture.png"),brief)
                self.assertEqual(result["status"],status)
    def test_real_admission_counts_three_and_rejects_fourth(self):
        self.text_model(BRIEF)
        def vision(name,args):
            brief=json.loads(args["prompt"].split("核对依据：",1)[1])
            return self.mcp({"status":"pass","summary":"fixture","visible_text":["AI生成概念示意"],"checks":[{"requirement":c,"status":"pass","evidence":"fixture visible"} for c in brief["checks"]]})
        parent=self.store.create_job(project_id=self.pid,job_type="assistant",title="test",request={"actor_user_id":"alice"})
        run=InteractionRun(parent.job_id,mode="chat")
        with interaction_scope(run),patch.object(self.runtime.vision_service.mcp_client,"_call_tool",side_effect=vision),patch.object(self.runtime.image_generation_service,"_request_image",return_value={"raw_bytes":TRANSPARENT_PNG,"mime_type":"image/png","suffix":".png","model":"image-01","aspect_ratio":"16:9","request_id":"fixture"}):
            generated=self.runtime.generate_image_asset(self.pid,"水循环示意图")
            self.assertEqual(run.calls,3)
            self.assertEqual(generated["status"],"success")
            self.assertFalse(generated["artifact"]["metadata"]["saved_to_library"])
            with self.assertRaises(ModelBudgetExceeded): self.runtime.vision_service.mcp_client.understand_image("check","fixture.png")
        self.assertEqual(run.calls,3)
    def test_reference_is_project_bound_and_hash_recorded(self):
        image=self.uploaded()
        run=InteractionRun("test",mode="chat")
        with interaction_scope(run),patch.object(self.runtime.vision_service.mcp_client,"_call_tool",return_value=self.mcp(BRIEF)) as call:
            brief=self.policy.prepare(self.pid,"根据参考图重新绘制示意图",image["artifact_id"])
            self.assertEqual(run.calls,1)
            self.assertEqual(brief["generation_method"],"reference_redraw")
            self.assertEqual(len(brief["reference"]["sha256"]),64)
            self.assertEqual(call.call_args.args[1]["image_url"],image["path"])
            other=self.runtime.create_project()["project_id"]
            with self.assertRaises(ValueError): self.policy.prepare(other,"重绘",image["artifact_id"])
            self.assertEqual(call.call_count,1)
    def test_original_edit_reads_but_does_not_generate(self):
        image=self.uploaded()
        with patch.object(self.runtime.vision_service.mcp_client,"_call_tool",return_value=self.mcp("可见河流向低处汇流。")),patch.object(self.runtime.image_generation_service,"generate") as generate:
            job=self.wait(self.runtime,self.runtime.submit_assistant_message(self.pid,"在原图上把河流箭头改成红色，保持布局不变",assistant_mode="chat",actor_role="admin",image_attachments=[{"artifact_id":image["artifact_id"]}])["job_id"])
            self.assertEqual(job["result"]["outcome"],"partial")
            self.assertIn("不支持",job["result"]["assistant_message"])
            self.assertEqual(job["usage"]["model_calls"],1)
            generate.assert_not_called()
    def test_failed_review_preview_cannot_be_saved(self):
        image=self.uploaded();record=self.store.get_artifact(image["artifact_id"])
        record.artifact_type="assistant_image_preview"
        record.metadata.update(owner_user_id="alice",geography_review={"status":"unknown"})
        with self.assertRaises(ValueError):self.store.save_assistant_image(record.artifact_id,"alice")
        with self.assertRaises(PermissionError):self.store.save_assistant_image(record.artifact_id,"bob")
        self.assertEqual(record.artifact_type,"assistant_image_preview")
    def test_cancelled_vision_never_becomes_success(self):
        with interaction_scope(InteractionRun("test",cancelled=lambda:True)),patch.object(self.runtime.vision_service.mcp_client,"_call_tool") as call:
            with self.assertRaises(RunStopped):self.policy.review(Path("fixture.png"),{"checks":["方向"]})
            call.assert_not_called()
    def test_edit_and_redraw_are_distinct(self):
        self.assertTrue(image_edit_request("把箭头改为红色",True))
        self.assertFalse(image_edit_request("分析地理过程",True))
        self.assertFalse(is_redraw("不要重新绘制，原图上修改"))
        self.assertTrue(is_redraw("根据参考图重新绘制一张示意图"))

    def test_reference_redraw_through_runtime_resolves_attachment_and_counts_calls(self):
        image=self.uploaded()
        def vision(name,args):
            if "核对依据：" not in args["prompt"]:return self.mcp(BRIEF)
            brief=json.loads(args["prompt"].split("核对依据：",1)[1])
            return self.mcp({"status":"pass","summary":"fixture","visible_text":["AI生成概念示意"],"checks":[{"requirement":c,"status":"pass","evidence":"fixture visible"} for c in brief["checks"]]})
        parent=self.store.create_job(project_id=self.pid,job_type="assistant",title="test",request={"actor_user_id":"alice"})
        run=InteractionRun(parent.job_id,mode="chat")
        with interaction_scope(run),patch.object(self.runtime.vision_service.mcp_client,"_call_tool",side_effect=vision),patch.object(self.runtime.image_generation_service,"_request_image",return_value={"raw_bytes":TRANSPARENT_PNG,"mime_type":"image/png","suffix":".png","model":"image-01","aspect_ratio":"16:9","request_id":"fixture"}):
            generated=self.runtime.generate_image_asset(self.pid,"根据参考图重新绘制一张水循环示意图",reference_image_id=image["artifact_id"])
        self.assertEqual(run.calls,3)
        self.assertEqual(generated["artifact"]["metadata"]["geography_brief"]["reference"]["artifact_id"],image["artifact_id"])

    def test_partial_watermark_is_not_full_concept_label(self):
        payload={"status":"pass","summary":"pass","visible_text":["AI生成"],"checks":[{"requirement":"方向","status":"pass","evidence":"可见向下"}]}
        with patch.object(self.runtime.vision_service.mcp_client,"_call_tool",return_value=self.mcp(payload)):
            self.assertEqual(self.policy.review(Path("fixture.png"),{"checks":["方向"]})["status"],"unknown")
    def test_review_interruption_keeps_generated_draft_but_never_saves(self):
        self.text_model(BRIEF)
        with patch.object(self.policy.__class__,"review",side_effect=RunStopped("cancelled")),patch.object(self.runtime.image_generation_service,"_request_image",return_value={"raw_bytes":TRANSPARENT_PNG,"mime_type":"image/png","suffix":".png","model":"image-01","aspect_ratio":"16:9","request_id":"fixture"}):
            with self.assertRaises(RunStopped):self.runtime.generate_image_asset(self.pid,"水循环示意图")
        previews=[a for a in self.store.artifacts.values() if a.artifact_type=="assistant_image_preview"]
        self.assertEqual(len(previews),1)
        self.assertTrue(Path(previews[0].path).exists())
        self.assertEqual(previews[0].metadata["geography_review"]["status"],"unknown")
        self.assertFalse(previews[0].metadata["saved_to_library"])
