"""Synthetic constructor boundaries; no providers, workers, auth DB or model warm-up."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from backend.app import runtime as runtime_module
from backend.app.runtime_assembly import RuntimeServiceFactories


FACTORIES = {
    "dataset": "DatasetService",
    "template": "TemplateService",
    "assistant": "AssistantService",
    "knowledge": "KnowledgeService",
    "knowledge_base": "KnowledgeBaseService",
    "one_map": "OneMapCatalogService",
    "population_sources": "PopulationSourceRegistryService",
    "resource_search": "ResourceSearchService",
    "poi": "PoiService",
    "vision": "MapVisionService",
    "llm_client": "build_llm_client",
    "image_generation": "MiniMaxImageClient",
    "teaching_maps": "TeachingMapService",
    "planner": "LLMPlanner",
    "session": "AssistantSessionEngine",
    "workflow": "WorkflowExecutor",
    "timeline": "TimelineService",
    "voice_asr": "VoiceAsrEngine",
    "classroom": "ClassroomWorkflowRuntime",
}


@pytest.fixture
def wiring(monkeypatch):
    events = []
    values = {name: SimpleNamespace(name=name) for name in FACTORIES}
    calls = {}
    bindings = {}
    mirrors = []
    values["session"].set_resource_search = lambda service: (
        events.append("bind_resource_search"), bindings.update(resource_search=service)
    )
    values["session"].set_session_stats_provider = lambda callback: (
        events.append("bind_stats"), bindings.update(stats=callback)
    )
    values["voice_asr"].warm_up = lambda: events.append("warm_up")
    values["workflow"]._write_workflow_files = lambda record: (
        events.append("mirror:" + record.workflow_id), mirrors.append(record)
    )
    config = SimpleNamespace(
        state_file="synthetic-unused-state-path",
        ensure_dirs=lambda: events.append("ensure_dirs"),
    )
    store = SimpleNamespace(
        close=Mock(side_effect=lambda: events.append("close")),
        get_workflow=Mock(side_effect=lambda workflow_id: SimpleNamespace(workflow_id=workflow_id)),
        reconcile_interrupted_tasks=Mock(side_effect=lambda: (
            events.append("reconcile") or {"jobs": ["job"], "workflows": ["interrupted"]}
        )),
    )
    def store_factory(path):
        assert path == config.state_file
        events.append("store")
        return store

    store_constructor = Mock(side_effect=store_factory)
    monkeypatch.setattr(runtime_module, "RuntimeStore", store_constructor)
    for name, symbol in FACTORIES.items():
        def construct(*args, _name=name, **kwargs):
            events.append(_name)
            calls[_name] = (args, kwargs)
            if _name == "planner":
                assert values["assistant"].teaching_map_service is values["teaching_maps"]
                assert values["assistant"].minimax_client is values["llm_client"]
            return values[_name]
        monkeypatch.setattr(runtime_module, symbol, construct)
    monkeypatch.setattr(runtime_module.WebGISRuntime, "_normalize_loaded_projects", lambda _: events.append("normalize"))
    return SimpleNamespace(events=events, values=values, calls=calls, bindings=bindings,
                           mirrors=mirrors, config=config, store=store, store_constructor=store_constructor)


@pytest.mark.parametrize("injected", [False, True])
def test_bootstrap_order_and_recovery_boundary(wiring, injected):
    t = wiring
    runtime = runtime_module.WebGISRuntime(t.config, store=t.store if injected else None)
    expected = ["ensure_dirs"] + ([] if injected else ["store", "reconcile"])
    expected += list(FACTORIES)[:15] + ["bind_resource_search", "workflow"]
    if not injected:
        expected += ["mirror:interrupted"]
    expected += ["timeline", "voice_asr", "warm_up", "classroom", "bind_stats", "normalize"]
    assert t.events == expected
    assert runtime.config is t.config and runtime.store is t.store
    assert t.store_constructor.call_count == (0 if injected else 1)
    assert t.store.reconcile_interrupted_tasks.call_count == (0 if injected else 1)
    t.store.close.assert_not_called()
    assert len(t.mirrors) == (0 if injected else 1)


def test_service_dependency_identity_and_existing_keyword_contracts(wiring):
    t = wiring
    runtime = runtime_module.WebGISRuntime(t.config, store=t.store)
    c, s, v = t.config, t.store, t.values
    for name in ["dataset", "template", "poi", "teaching_maps"]:
        assert t.calls[name] == ((c, s), {})
    for name in ["assistant", "knowledge", "knowledge_base", "one_map", "llm_client", "image_generation", "voice_asr"]:
        assert t.calls[name] == ((c,), {})
    assert t.calls["population_sources"] == ((c, s, v["one_map"], v["knowledge_base"]), {})
    assert t.calls["resource_search"] == ((c, v["knowledge_base"]), {})
    assert t.calls["vision"] == ((c,), {"store": s})
    assert t.calls["planner"] == ((v["llm_client"], v["assistant"]), {})
    session_args, session_kwargs = t.calls["session"]
    assert session_args[:4] == (c, s, v["planner"], v["assistant"])
    assert session_args[4].__self__ is runtime
    assert session_args[4].__func__ is runtime_module.WebGISRuntime._execute_assistant_action
    assert session_kwargs == {"vision_service": v["vision"]}
    workflow_args, workflow_kwargs = t.calls["workflow"]
    assert workflow_args == (c, s)
    assert workflow_kwargs["summary_callback"].__self__ is runtime
    assert workflow_kwargs["summary_callback"].__func__ is runtime_module.WebGISRuntime._generate_workflow_summary
    assert t.calls["timeline"] == ((v["llm_client"],), {})
    assert t.calls["classroom"] == ((runtime,), {})
    assert t.bindings["resource_search"] is v["resource_search"]
    assert t.bindings["stats"].__self__ is runtime
    assert t.bindings["stats"].__func__ is runtime_module.WebGISRuntime._session_statistics_for_assistant


@pytest.mark.parametrize("failure", [OSError("synthetic I/O"), RuntimeError("synthetic recovery"), KeyboardInterrupt()])
def test_fresh_recovery_failure_closes_before_any_service(wiring, failure):
    t = wiring
    t.store.reconcile_interrupted_tasks.side_effect = failure
    with pytest.raises(type(failure)):
        runtime_module.WebGISRuntime(t.config)
    t.store.close.assert_called_once_with()
    assert not t.calls
    assert t.events == ["ensure_dirs", "store", "close"]


@pytest.mark.parametrize("boundary", ["DatasetService", "MapVisionService", "WorkflowExecutor", "TimelineService"])
def test_original_runtime_constructor_patch_seams_remain_live(wiring, monkeypatch, boundary):
    t = wiring
    fail = Mock(side_effect=LookupError("synthetic constructor boundary"))
    monkeypatch.setattr(runtime_module, boundary, fail)
    with pytest.raises(LookupError, match="constructor boundary"):
        runtime_module.WebGISRuntime(t.config, store=t.store)
    fail.assert_called_once()
    assert "warm_up" not in t.events and "normalize" not in t.events
    # An injected store remains the caller's resource, including on constructor failure.
    t.store.close.assert_not_called()


def test_factory_bundle_is_explicit_and_immutable():
    factory = Mock()
    bundle = RuntimeServiceFactories(**{name: factory for name in FACTORIES})
    with pytest.raises(FrozenInstanceError):
        bundle.dataset = Mock()
    assert bundle.dataset is factory
