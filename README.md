# WebGIS-AI

`WebGIS-AI` 是面向地理课堂实时演示、读图讲解与 GIS 探究的本地 WebGIS 智能教学平台。项目当前主线已经从早期的 QGIS 教学脚本与文档产物生成，转向“全屏地图主舞台 + 悬浮课堂控制台 + 智能助教 + 知识库资料 + PyQGIS 分析工作流”的课堂大屏模式。

系统适合在教师机本地运行，用于地理课堂投屏、专题地图讲解、人口/气候/区域等案例分析、空间数据导入、POI 检索、地图标注、截图沉淀和 GIS 方法入门实验。

## 当前定位

- **地图主导**：以全屏 WebGIS 地图承载课堂观察、图层对比、标注和结论沉淀。
- **课堂可控**：教师通过顶部工具栏、左侧抽屉、右侧工具栏和右下角智能助教完成授课操作。
- **AI 辅助但不黑箱**：智能助教可读图、问答和规划 WebGIS 操作；真正执行的动作受工具白名单、风险评估和后端状态管理约束。
- **GIS 分析可追溯**：空间分析由后端工作流验证、执行并输出 GeoJSON、样式、统计、PNG 和 Markdown 解释。
- **本地运行优先**：后端统一持有外部服务 Key，前端不硬编码密钥，适合学校机房、实验室和教师个人电脑部署。

## 主要功能

### 1. 全屏课堂地图

- 基于 OpenLayers 的全屏地图主舞台。
- 支持高德标准、高德影像、高德浅灰和兼容 XYZ 底图。
- 配置 OpenWeatherMap 后可叠加实时降水、云图、温度、风速、气压等天气瓦片。
- 支持矢量图层、栅格覆盖层、POI 检索结果、课堂标注和测距结果。
- 支持视图复位、图层显隐、图层选择、要素高亮和地图截图。

### 2. 课堂交互工具

- 浏览、标注、测距、绘制 POI 检索区域、清除、缩放。
- 测距支持实时长度反馈。
- 标注可直接写入当前地图并沉淀到课堂截图。
- 左侧课堂控制台提供资料搜索、图层列表和 POI 结果联动。

### 3. POI 检索

配置 `WEBGIS_AI_AMAP_WEB_SERVICE_KEY` 后可使用高德 POI 检索：

- 当前视域检索。
- 手绘多边形区域检索。
- 检索结果自动写入点图层。
- 左侧结果列表与地图点位联动。

### 4. 课堂模板与课本地图

内置课堂模板：

- 人口专题包。
- 人口分布。
- 人口密度。
- 人口迁移。
- 胡焕庸线对比。

内置课本地图注册机制，支持将教材或教学地图作为半透明栅格覆盖层叠加到地图中。当前已包含人口、气候、地形和区域类素材注册入口。

> 注意：课本地图和图片覆盖层依赖 `bounds` 配准质量。正式课堂中建议先校准后使用；配准不准的图片不要作为空间证据主图层。

### 5. 数据上传与 CRS 处理

支持上传：

- `GeoJSON` / `JSON`
- `CSV` 经纬度点数据
- `ZIP Shapefile`
- `PNG` / `JPG` 图片覆盖层

数据处理特性：

- 项目内矢量数据统一存储为 `EPSG:4326`。
- GeoJSON 可读取显式 CRS。
- CSV 会校验经纬度字段和坐标范围，疑似投影坐标会明确报错。
- Shapefile ZIP 会尝试从 `.prj` 检测 CRS；缺失 `.prj` 时按 `EPSG:4326` 处理并写入警告。
- ZIP 解压包含路径安全检查。

### 6. 知识库与课程资料

- 内置知识库 manifest 和地理知识条目。
- 支持按关键词、主题、区域、标签检索。
- 支持将课堂图层注册为知识条目。
- 支持上传或链接图片、视频、动画、文档、外部链接等教学素材。
- 教学素材可绑定地区、图层、要素或行政编码。
- 支持“课时资料包”，将知识条目和素材导入当前课堂。
- 资料搜索面板同时支持本地知识库、素材和权威资料入口建议。

### 7. 专业教学智能体

专业教学智能体以可拖动、可缩放、可最小化的悬浮窗口呈现，是课堂中唯一的 AI 入口，支持：

- 教学讲解：地理概念、区域地理、地图判读与 GIS 方法问答；答复包含证据或观察点、给学生的问题和教师收束语。
- 课堂地图操作：切换底图、显示图层、应用模板、检索 POI、添加标注、读图讲解等；任何地图操作执行后都会附带教学解释。
- 课堂追问与课后复盘：支持带上下文的连续追问，以及课后要点收束与下一步建议。
- 文本输入和浏览器语音识别输入。
- 对话记忆、阶段状态展示和引用来源展示；高风险操作需教师确认后才执行。
- 地图截图读图：配置视觉模型后可调用多模态模型；未配置时回退到结构化地图上下文解释。

支持的 LLM / Vision 配置包括：

- MiniMax：推荐 provider，走 Anthropic 兼容接口（`https://api.minimaxi.com/anthropic`，默认模型 `MiniMax-M2.7-highspeed`；若把 `WEBGIS_AI_MINIMAX_BASE_URL` 指到不含 `/anthropic` 的地址则回退 OpenAI Chat Completions 格式）。设置 `WEBGIS_AI_LLM_PROVIDER=minimax` + `WEBGIS_AI_MINIMAX_API_KEY` 启用；文档见 https://platform.minimaxi.com/docs/api-reference/text-anthropic-api 。
- Xiaomi MiMo：旧默认 provider，兼容 OpenAI Chat Completions 风格接口（服务不可用时请切换到 MiniMax）。
- MiniMax Token Plan MCP：图片理解视觉通道（`WEBGIS_AI_MINIMAX_TOKEN_PLAN_KEY`）。

### 8. GIS 分析工作流

后端包含 PyQGIS worker 分析链路，前端通过“GIS 分析工作流”面板提交任务并通过 SSE 获取实时状态。

当前模板包括：

- 人口密度分级设色图。
- 设施缓冲区分析。
- 胡焕庸线对比分析。
- 区域裁剪分析。
- 图层求交集。
- 图层空间连接。
- 字段分级。

当前工作流操作白名单包括：

- `load_layer`
- `inspect_layer`
- `reproject`
- `fix_geometries`
- `filter_features`
- `calculate_field`
- `buffer`
- `choropleth`
- `aggregate_stats`
- `export_geojson`
- `export_style_json`
- `export_map_png`
- `clip`
- `intersection`
- `spatial_join`
- `classify`

工作流输出会登记为 artifact，并可在前端加载为地图图层、图例、统计表和结果解释。

## 课程使用示例

以《人口分布》为例，推荐使用“免配准依赖”的课堂流程：

1. 使用高德浅灰底图作为主地图。
2. 加载“人口专题包”，只使用内置人口矢量图层作为空间证据。
3. 通过图层显隐对比人口分布、人口密度、人口迁移和胡焕庸线。
4. 用标注工具标出东南稠密区、西北稀疏区、黑河、腾冲等关键位置。
5. 让学生先描述，再用智能助教生成规范表达或追问。
6. 最后导出带图层和标注的课堂截图，作为本节课的证据链。

更多课程场景：

- 气候与地形：对比温度、降水、地形和区域差异。
- 城市地理：检索学校、医院、交通站点等 POI，讨论公共服务设施布局。
- GIS 方法入门：上传数据并运行缓冲区、裁剪、空间连接、分级设色等工作流。
- 区域地理：围绕某一区域叠加素材、标注特征并生成读图讲解。

## 技术栈

- 前端：`React` + `TypeScript` + `Vite` + `Cesium` + `OpenLayers`
- 地图入口：默认进入 `Cesium` 3D 数字地球，并可切换为 `OpenLayers` 2D 地图
- 后端：`FastAPI`
- GIS 工作流：`PyQGIS worker`
- 状态模型：`projects / layers / jobs / artifacts / conversations / workflows`
- 实时状态：`SSE job stream` / `SSE workflow stream`

## 目录结构

```text
backend/
  app/
    main.py                 # FastAPI 入口
    runtime.py              # WebGIS 运行时服务编排
    config.py               # 环境变量、底图、LLM、路径配置
    models.py               # 项目、图层、任务、工作流数据模型
    services/               # 助教、知识库、POI、数据导入、工作流等服务
    data/builtin/           # 内置知识库、课堂数据、课本地图注册
  tests/                    # 后端单元测试
frontend/
  src/
    App.tsx                 # 主课堂页面
    api.ts                  # 前端 API 调用
    components/             # 地图工具栏、助教、工作流、知识资料等组件
    hooks/                  # 工作流 SSE hook
    lib/                    # 共享前端工具
scripts/
  start_webgis_ai.ps1       # Windows 启动脚本
start_webgis_ai.cmd         # 一键启动入口
```

## 快速启动

### Windows 一键启动

```powershell
.\start_webgis_ai.cmd
```

首次缺依赖时可自动安装并打开浏览器：

```powershell
.\start_webgis_ai.cmd -InstallIfMissing -OpenBrowser
```

默认访问地址：

```text
http://127.0.0.1:5173
```

### 手动启动

后端：

```powershell
python -m pip install -r requirements.txt
python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 18999
```

前端：

```powershell
cd frontend
npm install
npm run dev
```

## 常用环境变量

基础服务：

- `WEBGIS_AI_HOST`
- `WEBGIS_AI_PORT`
- `WEBGIS_AI_DEFAULT_BASEMAP`
- `WEBGIS_AI_AMAP_VECTOR_URL`
- `WEBGIS_AI_AMAP_IMAGERY_URL`
- `WEBGIS_AI_AMAP_ANNOTATION_URL`

在线服务：

- `WEBGIS_AI_AMAP_WEB_SERVICE_KEY`
- `WEBGIS_AI_AMAP_POI_POLYGON_URL`
- `WEBGIS_AI_OPENWEATHERMAP_API_KEY`
- `WEBGIS_AI_OPENWEATHERMAP_LAYER`

LLM / Vision：

- `WEBGIS_AI_LLM_PROVIDER`：`mimo` 或 `minimax`
- `WEBGIS_AI_MIMO_API_KEY`
- `WEBGIS_AI_MIMO_BASE_URL`
- `WEBGIS_AI_MIMO_MODEL`
- `WEBGIS_AI_MINIMAX_API_KEY`
- `WEBGIS_AI_MINIMAX_BASE_URL`
- `WEBGIS_AI_MINIMAX_MODEL`
- `WEBGIS_AI_VISION_ENABLED`
- `WEBGIS_AI_VISION_PROVIDER`
- `WEBGIS_AI_VISION_MODEL`
- `WEBGIS_AI_MINIMAX_TOKEN_PLAN_KEY`

GIS 工作流：

- `QGIS_ROOT`
- `WEBGIS_AI_QGIS_ROOT`
- `WEBGIS_AI_QGIS_PREFIX_SUBPATH`

资料搜索：

- `WEBGIS_AI_RESOURCE_SEARCH_ENDPOINT`

## 关键接口

- `GET /health`
- `GET /llm/status`
- `GET /basemaps`
- `GET /teaching-maps`
- `POST /projects`
- `GET /projects/{project_id}`
- `PATCH /projects/{project_id}/basemap`
- `GET /layers?project_id=...`
- `PATCH /layers`
- `POST /assistant/messages`
- `POST /assistant/confirm`
- `GET /assistant/conversations/{conversation_id}`
- `POST /templates/{template_id}/run`
- `POST /datasets/upload`
- `POST /search/poi`
- `POST /exports/snapshot`
- `GET /kb/manifest`
- `GET /kb/search`
- `GET /kb/topics`
- `POST /kb/items`
- `POST /kb/layers/register`
- `POST /kb/materials/upload`
- `POST /kb/materials/link`
- `GET /resources/search`
- `GET /workflow/templates`
- `POST /workflow/submit`
- `GET /workflow/history`
- `GET /workflow/{workflow_id}`
- `GET /workflow/{workflow_id}/stream`
- `GET /workflow/{workflow_id}/artifacts`
- `GET /outputs`

## 测试

后端：

```powershell
python -m unittest discover backend/tests
```

前端：

```powershell
cd frontend
npm run test
npm run build
```

## 当前边界

- 图片覆盖层和课本地图依赖人工配准，`bounds` 不准时不应作为课堂证据主图层。
- POI、天气、大模型和视觉读图均依赖外部 Key；未配置时系统会降级或提示不可用。
- GIS 工作流以模板化分析为主，适合课堂常见空间分析，不等同于完整桌面 GIS。
- 当前主课堂入口默认使用 Cesium 3D 数字地球，同时保留 OpenLayers 2D 模式切换能力。
- 项目不再维护旧的 Word / PPT 教案产物链路、Electron 桌面壳和 OpenClaw 教学蓝图链路。
