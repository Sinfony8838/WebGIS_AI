# 中国及周边400毫米年降水量对照线

用于人口分布课堂中对照胡焕庸线。它是一组气候等值线，不是人口分界线、国界或2020年实测降水边界。

## 来源与许可

- DWD / GPCC，Rustemeier、Finger、Schirmeister、Ziese（2025），GPCC Precipitation Analysis Climatology V2025，0.25°，选择1991—2020年气候值。
- [数据说明与下载](https://opendata.dwd.de/climate_environment/GPCC/html/gpcc_precipitation_analysis_climatology_v2025_doi_download.html)，[DOI](https://doi.org/10.5676/DWD_GPCC/CLIMAT_V2025_025)。
- [DWD官方使用条件](https://www.dwd.de/EN/service/legal_notice/legal_notice.html)：CC BY 4.0，保留署名并说明修改。本数据由 GeoBot 完成年总量计算、区域截取与等值线提取。
- 原始 gzip：28,442,738 字节；官方 MD5 `d701c717e08ce6ad457c9f4004984d65`；SHA256 `3bd80d05df52572f6409b594ae26b43e9045147cb3c25254cddb5a934c16e5c5`。原始数据只在忽略缓存保存，不随应用加载。

## 算法与限制

12个月降水气候值（mm/month）求和得到年降水量（mm/year）；任何月份缺失、负值或非有限值的格点均排除，不以零补齐。使用真实格点中心坐标线性提取400毫米等值线，不沿省界拼接、不按人口数据拟合、不平滑、不舍弃局部闭合分支。范围为73–136°E、18–55°N的中国及周边矩形窗口，边缘处允许曲线截断。

原始数值纬度从89.875递减到-89.875，沿用北正南负坐标；文件的`degrees_south`属性与数值方向不一致，不据此倒置纬度。已用北京、上海、塔克拉玛干及南半球网格样本核对方向。生成14段曲线、983个顶点；四舍五入至6位小数仅用于存储，不代表该精度的地理可信度。独立双线性回查所有顶点，最大降水残差约0.00112毫米。

GPCC由雨量站资料插值得到。1991—2020产品各站至少有20个完整年，站点覆盖、插值和雨量计误差影响结果；本处理未额外施加雨量计系统误差校正。0.25°网格适合区域格局对照，不适合判断街区，也不能单凭两条线的位置证明人口分布的因果关系。

## 复现

在仓库根目录运行：

```powershell
python -m pip install -r scripts/requirements-geodata.txt
python scripts/build_precipitation_comparison.py --download
python -m pytest backend/tests/test_precipitation_comparison.py -q
```

已有缓存时省略`--download`即可离线重建；源文件校验不符时拒绝生成。应用运行只读取GeoJSON，不依赖科学计算包或外部降水服务。课堂先完成自主绘线，再在胡焕庸线图例中打开“对照400毫米年降水量线”；世界/上海等下一场景会隐藏本图层。原有课时和题目不变。
