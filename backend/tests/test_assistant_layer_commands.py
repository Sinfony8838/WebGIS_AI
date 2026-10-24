import time
import threading
import unittest
from unittest.mock import patch
import pytest
from backend.app.config import AppConfig
from backend.app.models import ProjectRecord, LayerRecord
from backend.app.services.assistant import AssistantService, ASSISTANT_TOOL_SCHEMA
from backend.app.services.assistant_profiles import tool_allowed
from backend.tests import test_voice_tools as fixtures


def project():
    layers=[LayerRecord.create(name=name,layer_id=key,kind="vector",source="test",geometry_type="Point",visible=visible) for key,name,visible in [('short','人口',True),('pop','人口分布',True),('hu','胡焕庸线',False)]]
    return ProjectRecord(project_id='test',name='test',layers=layers,active_layer_id='short')


@pytest.mark.parametrize('message,tool,ids',[
 ('删除当前所有打开的图层','delete_layers',['short','pop']),
 ('删除当前显示的人口分布图层','delete_layers',['pop']),
 ('把隐藏的人口分布图层改成红色','style_layer',['pop']),
 ('把打开的人口分布图层置顶','reorder_layer',['pop']),
 ('把所有图层改成红色','style_layer',['short','pop','hu']),
 ('取消隐藏人口分布图层','toggle_layer',['pop']),
 ('隐藏人口分布图层和胡焕庸线','toggle_layer',['pop','hu']),
 ('删除所有图层','delete_layers',['short','pop','hu']),
 ('删除人口分布','delete_layers',['pop']),
])
def test_whole_layer_utterance(message,tool,ids):
    service=AssistantService(AppConfig())
    plan=service.plan_interaction_actions(message,project())
    assert plan['actions'] and all(action['tool_name']==tool for action in plan['actions'])
    actual=plan['actions'][0]['tool_params']['layer_ids'] if tool=='delete_layers' else [a['tool_params']['layer_id'] for a in plan['actions']]
    assert actual==ids
    if message.startswith('取消隐藏'):assert plan['actions'][0]['tool_params']['visible'] is True


@pytest.mark.parametrize('message',[
 '人口分布图层为什么没有显示','人口分布图层现在是半透明吗','把不存在的矿产图层改成红色',
 '导出当前显示的人口分布图层','不要删除当前所有打开的图层',
 '隐藏人口分布图层然后把不存在的矿产图层调到半透明',
 '人口分布图层现在是半透明吗然后切换到二维地图',
 '删除除人口分布以外的所有打开的图层',
])
def test_layer_feedback_constraints_and_missing_targets_never_partially_execute(message):
    assert AssistantService(AppConfig()).plan_interaction_actions(message,project())['actions']==[]


def test_sequential_delete_does_not_turn_into_visibility():
    plan=AssistantService(AppConfig()).plan_interaction_actions('删除隐藏的人口分布图层然后切换到二维地图',project())
    assert [a['tool_name'] for a in plan['actions']]==['delete_layers','switch_view_mode']


def test_duplicate_names_require_clarification():
    p=project();p.layers.append(LayerRecord.create(name='人口分布',kind='vector',source='test',geometry_type='Point'))
    result=AssistantService(AppConfig()).plan_interaction_actions('删除人口分布图层',p)
    assert not result['actions'] and '不唯一' in result['assistant_message']


def test_existing_basemap_shortcut_is_not_shadowed_by_layer_name():
    p = project()
    p.layers.append(LayerRecord.create(name='降水', kind='vector', source='test', geometry_type='Point'))
    plan = AssistantService(AppConfig()).plan_interaction_actions('切换到降水底图', p)
    assert plan['actions'][0]['tool_name'] == 'switch_basemap'


@pytest.mark.parametrize('text,tool', [('打开人口分布图','apply_template'), ('显示胡焕庸线对比图','run_workflow'), ('隐藏人口分布图','toggle_layer')])
def test_existing_map_templates_and_unique_map_name_alias(text, tool):
    plan = AssistantService(AppConfig()).plan_interaction_actions(text, project())
    assert plan['actions'][0]['tool_name'] == tool


class DeleteLayerFlowTest(unittest.TestCase):
    build_runtime=fixtures.InteractionToolsTest.build_runtime
    wait_for_job=fixtures.InteractionToolsTest.wait_for_job

    def setup_project(self):
        runtime,store,pid=self.build_runtime();self.addCleanup(store.close)
        for layer in project().layers:store.upsert_layer(pid,layer)
        return runtime,store,pid

    def request(self,runtime,pid,text='删除当前所有打开的图层'):
        return self.wait_for_job(runtime,runtime.submit_assistant_message(pid,text,assistant_mode='operate')['job_id'])

    def test_delete_requires_confirmation_freezes_ids_and_preserves_hidden_and_new_layers(self):
        runtime,store,pid=self.setup_project()
        job=self.request(runtime,pid)
        assert job['result']['requires_confirmation']
        assert job['usage']['model_calls']==0
        assert len(store.get_project(pid).layers)==3
        assert '人口分布' in job['result']['assistant_message']
        store.upsert_layer(pid,LayerRecord.create(name='后来新增',layer_id='new',kind='vector',source='test',geometry_type='Point'))
        cid=job['result']['confirmation_id']
        result=self.wait_for_job(runtime,runtime.confirm_assistant_action(cid)['job_id'])
        assert result['status']=='completed' and result['result']['outcome']=='completed'
        assert {l.layer_id for l in store.get_project(pid).layers}=={'hu','new'}
        assert result['ui_actions'][0]['removed_layer_ids']==['short','pop']
        assert result['ui_actions'][0]['status']=='applied'
        assert result['usage']['model_calls']==0

    def test_changed_or_missing_target_aborts_entire_batch(self):
        runtime,store,pid=self.setup_project();job=self.request(runtime,pid)
        store.patch_layer(pid,'pop',{'opacity':0.6})
        result=self.wait_for_job(runtime,runtime.confirm_assistant_action(job['result']['confirmation_id'])['job_id'])
        assert result['status']=='failed'
        assert {l.layer_id for l in store.get_project(pid).layers}=={'short','pop','hu'}
        assert store.get_confirmation(job['result']['confirmation_id']).status=='invalidated'

    def test_reject_and_duplicate_confirm_do_not_delete_twice(self):
        runtime,store,pid=self.setup_project();job=self.request(runtime,pid)
        cid=job['result']['confirmation_id']
        result=self.wait_for_job(runtime,runtime.confirm_assistant_action(cid,decision='reject')['job_id'])
        assert result['status']=='completed' and len(store.get_project(pid).layers)==3
        result=self.wait_for_job(runtime,runtime.confirm_assistant_action(cid)['job_id'])
        assert result['status']=='failed' and len(store.get_project(pid).layers)==3

    def test_foreign_or_duplicate_id_rejected_without_partial_delete(self):
        runtime,store,pid=self.setup_project();other=store.create_project('other')
        foreign=LayerRecord.create(name='foreign',kind='vector',source='test',geometry_type='Point');store.upsert_layer(other.project_id,foreign)
        for ids in [['pop',foreign.layer_id],['pop','pop'],[]]:
            with pytest.raises(ValueError):store.delete_layers(pid,ids)
        assert len(store.get_project(pid).layers)==3

    def test_missing_ui_receipt_is_partial_in_job_and_history(self):
        runtime,store,pid=self.setup_project();job=self.request(runtime,pid)
        store.get_job(job['job_id']).request['ui_observation_protocol']=0
        job_id = runtime.confirm_assistant_action(job['result']['confirmation_id'])['job_id']
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            result = runtime.get_job(job_id)
            if result['status'] in {'completed', 'failed'}:
                break
            time.sleep(0.02)
        assert result['status'] == 'completed'
        assert result['result']['outcome']=='partial'
        assert len(store.get_project(pid).layers)==1
        messages=store.list_conversation_messages(job['result']['conversation_id'])
        assert messages[-1].text==result['result']['assistant_message']
        assert '未确认' in messages[-1].text

    def test_confirmation_claim_is_atomic(self):
        runtime,store,pid=self.setup_project();job=self.request(runtime,pid);cid=job['result']['confirmation_id']
        barrier=threading.Barrier(2);outcomes=[]
        def claim():
            barrier.wait()
            try:store.resolve_confirmation(cid,'approved',expected_status='pending');outcomes.append('ok')
            except ValueError:outcomes.append('blocked')
        threads=[threading.Thread(target=claim) for _ in range(2)]
        for t in threads:t.start()
        for t in threads:t.join()
        assert sorted(outcomes)==['blocked','ok']

    def test_concurrent_confirmation_jobs_execute_delete_once(self):
        runtime, store, pid = self.setup_project()
        planned = self.request(runtime, pid)
        cid = planned['result']['confirmation_id']
        barrier = threading.Barrier(2)
        resolve = store.resolve_confirmation
        def competing_claim(key, status, **kwargs):
            if status == 'approved':
                barrier.wait(timeout=10)
            return resolve(key, status, **kwargs)
        with patch.object(store, 'resolve_confirmation', side_effect=competing_claim), patch.object(store, 'delete_layers', wraps=store.delete_layers) as delete:
            jobs = [runtime.confirm_assistant_action(cid)['job_id'] for _ in range(2)]
            results = [self.wait_for_job(runtime, job) for job in jobs]
        assert sorted(result['status'] for result in results) == ['completed', 'failed']
        assert delete.call_count == 1
        assert store.get_confirmation(cid).status == 'approved'
        assert [layer.layer_id for layer in store.get_project(pid).layers] == ['hu']

    def test_cancel_before_confirmed_tool_never_deletes(self):
        runtime, store, pid = self.setup_project()
        planned = self.request(runtime, pid)
        execute = runtime.session_engine.tool_executor.execute
        def cancel_then_execute(*args, **kwargs):
            from backend.app.services.interaction_run import current_run
            runtime.interaction_operations.cancel(current_run().job_id)
            return execute(*args, **kwargs)
        with patch.object(runtime.session_engine.tool_executor, 'execute', side_effect=cancel_then_execute):
            result = self.wait_for_job(runtime, runtime.confirm_assistant_action(planned['result']['confirmation_id'])['job_id'])
        assert len(store.get_project(pid).layers) == 3
        assert result['status'] == 'failed' or result['result'].get('outcome') == 'cancelled'

    def test_confirmation_inherits_planning_usage(self):
        runtime, store, pid = self.setup_project()
        planned = self.request(runtime, pid)
        store.update_job_activity(planned['job_id'], usage={'model_calls': 2, 'input_tokens': 120, 'output_tokens': 40,
            'model_ms': 1234, 'elapsed_ms': 1800, 'route': 'agent', 'search_calls': 1, 'search_ms': 123})
        result = self.wait_for_job(runtime, runtime.confirm_assistant_action(planned['result']['confirmation_id'])['job_id'])
        assert result['usage']['model_calls'] == 2
        assert result['usage']['input_tokens'] == 120
        assert result['usage']['route'] == 'agent'
        assert result['usage']['search_calls'] == 1

    def test_model_layer_reference_uses_exact_unique_names(self):
        runtime, store, pid = self.setup_project()
        p = store.get_project(pid)
        assert runtime._resolve_interaction_layer(p, {'layer_name': '人口分布'}, {}).layer_id == 'pop'
        assert runtime._resolve_interaction_layer(p, {'layer_name': '不存在的人口分布'}, {}) is None
        store.upsert_layer(pid, LayerRecord.create(name='人口分布', kind='vector', source='test', geometry_type='Point'))
        assert runtime._resolve_interaction_layer(p, {'layer_name': '人口分布'}, {}) is None
        assert runtime._resolve_interaction_layer(p, {'layer_id': 'pop'}, {}).layer_id == 'pop'

    def test_expired_and_tampered_plan_do_not_delete(self):
        for tamper in (False, True):
            runtime, store, pid = self.setup_project()
            planned = self.request(runtime, pid)
            confirmation = store.get_confirmation(planned['result']['confirmation_id'])
            if tamper:
                confirmation.payload['frozen_plan']['actions'][0]['tool_params']['layer_ids'].append('hu')
            else:
                confirmation.expires_at = '2000-01-01T00:00:00+00:00'
            result = self.wait_for_job(runtime, runtime.confirm_assistant_action(confirmation.confirmation_id)['job_id'])
            assert result['status'] == 'failed'
            assert len(store.get_project(pid).layers) == 3
            assert confirmation.status == ('invalidated' if tamper else 'expired')

    def test_conflicting_delete_plan_is_blocked_before_any_action(self):
        for text in ('隐藏人口分布图层然后删除人口分布图层', '删除人口分布图层然后删除所有图层'):
            runtime, store, pid = self.setup_project()
            plan = runtime.assistant_service.plan_interaction_actions(text, store.get_project(pid))
            assessment = runtime.session_engine.tool_executor.assess('webgis', plan['actions'], assistant_mode='interaction', project_state={'project_id': pid})
            assert assessment['risk_level'] == 'blocked'
            assert not assessment['requires_confirmation']
            assert len(store.get_project(pid).layers) == 3
            assert next(layer for layer in store.get_project(pid).layers if layer.layer_id == 'pop').visible

    def test_delete_conflicts_use_same_active_layer_as_runtime(self):
        runtime, store, pid = self.setup_project()
        p = store.get_project(pid)
        p.active_layer_id = 'short'
        actions = [{'tool_name':'set_layer_opacity','tool_params':{'opacity':0.5}},
            {'tool_name':'delete_layers','tool_params':{'layer_ids':['pop']}}]
        assessment = runtime.session_engine.tool_executor.assess('webgis', actions, assistant_mode='interaction',
            project_state={'project_id':pid}, map_context={'active_layer_id':'pop'})
        assert assessment['risk_level'] == 'blocked'

    def test_delete_capability_contract(self):
        runtime,store,pid=self.setup_project()
        assert 'delete_layers' in {t['name'] for t in ASSISTANT_TOOL_SCHEMA}
        assert not tool_allowed('delete_layers','chat') and tool_allowed('delete_layers','operate')
        assessment=runtime.session_engine.tool_executor.assess('webgis',[{'tool_name':'delete_layers','tool_params':{'layer_ids':['pop']}}],assistant_mode='interaction',project_state={'project_id':pid})
        assert assessment['requires_confirmation'] and assessment['risk_level']=='high'
