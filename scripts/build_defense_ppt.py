# -*- coding: utf-8 -*-
"""Build a defense PPT from the project proposal and the provided style sample.

This script intentionally uses only Python's standard library. The local
environment does not have python-pptx installed, so we preserve the sample
PPTX package and replace editable slide text at the OOXML level.
"""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
MATERIALS = ROOT / "docs" / "defense_ppt_materials"
SAMPLE = MATERIALS / "sample_style.pptx"
OUT = ROOT / "docs" / "GeoBot_WebGIS_AI_答辩PPT.pptx"
OUTLINE = MATERIALS / "defense_ppt_outline.md"

P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
CP_NS = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
DC_NS = "http://purl.org/dc/elements/1.1/"

ET.register_namespace("p", P_NS)
ET.register_namespace("a", A_NS)
ET.register_namespace("r", R_NS)
ET.register_namespace("cp", CP_NS)
ET.register_namespace("dc", DC_NS)


SLIDES: list[list[str]] = [
    [
        "2026-5",
        "GeoBot WebGIS-AI",
        "面向地理课堂的",
        "实时交互地图演示",
        "与智能助教",
        "负责人：张程祎",
        "指导教师：李治洪",
        "地理科学学院｜地理信息科学",
    ],
    [
        "目录",
        "01",
        "项目背景与定位",
        "02",
        "总体目标与技术路线",
        "03",
        "已取得进展",
        "04",
        "后续计划与预期成果",
    ],
    ["项目背景与定位", "01", "面向课堂实时地图交互"],
    [
        "01 项目背景与定位",
        "项目目标",
        "降低 GIS 使用门槛，让教师在课堂中完成地图观察、讲解与分析。",
        "课堂真实痛点",
        "地理课堂更需要即时、可视、可操作的大屏地图演示。",
        "产品定位",
        "面向地理课堂的 WebGIS 实时交互系统。",
    ],
    [
        "01 新产品定位",
        "单教师本机部署",
        "面向课堂大屏，不依赖云端协同。",
        "全屏地图主舞台",
        "控件以浅灰透明面板环绕四周，减少遮挡。",
        "智能助教悬浮",
        "支持读图讲解、辅助制图、检索和课堂提问。",
        "后台 GIS 分析",
        "通过工作流封装常用空间分析任务，不干扰课堂主界面。",
    ],
    [
        "01 拟解决的关键问题",
        "自然语言如何稳定转成地图动作？",
        "当前地图画面如何被 AI 理解并讲解？",
        "教师资料如何沉淀为可检索知识库？",
        "地图交互与后台分析如何形成闭环？",
        "系统如何保证本地可用、可控、可演示？",
    ],
    ["总体目标与技术路线", "02", "WebGIS 课堂模式 + 后台 GIS 工作流 + MiniMax 助教"],
    [
        "02 总体架构",
        "课堂模式",
        "React + TypeScript + Vite + OpenLayers 构建全屏 WebGIS。",
        "后端运行时",
        "FastAPI 本地服务，管理项目、图层、任务流和 artifact。",
        "AI 助教",
        "MiniMax 文本规划优先，规则引擎兜底，输出讲解或地图动作。",
        "后台工作流",
        "封装分析、统计、导出和任务状态推送能力。",
    ],
    [
        "02 核心工作流",
        "教师输入",
        "自然语言、点击工具、上传数据或选择资料专题。",
        "系统感知",
        "当前视域、底图、可见图层、活动图层、截图与知识库命中。",
        "助教规划",
        "生成讲解型回复或白名单地图动作。",
        "地图执行",
        "切换底图、POI 检索、图层显隐、标注、测距、导出截图。",
        "成果沉淀",
        "课堂截图、讲解稿、查询摘要进入课堂产物。",
    ],
    ["已取得进展", "03", "原型系统已具备可运行课堂闭环"],
    [
        "03 前端课堂页进展",
        "课堂大屏界面已完成 v1.1 重构。",
        "地图全屏占主视口，控件轻量悬浮。",
        "左侧课堂控制台：资料、图层、检索、产物。",
        "右侧地图工具：选择、标注、测距、绘区、清除、缩放。",
        "助教升级为圆球/浮窗双态，可缩小、拖动、展开对话。",
    ],
    [
        "03 后端与 AI 进展",
        "FastAPI 运行时已具备项目、图层、任务、artifact、SSE 状态流。",
        "已接入 MiniMax 文本助教：模型规划失败时自动规则兜底。",
        "读图理解升级为截图 + map_context 双通道。",
        "视觉 MCP 未配置时，系统明确回退到结构化地图上下文讲解。",
    ],
    [
        "03 数据与知识库进展",
        "知识库面板已接入课堂页。",
        "支持可视化检索、条目编辑、活动图层一键关联。",
        "已整理资料：人口普查 3 条、气候区划 3 条、系统示例 1 条。",
        "世界柯本气候图作为可显示影像层保留。",
        "原占位专题包已清空，等待正式教案后重建。",
    ],
    [
        "03 创新点与后台 GIS 工作流",
        "WebGIS 主课堂 + 智能助教 + 后台分析工作流。",
        "教师在地图界面中完成观察、检索、分析和导出。",
        "任务流通过后端统一管理，前端可观察进度与结果。",
        "白名单工具覆盖图层控制、查询、统计、样式和地图导出。",
        "高风险能力默认不暴露，保证课堂系统安全可控。",
    ],
    ["后续计划与预期成果", "04", "围绕课堂可用性、正式教案与示范应用继续推进"],
    [
        "04 后续计划",
        "5-6月：稳定课堂模式与知识库。",
        "完善地图显示、截图导出、资料检索和交互细节。",
        "7-8月：重建专题教学模板。",
        "结合正式教案导入人口、气候、区域案例。",
        "9-10月：完善 GIS 分析工作流。",
        "扩展分析、样式、导出和错误提示。",
        "11月以后：课堂试用、反馈迭代、报告与软著材料。",
    ],
    [
        "04 预期成果",
        "一套 WebGIS-AI 原型系统。",
        "一批可复用地理教学数据与知识库条目。",
        "若干课堂演示案例：人口、气候、区位、读图。",
        "系统测试报告与教师使用说明。",
        "项目总结报告、论文或课程研究成果。",
        "软件著作权申请材料。",
    ],
    [
        "答辩重点",
        "项目计划",
        "面向地理课堂实时 WebGIS 系统。",
        "已取得进展",
        "前端大屏、后端运行时、MiniMax 助教、知识库和后台 GIS 工作流均已完成基础闭环。",
        "下一步",
        "以正式教案驱动专题模板和课堂案例建设。",
    ],
    ["谢谢！", "欢迎批评指正", "GeoBot WebGIS-AI"],
]


def remove_pictures(root: ET.Element) -> None:
    """Remove template pictures so old sample project visuals do not mislead."""

    for parent in root.iter():
        for child in list(parent):
            if child.tag == f"{{{P_NS}}}pic":
                parent.remove(child)


def replace_slide_text(xml_bytes: bytes, texts: list[str]) -> bytes:
    root = ET.fromstring(xml_bytes)
    remove_pictures(root)
    text_nodes = root.findall(f".//{{{A_NS}}}t")

    for index, node in enumerate(text_nodes):
        node.text = texts[index] if index < len(texts) else ""

    return b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + ET.tostring(
        root, encoding="utf-8"
    )


def replace_core_props(xml_bytes: bytes) -> bytes:
    root = ET.fromstring(xml_bytes)
    title = root.find(f".//{{{DC_NS}}}title")
    if title is not None:
        title.text = "GeoBot WebGIS-AI 答辩PPT"
    return b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + ET.tostring(
        root, encoding="utf-8"
    )


def build_pptx() -> None:
    if not SAMPLE.exists():
        raise FileNotFoundError(f"Missing sample template: {SAMPLE}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SAMPLE, OUT)

    temp_out = OUT.with_suffix(".tmp.pptx")
    with zipfile.ZipFile(OUT, "r") as zin, zipfile.ZipFile(
        temp_out, "w", compression=zipfile.ZIP_DEFLATED
    ) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename.startswith("ppt/slides/slide") and info.filename.endswith(".xml"):
                stem = Path(info.filename).stem
                try:
                    slide_number = int(stem.replace("slide", ""))
                except ValueError:
                    slide_number = 0
                if 1 <= slide_number <= len(SLIDES):
                    data = replace_slide_text(data, SLIDES[slide_number - 1])
            elif info.filename == "docProps/core.xml":
                data = replace_core_props(data)
            zout.writestr(info, data)

    temp_out.replace(OUT)


def write_outline() -> None:
    lines = ["# GeoBot WebGIS-AI 答辩PPT内容大纲", ""]
    for index, slide in enumerate(SLIDES, start=1):
        lines.append(f"## {index}. {slide[0] if slide else '空白页'}")
        for item in slide[1:]:
            lines.append(f"- {item}")
        lines.append("")
    OUTLINE.write_text("\n".join(lines), encoding="utf-8")


def verify_package() -> None:
    with zipfile.ZipFile(OUT, "r") as zf:
        slide_files = sorted(
            name
            for name in zf.namelist()
            if name.startswith("ppt/slides/slide") and name.endswith(".xml")
        )
    if len(slide_files) != len(SLIDES):
        raise RuntimeError(f"Expected {len(SLIDES)} slides, found {len(slide_files)}")


def main() -> None:
    build_pptx()
    write_outline()
    verify_package()
    print(f"Built: {OUT}")
    print(f"Outline: {OUTLINE}")


if __name__ == "__main__":
    main()
