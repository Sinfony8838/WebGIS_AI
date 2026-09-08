import json
import threading
import unittest

from unittest.mock import patch

from backend.app.models import LayerRecord
from backend.app.services.assistant import ASSISTANT_TOOL_SCHEMA
from backend.tests.test_voice_tools import FakeLLM
from backend.tests import test_voice_tools as voice_tests


class InteractionRegressionTest(unittest.TestCase):
    build_runtime = voice_tests.InteractionToolsTest.build_runtime
    wait_for_job = voice_tests.InteractionToolsTest.wait_for_job

    def test_every_advertised_interaction_tool_is_visible_to_executor(self):
        runtime, _, _ = self.build_runtime()
        registry = runtime.session_engine.tool_executor.tool_registry
        for tool in ASSISTANT_TOOL_SCHEMA:
            if 'interaction' in tool.get('modes', []):
                self.assertIn('interaction', registry[tool['name']]['visible_in_mode'], tool['name'])
        for forbidden in ('generate_image', 'record_observation', 'launch_question', 'open_material', 'toggle_teaching_map'):
            assessment = runtime.session_engine.tool_executor.assess('webgis', [{'tool_name': forbidden, 'tool_params': {}}], assistant_mode='interaction')
            self.assertEqual(assessment['risk_level'], 'blocked')

    def test_negated_single_command_does_not_execute_or_call_llm(self):
        runtime, _, pid = self.build_runtime()
        fake = FakeLLM()
        runtime.llm_planner.minimax_client = fake
        for command in ('不要切换到三维地球', '别结束上课', '不用打开数据库', '请记住，这两个面板指图层管理器和数据库面板，暂时不用打开'):
            result = self.wait_for_job(runtime, runtime.submit_assistant_message(pid, command, assistant_mode='interaction')['job_id'])['result']
            self.assertEqual(result['actions_executed'], [])
            self.assertFalse(result['requires_confirmation'])
        self.assertEqual(fake.calls, 0)

    def test_compound_command_reaches_planner_as_one_request(self):
        runtime, _, pid = self.build_runtime()
        fake = FakeLLM(json.dumps({'assistant_message': '已完成', 'actions': [
            {'tool_name': 'switch_view_mode', 'tool_params': {'mode': 'plane'}},
            {'tool_name': 'open_panel', 'tool_params': {'panel': 'layers', 'open': True}},
        ]}))
        runtime.llm_planner.minimax_client = fake
        result = self.wait_for_job(runtime, runtime.submit_assistant_message(pid, '先切换到二维地图，再打开图层管理器', assistant_mode='interaction')['job_id'])['result']
        self.assertEqual(fake.calls, 1)
        self.assertEqual([a['action']['tool_name'] for a in result['actions_executed']], ['switch_view_mode', 'open_panel'])

    def test_negated_compound_does_not_short_circuit_to_end_class(self):
        runtime, _, pid = self.build_runtime()
        fake = FakeLLM()
        runtime.llm_planner.minimax_client = fake
        result = self.wait_for_job(runtime, runtime.submit_assistant_message(pid, '不要结束上课，只打开图层管理器', assistant_mode='interaction')['job_id'])['result']
        self.assertEqual(fake.calls, 1)
        self.assertEqual(result['actions_executed'][0]['action']['tool_name'], 'open_panel')

    def test_rule_path_never_calls_hidden_geocoder(self):
        runtime, store, pid = self.build_runtime()
        fake = FakeLLM()
        runtime.assistant_service.minimax_client = fake
        with patch.object(runtime.config, 'minimax_enabled', return_value=True):
            plan = runtime.assistant_service.plan_interaction_actions('切换到卫星底图', store.get_project(pid))
        self.assertEqual(fake.calls, 0)
        self.assertEqual(plan['actions'][0]['tool_name'], 'switch_basemap')

    def test_unmatched_named_layer_does_not_mutate_active_layer_or_claim_success(self):
        runtime, store, pid = self.build_runtime()
        store.upsert_layer(pid, LayerRecord(layer_id='known', name='已知图层', kind='geojson', source='builtin', geometry_type='polygon', opacity=1.0))
        store.get_project(pid).active_layer_id = 'known'
        fake = FakeLLM(json.dumps({'assistant_message': '已经修改完成', 'actions': [{'tool_name': 'set_layer_opacity', 'tool_params': {'layer_name': '不存在的火星矿产', 'opacity': 0.5}}]}))
        runtime.llm_planner.minimax_client = fake
        result = self.wait_for_job(runtime, runtime.submit_assistant_message(pid, '处理目标xyz', assistant_mode='interaction')['job_id'])['result']
        self.assertEqual(store.get_project(pid).layers[0].opacity, 1.0)
        self.assertNotEqual(result['assistant_message'], '已经修改完成')
        self.assertEqual(result['assistant_message'], result['actions_executed'][0]['result']['assistant_message'])

    def test_job_wait_wakes_on_change_and_handles_update_before_wait(self):
        runtime, store, pid = self.build_runtime()
        job = store.create_job(project_id=pid, job_type='assistant', title='test', workflow_type='assistant_message', request={})
        version = job.updated_at
        waiting = threading.Event()
        finished = threading.Event()
        def subscriber():
            waiting.set()
            store.wait_for_job_update(job.job_id, version, timeout=5)
            finished.set()
        thread = threading.Thread(target=subscriber, daemon=True)
        thread.start()
        self.assertTrue(waiting.wait(1))
        store.set_job_status(job.job_id, 'completed')
        self.assertTrue(finished.wait(1), 'completed job must wake subscriber without polling delay')
        thread.join(1)
        store.wait_for_job_update(job.job_id, version, timeout=5)

    def test_opacity_rules_do_not_replace_unknown_target_with_active_layer(self):
        runtime, store, pid = self.build_runtime()
        store.upsert_layer(pid, LayerRecord(layer_id='known', name='已知图层', kind='geojson', source='builtin', geometry_type='polygon'))
        project = store.get_project(pid)
        project.active_layer_id = 'known'
        plan = runtime.assistant_service.plan_interaction_actions('请把不存在的火星矿产图层调到半透明', project)
        self.assertEqual(plan['actions'], [])
        for text in ('把当前图层调到半透明', '把图层调到半透明'):
            plan = runtime.assistant_service.plan_interaction_actions(text, project)
            self.assertEqual(plan['actions'][0]['tool_params'], {'layer_id': 'known', 'opacity': 0.5})

    def test_separate_is_not_negation_and_comma_preserves_second_command(self):
        runtime, store, pid = self.build_runtime()
        for text in ('分别打开图层管理器和数据库面板', '不要结束上课，打开图层管理器'):
            plan = runtime.assistant_service.plan_interaction_actions(text, store.get_project(pid))
            self.assertEqual(plan['actions'], [])
            self.assertFalse(plan.get('stop_planning'))

    def test_failed_planning_is_not_reported_as_successful_ai_planning(self):
        runtime, _, pid = self.build_runtime()
        job = self.wait_for_job(runtime, runtime.submit_assistant_message(pid, '无法理解的xyz', assistant_mode='interaction')['job_id'])
        self.assertEqual(job['stages']['planning']['status'], 'error')
        self.assertEqual(job['result']['actions_executed'], [])

    def test_interaction_retains_valid_llm_clarification_without_actions(self):
        runtime, _, pid = self.build_runtime()
        runtime.llm_planner.minimax_client = FakeLLM(json.dumps({'assistant_message': '请先指定要查询的数据年份。', 'actions': []}))
        job = self.wait_for_job(runtime, runtime.submit_assistant_message(pid, '帮我处理xyz', assistant_mode='interaction')['job_id'])
        self.assertEqual(job['result']['assistant_message'], '请先指定要查询的数据年份。')
        self.assertEqual(job['result']['planner'], 'interaction_minimax')
        self.assertEqual(job['result']['actions_executed'], [])

    def test_unknown_basemap_is_not_silently_replaced_with_default(self):
        runtime, store, pid = self.build_runtime()
        runtime.set_basemap(pid, 'amap_imagery')
        before = store.get_project(pid).base_map.copy()
        runtime.llm_planner.minimax_client = FakeLLM(json.dumps({'assistant_message': '卫星底图已设置', 'actions': [{'tool_name': 'switch_basemap', 'tool_params': {'basemap_id': 'satellite'}}]}))
        job = self.wait_for_job(runtime, runtime.submit_assistant_message(pid, '执行xyz', assistant_mode='interaction')['job_id'])
        self.assertEqual(store.get_project(pid).base_map, before)
        self.assertIn('未找到指定底图', job['result']['assistant_message'])

    def test_state_encoder_preserves_existing_json_and_reload(self):
        runtime, store, pid = self.build_runtime()
        from backend.app.store import RuntimeStore
        store.upsert_layer(pid, LayerRecord(layer_id='geometry', name='中文地图', kind='geojson', source='builtin', geometry_type='point', data={'type': 'FeatureCollection', 'features': [{'type': 'Feature', 'properties': {'missing': None, 'visible': True}, 'geometry': {'type': 'Point', 'coordinates': [120.5, 31.2]}}]}))
        runtime.classroom.create_class_session('lesson_builtin_population_distribution', pid)
        self.wait_for_job(runtime, runtime.submit_assistant_message(pid, '打开图层管理器', assistant_mode='interaction')['job_id'])
        collections = ('projects', 'jobs', 'artifacts', 'lessons', 'lesson_designs', 'lesson_rehearsals', 'class_sessions', 'conversations', 'messages', 'confirmations', 'workflows')
        expected = {name: {key: record.to_dict() for key, record in getattr(store, name).items()} for name in collections}
        expected = json.loads(json.dumps(expected, ensure_ascii=False))
        actual = json.loads(store.state_file.read_text(encoding='utf8'))
        self.assertEqual(actual, expected)
        restored = RuntimeStore(store.state_file)
        self.assertEqual(restored.get_project(pid).layers[0].data, store.get_project(pid).layers[0].data)

    def test_confirmed_end_class_reports_original_valid_assessment(self):
        runtime, _, pid = self.build_runtime()
        session = runtime.classroom.create_class_session('lesson_builtin_population_distribution', pid)['session']
        submitted = runtime.submit_assistant_message(pid, '结束上课', assistant_mode='interaction', teaching_context={'session_id': session['session_id']})
        plan = self.wait_for_job(runtime, submitted['job_id'])['result']
        confirmed = runtime.confirm_assistant_action(plan['confirmation_id'], decision='approve')
        result = self.wait_for_job(runtime, confirmed['job_id'])['result']
        self.assertEqual(result['actions_executed'][0]['result']['class_session']['status'], 'ended')
        self.assertEqual(result['actions_planned'][0]['risk_level'], 'high')
        self.assertIn('已结束', result['assistant_message'])
