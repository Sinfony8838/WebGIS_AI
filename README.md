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
