"""人口 Demo 智能交互规划（planner）覆盖矩阵与回归测试。

本文件是“已注册工具 — 规则规划覆盖 — 参数是否齐全 — 是否可真实执行”
矩阵的可执行版本：§A/§B 用自然中文语句直接驱动
``AssistantService.plan_interaction_actions``，§C 用真实 Runtime 验证规划
结果能通过 ToolExecutor 的校验/权限门并被顺序执行。

== 覆盖矩阵（interaction 模式规则层） ==

| 工具                | 成功路径（示例语句）                     | 参数不足 → 行为                 | 不支持 / 不可执行 → 行为            |
|---------------------|------------------------------------------|--------------------------------|-------------------------------------|
| switch_basemap      | 切换到夜光/人口密度/天气/降水/影像底图    | “切换到底图”→ 交 LLM           | 未知底图名 → 交 LLM（执行器兜底拒绝）|
| toggle_layer        | 显示/隐藏/关闭/叠加 胡焕庸线、400毫米线   | “显示图层”→ 一次澄清           | 图层未加载 → 一次澄清（不假装执行） |
| reorder_layer       | 置顶 / 移到最上层 / 最下面                | 指定图层不存在 → 一次澄清      | —                                   |
| set_layer_opacity   | 半透明 / 80% / 百分之三十                 | 无数值 → 问一次数值            | 图层不存在 → 确认目标（不得改活动图层）|
| set_view            | 定位到上海 / 转到西北地区 / 看看东南沿海  | —                              | 未收录地名 → 交 LLM 地理编码        |
| focus_layer         | 定位到人口分布图层                        | 图层不存在 → 一次澄清          | —                                   |
| switch_view_mode    | 三维地球 / 二维平面                       | —                              | “四维”→ 无动作                      |
| open_panel          | 图层/数据库/工作流 面板，打开与收起        | “打开面板”→ 一次澄清           | —                                   |
| run_workflow        | 人口分级设色 / 胡焕庸线对比 / 字段分级     | “做个分析”→ 列三类问一次       | 非白名单（缓冲区）→ 不产出动作      |
| enter_lesson_stage  | 下一环节 / 上一环节 / 进入“X”环节          | —                              | 无进行中班课 → 执行器阻断（§C）     |
| start_class_session | 开始上课                                  | —                              | 已有班课 → 执行器阻断               |
| end_class_session   | 结束上课（话术明确要求确认）               | —                              | 高风险：执行器要求确认（§C）        |
| apply_template      | 打开人口分布图（模板/多步第一步）          | —                              | —                                   |
| explain_current_view| 解释/为什么子句（含多步最后一步）          | —                              | —                                   |
| style_layer         | 把人口分布图层改成红色（经继承语音规则）   | —                              | —                                   |
| run_visual_query    | 查一下人口前10的城市（经继承语音规则）     | 非人口/非城市 → 不产出         | —                                   |

== 规则层明确不覆盖（交 LLM 完整规划或属于其他模式，不允许假装支持） ==

* query_features、draw_annotation、measure、export_snapshot、search_poi：
  interaction 规则层不产出，语音/文本中交给 MiniMax planner 规划。
* toggle_teaching_map / open_material / generate_image / record_observation /
  launch_question：不属于 interaction 模式可见工具（执行器阻断），在
  teaching/tool 模式由 plan_actions 规划，见 test_assistant.py。
* 多步分解边界：面板、班课开始/结束、环节推进不参与确定性顺序分解
  （保留“复合面板指令交 LLM 整体规划”的既有回归约束）；分解中任何一步
  无法确定时整体放弃，交 LLM，绝不输出部分计划。
* 天气底图是否真正可用由天气任务负责：本层只负责正确识别“天气/降水”
  并规划 switch_basemap。
"""
from __future__ import annotations

import json
import unittest

from backend.app.config import AppConfig
from backend.app.models import LayerRecord, ProjectRecord
from backend.app.services.assistant import ASSISTANT_TOOL_SCHEMA, AssistantService
from backend.tests.test_assistant import FakeTeachingMapService
from backend.tests.test_voice_tools import FakeLLM
from backend.tests import test_voice_tools as voice_tests


def build_project(with_line_layers: bool = True) -> ProjectRecord:
    """人口 Demo 课中项目：人口分布（活动图层）+ 可选的两条教学线要素。"""
    project = ProjectRecord.create(base_map=AppConfig().default_basemap())
    layers = [
        LayerRecord.create(
            layer_id="lyr_pop",
            name="人口分布",
            kind="vector",
            source="builtin",
            geometry_type="Polygon",
            visible=True,
        ),
    ]
    if with_line_layers:
        layers.insert(0, LayerRecord.create(
            layer_id="lyr_hu_line", name="胡焕庸线", kind="vector", source="builtin",
            geometry_type="LineString", visible=True,
        ))
        layers.insert(1, LayerRecord.create(
            layer_id="lyr_400mm", name="400毫米年降水量线（1991—2020）", kind="vector", source="builtin",
            geometry_type="LineString", visible=True,
        ))
    project.layers = layers
    project.active_layer_id = "lyr_pop"
    return project


class PlannerCoverageTest(unittest.TestCase):
    """§A 成功路径、§B 参数不足/不支持路径 —— 全部走确定性规则层。"""

    def setUp(self) -> None:
        self.service = AssistantService(AppConfig())

    # ------------------------------------------------------------------
    # §A 成功路径：自然中文操控语句 → 顺序正确的动作
    # ------------------------------------------------------------------

    def test_a_view_mode_and_basemap_commands(self) -> None:
        project = build_project()
        cases = [
            ("切换到三维地球", "switch_view_mode", {"mode": "globe"}),
            ("帮我把地图切回二维平面", "switch_view_mode", {"mode": "plane"}),
            ("切换到夜光底图", "switch_basemap", {"basemap_id": "nasa_nightlights_2016"}),
            ("切换到人口密度底图", "switch_basemap", {"basemap_id": "nasa_population_2020"}),
            ("切换到天气地图", "switch_basemap", {"basemap_id": "weather_precipitation"}),
            ("切换到降水底图", "switch_basemap", {"basemap_id": "weather_precipitation"}),
            ("把底图换成影像", "switch_basemap", {"basemap_id": "amap_imagery"}),
        ]
        for text, tool, params in cases:
            with self.subTest(text=text):
                plan = self.service.plan_interaction_actions(text, project, {})
                self.assertEqual([item["tool_name"] for item in plan["actions"]], [tool])
                self.assertEqual(plan["actions"][0]["tool_params"], params)

    def test_a_line_layer_toggle_commands(self) -> None:
        project = build_project()
        cases = [
            ("显示胡焕庸线", "lyr_hu_line", True),
            ("显示胡焕庸线图层", "lyr_hu_line", True),
            ("关闭胡焕庸线图层", "lyr_hu_line", False),
            ("显示400毫米等降水量线", "lyr_400mm", True),
            ("叠加400毫米等降水量线", "lyr_400mm", True),
            ("隐藏400毫米等降水量线", "lyr_400mm", False),
        ]
        for text, layer_id, visible in cases:
            with self.subTest(text=text):
                plan = self.service.plan_interaction_actions(text, project, {})
                self.assertEqual([item["tool_name"] for item in plan["actions"]], ["toggle_layer"])
                self.assertEqual(plan["actions"][0]["tool_params"], {"layer_id": layer_id, "visible": visible})

    def test_a_opacity_reorder_focus_commands(self) -> None:
        project = build_project()
        opacity = self.service.plan_interaction_actions("把人口分布图层调到半透明", project, {})
        self.assertEqual(opacity["actions"][0]["tool_name"], "set_layer_opacity")
        self.assertEqual(opacity["actions"][0]["tool_params"], {"layer_id": "lyr_pop", "opacity": 0.5})

        percent = self.service.plan_interaction_actions("透明度调到30%", project, {})
        self.assertEqual(percent["actions"][0]["tool_params"]["opacity"], 0.3)

        chinese_percent = self.service.plan_interaction_actions("把胡焕庸线图层透明度调到百分之八十", project, {})
        self.assertEqual(chinese_percent["actions"][0]["tool_params"], {"layer_id": "lyr_hu_line", "opacity": 0.8})

        to_top = self.service.plan_interaction_actions("把胡焕庸线图层移到最上层", project, {})
        self.assertEqual(to_top["actions"][0]["tool_name"], "reorder_layer")
        self.assertEqual(to_top["actions"][0]["tool_params"], {"layer_id": "lyr_hu_line", "z_index": 10})

        to_bottom = self.service.plan_interaction_actions("把400毫米等降水量线图层置底移到最下面", project, {})
        self.assertEqual(to_bottom["actions"][0]["tool_params"]["layer_id"], "lyr_400mm")
        self.assertLess(to_bottom["actions"][0]["tool_params"]["z_index"], 0)

        focus = self.service.plan_interaction_actions("定位到人口分布图层", project, {})
        self.assertEqual(focus["actions"][0]["tool_name"], "focus_layer")
        self.assertEqual(focus["actions"][0]["tool_params"], {"layer_id": "lyr_pop"})

    def test_a_region_view_and_panel_commands(self) -> None:
        project = build_project()
        shanghai = self.service.plan_interaction_actions("定位到上海", project, {})
        self.assertEqual(shanghai["actions"][0]["tool_name"], "set_view")
        self.assertEqual(shanghai["actions"][0]["tool_params"]["center"], [121.47, 31.23])
        self.assertEqual(shanghai["actions"][0]["tool_params"]["zoom"], 8)

        northwest = self.service.plan_interaction_actions("转到西北地区", project, {})
        self.assertEqual(northwest["actions"][0]["tool_params"]["extent"], [73.0, 32.0, 112.0, 50.0])

        coast = self.service.plan_interaction_actions("看看东南沿海", project, {})
        self.assertEqual(coast["actions"][0]["tool_name"], "set_view")

        panels = [
            ("打开图层管理器", "layers", True),
            ("打开数据库面板", "database", True),
            ("打开工作流坞", "workflow", True),
            ("收起数据库面板", "database", False),
        ]
        for text, panel, open_state in panels:
            with self.subTest(text=text):
                plan = self.service.plan_interaction_actions(text, project, {})
                self.assertEqual([item["tool_name"] for item in plan["actions"]], ["open_panel"])
                self.assertEqual(plan["actions"][0]["tool_params"], {"panel": panel, "open": open_state})

    def test_a_workflow_stage_and_session_commands(self) -> None:
        project = build_project()
        workflows = [
            ("做一个人口分级设色分析", "population_choropleth"),
            ("运行胡焕庸线对比", "hu_line_compare"),
            ("对人口数据做字段分级", "classify_field"),
        ]
        for text, template_id in workflows:
            with self.subTest(text=text):
                plan = self.service.plan_interaction_actions(text, project, {})
                self.assertEqual([item["tool_name"] for item in plan["actions"]], ["run_workflow"])
                self.assertEqual(plan["actions"][0]["tool_params"], {"template_id": template_id})

        self.assertEqual(
            self.service.plan_interaction_actions("进入下一环节", project, {})["actions"][0]["tool_params"],
            {"offset": "next"},
        )
        self.assertEqual(
            self.service.plan_interaction_actions("回到上一环节", project, {})["actions"][0]["tool_params"],
            {"offset": "previous"},
        )
        titled = self.service.plan_interaction_actions("进入河流对城市的影响环节", project, {})
        self.assertEqual(titled["actions"][0]["tool_params"], {"stage_title": "河流对城市的影响"})

        start = self.service.plan_interaction_actions("开始上课", project, {})
        self.assertEqual([item["tool_name"] for item in start["actions"]], ["start_class_session"])
        end = self.service.plan_interaction_actions("结束上课", project, {})
        self.assertEqual([item["tool_name"] for item in end["actions"]], ["end_class_session"])
        # 高风险动作：话术必须明确要求确认；普通查看类不出现“确认”字样。
        self.assertIn("确认", end["assistant_message"])
        plain_view = self.service.plan_interaction_actions("定位到上海", project, {})
        self.assertNotIn("确认", plain_view["assistant_message"])

    def test_a_inherited_style_and_visual_query_commands(self) -> None:
        project = build_project()
        style = self.service.plan_interaction_actions("把人口分布图层改成红色", project, {})
        self.assertEqual([item["tool_name"] for item in style["actions"]], ["style_layer"])
        self.assertEqual(style["actions"][0]["tool_params"]["style"]["fillColor"], "#ef4444")

        visual = self.service.plan_interaction_actions("查一下人口前10的城市", project, {})
        self.assertEqual([item["tool_name"] for item in visual["actions"]], ["run_visual_query"])
        self.assertEqual(visual["actions"][0]["tool_params"]["operation"], "top")

    def test_a_multi_step_commands_keep_action_order(self) -> None:
        project = build_project()
        demo = self.service.plan_interaction_actions(
            "打开人口分布图，定位西北地区，然后解释为什么人口较稀疏。", project, {}
        )
        self.assertEqual(
            [item["tool_name"] for item in demo["actions"]],
            ["apply_template", "set_view", "explain_current_view"],
        )
        self.assertEqual(demo["actions"][0]["tool_params"], {"template_id": "population_distribution"})
        self.assertEqual(demo["actions"][1]["tool_params"]["extent"], [73.0, 32.0, 112.0, 50.0])
        self.assertIn("人口较稀疏", demo["actions"][2]["tool_params"]["focus"])

        night = self.service.plan_interaction_actions("切换到夜光底图，然后定位到上海", project, {})
        self.assertEqual(
            [item["tool_name"] for item in night["actions"]],
            ["switch_basemap", "set_view"],
        )
        self.assertEqual(night["actions"][0]["tool_params"]["basemap_id"], "nasa_nightlights_2016")
        self.assertEqual(night["actions"][1]["tool_params"]["center"], [121.47, 31.23])

        toggle_then_opacity = self.service.plan_interaction_actions(
            "显示胡焕庸线，然后把人口分布图层调到半透明", project, {}
        )
        self.assertEqual(
            [item["tool_name"] for item in toggle_then_opacity["actions"]],
            ["toggle_layer", "set_layer_opacity"],
        )

        three_steps = self.service.plan_interaction_actions(
            "切换到三维地球，然后转到西北地区，最后解释西北人口为什么稀疏", project, {}
        )
        self.assertEqual(
            [item["tool_name"] for item in three_steps["actions"]],
            ["switch_view_mode", "set_view", "explain_current_view"],
        )
        self.assertEqual(three_steps["actions"][0]["tool_params"], {"mode": "globe"})

        analysis_first = self.service.plan_interaction_actions(
            "先做一个人口分级设色分析，然后转到长三角", project, {}
        )
        self.assertEqual(
            [item["tool_name"] for item in analysis_first["actions"]],
            ["run_workflow", "set_view"],
        )

    # ------------------------------------------------------------------
    # §B 参数不足 → 一次简短具体的澄清；不支持 → 诚实无动作
    # ------------------------------------------------------------------

    def test_b_missing_params_ask_one_specific_clarification(self) -> None:
        project = build_project()
        plain = build_project(with_line_layers=False)
        cases = [
            (project, "调整图层透明度", "透明度"),
            (project, "做个分析", "三类分析"),
            (project, "打开面板", "哪个面板"),
            (project, "显示图层", "哪个图层"),
            (plain, "显示胡焕庸线", "胡焕庸线图层"),
            (plain, "显示400毫米等降水量线", "导入"),
            (project, "定位到火星矿产图层", "火星矿产"),
            (project, "把火星矿产图层置顶", "火星矿产"),
        ]
        for ctx_project, text, hint in cases:
            with self.subTest(text=text):
                plan = self.service.plan_interaction_actions(text, ctx_project, {})
                self.assertEqual(plan["actions"], [])
                self.assertTrue(plan.get("stop_planning"), "澄清应由规则层直接作答，不再打扰 LLM")
                self.assertIn(hint, plan["assistant_message"])
                self.assertIn("？", plan["assistant_message"])

    def test_b_opacity_without_value_never_mutates_active_layer(self) -> None:
        project = build_project()
        plan = self.service.plan_interaction_actions("请把不存在的火星矿产图层调到半透明", project, {})
        self.assertEqual(plan["actions"], [])
        self.assertEqual(project.layers[0].opacity, 1.0)

    def test_b_unsupported_requests_return_no_action(self) -> None:
        project = build_project()
        cases = [
            "做一个缓冲区分析",       # 工作流白名单之外
            "把当前地图变成热力图",   # 无对应工具
            "切换到四维空间",         # 视图模式取值不支持
            "刚才说切换到三维地球",   # 转述/时秽指令不得执行
            "比如打开图层管理器",     # 举例不是命令
        ]
        for text in cases:
            with self.subTest(text=text):
                plan = self.service.plan_interaction_actions(text, project, {})
                self.assertEqual(plan["actions"], [])
                for marker in ("已执行", "已切换", "已打开", "已提交"):
                    self.assertNotIn(marker, plan["assistant_message"])

    def test_b_negation_keeps_current_state(self) -> None:
        project = build_project()
        plan = self.service.plan_interaction_actions("不要切换到三维地球", project, {})
        self.assertEqual(plan["actions"], [])
        self.assertTrue(plan.get("stop_planning"))


class PlannerExecutionGateTest(unittest.TestCase):
    """§C 矩阵“是否可真实执行”列：规划结果必须通过执行器校验/权限门。"""

    build_runtime = voice_tests.InteractionToolsTest.build_runtime
    wait_for_job = voice_tests.InteractionToolsTest.wait_for_job
    start_session = voice_tests.InteractionToolsTest.start_session
    teaching_context = voice_tests.InteractionToolsTest.teaching_context

    def _plan(self, runtime, text: str, project_id: str, map_context: dict | None = None) -> dict:
        return runtime.assistant_service.plan_interaction_actions(
            text, runtime.store.get_project(project_id), map_context or {}
        )

    def test_viewing_plans_pass_executor_without_confirmation(self) -> None:
        runtime, _store, project_id = self.build_runtime()
        executor = runtime.session_engine.tool_executor
        for text in ("定位到上海", "切换到三维地球", "打开图层管理器", "显示胡焕庸线"):
            with self.subTest(text=text):
                runtime.store.upsert_layer(
                    project_id,
                    LayerRecord(layer_id="lyr_hu_line", name="胡焕庸线", kind="geojson", source="builtin", geometry_type="LineString"),
                )
                plan = self._plan(runtime, text, project_id)
                assessment = executor.assess("webgis", plan["actions"], assistant_mode="interaction")
                self.assertNotEqual(assessment["risk_level"], "blocked", assessment)
                self.assertFalse(assessment["requires_confirmation"], "普通地图查看不得引入确认")

    def test_end_class_plan_is_gated_by_confirmation(self) -> None:
        runtime, _store, project_id = self.build_runtime()
        session_id = self.start_session(runtime, project_id)
        plan = self._plan(runtime, "结束上课", project_id)
        assessment = runtime.session_engine.tool_executor.assess(
            "webgis",
            plan["actions"],
            assistant_mode="interaction",
            map_context={"teaching_context": self.teaching_context(session_id=session_id, phase="in_class")},
        )
        self.assertEqual(assessment["risk_level"], "high")
        self.assertTrue(assessment["requires_confirmation"])

    def test_stage_plan_blocked_without_running_session(self) -> None:
        runtime, _store, project_id = self.build_runtime()
        plan = self._plan(runtime, "进入下一环节", project_id)
        assessment = runtime.session_engine.tool_executor.assess(
            "webgis",
            plan["actions"],
            assistant_mode="interaction",
            map_context={"teaching_context": self.teaching_context(phase="course_prep")},
        )
        self.assertEqual(assessment["risk_level"], "blocked")
        self.assertIn("班课", assessment["actions_planned"][0]["validation_error"])

    def test_multi_step_demo_executes_in_order_without_llm(self) -> None:
        runtime, _store, project_id = self.build_runtime()
        fake = FakeLLM()
        runtime.session_engine.tool_planner.llm_planner.minimax_client = fake
        job = self.wait_for_job(runtime, runtime.submit_assistant_message(
            project_id,
            "打开人口分布图，定位西北地区，然后解释为什么人口较稀疏。",
            assistant_mode="interaction",
            input_mode="voice",
            map_context={"center": [104.0, 35.0], "zoom": 4, "extent": [78.0, 18.0, 132.0, 50.5]},
        )["job_id"])
        result = job["result"]
        self.assertEqual(result["planner"], "interaction_rule")
        self.assertEqual(fake.calls, 0)
        executed = [item["action"]["tool_name"] for item in result["actions_executed"]]
        self.assertEqual(executed, ["apply_template", "set_view", "explain_current_view"])

    def test_clarification_answers_directly_and_executes_nothing(self) -> None:
        runtime, _store, project_id = self.build_runtime()
        fake = FakeLLM()
        runtime.session_engine.tool_planner.llm_planner.minimax_client = fake
        for text, hint in (("调整图层透明度", "透明度"), ("做个分析", "三类分析")):
            with self.subTest(text=text):
                job = self.wait_for_job(runtime, runtime.submit_assistant_message(
                    project_id, text, assistant_mode="interaction", input_mode="voice"
                )["job_id"])
                result = job["result"]
                self.assertEqual(result["actions_executed"], [])
                self.assertEqual(fake.calls, 0, "参数不足的澄清应由规则层直接作答")
                self.assertIn(hint, result["assistant_message"])
                self.assertIn("？", result["assistant_message"])

    def test_line_toggle_executes_when_layer_loaded_and_clarifies_when_missing(self) -> None:
        runtime, store, project_id = self.build_runtime()
        job = self.wait_for_job(runtime, runtime.submit_assistant_message(
            project_id, "显示400毫米等降水量线", assistant_mode="interaction", input_mode="voice"
        )["job_id"])
        self.assertEqual(job["result"]["actions_executed"], [])
        self.assertIn("导入", job["result"]["assistant_message"])

        store.upsert_layer(
            project_id,
            LayerRecord(
                layer_id="lyr_400mm",
                name="400毫米年降水量线（1991—2020）",
                kind="geojson",
                source="builtin",
                geometry_type="LineString",
                visible=False,
            ),
        )
        job = self.wait_for_job(runtime, runtime.submit_assistant_message(
            project_id, "显示400毫米等降水量线", assistant_mode="interaction", input_mode="voice"
        )["job_id"])
        executed = job["result"]["actions_executed"]
        self.assertEqual([item["action"]["tool_name"] for item in executed], ["toggle_layer"])
        self.assertEqual(executed[0]["action"]["tool_params"], {"layer_id": "lyr_400mm", "visible": True})
        layer = next(l for l in store.get_project(project_id).layers if l.layer_id == "lyr_400mm")
        self.assertTrue(layer.visible)


class PlannerRuleCoverageMatrixTest(unittest.TestCase):
    """矩阵完整性：interaction 可见工具必须全部落在“规则覆盖”或“明确清单”之一。"""

    RULE_REACHABLE_TOOLS = {
        "set_view", "toggle_layer", "reorder_layer", "style_layer",
        "apply_template", "explain_current_view", "switch_basemap",
        "run_visual_query", "switch_view_mode", "open_panel", "focus_layer",
        "set_layer_opacity", "enter_lesson_stage", "run_workflow",
        "start_class_session", "end_class_session",
    }
    # 规则层刻意不产出、交给 LLM 完整规划（或属于其他模式）的能力。
    RULE_ESCALATED_TOOLS = {
        "query_features", "draw_annotation", "measure", "export_snapshot", "search_poi",
    }

    def test_every_interaction_tool_is_classified(self) -> None:
        interaction_tools = {
            tool["name"] for tool in ASSISTANT_TOOL_SCHEMA if "interaction" in tool.get("modes", [])
        }
        overlap = self.RULE_REACHABLE_TOOLS & self.RULE_ESCALATED_TOOLS
        self.assertEqual(overlap, set())
        self.assertEqual(
            self.RULE_REACHABLE_TOOLS | self.RULE_ESCALATED_TOOLS,
            interaction_tools,
            "每个 interaction 可见工具都必须有明确的覆盖结论，不允许‘后续完善’式含糊",
        )


if __name__ == "__main__":
    unittest.main()
