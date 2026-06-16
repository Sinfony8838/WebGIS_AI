# WebGIS-AI 当前状态说明

本文档用于说明当前公开仓库的功能状态。项目主线是面向地理课堂的 WebGIS 智能教学平台，不包含历史路线说明。

## 当前能力

- 全屏 WebGIS 课堂地图，支持底图切换、图层显隐、课堂标注、测距、绘区和截图导出。
- 课堂模板与专题图层，支持通用课堂包、人口专题、人口分布、人口密度、人口迁移和胡焕庸线对比。
- 数据导入，支持 GeoJSON、CSV、ZIP Shapefile、PNG/JPG 覆盖图。
- POI 在线检索，配置高德 Web 服务 key 后可按当前视域或手绘区域检索。
- 智能助教，支持地图上下文讲解、图层控制、模板触发、POI 检索提示和课堂产物生成。
- 后台 GIS 分析工作流，支持任务状态、产物登记、统计摘要和结果回写地图。
- 本地优先部署，外部服务 key 均通过后端环境变量配置。
- 公网部署支持访问令牌鉴权和 CORS 白名单。

## 发布关注点

- GitHub 仓库只提交源码、内置教学资源和必要文档。
- `backend/data/` 运行产物、上传文件、工作流输出和备份不提交。
- `frontend/dist/`、日志、临时文件和 TypeScript build info 不提交。
- 公网部署必须设置 `WEBGIS_AI_AUTH_TOKEN` 和 `WEBGIS_AI_CORS_ALLOW_ORIGINS`。
- 高德 POI、MiniMax 等外部服务 key 不写入代码和文档。

## 验证命令

```powershell
python -m unittest discover backend/tests
cd frontend
npm test
npm run build
```
