# WebGIS-AI

`WebGIS-AI` 是面向地理课堂实时演示的本地 WebGIS 系统，采用“全屏地图 + 悬浮面板 + 智能助教副驾驶”的课堂大屏模式。

## 功能重点

- 全屏地图主舞台，界面改成浅灰透明悬浮面板
- 内置多底图切换：`高德标准 / 高德影像 / 高德浅灰`
- 新增 POI 检索：
  - 当前视域检索
  - 手绘区域检索
  - 结果列表与地图点位联动
- 智能助教升级为桌面悬浮部件：
  - 可最小化成圆球
  - 可拖动
  - 展开后可移动、缩放
- 保留课堂模板、数据导入、标注、测距、截图导出

## 技术栈

- 前端：`React + TypeScript + Vite + OpenLayers`
- 后端：`FastAPI`
- 运行时模型：`projects / jobs / artifacts / SSE job stream`

## 整体架构设计

`WebGIS-AI` 采用前后端分离架构。前端负责地图交互、课堂大屏界面和智能助教操作入口；后端负责项目状态、图层数据、课堂模板、POI 检索、文件产物、异步任务和访问控制。

```text
Browser / Classroom Screen
        |
        | HTTP JSON / file upload / SSE
        v
React + OpenLayers frontend
        |
        | REST API client
        v
FastAPI backend
        |
        +-- Runtime orchestration: projects, layers, jobs, artifacts
        +-- Services: assistant, templates, datasets, POI, map exports
        +-- Storage: JSON state, uploaded datasets, generated outputs
        +-- External services: basemap tiles, POI web service, optional LLM
```

核心数据流：

- 启动后前端调用 `/health`、`/basemaps` 获取运行状态和底图配置。
- 用户创建或打开课堂项目后，后端用 `project_id` 管理视图、底图、图层、产物和最近操作。
- 数据上传接口将 `GeoJSON / CSV / ZIP Shapefile / 图片覆盖层` 转换为前端可渲染图层。
- 课堂模板和智能助教请求会创建后台任务，前端通过 `/jobs/{job_id}` 和 `/jobs/{job_id}/stream` 读取进度。
- 导出、报告、截图等产物统一登记为 `artifact`，再通过受控文件接口下载。
- 公网发布时通过 `WEBGIS_AI_AUTH_TOKEN` 做访问令牌校验，通过 `WEBGIS_AI_CORS_ALLOW_ORIGINS` 限制允许访问的前端域名。

## 代码文件说明

```text
WebGIS-AI/
├─ README.md                         项目入口说明、启动方式、接口和架构说明
├─ PROJECT_DESCRIPTION.md             项目介绍材料
├─ requirements.txt                   后端 Python 依赖
├─ start_webgis_ai.cmd                Windows 一键启动入口
├─ scripts/
│  ├─ start_webgis_ai.ps1             一键启动脚本主体
│  ├─ build_project_introduction_doc.py
│  └─ build_defense_ppt.py            说明文档和答辩材料生成脚本
├─ backend/
│  ├─ app/
│  │  ├─ main.py                      FastAPI 应用入口、鉴权中间件和 HTTP 路由
│  │  ├─ config.py                    环境变量、路径、底图、鉴权和外部服务配置
│  │  ├─ runtime.py                   课堂运行时编排，连接项目、图层、任务和服务
│  │  ├─ store.py                     本地 JSON 状态存储，管理 projects/jobs/artifacts
│  │  ├─ models.py                    Project、Layer、Job、Artifact 数据模型
│  │  ├─ geo.py                       地理计算辅助函数
│  │  ├─ data/builtin/                内置课堂模板和人口专题 GeoJSON 数据
│  │  └─ services/
│  │     ├─ assistant.py              智能助教规则规划和课堂解释生成
│  │     ├─ datasets.py               上传数据解析、标准化和图层生成
│  │     ├─ templates.py              课堂模板执行和专题图层生成
│  │     ├─ poi.py                    POI 检索、结果标准化和图层转换
│  │     ├─ minimax_client.py         可选 LLM 客户端封装
│  │     └─ llm_planner.py            LLM 规划结果校验和规则兜底
│  └─ tests/                          后端单元测试和接口安全测试
├─ frontend/
│  ├─ package.json                    前端依赖和 npm scripts
│  ├─ vite.config.ts                  Vite 构建配置
│  └─ src/
│     ├─ main.tsx                     React 入口
│     ├─ App.tsx                      主界面、地图舞台、工具栏和状态编排
│     ├─ api.ts                       后端 API 客户端、鉴权 token 和 SSE URL 处理
│     ├─ types.ts                     前后端共享的 TypeScript 类型
│     ├─ styles.css                   全局样式和课堂大屏布局
│     ├─ components/
│     │  ├─ BasemapMenu.tsx           底图切换菜单
│     │  ├─ CopilotWidget.tsx         悬浮智能助教窗口
│     │  ├─ SideDrawer.tsx            图层、POI 结果和产物抽屉
│     │  ├─ ToastStack.tsx            全局提示消息
│     │  └─ UploadDialog.tsx          数据上传对话框
│     └─ __tests__/                   前端组件和 API 鉴权测试
└─ docs/                              上线配置、安全核查、课程融合和答辩材料
```

## 当前界面

- 顶部：品牌条、底图切换、模板切换、上传、导出、复位
- 左侧：可收起抽屉，包含图层、POI 检索结果、课堂产物
- 右侧：地图工具栏，包含选择、标注、测距、绘区、清除、缩放
- 底部：课堂快捷动作条
- 右下：悬浮智能助教

## 数据与模板

内置模板：

- 通用地理课堂包
- 人口专题课堂包
- 人口分布
- 人口密度
- 人口迁移
- 胡焕庸线对比

支持上传：

- `GeoJSON`
- `CSV`
- `ZIP Shapefile`
- `PNG / JPG` 图片覆盖层

## 环境变量

后端统一持有底图和 POI 服务配置。前端不会硬编码服务 key。

常用环境变量：

- `WEBGIS_AI_AMAP_WEB_SERVICE_KEY`
- `WEBGIS_AI_DEFAULT_BASEMAP`
- `WEBGIS_AI_AMAP_VECTOR_URL`
- `WEBGIS_AI_AMAP_IMAGERY_URL`
- `WEBGIS_AI_AMAP_ANNOTATION_URL`
- `WEBGIS_AI_AMAP_POI_POLYGON_URL`
- `WEBGIS_AI_AUTH_TOKEN`：公网部署时必须设置，后端所有 API、文件下载、任务流均需要访问令牌
- `WEBGIS_AI_CORS_ALLOW_ORIGINS`：公网部署时设置为真实前端域名，例如 `https://webgis.example.edu`
- `WEBGIS_AI_AUTH_EXEMPT_PATHS`：可选免鉴权路径，公网不建议豁免 `/health`

如果没有配置 `WEBGIS_AI_AMAP_WEB_SERVICE_KEY`：

- 底图切换仍可使用
- POI 在线检索会在界面中提示未配置

## 启动方式

### 一键启动

```powershell
.\start_webgis_ai.cmd
```

首次缺依赖时自动安装并打开浏览器：

```powershell
.\start_webgis_ai.cmd -InstallIfMissing -OpenBrowser
```

如果自动识别 Python 失败，可显式指定 `Python 3.12`：

```powershell
.\start_webgis_ai.cmd -PythonExe "C:\Users\zcyxn\AppData\Local\Programs\Python\Python312\python.exe" -InstallIfMissing -OpenBrowser
```

### 手动启动

后端：

```powershell
& 'C:\Users\zcyxn\AppData\Local\Programs\Python\Python312\python.exe' -m pip install -r requirements.txt
& 'C:\Users\zcyxn\AppData\Local\Programs\Python\Python312\python.exe' -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 18999
```

前端：

```powershell
cd .\frontend
& 'C:\Program Files\nodejs\node.exe' 'C:\Program Files\nodejs\node_modules\npm\bin\npm-cli.js' install
& 'C:\Program Files\nodejs\node.exe' 'C:\Program Files\nodejs\node_modules\npm\bin\npm-cli.js' run dev
```

默认访问：

```text
http://127.0.0.1:5173
```

## 关键接口

- `GET /health`
- `GET /basemaps`
- `POST /projects`
- `GET /projects/{project_id}`
- `PATCH /projects/{project_id}/basemap`
- `GET /layers?project_id=...`
- `PATCH /layers`
- `POST /assistant/messages`
- `POST /templates/{template_id}/run`
- `POST /datasets/upload`
- `POST /search/poi`
- `POST /exports/snapshot`
- `GET /jobs/{job_id}`
- `GET /jobs/{job_id}/stream`
- `GET /outputs`

## 测试

后端：

```powershell
& 'C:\Users\zcyxn\AppData\Local\Programs\Python\Python312\python.exe' -m unittest discover backend/tests
```

前端：

```powershell
cd .\frontend
& 'C:\Program Files\nodejs\node.exe' 'C:\Program Files\nodejs\node_modules\npm\bin\npm-cli.js' run test
& 'C:\Program Files\nodejs\node.exe' 'C:\Program Files\nodejs\node_modules\npm\bin\npm-cli.js' run build
```
