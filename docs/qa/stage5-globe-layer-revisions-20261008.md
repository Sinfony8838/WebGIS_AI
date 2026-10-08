# Stage 5b — 三维项目矢量按修订对账

- 分支：`codex/stage5-globe-layer-revisions`；起点：`85eb3c293151a02b57b5399c02de8289fdc3ef23`。
- 目标：对上传和分析产物矢量按用户、项目及 `data_rev` 复用 Cesium 数据源，合并隐藏视图更新。
- 范围：`frontend/src/App.tsx`、`frontend/src/components/Map3DGlobe.tsx`、`frontend/src/lib/globeProjectLayers.ts`、对应测试及本记录。其他源码不改。
- 禁止范围：后端、公开 API、资源 ID、GIS 数学、持久化格式、生产数据、依赖安装及发布配置。

## 行为

`GlobeProjectLayers.sync` 按几何修订决定解析，样式、透明度、可见性及层级原地更新。无合法修订的旧记录以数据内容比较，兼容旧客户端。用户或项目切换、图层删除、卸载会释放本模块拥有的源；既有城市和专题数据源保留。失败在下一次快照重试，不自动循环重试。

隐藏视图不启动新的 GeoJSON 解析、不逐要素应用样式。已经开始的解析不能中止，完成后留在未挂载状态；恢复时只对账最新快照。Cesium 的异步 `dataSources.add` 在完成后再次核对归属，迟到结果不会留在旧项目或销毁的视图中。

保留 Viewer、相机、底图、专题、截图与课堂编排。数据坐标、业务属性和输入 GeoJSON 不变。仅对当前项目缓存，不持久化到磁盘。

## 验证

- 聚焦命令：`npm test -- --maxWorkers=2 --minWorkers=1 src/__tests__/globeProjectLayers.test.ts src/__tests__/vectorStyle.test.ts src/__tests__/globeGeojson.test.ts`：3 文件、56 项通过，其中新缓存测试 29 项。
- 全量：`npm test -- --maxWorkers=2 --minWorkers=1`：90 文件、692 项通过，73.56 秒；未跳过用例或放宽超时。
- `npm run build`：通过，502 模块、5.18 秒；保留原有体积提示。`git diff --check` 通过。
- 测试使用真实 Cesium DataSourceCollection/Entity/Graphics，包括真实合成 LineString GeoJSON 解析；可控延迟只用于模拟异步边界。
- 隔离浏览器使用本地合成几何、本地空白底图和组件真实 Viewer，无后端：首次解析 1 次；十次普通刷新仍为 1；隐藏更新十次仍为 1；恢复后为 2；切换项目后为 3，当前数据源始终 1 个；相机高度从 350 万米调整到 250 万米；截图接口生成可显示图像；页面错误栏为空。
- 浏览器截图图像在页面中已核实；工具导出图片超时，没有声称保存成功。临时验收页面不纳入提交。
- lesson/session/report、TOP20、图例和截图相关现有回归仍通过，课堂入口和健康端点保留。

## 边界与回滚

未运行真实 QGIS、COM、模型调用、真实课堂或多显卡像素对照；解析调用次数不是延迟、FPS 或生产性能量测。隐藏前已经开始的解析仍可消耗 CPU。代码回退到起点，保留新教学数据，无持久化迁移。

本工作树使用清单一致的物理依赖副本，无生产数据 Junction。未修改主目录已有变更、其他任务工作树或临时验收页面以外的无关文件。提交、CI 与发布结果随 PR 记录。
