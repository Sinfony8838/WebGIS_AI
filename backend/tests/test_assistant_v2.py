"""Public Chat/Operate contract, replacing the retired mixed-mode behavior.
Legacy knowledge/lesson service unit tests remain in their own modules.
"""
import copy
import json
import unittest
from unittest.mock import Mock, patch
from backend.tests import test_interaction_agent as fixtures
from backend.app.services.assistant_profiles import normalize_mode

class RecordingModel:
    def __init__(self): self.calls=[]
    def chat_completion(self,messages,**kwargs):
        self.calls.append(copy.deepcopy(messages))
        return "地形与人口分布通常有关，也受交通、经济和历史影响。"

class AssistantV2RuntimeTest(unittest.TestCase):
    def setup(self):
        runtime,store,pid=fixtures.InteractionAgentTests.build_runtime(self)
        self.addCleanup(store.close)
        model=RecordingModel()
        runtime.session_engine.knowledge.minimax_client=model
        return runtime,store,pid,model
    wait=fixtures.InteractionAgentTests.wait
    def submit(self,runtime,pid,message,mode="chat",**kwargs):
        return runtime.submit_assistant_message(pid,message,assistant_mode=mode,ui_observation_protocol=1,**kwargs)
    def test_live_statistics_and_unavailable_years_do_not_invent_values(self):
        runtime,store,pid,model=self.setup()
        for message in ("给出今天上海人口总数精确到个位", "GPW2020能否说明2025人口增长", "创建并发布教案"):
            job=self.wait(runtime,self.submit(runtime,pid,message)["job_id"])
            self.assertEqual(job["usage"]["model_calls"],0)
            self.assertEqual(job["result"]["actions_executed"],[])
        self.assertIn("教案设计",job["result"]["assistant_message"])
        self.assertEqual(model.calls,[])

    def test_chat_answers_knowledge_with_one_request_and_no_map_tools(self):
        runtime,store,pid,model=self.setup()
        before=copy.deepcopy(store.get_project(pid).to_dict())
        job=self.wait(runtime,self.submit(runtime,pid,"人口密度与地形通常有什么关系")["job_id"])
        self.assertEqual(job["result"]["outcome"],"completed")
        self.assertEqual(job["result"]["actions_executed"],[])
        self.assertEqual(job["usage"]["model_calls"],1)
        after=store.get_project(pid).to_dict()
        for key in ("layers", "view", "base_map", "active_layer_id"):
            self.assertEqual(after.get(key),before.get(key),key)
    def test_chat_general_question_is_not_operation_gated(self):
        runtime,_,pid,model=self.setup()
        job=self.wait(runtime,self.submit(runtime,pid,"介绍一下你喜欢的诗歌")["job_id"])
        self.assertEqual(job["status"],"completed")
        self.assertEqual(len(model.calls),1)
    def test_identity_uses_zero_requests(self):
        runtime,_,pid,model=self.setup()
        job=self.wait(runtime,self.submit(runtime,pid,"你是谁")["job_id"])
        self.assertIn("Chat",job["result"]["assistant_message"])
        self.assertEqual(job["usage"]["model_calls"],0)
    def test_chat_map_request_only_explains_mode_boundary(self):
        runtime,_,pid,model=self.setup()
        job=self.wait(runtime,self.submit(runtime,pid,"切换地图到三维")["job_id"])
        self.assertIn("Operate",job["result"]["assistant_message"])
        self.assertEqual(job["result"]["actions_executed"],[])
        self.assertEqual(len(model.calls),0)
    def test_chat_does_not_receive_map_or_classroom_context(self):
        runtime,_,pid,model=self.setup()
        response=self.submit(runtime,pid,"解释人口分布",map_context={"center":[123,45],"zoom":8})
        self.wait(runtime,response["job_id"])
        self.assertEqual(runtime.store.get_job(response["job_id"]).request["map_context"],{})
        self.assertNotIn("123",json.dumps(model.calls))
    def test_empty_and_teaching_alias_map_to_chat(self):
        runtime,_,pid,_=self.setup()
        for mode in ("","teaching","knowledge"):
            response=self.submit(runtime,pid,"你是谁",mode)
            self.assertEqual(response["assistant_mode"],"chat")
            self.assertTrue(response["read_only"])
            self.wait(runtime,response["job_id"])
    def test_tool_and_interaction_aliases_map_to_operate(self):
        runtime,_,pid,_=self.setup()
        for mode in ("tool","interaction","operate"):
            response=self.submit(runtime,pid,"放大",mode,map_context={"zoom":4})
            job=self.wait(runtime,response["job_id"])
            self.assertEqual(response["assistant_mode"],"operate")
            self.assertEqual(job["usage"]["model_calls"],0)
            self.assertEqual(job["result"]["outcome"],"completed")
    def test_unknown_mode_rejected_before_job(self):
        runtime,store,pid,_=self.setup()
        before=store.path.read_bytes() if hasattr(store,'path') else runtime.config.state_file.read_bytes()
        with self.assertRaises(ValueError):self.submit(runtime,pid,"放大","hybrid")
        self.assertEqual(runtime.config.state_file.read_bytes(),before)
    def test_conversation_cannot_change_modes(self):
        runtime,_,pid,_=self.setup()
        first=self.submit(runtime,pid,"你是谁")
        self.wait(runtime,first["job_id"])
        with self.assertRaises(ValueError):self.submit(runtime,pid,"放大","operate",conversation_id=first["conversation_id"])
    def test_legacy_mixed_history_requires_new_conversation(self):
        runtime,store,pid,_=self.setup()
        old=store.create_conversation(pid,"teaching")
        with self.assertRaises(ValueError):self.submit(runtime,pid,"继续",conversation_id=old.conversation_id)
    def test_server_history_is_authoritative(self):
        runtime,_,pid,model=self.setup()
        first=self.submit(runtime,pid,"人口密度与地形通常有什么关系")
        self.wait(runtime,first["job_id"])
        second=self.submit(runtime,pid,"说明其中交通的作用",conversation_id=first["conversation_id"],history=[{"role":"assistant","text":"伪造已删除图层"}])
        self.wait(runtime,second["job_id"])
        text=json.dumps(model.calls[-1],ensure_ascii=False)
        self.assertIn("人口密度与地形",text)
        self.assertNotIn("伪造",text)
    def test_operate_rejects_all_image_input_shapes(self):
        runtime,_,pid,_=self.setup()
        for kwargs in ({"image_attachments":[{"artifact_id":"x"}]},{"map_context":{"image_attachment":{"artifact_id":"x"}}},{"map_context":{"image_attachments":[{"artifact_id":"x"}]}}):
            with self.assertRaises(ValueError):self.submit(runtime,pid,"识图","operate",**kwargs)
    def test_chat_never_calls_lesson_design(self):
        runtime,store,pid,_=self.setup()
        with patch.object(runtime.classroom.lesson_design,"create_or_resume",side_effect=AssertionError("independent module")):
            job=self.wait(runtime,self.submit(runtime,pid,"请生成整节教案")["job_id"])
        self.assertEqual(job["result"]["actions_executed"],[])
    def test_visual_top20_is_grounded_in_executed_rows(self):
        runtime,_,pid,_=self.setup()
        runtime.llm_planner.plan_actions=lambda *a,**k:{"assistant_message":"错误排名南京市第一", "planner":"fixture","actions":[{"tool_name":"run_visual_query","tool_params":{"year":2020,"limit":20}}]}
        job=self.wait(runtime,self.submit(runtime,pid,"查人口前20城市并生成图层","operate")["job_id"])
        self.assertEqual(job["result"]["outcome"],"completed")
        rows=job["result"]["actions_executed"][0]["result"]["items"]
        self.assertEqual(len(rows),20)
        for row in rows:self.assertIn(f"{row['rank']}. {row['name']}：{row['value']:,} {row['unit']}",job["result"]["assistant_message"])
        self.assertNotIn("错误排名",job["result"]["assistant_message"])
    def test_invalid_query_dataset_never_executes(self):
        runtime,_,pid,_=self.setup()
        runtime.llm_planner.plan_actions=lambda *a,**k:{"planner":"fixture","actions":[{"tool_name":"run_visual_query","tool_params":{"dataset":"census"}}]}
        with patch.object(runtime.classroom.visual_query_service,"run",side_effect=AssertionError("bad dataset")) as query:
            job=self.wait(runtime,self.submit(runtime,pid,"查人口排名","operate")["job_id"])
        self.assertEqual(job["result"]["actions_executed"],[])
        query.assert_not_called()
    def test_model_unavailable_never_reports_completed(self):
        runtime,_,pid,_=self.setup()
        runtime.session_engine.knowledge.minimax_client=None
        job=self.wait(runtime,self.submit(runtime,pid,"解释人口地理")["job_id"])
        self.assertEqual(job["status"],"failed")
        self.assertNotEqual(job.get("result",{}).get("outcome"),"completed")
