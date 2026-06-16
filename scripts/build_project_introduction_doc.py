# -*- coding: utf-8 -*-
"""Generate the GeoBot WebGIS-AI project introduction document.

The environment used for this project does not consistently provide
python-docx, so this builder writes a standards-compliant DOCX package with
Python's standard library only.
"""

from __future__ import annotations

import html
import zipfile
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
OUT_DOCX = DOCS / "GeoBot_WebGIS_AI_项目介绍书.docx"
OUT_MD = DOCS / "GeoBot_WebGIS_AI_项目介绍书.md"

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def esc(text: str) -> str:
    return html.escape(text, quote=False)


def r(text: str, *, bold: bool = False, color: str | None = None, size: int | None = None) -> str:
    props: list[str] = []
    props.append('<w:rFonts w:ascii="Microsoft YaHei" w:eastAsia="Microsoft YaHei" w:hAnsi="Microsoft YaHei"/>')
    if bold:
        props.append("<w:b/>")
    if color:
        props.append(f'<w:color w:val="{color}"/>')
    if size:
        props.append(f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>')
    rpr = f"<w:rPr>{''.join(props)}</w:rPr>"
    preserve = ' xml:space="preserve"' if text.startswith(" ") or text.endswith(" ") else ""
    return f"<w:r>{rpr}<w:t{preserve}>{esc(text)}</w:t></w:r>"


def p(
    text: str = "",
    *,
    style: str | None = None,
    bold: bool = False,
    color: str | None = None,
    size: int | None = None,
    align: str | None = None,
    before: int = 0,
    after: int = 120,
    line: int = 360,
) -> str:
    ppr: list[str] = []
    if style:
        ppr.append(f'<w:pStyle w:val="{style}"/>')
    if align:
        ppr.append(f'<w:jc w:val="{align}"/>')
    ppr.append(f'<w:spacing w:before="{before}" w:after="{after}" w:line="{line}" w:lineRule="auto"/>')
    return f"<w:p><w:pPr>{''.join(ppr)}</w:pPr>{r(text, bold=bold, color=color, size=size)}</w:p>"


def bullet(text: str) -> str:
    return p("• " + text, after=80)


def numbered(index: int, text: str) -> str:
    return p(f"{index}. {text}", after=80)


def heading(level: int, text: str) -> str:
    return p(text, style=f"Heading{level}", after=180)


def page_break() -> str:
    return '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'


def cell(text: str, *, shade: str | None = None, bold: bool = False) -> str:
    tc_pr = '<w:tcPr><w:tcMar><w:top w:w="120" w:type="dxa"/><w:left w:w="120" w:type="dxa"/><w:bottom w:w="120" w:type="dxa"/><w:right w:w="120" w:type="dxa"/></w:tcMar>'
    if shade:
        tc_pr += f'<w:shd w:fill="{shade}"/>'
    tc_pr += "</w:tcPr>"
    return f"<w:tc>{tc_pr}{p(text, bold=bold, after=60, line=320)}</w:tc>"


def table(rows: list[list[str]], *, header: bool = True) -> str:
    cols = max(len(row) for row in rows)
    grid = "".join('<w:gridCol w:w="2400"/>' for _ in range(cols))
    parts = [
        "<w:tbl>",
        '<w:tblPr><w:tblW w:w="0" w:type="auto"/><w:tblBorders>'
        '<w:top w:val="single" w:sz="6" w:space="0" w:color="B9C5D6"/>'
        '<w:left w:val="single" w:sz="6" w:space="0" w:color="B9C5D6"/>'
        '<w:bottom w:val="single" w:sz="6" w:space="0" w:color="B9C5D6"/>'
        '<w:right w:val="single" w:sz="6" w:space="0" w:color="B9C5D6"/>'
        '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="D8DEE8"/>'
        '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="D8DEE8"/>'
        "</w:tblBorders></w:tblPr>",
        f"<w:tblGrid>{grid}</w:tblGrid>",
    ]
    for i, row in enumerate(rows):
        parts.append("<w:tr>")
        for value in row:
            parts.append(cell(value, shade="DCEAF7" if header and i == 0 else None, bold=header and i == 0))
        parts.append("</w:tr>")
    parts.append("</w:tbl>")
    parts.append(p("", after=160))
    return "".join(parts)


def callout(title: str, body: str) -> str:
    return table([[title, body]], header=False).replace("<w:tblPr>", '<w:tblPr><w:tblStyle w:val="TableGrid"/>', 1)


def section_properties() -> str:
    return (
        "<w:sectPr>"
        '<w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1440" w:right="1260" w:bottom="1440" w:left="1260" w:header="720" w:footer="720" w:gutter="0"/>'
        "</w:sectPr>"
    )


def styles_xml() -> str:
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{W_NS}">
  <w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Microsoft YaHei" w:eastAsia="Microsoft YaHei" w:hAnsi="Microsoft YaHei"/><w:sz w:val="21"/></w:rPr></w:rPrDefault></w:docDefaults>
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:pPr><w:spacing w:after="120" w:line="360" w:lineRule="auto"/></w:pPr><w:rPr><w:rFonts w:ascii="Microsoft YaHei" w:eastAsia="Microsoft YaHei" w:hAnsi="Microsoft YaHei"/><w:sz w:val="21"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:rPr><w:b/><w:color w:val="17365D"/><w:sz w:val="40"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:rPr><w:color w:val="5F6F82"/><w:sz w:val="24"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:pPr><w:keepNext/><w:spacing w:before="360" w:after="160"/></w:pPr><w:rPr><w:b/><w:color w:val="17365D"/><w:sz w:val="30"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:pPr><w:keepNext/><w:spacing w:before="240" w:after="120"/></w:pPr><w:rPr><w:b/><w:color w:val="2F5597"/><w:sz w:val="25"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:pPr><w:keepNext/><w:spacing w:before="160" w:after="80"/></w:pPr><w:rPr><w:b/><w:color w:val="3B4A5A"/><w:sz w:val="22"/></w:rPr></w:style>
</w:styles>'''


def build_body() -> str:
    parts: list[str] = []
    now = datetime.now()
    today_cn = f"{now.year}年{now.month:02d}月{now.day:02d}日"
    parts.append(p("GeoBot WebGIS-AI", style="Title", align="center", after=160))
    parts.append(p("面向地理课堂的实时交互地图演示与智能助教系统", style="Subtitle", align="center", after=480))
    parts.append(table([
        ["项目名称", "面向教学的地理智能小助手（GeoBot）研发与示范应用"],
        ["当前产品线", "WebGIS-AI：课堂实时 WebGIS + 智能助教 + 后台 GIS 工作流"],
        ["负责人", "张程祎"],
        ["指导教师", "李治洪"],
        ["建设周期", "2026年5月 - 2027年4月"],
        ["文档用途", "项目介绍、阶段汇报、答辩材料与后续开发说明"],
        ["生成日期", today_cn],
    ], header=False))
    parts.append(callout("一句话概括", "本项目面向课堂大屏演示构建 WebGIS-AI 系统：地图占据主屏，教师可通过点击、绘制、上传数据或自然语言即时操控地图，智能助教以悬浮部件形式提供读图讲解、知识解释、检索和 GIS 分析支持。"))
    parts.append(page_break())

    parts.append(heading(1, "一、项目概述"))
    parts.append(p("GeoBot WebGIS-AI 是一个面向地理教学场景的本地化智能地图交互系统。项目的核心目标不是替代教师的教学设计能力，而是在课堂现场提供可即时操作、可解释、可导出的地图演示环境，使教师能够围绕真实空间现象进行读图、制图、空间检索、标注、对比和问题引导。"))
    parts.append(p("与传统 GIS 软件相比，本系统强调低门槛课堂操作；与单纯的 AI 文档生成工具相比，本系统强调地图画面、图层状态、知识库资料和课堂动作之间的闭环。WebGIS 课堂页作为主入口，后台 GIS 工作流作为空间分析与成果输出支撑。"))
    parts.append(table([
        ["维度", "项目当前定位"],
        ["主要对象", "中学/高校地理教师、地理信息科学课程教师、课堂演示与实验教学场景"],
        ["核心场景", "课堂大屏即时演示、读图讲解、专题地图展示、POI 检索、资料知识调用、GIS 分析工作流"],
        ["部署方式", "教师机本地启动 FastAPI 后端与 Vite 前端，浏览器访问，默认不依赖云端部署"],
        ["交互方式", "地图点击、绘区、工具按钮、文件上传、自然语言对话、任务流状态反馈"],
        ["产出形式", "课堂截图、助教讲解稿、查询摘要、地图导出、知识库条目、GIS 分析成果"],
    ]))

    parts.append(heading(1, "二、项目背景与定位依据"))
    parts.append(heading(2, "2.1 课堂需求"))
    parts.append(p("地理课堂需要能够承载空间观察、图层对比、区域检索、现场标注和分析结果展示的一体化工具。WebGIS-AI 围绕教师授课现场设计，让地图成为课堂主界面，让 AI 助教和后台分析能力围绕地图上下文工作。"))
    parts.append(heading(2, "2.2 课堂使用问题"))
    for text in [
        "静态课件难以支撑实时提问、局部放大、图层对比和现场标注。",
        "通用 AI 问答若脱离地图证据，容易变成泛泛文字解释。",
        "空间分析任务需要明确步骤、参数、结果和解释，课堂展示必须可观察、可追踪。",
        "课堂大屏交互需要更轻、更直观的界面，控件不能遮挡地图，操作反馈必须即时可见。",
    ]:
        parts.append(bullet(text))
    parts.append(heading(2, "2.3 当前定位"))
    parts.append(p("WebGIS-AI 采用 React、OpenLayers 和 FastAPI 构建浏览器端地图课堂，智能助教固定为地图副驾驶，后台 GIS 工作流负责可复现的空间分析和成果输出。"))
    parts.append(table([
        ["能力方向", "当前处理方式"],
        ["课堂地图交互", "作为主界面能力，支持底图、图层、标注、测距、绘区和截图"],
        ["智能助教", "围绕地图上下文进行讲解、检索、模板触发和工具规划"],
        ["教学资料", "以知识库、专题资料和课堂讲解能力组织"],
        ["GIS 分析", "通过后台工作流封装常用空间分析和成果导出"],
    ]))

    parts.append(heading(1, "三、建设目标"))
    parts.append(p("项目建设目标可概括为“一主两辅三闭环”。“一主”是以 WebGIS 课堂大屏作为主界面；“两辅”是智能助教与后台 GIS 工作流；“三闭环”是地图交互闭环、知识解释闭环和成果导出闭环。"))
    parts.append(heading(2, "3.1 总体目标"))
    for text in [
        "构建一个可在教师机本地运行的 WebGIS-AI 原型系统，支持课堂大屏地图演示与实时交互。",
        "实现智能助教围绕地图上下文工作，支持读图讲解、地图动作规划、知识解释和课堂提问。",
        "建立地理教学资料知识库，使人口、气候、区域等资料能够被检索、编辑、关联图层并服务课堂讲解。",
        "建设后台 GIS 分析工作流，形成课堂交互与空间分析分工明确的系统架构。",
    ]:
        parts.append(bullet(text))
    parts.append(heading(2, "3.2 阶段性目标"))
    parts.append(table([
        ["阶段", "目标", "验收重点"],
        ["v1 基础闭环", "WebGIS 课堂页、图层状态、助教规则动作、截图导出", "地图可显示、控件可操作、助教可执行基础动作"],
        ["v1.1 交互重构", "大屏地图优先、浅灰透明浮层、POI 检索、知识库折叠面板", "地图占屏为主，功能悬浮，知识库可检索编辑"],
        ["AI 与分析接入", "MiniMax 文本助教、截图读图流程、后台 GIS 工作流", "LLM 可规划，分析任务可追踪"],
        ["后续专题版", "基于正式教案重建人口、气候、区域专题模板", "模板有教学逻辑、地图图层和讲解脚本"],
    ]))

    parts.append(heading(1, "四、系统总体架构"))
    parts.append(p("系统采用前后端分离的双层架构，前端负责课堂交互与地图渲染，后端负责项目状态、数据、知识库、LLM 规划和任务流管理。整体设计强调本地可控、服务可替换、接口清晰和课堂实时响应。"))
    parts.append(table([
        ["层级", "组成", "职责"],
        ["前端课堂层", "React + TypeScript + Vite + OpenLayers", "全屏地图、浮动面板、地图工具、知识库面板、助教浮窗、截图捕获"],
        ["后端服务层", "FastAPI + 本地状态文件", "项目、图层、任务、artifact、SSE 状态流、数据上传、导出"],
        ["AI 规划层", "MiniMax OpenAI-compatible Chat Completions + 规则兜底", "将自然语言转为结构化讲解或工具动作"],
        ["知识库层", "本地知识条目、专题聚合、图层关联", "资料检索、编辑、专题组织、课堂解释支撑"],
        ["GIS 工作流层", "后台任务服务", "执行空间分析、统计、样式和地图导出能力"],
    ]))
    parts.append(heading(2, "4.1 课堂模式"))
    parts.append(p("课堂模式是默认入口。界面以地图为主，顶部为全局操作条，左侧为课堂控制台，右侧为地图工具与知识库折叠窗，底部为课堂快捷动作，右下角为可缩小、可拖动、可展开的智能助教。该模式面向现场教学，强调“不打开复杂 GIS 软件也能完成演示”。"))
    parts.append(heading(2, "4.2 后台 GIS 工作流"))
    parts.append(p("后台 GIS 工作流用于承载空间分析、统计、样式生成和地图导出。任务通过后端统一调度，前端通过 SSE 获取执行状态，所有能力都经过白名单和参数校验。"))
    parts.append(heading(2, "4.3 AI 助教规划模式"))
    parts.append(p("助教采用 MiniMax LLM 优先、规则引擎兜底的策略。LLM 输出必须为结构化 JSON，包含 assistant_message、target 与 actions；后端再进行工具白名单校验，防止模型编造工具或执行不安全操作。当 API key 缺失、请求失败、JSON 无法解析或工具不合法时，系统自动回退到规则型规划器。"))

    parts.append(heading(1, "五、核心功能设计"))
    parts.append(heading(2, "5.1 全屏 WebGIS 课堂主舞台"))
    for text in [
        "地图画布占据主视口，降低面板遮挡，适配 16:9 课堂大屏。",
        "底图由后端统一下发预设目录，可配置高德、天地图或兼容 XYZ/WMTS 服务。",
        "支持图层显隐、活动图层、课堂标注、测距、绘制检索区域、视图复位和截图导出。",
        "所有业务控件以浅灰透明玻璃态浮层呈现，视觉方向贴近交互式地图大屏。",
    ]:
        parts.append(bullet(text))
    parts.append(heading(2, "5.2 智能助教"))
    parts.append(p("智能助教被设计为桌面悬浮部件，而不是固定聊天栏。最小化时是地理主题圆球，展开后是可拖动、可缩放的对话窗口。其输出分为两类：讲解型回复与地图动作。非破坏性地图动作可直接执行，删除图层、重置项目、覆盖导出等破坏性动作需要二次确认。"))
    parts.append(table([
        ["工具类别", "代表能力"],
        ["地图视图", "set_view、switch_basemap、explain_current_view"],
        ["图层控制", "toggle_layer、reorder_layer、style_layer"],
        ["查询分析", "query_features、search_poi、measure"],
        ["课堂制图", "draw_annotation、apply_template、export_snapshot"],
        ["GIS 工作流", "缓冲区、裁剪、空间连接、统计、样式和地图导出等白名单工具"],
    ]))
    parts.append(heading(2, "5.3 读图理解"))
    parts.append(p("读图讲解不再只依赖固定话术。前端在用户点击“读图讲解”时捕获当前地图画面，并同时发送 map_context，包括中心点、缩放级别、底图、可见图层、活动图层、选中要素摘要、最近操作和知识库命中条目。后端优先走视觉理解流程；如果视觉服务未配置，则明确回退为结构化上下文讲解。"))
    parts.append(heading(2, "5.4 知识库"))
    parts.append(p("知识库用于把教师提供的资料沉淀成可检索、可编辑、可关联图层的课堂知识条目。它不是简单文件夹，也不是正式教案目录，而是课堂助教进行解释、检索和专题组织的资料底座。当前知识库已整理人口普查、气候区划和系统示例等条目，并对每条资料标注状态：仅知识资料、可渲染图层或存档数据。"))
    parts.append(table([
        ["能力", "说明"],
        ["可视化检索", "按关键词、专题、地区、标签筛选知识条目"],
        ["条目编辑", "维护标题、主题、区域、时间、关键词、摘要、标准解释和教学要点"],
        ["图层关联", "将当前活动图层注册到知识库条目，后续可在讲解中自动引用"],
        ["专题聚合", "通过 /kb/topics 生成资料专题，驱动左侧课堂控制台"],
        ["坏数据防护", "屏蔽问号串、乱码和空标题，避免直接污染课堂界面"],
    ]))
    parts.append(heading(2, "5.5 课堂控制台"))
    parts.append(p("左侧课堂控制台已从“硬编码课堂包目录”改为资料驱动面板。其页签包括资料、图层、检索和产物：资料页展示知识库专题；图层页区分可见图层、知识库关联图层和仅存档数据；检索页显示 POI 或区域检索记录；产物页仅展示教师可直接使用的课堂截图、助教讲解稿和查询摘要。"))
    parts.append(heading(2, "5.6 数据与图源"))
    parts.append(p("v1 数据策略采用“内置教学数据包 + 教师上传基础格式”。系统支持 GeoJSON、CSV 经纬度映射、ZIP Shapefile、PNG/JPG 图片覆盖层等基础资料类型。当前阶段部分 Shapefile ZIP 暂不作为可视化图层导入，而是作为知识库资料与后续专题模板设计素材保存；世界柯本气候图作为可渲染影像层保留。"))

    parts.append(heading(1, "六、已取得进展"))
    parts.append(table([
        ["模块", "当前状态", "说明"],
        ["WebGIS 课堂页", "已完成基础闭环", "大屏地图、浮动面板、右侧工具、左侧控制台和底部课堂动作已形成统一界面"],
        ["底图系统", "已实现可配置目录", "支持底图预设与自定义配置，前端不直接硬编码真实服务 key"],
        ["POI 检索", "已接入后端代理设计", "支持视域检索与绘区检索，服务 key 缺失时 UI 明确提示"],
        ["智能助教", "已接入 MiniMax 文本规划", "LLM 优先、规则兜底，支持 WebGIS 工具规划"],
        ["读图理解", "已完成截图与上下文流程", "视觉服务未配置时回退到结构化地图上下文解释"],
        ["知识库", "已接入课堂页", "支持检索、编辑、专题聚合、活动图层关联和坏文本防护"],
        ["GIS 工作流", "已建立任务式能力", "支持分析任务、产物登记和结果回写地图"],
        ["测试", "已建立基础测试", "前端测试、前端构建、后端 unittest 与 py_compile 均已通过阶段性验证"],
    ]))
    parts.append(p("当前系统已经能够支撑一条完整课堂演示路径：启动本地服务后进入课堂页，加载底图和基础图层，教师可通过工具或助教进行视图切换、读图讲解、资料检索、知识库引用、截图导出和 GIS 分析。"))

    parts.append(heading(1, "七、课堂流程与分析工作流"))
    parts.append(p("WebGIS-AI 将课堂主流程、智能助教和后台 GIS 分析统一在同一个运行时中。教师在浏览器中完成观察、提问和操作，系统在后台执行分析任务并把结果回写到地图。"))
    parts.append(table([
        ["环节", "课堂侧", "后台侧"],
        ["地图展示", "底图、图层、标注、测距、检索", "图层状态、产物和任务记录"],
        ["智能助教", "接收自然语言和地图上下文", "规划安全白名单工具动作"],
        ["GIS 分析", "提交任务并观察结果", "执行分析、统计、样式和导出"],
        ["成果沉淀", "截图、讲解稿、课堂产物", "artifact 登记与文件服务"],
    ]))
    parts.append(callout("设计判断", "系统以课堂即时演示为第一目标，后台分析能力只通过可控工作流进入课堂，避免复杂操作打断教学节奏。"))

    parts.append(heading(1, "八、技术实现要点"))
    parts.append(heading(2, "8.1 后端接口体系"))
    parts.append(table([
        ["接口类型", "代表接口", "作用"],
        ["基础状态", "/health、/projects、/jobs/{id}、/jobs/{id}/stream、/outputs", "服务检测、项目管理、任务状态与产物管理"],
        ["WebGIS", "/basemaps、/layers、/datasets/upload、/exports/snapshot", "底图、图层、数据上传与截图导出"],
        ["助教", "/assistant/messages", "统一接收课堂自然语言请求"],
        ["知识库", "/kb/manifest、/kb/search、/kb/topics、/kb/items、/kb/layers/register", "资料检索、专题聚合、编辑与图层关联"],
    ]))
    parts.append(heading(2, "8.2 安全与可控性"))
    for text in [
        "前端不保存 MiniMax key 或地图服务 key。",
        "LLM 输出必须经过 JSON 解析、工具白名单校验和参数校验。",
        "后台分析能力不开放任意代码执行。",
        "破坏性地图动作默认需要二次确认。",
        "外部服务未配置或不可达时，系统保留本地课堂能力并给出明确提示。",
    ]:
        parts.append(bullet(text))
    parts.append(heading(2, "8.3 本地部署"))
    parts.append(p("项目默认在教师机本地运行，使用一键启动脚本同时拉起 FastAPI 后端与 Vite 前端。MiniMax 和地图服务均通过环境变量或本地配置接入。未配置外部服务时，系统不会整体崩溃，而是进入规则兜底或本地能力模式。"))

    parts.append(heading(1, "九、应用场景"))
    parts.append(table([
        ["场景", "示例流程", "教学价值"],
        ["区域认知", "缩放到长三角或上海，叠加行政/交通/兴趣点，助教讲解区位特征", "帮助学生建立区域空间结构认知"],
        ["人口专题", "加载人口普查资料，后续结合胡焕庸线、迁移方向和密度对比重建模板", "理解人口分布与自然、经济因素的关系"],
        ["气候专题", "叠加世界柯本气候图，结合知识库解释气候区划与纬度、海陆、地形关系", "支持气候类型判读和空间分布规律讲解"],
        ["POI 与区位", "绘制区域检索港口、高铁站或城市，生成点图并解释布局价值", "训练学生从空间分布推断区位因素"],
        ["GIS 实验", "通过后台工作流执行分析、设置样式、导出地图", "支持 GIS 教学与实验深度"],
    ]))

    parts.append(heading(1, "十、后续计划"))
    parts.append(table([
        ["时间", "工作重点", "具体任务"],
        ["2026年5-6月", "稳定课堂模式与知识库", "完善地图显示、截图导出、知识库检索编辑、UI 可用性和错误提示"],
        ["2026年7-8月", "重建专题模板", "根据正式教案导入人口、气候、区域案例，形成可演示路径"],
        ["2026年9-10月", "完善 GIS 分析工作流", "扩展样式、查询、导入导出、常用工具和任务回放"],
        ["2026年11-12月", "课堂试用与反馈", "组织示范课或实验课试用，收集教师操作问题和学生理解反馈"],
        ["2027年1-3月", "优化与成果整理", "补测试、写文档、整理数据包、制作案例视频和答辩材料"],
        ["2027年4月", "结题与推广", "完成项目报告、PPT、软件著作权材料和后续研究计划"],
    ]))
    parts.append(heading(2, "10.1 专题模板建设原则"))
    for text in [
        "专题模板必须由正式教案、真实数据和课堂问题共同驱动。",
        "每个专题至少包含底图、图层、关键问题、讲解脚本、课堂提问和导出成果。",
        "优先建设人口分布、人口迁移、胡焕庸线、气候区划和区域区位分析五类可复用案例。",
    ]:
        parts.append(bullet(text))

    parts.append(heading(1, "十一、预期成果"))
    parts.append(table([
        ["成果类型", "成果内容"],
        ["软件原型", "WebGIS-AI 本地课堂系统，包含课堂模式、知识库、智能助教和 GIS 分析工作流"],
        ["教学数据", "人口、气候、区域等地理教学资料包与知识库条目"],
        ["课堂案例", "人口分布/迁移、气候区划、城市区位、区域认知等示范演示路径"],
        ["技术文档", "部署说明、教师使用说明、接口说明、测试报告和维护手册"],
        ["研究成果", "项目总结报告、课程研究论文或教学改革论文、答辩 PPT"],
        ["知识产权", "软件著作权申请材料与版本说明"],
    ]))

    parts.append(heading(1, "十二、风险与应对"))
    parts.append(table([
        ["风险", "表现", "应对策略"],
        ["在线地图服务不稳定", "课堂现场底图无法加载", "保留可替换底图配置，支持天地图/高德/本地瓦片等多源方案"],
        ["LLM 输出不可靠", "编造工具或错误解释", "结构化 JSON、白名单校验、规则兜底、知识库约束提示词"],
        ["视觉读图服务未配置", "无法像 GPT 截图读图一样直接看图", "使用 map_context 回退，并在后续接入 MiniMax Token Plan MCP 视觉能力"],
        ["教学资料不规范", "数据难以直接渲染或解释", "建立知识库元数据、状态标注和专题模板准入标准"],
        ["分析任务失败", "后台工作流不可用或参数不合法", "前端明确提示任务状态、错误原因和排查步骤"],
    ]))

    parts.append(heading(1, "十三、结语"))
    parts.append(p("GeoBot WebGIS-AI 的核心价值在于把 GIS 能力嵌入课堂现场可交互演示。项目以地图演示、读图讲解、资料检索、空间分析和即时反馈为核心，后续工作将以正式教案和真实课堂试用为牵引，持续完善专题模板、知识库质量和 GIS 工具链，形成可展示、可复用、可推广的地理智能教学平台。"))

    parts.append(section_properties())
    return "".join(parts)


def document_xml() -> str:
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W_NS}" xmlns:r="{R_NS}">
  <w:body>
    {build_body()}
  </w:body>
</w:document>'''


def content_types_xml() -> str:
    return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
  <Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>
  <Override PartName="/word/fontTable.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.fontTable+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>'''


def rels_xml() -> str:
    return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>'''


def doc_rels_xml() -> str:
    return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/fontTable" Target="fontTable.xml"/>
</Relationships>'''


def settings_xml() -> str:
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:settings xmlns:w="{W_NS}"><w:zoom w:percent="100"/><w:defaultTabStop w:val="720"/></w:settings>'''


def font_table_xml() -> str:
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:fonts xmlns:w="{W_NS}"><w:font w:name="Microsoft YaHei"><w:family w:val="swiss"/></w:font></w:fonts>'''


def core_xml() -> str:
    created = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>GeoBot WebGIS-AI 项目介绍书</dc:title>
  <dc:creator>WebGIS-AI</dc:creator>
  <cp:lastModifiedBy>WebGIS-AI</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">{created}</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">{created}</dcterms:modified>
</cp:coreProperties>'''


def app_xml() -> str:
    return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>WebGIS-AI Document Builder</Application>
  <DocSecurity>0</DocSecurity>
  <ScaleCrop>false</ScaleCrop>
  <Company>GeoBot WebGIS-AI</Company>
</Properties>'''


def build_docx() -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    files = {
        "[Content_Types].xml": content_types_xml(),
        "_rels/.rels": rels_xml(),
        "word/document.xml": document_xml(),
        "word/_rels/document.xml.rels": doc_rels_xml(),
        "word/styles.xml": styles_xml(),
        "word/settings.xml": settings_xml(),
        "word/fontTable.xml": font_table_xml(),
        "docProps/core.xml": core_xml(),
        "docProps/app.xml": app_xml(),
    }
    with zipfile.ZipFile(OUT_DOCX, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content.encode("utf-8"))


def build_markdown() -> None:
    markdown = """# GeoBot WebGIS-AI 项目介绍书

## 项目定位

GeoBot WebGIS-AI 是一个面向地理课堂的实时交互地图演示与智能助教系统，采用“WebGIS 课堂大屏 + 悬浮智能助教 + 知识库 + 后台 GIS 工作流”的系统架构。

## 核心目标

- 构建教师机本地可运行的 WebGIS 课堂系统。
- 支持课堂现场读图、制图、检索、标注、截图导出和知识讲解。
- 接入 MiniMax 文本助教，并以规则引擎兜底。
- 建立后台 GIS 分析工作流，为课堂空间分析和成果输出提供支撑。
- 建立地理教学资料知识库，为后续专题模板和正式教案提供资料底座。

## 已取得进展

- 已完成 React + TypeScript + Vite + OpenLayers 的课堂页基础重构。
- 已完成 FastAPI 本地后端、项目/图层/任务/artifact/SSE 状态流。
- 已接入 MiniMax 文本助教和规则兜底规划。
- 已建立知识库面板，支持检索、编辑、专题聚合和活动图层关联。
- 已建立后台 GIS 工作流能力，支持任务状态、产物登记和结果回写地图。
- 已完成截图读图流程；视觉 MCP 未配置时回退到 map_context 结构化解释。

## 后续计划

- 稳定课堂模式与知识库交互。
- 根据正式教案重建人口、气候、区位等专题模板。
- 完善 GIS 分析工具链。
- 组织课堂试用并整理测试报告、项目总结和软著材料。
"""
    OUT_MD.write_text(markdown, encoding="utf-8")


def verify_docx() -> None:
    with zipfile.ZipFile(OUT_DOCX, "r") as zf:
        names = set(zf.namelist())
        required = {"[Content_Types].xml", "word/document.xml", "word/styles.xml", "_rels/.rels"}
        missing = required - names
        if missing:
            raise RuntimeError(f"Missing required DOCX parts: {sorted(missing)}")
        document = zf.read("word/document.xml").decode("utf-8")
        for token in ["WebGIS-AI", "MiniMax", "GIS 工作流", "知识库", "课堂控制台"]:
            if token not in document:
                raise RuntimeError(f"Expected token not found in document: {token}")


def main() -> None:
    build_docx()
    build_markdown()
    verify_docx()
    print(f"Built: {OUT_DOCX}")
    print(f"Markdown: {OUT_MD}")


if __name__ == "__main__":
    main()
