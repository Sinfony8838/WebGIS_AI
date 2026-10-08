"""Service wiring only: store ownership/recovery and business logic stay in runtime."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Iterable

if TYPE_CHECKING:
    from .runtime import WebGISRuntime


@dataclass(frozen=True)
class RuntimeServiceFactories:
    """Explicit constructors supplied at bootstrap; preserve runtime's patch seams."""

    dataset: Callable[..., Any]
    template: Callable[..., Any]
    assistant: Callable[..., Any]
    knowledge: Callable[..., Any]
    knowledge_base: Callable[..., Any]
    one_map: Callable[..., Any]
    population_sources: Callable[..., Any]
    resource_search: Callable[..., Any]
    poi: Callable[..., Any]
    vision: Callable[..., Any]
    llm_client: Callable[..., Any]
    image_generation: Callable[..., Any]
    teaching_maps: Callable[..., Any]
    planner: Callable[..., Any]
    session: Callable[..., Any]
    workflow: Callable[..., Any]
    timeline: Callable[..., Any]
    voice_asr: Callable[..., Any]
    classroom: Callable[..., Any]


def assemble_runtime_services(
    runtime: WebGISRuntime,
    factories: RuntimeServiceFactories,
    interrupted_workflow_ids: Iterable[str],
) -> None:
    """Wire the existing services in their original startup and callback order."""
    runtime.dataset_service = factories.dataset(runtime.config, runtime.store)
    runtime.template_service = factories.template(runtime.config, runtime.store)
    runtime.assistant_service = factories.assistant(runtime.config)
    runtime.knowledge_service = factories.knowledge(runtime.config)
    runtime.knowledge_base_service = factories.knowledge_base(runtime.config)
    runtime.one_map_catalog_service = factories.one_map(runtime.config)
    runtime.population_source_registry_service = factories.population_sources(
        runtime.config,
        runtime.store,
        runtime.one_map_catalog_service,
        runtime.knowledge_base_service,
    )
    runtime.resource_search_service = factories.resource_search(runtime.config, runtime.knowledge_base_service)
    runtime.poi_service = factories.poi(runtime.config, runtime.store)
    runtime.vision_service = factories.vision(runtime.config, store=runtime.store)
    runtime.minimax_client = factories.llm_client(runtime.config)
    runtime.image_generation_service = factories.image_generation(runtime.config)
    runtime.teaching_map_service = factories.teaching_maps(runtime.config, runtime.store)
    runtime.assistant_service.teaching_map_service = runtime.teaching_map_service
    runtime.assistant_service.minimax_client = runtime.minimax_client
    runtime.llm_planner = factories.planner(runtime.minimax_client, runtime.assistant_service)
    runtime.session_engine = factories.session(
        runtime.config,
        runtime.store,
        runtime.llm_planner,
        runtime.assistant_service,
        runtime._execute_assistant_action,
        vision_service=runtime.vision_service,
    )
    runtime.session_engine.set_resource_search(runtime.resource_search_service)
    runtime.workflow_executor = factories.workflow(
        runtime.config,
        runtime.store,
        summary_callback=runtime._generate_workflow_summary,
    )
    for workflow_id in interrupted_workflow_ids:
        runtime.workflow_executor._write_workflow_files(runtime.store.get_workflow(workflow_id))
    runtime.timeline_service = factories.timeline(runtime.minimax_client)
    runtime.voice_asr = factories.voice_asr(runtime.config)
    # Preserve the existing asynchronous ONNX warm-up and its position in bootstrap.
    runtime.voice_asr.warm_up()
    runtime.classroom = factories.classroom(runtime)
    runtime.session_engine.set_session_stats_provider(runtime._session_statistics_for_assistant)
