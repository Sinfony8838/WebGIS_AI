"""中文检索评测样本集：104 条，分为调优集(tune)与保留测试集(heldout)。

每条样本的 expected 列出资料 ID 与依据（依据引用资料自身的
标题/关键词/区域/年份字段，不依赖模型判断）。语料见 corpus.json：
builtin 条目来自仓库内置知识库，eval_ 前缀为仅评测用的合成资料描述。

类别说明：
- natural     自然中文问法
- paraphrase  同义表达与别称
- region_year 地域/年份/指标约束（全国≠上海、人口数量≠密度、五普/六普/七普）
- ambiguous   无年份或无区域的宽泛问法（多个资料均可相关）
- no_answer   知识库中没有资料的问题（应如实返回无结果）
"""

from __future__ import annotations

from pathlib import Path

# 内置知识库条目 ID（与 backend/app/data/builtin/knowledge/kb_manifest.json 一致）
HU_LINE = "kb_hu_line"
HU_LINE_GEO = "hu_huanyong_line"
POP_DENSITY = "kb_population_density"
MIGRATION_FLOW = "kb_population_migration_flow"
TIME_SCOPE = "kb_population_data_time_scope"
CN_DISTRIBUTION = "sample_population_distribution_cn"
SH_DENSITY_PRECLASS = "shanghai_population_density_preclass"
CN_PATTERN_SUMMARY = "china_population_pattern_summary"
CENSUS_6 = "project_349d85af43884d3cb1b5904ce6bd0a94_upload"
CENSUS_5 = "project_349d85af43884d3cb1b5904ce6bd0a94_upload___a1f9b3d2"
CENSUS_7 = "project_349d85af43884d3cb1b5904ce6bd0a94_upload___fffdbf28"
CN_CLIMATE = "project_349d85af43884d3cb1b5904ce6bd0a94_upload___4aa48126"
KOPPEN_HD = "project_349d85af43884d3cb1b5904ce6bd0a94_upload_world_koppen_map_3892928b"
KOPPEN_LITE = "project_349d85af43884d3cb1b5904ce6bd0a94_upload_world_koppen_map_small_b7d4a859"
COASTAL_PULL = "coastal_attraction_population_migration"
BUFFER_GEO = "gis_buffer_analysis"

ALL_CENSUS = [CENSUS_5, CENSUS_6, CENSUS_7]
HU_LINE_SET = [HU_LINE, HU_LINE_GEO, "eval_hu_line_theme_map"]
SH_DENSITY_SET = [SH_DENSITY_PRECLASS, "eval_shanghai_density_2020", "eval_shanghai_density_video"]


def _sample(sid: str, query: str, category: str, split: str, expected: list[str], reason: str) -> dict:
    return {
        "id": sid,
        "query": query,
        "category": category,
        "split": split,
        "expected": expected,
        "reason": reason,
    }


SAMPLES: list[dict] = [
    # ---------- natural 自然问法 ----------
    _sample("n01", "胡焕庸线是一条什么线？", "natural", "tune", HU_LINE_SET,
            "三条资料标题/关键词均含“胡焕庸线”"),
    _sample("n02", "上海的人口密度怎么样？", "natural", "tune", SH_DENSITY_SET,
            "资料 region=shanghai 且标题/关键词含上海人口密度"),
    _sample("n03", "中国人口分布有什么特点？", "natural", "tune",
            [CN_DISTRIBUTION, CN_PATTERN_SUMMARY, HU_LINE],
            "两条 china 区域分布汇总资料与胡焕庸线卡片均直接讲中国人口分布特点"),
    _sample("n04", "什么是人口密度？", "natural", "tune", [POP_DENSITY],
            "概念问句，kb_population_density 即该概念卡片"),
    _sample("n05", "人口迁移流线应该怎么看？", "natural", "tune", [MIGRATION_FLOW],
            "判读方法问句对应“人口迁移流线判读”卡片"),
    _sample("n06", "使用人口普查数据要注意什么？", "natural", "tune", [TIME_SCOPE, "eval_census_method_doc"],
            "两条资料分别讲普查数据时点口径与常住人口/户籍人口口径"),
    _sample("n07", "缓冲区分析是怎么做的？", "natural", "tune", [BUFFER_GEO, "eval_buffer_analysis_video"],
            "geo 卡片与教学视频标题/关键词均含“缓冲区分析”"),
    _sample("n08", "中国的气候类型有哪些？", "natural", "tune", [CN_CLIMATE, "eval_china_climate_zoning"],
            "两条 china 区域气候类型/区划资料"),
    _sample("n09", "世界人口分布有什么规律？", "natural", "heldout", ["eval_world_population_map"],
            "资料标题“世界人口分布图”，region=global"),
    _sample("n10", "人口为什么向沿海地区迁移？", "natural", "heldout",
            [COASTAL_PULL, "eval_migration_causes_animation", "eval_china_migration_2020"],
            "沿海吸引力卡片讲迁移拉力，迁移成因动画与迁移流向图为同类支撑资料"),
    _sample("n11", "青藏高原为什么人口稀少？", "natural", "heldout", ["eval_qinghai_tibet_population"],
            "资料标题/关键词即青藏高原人口稀疏案例"),
    _sample("n12", "城镇化是怎么回事？", "natural", "heldout", ["eval_china_urbanization_2010"],
            "资料关键词含“城镇化/城市化”"),
    _sample("n13", "一月气温分布图能说明什么？", "natural", "heldout", ["eval_january_temperature_map"],
            "资料标题“全国1月气温分布图”"),
    _sample("n14", "常住人口和户籍人口有什么区别？", "natural", "heldout",
            ["eval_census_method_doc", TIME_SCOPE],
            "两条资料关键词均含常住人口、户籍人口、统计口径"),
    _sample("n15", "河网密度图有什么用？", "natural", "heldout", ["eval_china_river_density_map"],
            "资料标题“全国河网密度图”"),
    _sample("n16", "图层叠加分析怎么用于地理学习？", "natural", "heldout", ["eval_gis_overlay_doc"],
            "资料标题/关键词含“图层叠加/叠加分析”"),

    # ---------- paraphrase 同义表达 ----------
    _sample("p01", "黑河—腾冲线两侧人口差异很大，为什么？", "paraphrase", "tune", HU_LINE_SET,
            "kb_hu_line 关键词含“黑河腾冲线”，胡线资料同主题"),
    _sample("p02", "每平方千米居住多少人叫什么概念？", "paraphrase", "tune", [POP_DENSITY],
            "kb_population_density 关键词含“每平方千米”"),
    _sample("p03", "我国人口分布东多西少怎么解释？", "paraphrase", "tune",
            [HU_LINE, CN_DISTRIBUTION, CN_PATTERN_SUMMARY],
            "东密西疏/东多西疏是三条资料的共同关键词"),
    _sample("p04", "净迁入和净迁出在图上怎么看？", "paraphrase", "tune", [MIGRATION_FLOW],
            "卡片关键词含“净迁移/净迁入/迁出”"),
    _sample("p05", "五普是哪一年开展的？", "paraphrase", "tune", [CENSUS_5],
            "五普资料 time=2000，关键词含“五普”"),
    _sample("p06", "柯本气候分区把世界分成哪些类型？", "paraphrase", "tune", [KOPPEN_HD],
            "柯本图为同一图的高清/轻量变体，判重后返回其一即可"),
    _sample("p07", "全国人口总数有哪年的资料？", "paraphrase", "tune",
            ["eval_china_count_2010", "eval_china_count_2020"],
            "两条资料关键词含“人口数量/总数”，年份分别为2010/2020"),
    _sample("p08", "人口从内陆流向东南沿海是什么原因？", "paraphrase", "tune",
            [COASTAL_PULL, "eval_migration_causes_animation"],
            "沿海吸引力与迁移成因资料同主题"),
    _sample("p09", "户籍人口的口径要注意什么？", "paraphrase", "tune",
            ["eval_census_method_doc", TIME_SCOPE],
            "两条资料关键词含“户籍人口/统计口径”"),
    _sample("p10", "沿海地区凭什么吸引人？", "paraphrase", "heldout", [COASTAL_PULL],
            "资料标题“沿海吸引力”，标签含区位优势"),
    _sample("p11", "空间分析里的 buffer 是什么？", "paraphrase", "heldout", [BUFFER_GEO, "eval_buffer_analysis_video"],
            "缓冲区分析卡片/视频对应英文 buffer 概念"),
    _sample("p12", "中国人口地理的分界线叫什么？", "paraphrase", "heldout", HU_LINE_SET,
            "kb_hu_line 关键词含“人口地理分界线”"),
    _sample("p13", "人口稠密区主要分布在东南半壁吗？", "paraphrase", "heldout",
            [HU_LINE, CN_DISTRIBUTION, CN_PATTERN_SUMMARY],
            "东密西疏即东南半壁人口稠密，同三条分布资料"),
    _sample("p14", "统计表里的时点数据怎么读？", "paraphrase", "heldout",
            [TIME_SCOPE, "eval_census_method_doc"],
            "两条口径资料讲数据时点与统计单位"),
    _sample("p15", "等温线图在冬天能看出什么？", "paraphrase", "heldout", ["eval_january_temperature_map"],
            "1月气温图关键词含“等温线”，冬季即1月"),
    _sample("p16", "推拉理论怎么解释进城打工潮？", "paraphrase", "heldout",
            ["eval_migration_causes_animation", COASTAL_PULL],
            "动画关键词含“推拉理论”，沿海吸引力卡片讲拉力"),
    _sample("p17", "六普数据是哪年的？", "paraphrase", "heldout", [CENSUS_6],
            "六普资料 time=2010，关键词含“六普”"),
    _sample("p18", "GIS 里做邻近范围用什么分析？", "paraphrase", "heldout", [BUFFER_GEO, "eval_buffer_analysis_video"],
            "缓冲区分析用于邻近性判断，geo 卡片与视频同主题"),
    _sample("p19", "服务半径怎么画出来？", "paraphrase", "heldout", [BUFFER_GEO, "eval_buffer_analysis_video"],
            "缓冲区卡片教学要点：“点缓冲区常用于服务半径”"),
    _sample("p20", "水系图能看出河流疏密吗？", "paraphrase", "heldout", ["eval_china_river_density_map"],
            "资料关键词含“河流/水系/河网密度”"),

    # ---------- region_year 地域/年份/指标约束 ----------
    _sample("r01", "上海2010年的人口普查资料", "region_year", "tune", ["eval_shanghai_census_2010"],
            "该资料 region=shanghai 且 time=2010，标题含上海人口普查"),
    _sample("r02", "上海2020年人口密度图", "region_year", "tune", ["eval_shanghai_density_2020"],
            "region=shanghai，time=2020，标题为人口密度图"),
    _sample("r03", "全国2000年人口密度", "region_year", "tune", ["eval_china_density_2000"],
            "region=china，time=2000 的密度图；2020 年资料应让位"),
    _sample("r04", "2000年人口普查资料", "region_year", "tune", [CENSUS_5],
            "五普资料 time=2000；六普/七普年份冲突应靠后"),
    _sample("r05", "2010年人口普查资料", "region_year", "tune", [CENSUS_6],
            "六普资料 time=2010"),
    _sample("r06", "七普资料", "region_year", "tune", [CENSUS_7, TIME_SCOPE],
            "七普资料与含“七普”关键词的数据时点卡片"),
    _sample("r07", "全国2020年人口数量", "region_year", "tune", ["eval_china_count_2020"],
            "region=china，time=2020，指标为人口数量（非密度）"),
    _sample("r08", "全国2010年人口数量统计", "region_year", "tune", ["eval_china_count_2010"],
            "region=china，time=2010，人口数量统计表"),
    _sample("r09", "上海人口密度分布图", "region_year", "tune", SH_DENSITY_SET,
            "三条上海人口密度资料（课前图/2020图/视频）"),
    _sample("r10", "全国人口迁移流向2020", "region_year", "tune", ["eval_china_migration_2020"],
            "region=china，time=2020 的迁移流向图"),
    _sample("r11", "世界人口分布图", "region_year", "heldout", ["eval_world_population_map"],
            "region=global 的世界人口分布图"),
    _sample("r12", "中国人口密度图", "region_year", "heldout", [POP_DENSITY, "eval_china_density_2000"],
            "china 区域的概念卡片与密度图；上海资料不应进入"),
    _sample("r13", "上海市青浦区的人口案例", "region_year", "heldout", ["eval_shanghai_qingpu_case"],
            "资料标题含上海青浦区案例，region=shanghai"),
    _sample("r14", "六普是哪一年开展的", "region_year", "heldout", [CENSUS_6],
            "六普资料 time=2010，关键词含六普"),
    _sample("r15", "全国1月降水分布有什么特点", "region_year", "heldout", ["eval_january_precipitation_map"],
            "资料标题“全国1月降水分布图”"),
    _sample("r16", "全国1月气温分布", "region_year", "heldout", ["eval_january_temperature_map"],
            "资料标题“全国1月气温分布图”"),
    _sample("r17", "中国气候区划", "region_year", "heldout", ["eval_china_climate_zoning", CN_CLIMATE],
            "两条 china 区域气候区划/类型资料"),
    _sample("r18", "2010年城镇化资料", "region_year", "heldout", ["eval_china_urbanization_2010"],
            "资料 time=2010，关键词含城镇化"),
    _sample("r19", "全球人口分布", "region_year", "heldout", ["eval_world_population_map"],
            "region=global；全国资料不应冒充全球"),
    _sample("r20", "七普数据时点要注意什么", "region_year", "heldout", [TIME_SCOPE, CENSUS_7],
            "时点口径卡片 time=2020 且关键词含七普；七普资料同年份"),
    _sample("r21", "上海青浦人口文档", "region_year", "heldout", ["eval_shanghai_qingpu_case"],
            "标题/关键词含上海、青浦，类型为文档"),
    _sample("r22", "2000年的全国人口密度图", "region_year", "heldout", ["eval_china_density_2000"],
            "region=china，time=2000 的密度图"),
    _sample("r23", "2020年全国迁移流线图", "region_year", "heldout",
            ["eval_china_migration_2020", MIGRATION_FLOW],
            "2020 迁移流向图与流线判读卡片（general 区域不冲突）"),
    _sample("r24", "世界柯本气候图", "region_year", "heldout", [KOPPEN_HD],
            "柯本图高清变体，判重后返回其一"),
    _sample("r25", "全国人口密度2020年", "region_year", "heldout", [POP_DENSITY],
            "china/2020 的人口密度概念卡片；2000 年密度图年份冲突"),
    _sample("r26", "上海常住人口密度", "region_year", "heldout", SH_DENSITY_SET,
            "上海密度资料，2020 图关键词含常住人口"),
    _sample("r27", "中国人口分布特点汇总", "region_year", "heldout",
            [CN_PATTERN_SUMMARY, CN_DISTRIBUTION],
            "标题即“中国人口分布特点与成因汇总”与读图示例"),
    _sample("r28", "五普到七普的对比资料", "region_year", "heldout", ALL_CENSUS,
            "三次普查资料 time 分别为 2000/2010/2020，五普摘要明示时序对比"),
    _sample("r29", "青藏高原人口分布案例", "region_year", "heldout", ["eval_qinghai_tibet_population"],
            "标题/关键词含青藏高原人口稀疏案例"),
    _sample("r30", "城镇化2010", "region_year", "heldout", ["eval_china_urbanization_2010"],
            "资料 time=2010，关键词含城镇化"),

    # ---------- ambiguous 宽泛/歧义 ----------
    _sample("a01", "人口普查资料有哪些", "ambiguous", "tune",
            ALL_CENSUS + ["eval_shanghai_census_2010", "eval_census_method_doc"],
            "无年份/区域约束时三普资料、上海普查与口径说明均相关"),
    _sample("a02", "人口密度图", "ambiguous", "tune",
            ["eval_china_density_2000", SH_DENSITY_PRECLASS, "eval_shanghai_density_2020", POP_DENSITY],
            "各区域/年份的密度图与概念卡片均可相关"),
    _sample("a03", "人口迁移的资料", "ambiguous", "tune",
            [MIGRATION_FLOW, "eval_china_migration_2020", "eval_migration_causes_animation", COASTAL_PULL],
            "迁移判读/流向/成因/拉力四条资料同主题"),
    _sample("a04", "气候方面的图", "ambiguous", "tune",
            ["eval_china_climate_zoning", KOPPEN_HD, "eval_january_precipitation_map",
             "eval_january_temperature_map", CN_CLIMATE],
            "气候区划图、柯本图、降水/气温图与气候类型资料均含“图”且属气候主题"),
    _sample("a05", "上海的资料", "ambiguous", "tune",
            [SH_DENSITY_PRECLASS, "eval_shanghai_density_2020", "eval_shanghai_density_video",
             "eval_shanghai_qingpu_case", "eval_shanghai_census_2010"],
            "五条 region=shanghai 资料在 top5 内即满分"),
    _sample("a06", "人口数据", "ambiguous", "tune",
            [TIME_SCOPE, "eval_census_method_doc"],
            "泛问“人口数据”时，口径/时点类卡片是最直接相关的资料"),
    _sample("a07", "普查", "ambiguous", "heldout",
            ALL_CENSUS + ["eval_shanghai_census_2010", "eval_census_method_doc"],
            "仅含“普查”一词，普查类资料均相关"),
    _sample("a08", "密度", "ambiguous", "heldout",
            [POP_DENSITY, "eval_china_density_2000", "eval_shanghai_density_2020",
             SH_DENSITY_PRECLASS, "eval_china_river_density_map"],
            "未限定人口或河网时，两类密度资料均相关"),
    _sample("a09", "中国资料", "ambiguous", "heldout", [CN_PATTERN_SUMMARY, CN_DISTRIBUTION],
            "泛中国查询以两条汇总资料为最相关"),
    _sample("a10", "迁移图", "ambiguous", "heldout", ["eval_china_migration_2020", MIGRATION_FLOW],
            "迁移流向图与流线判读卡片"),
    _sample("a11", "讲解视频", "ambiguous", "heldout", ["eval_buffer_analysis_video", "eval_shanghai_density_video"],
            "资料类型约束：两条标题含“视频”的资料"),
    _sample("a12", "上海人口", "ambiguous", "heldout",
            [SH_DENSITY_PRECLASS, "eval_shanghai_density_2020", "eval_shanghai_density_video",
             "eval_shanghai_qingpu_case", "eval_shanghai_census_2010"],
            "五条上海人口资料均为相关结果"),

    # ---------- no_answer 无答案 ----------
    _sample("x01", "今天上海的天气怎么样", "no_answer", "tune", [],
            "语料只有人口/气候资料，无天气实况类资料"),
    _sample("x02", "上海明天会下雨吗", "no_answer", "tune", [],
            "无天气预报类资料"),
    _sample("x03", "中国的GDP是多少", "no_answer", "tune", [],
            "无经济总量资料"),
    _sample("x04", "如何用Python画人口金字塔", "no_answer", "tune", [],
            "无编程教学资料"),
    _sample("x05", "人口密度和股票价格的关系", "no_answer", "tune", [],
            "无金融资料；不应因出现“人口密度”就返回密度图"),
    _sample("x06", "珠穆朗玛峰有多高", "no_answer", "tune", [],
            "无地形高程资料"),
    _sample("x07", "语文课怎么讲比喻修辞", "no_answer", "tune", [],
            "语料为地理教学资料"),
    _sample("x08", "新冠疫情期间的人口流动数据", "no_answer", "tune", [],
            "无疫情时期流动数据资料"),
    _sample("x09", "2025年最新人口数据", "no_answer", "tune", [],
            "语料最晚到2020年；不同统计年份不得混淆"),
    _sample("x10", "河流的航运价值怎么评价", "no_answer", "tune", [],
            "河网密度图不涉及航运价值"),
    _sample("x11", "怎么下载这些地图", "no_answer", "tune", [],
            "操作流程类问题，非资料检索"),
    _sample("x12", "七普的房价数据", "no_answer", "tune", [],
            "普查资料不含房价指标"),
    _sample("x13", "月球表面的地形是什么样的", "no_answer", "tune", [],
            "无天文资料"),
    _sample("x14", "唐朝的都城在哪里", "no_answer", "tune", [],
            "无历史朝代资料"),
    _sample("x15", "光合作用的过程", "no_answer", "tune", [],
            "无生物资料"),
    _sample("x16", "美元汇率今天多少", "no_answer", "heldout", [],
            "无金融行情资料"),
    _sample("x17", "英语语法怎么学", "no_answer", "heldout", [],
            "无英语教学资料"),
    _sample("x18", "推荐一部地理纪录片", "no_answer", "heldout", [],
            "无纪录片推荐资料；动画/视频均为知识点讲解"),
    _sample("x19", "2021年的房价走势", "no_answer", "heldout", [],
            "无房价资料"),
    _sample("x20", "交通流量数据怎么获取", "no_answer", "heldout", [],
            "无交通流量资料"),
    _sample("x21", "全国人口出生率排名", "no_answer", "heldout", [],
            "语料无出生率指标资料；人口数量表不等于出生率"),
    _sample("x22", "请告诉我下周的考试安排", "no_answer", "heldout", [],
            "教务信息非知识库资料"),
    _sample("x23", "火山喷发的原因", "no_answer", "heldout", [],
            "无火山地质资料"),
    _sample("x24", "上海的房价地图", "no_answer", "heldout", [],
            "上海资料均为人口主题，无房价地图"),
    _sample("x25", "世界EndDate未日地图", "no_answer", "heldout", [],
            "无此资料；同时检验乱码词不引发误报"),
    _sample("x26", "缓冲区分析的英文缩写怎么读", "no_answer", "heldout", [],
            "缓冲区资料讲概念与步骤，不涉及缩写读音"),
]


def load_samples() -> list[dict]:
    return [dict(sample) for sample in SAMPLES]


def samples_path() -> Path:
    return Path(__file__).resolve().parent / "samples.py"


if __name__ == "__main__":
    counts: dict[str, int] = {}
    for sample in SAMPLES:
        counts[sample["category"]] = counts.get(sample["category"], 0) + 1
    print("total:", len(SAMPLES), counts)
    splits: dict[str, int] = {}
    for sample in SAMPLES:
        splits[sample["split"]] = splits.get(sample["split"], 0) + 1
    print("splits:", splits)
