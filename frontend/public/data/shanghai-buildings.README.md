# 上海局部建筑模型

数据来源：© OpenStreetMap contributors，ODbL 1.0。https://www.openstreetmap.org/copyright
数据文件沿用 ODbL：https://opendatacommons.org/licenses/odbl/1-0/

2026-09-09 OSM 数据库快照（不是建筑采集日期）；陆家嘴、中心城区和松江新城三个小范围，边界见 GeoJSON 的 bounds。脚本 scripts/fetch_shanghai_buildings.py 可重建。保留每个要素的 OSM way ID、原始高度/楼层标签和来源链接。

1448 个闭合建筑轮廓：34 个带 height 标签（社区标注，非测绘保证）；117 个仅有楼层数，按每层 3 米估算，仅供形态比较；1297 个无可用高度，只显示地面轮廓。非完整覆盖，不可用缺失建筑或高度推算人口、容积率或统计城市密度。未处理复杂多面关系或建筑分部，因此不是精细建筑模型。

模型为 WGS84 坐标；内置模型观察时使用同坐标的 OSM 底图，退出后恢复原底图。模型无摄影纹理，不是倾斜摄影实景。底图瓦片在线加载；建筑文件随应用分发。
