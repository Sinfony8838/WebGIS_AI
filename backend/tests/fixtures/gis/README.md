# USGS 能登地震公开测试样本

原始 GeoJSON 共 35 个点，未经字段补齐或坐标修改。来源为美国地质调查局 USGS FDSN Event API，查询 2024-01-01 UTC、35–39°N、135–139°E、震级至少 4.5 的地震，按时间升序。

[原始查询](https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&starttime=2024-01-01T00:00:00&endtime=2024-01-02T00:00:00&minlatitude=35&maxlatitude=39&minlongitude=135&maxlongitude=139&minmagnitude=4.5&eventtype=earthquake&orderby=time-asc)

获取日期：2026-09-22。SHA256：`3adc7b2546c0dc1c4e0a25c1efc848ee90b82755f6ae2b50c6725f40035bec35`。

快照用于可重复回归，USGS 后续修订可能使重新下载的字节不同。数据无 `name` 字段；使用 `place` 作为标签。`mag` 范围 4.5–7.5，等距三档边界 4.5、5.5、6.5、7.5，左闭右开、末档两端包含，计数 29、5、1。空值或非数值应保留为未分级。
