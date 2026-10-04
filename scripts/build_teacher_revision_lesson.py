"""Reproducible teacher-revision lesson; the original Word remains private."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHA = "d26a413034dfdb0fdd1a5d8c1674cb8b35f7f0b4e0796a49b6c29e452727731a"


def scene(region="world", maps=(), catalog=(), base="amap_light", hu=False):
    center, zoom = {"world": ([15, 20], 2), "china": ([104, 35], 4), "shanghai": ([121.47, 31.23], 9),
                    "finland": ([26, 64], 5), "tarim": ([84, 39], 6), "northeast": ([126, 45], 6)}[region]
    return {"basemap_id": base, "templates": ["hu_line_comparison"] if hu else [],
            "strict_resources": True,
            "catalog_layers": list(catalog), "teaching_maps": [{"id": m, "opacity": .5} for m in maps],
            "layer_visibility": {"builtin_population_regions": False, "builtin_population_density": False,
                                 "builtin_population_migration": False, "generated_hu_line": hu},
            "view": {"center": center, "zoom": zoom}, "annotations": [], "visual_query": None,
            "globe": {"enabled": False}}


def action(id, label, type="scene", **kwargs):
    return {"action_id": id, "label": label, "type": type, **kwargs}


def question(id, text, answer, options=(), index=None, images=(), material=""):
    return {"question_id": id, "type": "choice" if options else "open", "text": text,
            "source": "teacher_manual", "material": material, "options": list(options), "answer_index": index,
            "answer": answer, "expected_points": [answer], "misconceptions": [],
            "images": [{"url": f"/files/uploads/teacher_population_revised/source_row_{row}_{n}.png", "order": i}
                       for i, (row, n) in enumerate(images)]}


def stage(id, title, row, initial, questions=(), actions=(), unit="人口分布", point="", task="", conclusion=""):
    return {"stage_id": id, "title": title, "kind": "practice" if questions else "presentation", "minutes": 0,
            "timing_mode": "teacher", "source_row": row, "scene": initial, "questions": list(questions),
            "actions": list(actions), "knowledge_unit": unit, "knowledge_point": point or title,
            "script": [task or "先观察材料并回答问题，再由教师确认归纳。"], "material": task,
            "student_activities": [task] if task else [], "teacher_activities": ["教师决定显示材料、揭示答案及进入下一环节的时机。"],
            "knowledge_conclusion": conclusion, "assistant_prompts": [],
            "evidence_refs": [{"type": "source", "label": f"张玥修订稿 第{row+1}行", "source_id": "teacher_population_revised"}]}


WORLD = scene(maps=["worldpop_global_teacher"], base="amap_imagery")
CHINA = scene("china", catalog=["china_province_population_density"], hu=True)
FINLAND = scene("finland", maps=["finland_population"])
SUMMARY = "只使用本环节已展示材料和可视图层及其来源年份，生成简短小结草稿。区分读图判断与数值统计，不补写学生回答，不凭最后一张地图假装看到了全部因素。教师确认后再用于展示。"
STAGES = [
    stage("world_intro", "世界导入 人类迁徙与人口集聚", 12, WORLD,
          [question("world_circle", "按材料示意在亚洲附近圈定区域：圈内与圈外哪一侧人口更多？请先提出判断，再核对统计。", "以本次圈定范围的实际统计为准，不预设圈内必定超过一半。")],
          [action("migration_video", "智人迁徙视频", "video", url="https://www.bilibili.com/video/BV1NW4y1w7ry/", note="原稿建议约2分钟，教师点击播放。"),
           action("world_map", "世界人口与影像", scene=WORLD, resource_rows=[12]),
           action("circle_statistics", "圈内外人口统计", "statistics", source_id="worldpop_global_2015")],
          task="观看迁徙材料，观察世界人口图。使用绘区工具画出可统计的范围，先判断后比较人口占比。"),
    stage("world_features", "方法建构 世界人口分布特征", 13, WORLD,
          [question("world_pattern", "从总体、半球与纬度、距海远近、海拔、大洲和国家六个角度描述世界人口分布。", "总体分布不均；可结合图例和材料说明主要人口集聚区、北半球及中低纬度、沿海与低地等总体倾向，同时注意例外。")],
          [action("overall", "总体", scene=WORLD, resource_rows=[13], note="找出稠密区和稀疏区，用具体位置描述。"),
           action("latitude", "半球及纬度", scene=WORLD, note="原稿约90%及10°—50°N作为教材描述材料，不称为本次实时统计。"),
           action("coast", "距海远近", scene=WORLD, note="使用测距工具从中亚向东部沿海测量公里数；一条测线用于案例比较，不能证明全球因果规律。原稿约60%在距海200公里内为教材材料。"),
           action("altitude", "海拔高度", scene=scene(base="amap_imagery", maps=["worldpop_global_teacher"]), note="结合地貌影像和地图剖面工具比较低地与高地；原稿约80%在500米以下为教材材料，不是实时海拔分组统计。"),
           action("continents", "大洲", scene=WORLD, note="教材描述：亚洲人口最多；亚洲、非洲及拉丁美洲约占85%。保留为教材历史概括，不称为本次实时统计。区分南极常住人口与考察人员。"),
           action("countries", "国家", scene=scene(catalog=["world_population_density"]), note="原稿2023年人口过亿国家：印度、中国、美国、印度尼西亚、巴西、巴基斯坦、尼日利亚、孟加拉国、俄罗斯、日本、墨西哥、埃塞俄比亚、菲律宾、越南。此处仅列原稿名单，不代表实时排名；国家平均密度图为2019年资料。"),
           action("world_summary", "世界分布小结", "summary", prompt=SUMMARY)],
          task="逐项读图与比较；描述时说明位置、程度、尺度和资料年份。"),
    stage("reading_method", "方法归纳 宏观与微观描述", 14, WORLD,
          actions=[action("method_board", "描述方法板书", "activity", note="宏观：空间范围、总体疏密、均匀程度、分布形态。微观：哪里多与少、尺度差异、极值、特殊区域；变化趋势需要可比的多期资料。")],
          task="将读图结果整理为宏观和微观两个层次；单期地图不能说明变化趋势。"),
    stage("china_practice", "方法练习 中国与胡焕庸线", 15, CHINA,
          [question("china_pattern", "描述中国人口分布特点，并说明胡焕庸线两侧的差异。", "总体东南稠密、西北稀疏；东部平原、沿海和河流附近较集中，局地仍有例外。参考线概括总体格局，不是人口硬边界。"),
           question("china_video", "观看材料后说明胡焕庸线的划分依据、两侧差异及地理意义。", "结合人口资料比较两侧的总体疏密差异；作为分析区域人口格局的参考。胡焕庸线不等于400毫米年降水量线。")],
          [action("china_map", "案例1 中国", scene=CHINA),
           action("hu_video", "胡焕庸线视频", "video", url="https://www.bilibili.com/video/BV13p4y1X7LU/"),
           action("west_research", "跨越发展空间证据", "activity", note="课后研究胡焕庸线能否打破：记录来源、年份、链接和位置，收集西部城镇、能源或电商案例；学生纸笔整理或教师代录，不预设研究结论。")],
          task="本版按教师稿先展示胡焕庸线，再开展描述与解释。"),
    stage("shanghai_practice", "方法练习 上海人口分布", 15, scene("shanghai", catalog=["shanghai_population_density"]),
          [question("shanghai_pattern", "描述上海人口分布特点，哪些资料支持中心—外围、圈层与副中心的判断？", "总体较密但分布不均，中心与外围存在差异；圈层和副中心需结合较细人口网格或教师原图，区级均值不能精确证实。")],
          [action("shanghai_map", "案例2 上海", scene=scene("shanghai", catalog=["shanghai_population_density"]), resource_rows=[15]),
           action("shanghai_grid", "上海人口网格", scene=scene("shanghai", maps=["shanghai_worldpop_teacher"]), resource_rows=[15], note="2015年WorldPop约1公里模型估计，辅助观察中心—外围；教师原稿2020年街镇图保留为独立材料，网格不能精确证明街镇圈层或副中心。")],
          task="沿用宏观与微观描述方法，分别核对教材材料、区级统计和人口网格能支持的判断。"),
    stage("factor_transition", "影响因素过渡 可选材料", 16, scene(base="nasa_nightlights_2016"),
          actions=[action("lights_video", "夜间灯光视频", "video", url="https://www.bilibili.com/video/BV1uj421U7i2/", note="原稿建议约2分41秒；过渡文案由教师后续补充，可跳过。"),
                   action("lights_question", "灯光观察任务", "activity", note="比较尼罗河、朝鲜半岛附近灯光和高纬度地区；灯光可能来自渔船或工业活动，不能等同人口。")],
          task="原稿注明过渡素材待教师完善。现阶段只提供候选视频和观察任务，不自动播放。"),
    stage("natural_factors", "影响因素 自然条件", 17, scene("china", catalog=["china_province_population_density"]),
          [question("tarim_water", "塔里木盆地的绿洲和聚落为什么主要分布在盆地边缘及河流附近？", "山地来水为生活与灌溉农业提供条件，在盆地边缘形成局部绿洲与聚落。"),
           question("sparse_regions", "解释干旱区、高纬度、高海拔及热带雨林地区部分区域人口稀疏的原因。", "结合具体材料解释水源、热量、地形或湿热环境怎样影响生产生活，不只罗列因素名称。")],
          [action("climate", "气候", scene=scene("china", maps=["china_precipitation", "china_jan_temperature"], catalog=["china_province_population_density"]), note="比较长期平均降水和1月平均气温；实时天气不能替代气候资料。"),
           action("terrain", "地形", scene=scene("china", maps=["china_topography"], catalog=["china_province_population_density"])),
           action("water", "水资源", scene=scene("tarim", base="amap_imagery", catalog=["china_major_rivers"]), resource_rows=[17], note="塔里木教材图作为原图材料对照；影像和河流用于位置参照，不把未配准的原图当作精确叠置。"),
           action("soil", "土壤", scene=scene("northeast", maps=["northeast_population"]), resource_rows=[17], note="对照教师原稿2019年东北人口图与土壤配图、2015年人口网格。土壤配图为读图材料，未经配准不作为精确叠置。土壤通过农业条件影响人口，还需结合气候、经济及历史。"),
           action("minerals", "矿产与城市", "activity", note="在地图上定位克拉玛依、大庆、大同，结合教师材料说明资源开发与城市发展。", scene=scene("china", base="amap_imagery", catalog=["world_major_cities"]))],
          unit="影响人口分布的因素", task="每次聚焦一种因素，比较人口与环境证据，并说明其作用过程。"),
    stage("human_factors", "影响因素 人文条件", 18, scene(base="nasa_nightlights_2016"),
          actions=[action("production", "社会生产方式", "activity", note="农业社会案例：尼罗河平原、两河流域；工业社会案例：长三角、珠三角、欧洲西部、北美东部。"),
                   action("economy", "经济发展", scene=scene(base="nasa_nightlights_2016"), note="灯光和城市夜景用于观察经济活动，亮度不等于人口密度；经济发达也不能无条件推出人口稠密。"),
                   action("history", "历史因素", "activity", note="东亚、南亚开发历史与人口集聚的教材案例。"),
                   action("politics", "政治因素", "activity", note="深圳政策与人口迁入、巴西利亚迁都案例；原稿深圳1300万人为历史材料，不能表述为现时人口。"),
                   action("military", "军事因素", "activity", note="使用原稿战争与人口流失案例；不补写未经核实的现时人口或伤亡数字。"),
                   action("culture", "文化因素", "activity", note="伦敦唐人街等案例，分析文化联系与聚居；避免把民族背景当成唯一成因。"),
                   action("human_summary", "影响因素小结", "summary", prompt=SUMMARY)],
          unit="影响人口分布的因素", task="结合各案例解释生产、就业、历史、政策和文化怎样共同影响人口分布。"),
    stage("factor_summary", "归纳总结 建立知识框架", 19, scene("china", catalog=["china_province_population_density"]),
          actions=[action("factor_board", "因素框架板书", "activity", note="自然因素：气候、地形、水资源、土壤及资源条件。人文因素：生产方式、经济、历史、政策、军事、文化。用材料说明条件—生产生活—人口集聚的作用过程。"),
                   action("factor_handout", "生成小结草稿", "summary", prompt=SUMMARY)],
          unit="影响人口分布的因素", task="归纳本课已覆盖的因素，区分总体规律、局地例外和资料能够证明的内容。"),
    stage("finland_application", "小试牛刀 芬兰综合探究", 20, FINLAND,
          [question("finland_pattern", "读图描述芬兰人口分布特点。", "分布不均，人口密度较低，南多北少；赫尔辛基及周边集聚。", images=[(20,1)], material="教师稿2015年案例：约550万人，赫尔辛基及周边约140万人；保留原年份。"),
           question("finland_climate", "对照人口与气候图，解释气温和降水的影响。", "南部与沿海相对较温暖、降水较多，生产生活条件有利；北部条件不同。", images=[(20,2)]),
           question("finland_terrain", "对照人口与地形图，解释地形的影响。", "南部低地较多，交通与生产生活条件较有利；分析时还需结合其他因素。", images=[(20,3)]),
           question("finland_human", "为何较多人口集中于赫尔辛基及周边城镇？", "首都及经济、文化、交通中心的综合作用，结合历史和就业条件说明。")],
          [action("finland_1", "案例3-1 人口", scene=FINLAND),
           action("finland_2", "案例3-2 气候", scene=scene("finland", maps=["finland_population", "finland_climate"])),
           action("finland_3", "案例3-3 地形", scene=scene("finland", maps=["finland_population", "finland_topography"])),
           action("finland_overlay", "三图叠置实验", scene=scene("finland", maps=["finland_population", "finland_climate", "finland_topography"]), note="分别调整透明度，提出候选分界，不把0℃或某条等高线当作唯一正确答案。"),
           action("finland_reproduce", "数据复现 PyQGIS", "workflow", scene=scene("finland", catalog=["finland_population_density_2015"]), note="2015年WorldPop网格聚合为0.1°教学网格，再按人数与实际面积计算密度；与教材图分别标注。"),
           action("finland_review", "手绘分界与协同审阅", "summary", prompt="根据当前地图截图、教师实际绘制的检索区或标注及已展示的芬兰材料，分析分界两侧差异并提出修正建议。没有划线或数值图层时明确资料不足，不编造两侧统计。"),
           action("finland_export", "探究报告导出", "activity", note="保留自己的初始分界和修正理由；确认分析摘要后导出含地图、图例、标注与来源的PNG。")],
          unit="影响人口分布的因素", task="先读三张图并回答四个问题，再由代表或教师绘制候选分界；AI仅提供可修改的参考草稿。"),
    stage("reinforcement", "强化训练 四组区域案例", 21, scene(),
          [question("central_asia_1", "中亚五国材料：下列国家中人口密度最小的是？", "哈萨克斯坦", ["土库曼斯坦", "哈萨克斯坦", "吉尔吉斯斯坦", "塔吉克斯坦"], 1, [(21,1)]),
           question("central_asia_2", "影响中亚东南部地区人口较密集的主要自然因素是？", "水源", ["热量", "矿产", "水源", "土壤"], 2, [(21,1)]),
           question("germany_aging", "据2018年德国各州65岁及以上人口密度图，描述德国老龄人口密度分布特征。", "分布不均，西部密度大，东部密度小，东北部差异显著。", images=[(21,2)]),
           question("russia_line", "推测俄罗斯圣彼得堡—图瓦线西南侧人口分布状况的主要原因。", "东欧平原、气候相对温和；开发历史悠久，工农业、经济和交通条件较好，城市较多。", images=[(21,3)]),
           question("yarlung", "结合雅鲁藏布江流域河谷、冲洪积扇材料，分析当地居民定居的原因。", "结合具体地形说明防灾、水源、热量、土壤、耕作、放牧和建房条件，避免把整个高原概括为条件优越。", images=[(21,4)])],
          unit="影响人口分布的因素", task="原稿四组案例保留题图、年份和来源；先作答，再由教师揭示参考答案。"),
    stage("homework_reflection", "课后探究与课堂复盘", 23, scene(),
          actions=[action("homework_card", "课后任务卡", "activity", note="任务一：胡焕庸线能否打破，收集有来源和位置的西部发展证据。任务二：提出芬兰人口分界并说明证据和修正。下次课展示纸笔或教师端导出的成果。"),
                   action("class_review", "课堂回顾草稿", "summary", prompt=SUMMARY)],
          task="课堂记录区分真实回答、教师代录与预设示例。未采集回答时保持未采集；教学反思作为设计与复盘框架，不能自动宣称教学效果已证实。"),
]

LESSON = {"lesson_id": "lesson_builtin_population_teacher_revised", "title": "人口分布 张玥修订稿教学课时", "source": "builtin",
          "subject": "地理", "grade": "人教版高中地理必修第二册 第一章第一节", "objectives": ["运用资料描述世界、中国、上海及芬兰的人口分布特点", "掌握宏观与微观描述方法", "结合空间证据分析自然与人文影响因素", "通过绘图、比较、修正和成果导出开展地理探究"],
          "metadata": {"builtin_version": "2", "recommended": True, "pacing_mode": "teacher", "duration_minutes": 0,
                       "population_topic": True, "reference": "张玥 人口分布稿本设计 修订稿",
                       "source_document": {"filename": "1-人口分布稿本设计.docx", "sha256": SOURCE_SHA, "designer": "张玥", "revision": "用户提供的修订稿"},
                       "curriculum_standard": "本课为普通高中地理课程；原稿列出的义务教育2022课标不能替代高中课标。课标要求与GeoAI教学扩展分别表述。",
                       "data_limitations": ["教材历史比例不作为当前栅格的实时计算结果", "单期数据不能推断变化趋势", "图片必须完成配准才可空间叠置", "WorldPop为模型估计，年份与分辨率随图显示"],
                       "student_participation": "教师端展示、纸笔活动、代表操作或教师代录；不新增独立学生作业平台"},
          "plan": {"pacing_mode": "teacher", "duration_minutes": 0,
                   "design_thinking": "从世界人口分布与迁徙材料引入观察任务，通过总体、纬度、海陆、地形、大洲和国家六个角度建立读图方法，再以中国和上海练习宏观与微观描述。结合自然和人文条件分析作用过程，以芬兰三图叠置、手绘分界和修正建议开展综合探究，最后用区域题与课后任务检查学习，教师自主决定推进与揭示时机。",
                   "board_design": "人口分布：宏观与微观描述；自然条件与人文条件；证据—解释—例外；芬兰分界初稿—修正依据。",
                   "reflection": "观察学生是否能准确描述空间差异、解释因素作用过程及引用材料。尚未采集的课堂表现保持未采集，不预写教学效果。",
                   "homework": {"basic": ["描述一个区域的人口分布并说明材料依据"], "inquiry": ["胡焕庸线能否打破：收集西部发展证据", "芬兰人口分界：保留初稿与修正理由"]}}, "stages": STAGES}

# Preserve the teacher's lesson topology in rehearsal, with complete question
# snapshots and a distinguishable teacher-only reference conclusion.
for s in STAGES:
    s["objective_refs"] = [1,2] if s["source_row"] <= 15 else [3] if s["source_row"] <= 19 else [1,3,4]
    if not s["knowledge_conclusion"]:
        s["knowledge_conclusion"] = "；".join(q["answer"] for q in s["questions"]) or s["script"][0]
    if not s["questions"]:
        s["questions"] = [question(s["stage_id"]+"_task", s["script"][0], s["knowledge_conclusion"])]
    for q in s["questions"]:
        q["explanation"] = q["answer"]
    if s["stage_id"] == "human_factors":
        for a in s["actions"]:
            a["resource_rows"] = [18]
    if s["stage_id"] == "natural_factors":
        for a in s["actions"]:
            a["resource_rows"] = [17]
            if a["action_id"] == "minerals":
                a["scene"]["annotations"] = [{"text": name, "position": point} for name,point in [
                    ("克拉玛依（位置参照）",[84.89,45.60]), ("大庆（位置参照）",[125.03,46.58]), ("大同（位置参照）",[113.30,40.08])]]
    if s["stage_id"] == "human_factors":
        for a in s["actions"]:
            if a["action_id"] == "politics":
                a["scene"] = scene(base="amap_imagery")
                a["scene"]["annotations"] = [{"text":"深圳 政策案例","position":[114.05,22.55]}, {"text":"巴西利亚 迁都案例","position":[-47.88,-15.80]}]

LESSON["plan"].update({
    "topic": "人口分布", "requirements": {"raw": "以张玥修订稿为依据，完整保留教学顺序、案例和活动；教师自主推进，不限总时长。"},
    "curriculum_interpretation": "原稿要求：运用资料，描述人口分布特点及其影响因素。读图、空间证据与综合分析贯穿教学；WebGIS与GeoAI为本课教学扩展，不直接等同官方课标条文。引用原稿中的义务教育2022年课标前需另行核对高中适用性。",
    "student_analysis": "高一学生对生活中的人口集聚具有经验，已学习常见气候和地形知识，但统计图和人口图的规范描述、逻辑归纳与证据解释仍需训练。通过具体案例分步建立读图方法。",
    "textbook_analysis": "高中人文地理开篇内容，承接自然地理知识，为人口迁移、人口容量与产业区位学习打下基础。以世界与中国人口格局引出自然、人文因素，结合案例进行综合分析。",
    "key_difficulties": {"key": ["运用材料描述人口分布特点", "分析自然与人文因素"], "difficult": ["说明因素的作用过程", "区分总体格局、局地例外和证据尺度"]},
    "methods": ["读图分析", "叠置实验", "问题探究", "讲授归纳"],
    "knowledge_structure": ["人口分布特点：宏观与微观描述", "自然因素：气候、地形、水资源、土壤与矿产", "人文因素：生产、经济、历史、政治、军事与文化", "芬兰综合探究与证据修正"],
    "references": [{"title": "张玥 人口分布稿本设计 修订稿", "year": "用户提供版本"}, {"title": "人教版高中地理必修第二册"}, {"title": "中图版高中地理必修第二册"}],
})

if __name__ == "__main__":
    path = ROOT / "backend/app/data/builtin/lessons/population_teacher_revised_lesson.json"
    path.write_text(json.dumps(LESSON, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(f"Wrote {len(STAGES)} stages and {sum(len(s['actions']) for s in STAGES)} actions")
