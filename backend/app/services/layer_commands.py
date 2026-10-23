"""Whole-clause layer commands shared by single and sequential Operate routing."""
from __future__ import annotations
import re


def _clean_name(value):
    return re.sub(r"\s+", "", value).strip('的“”\"\'「」')


def resolve_layers(target, project, *, allow_all=False):
    """Exact names/IDs only; never substitute the active layer for a named miss."""
    target = _clean_name(target)
    if re.fullmatch(r"(?:当前|目前|现在)?(?:所有|全部)(?:的)?图层", target):
        return list(project.layers), "" if allow_all else "请明确一个图层。"
    if re.fullmatch(r"(?:当前|目前|现在)?(?:(?:所有|全部)(?:的)?)?(?:已)?(?:打开|显示|可见|开启)(?:的)?(?:(?:所有|全部)(?:的)?)?图层", target):
        return [layer for layer in project.layers if layer.visible], ""
    if re.fullmatch(r"(?:当前|目前|现在)?(?:(?:所有|全部)(?:的)?)?(?:已)?(?:隐藏|关闭|不可见)(?:的)?图层", target):
        return [layer for layer in project.layers if not layer.visible], ""
    if target in {"当前图层", "选中图层", "这个图层", "该图层", "活动图层", "当前", "选中", "这个", "该", "活动"}:
        layers = [layer for layer in project.layers if layer.layer_id == project.active_layer_id]
        return layers, "" if layers else "当前没有选中的图层，请说出图层名称。"
    # Descriptive visibility belongs to the target, not to the requested action.
    target = re.sub(r"^(?:当前)?(?:已)?(?:打开|显示|可见|隐藏|关闭)的", "", target)
    target = re.sub(r"^(?:名为|名称为)", "", target)
    if not target or target == "图层":
        return [], "请明确要操作的图层名称，或说“当前图层”“所有可见图层”。"
    variants = {target, target.removesuffix("图层"), target.removeprefix("图层"), target.removesuffix("图")}
    variants = {_clean_name(value) for value in variants if value}
    matches = [layer for layer in project.layers if _clean_name(layer.name) in variants or layer.layer_id in variants]
    if len(matches) == 1:
        return matches, ""
    if len(matches) > 1:
        return [], f"图层名称“{target}”不唯一，请使用图层 ID 区分。"
    aliases = (("胡线", "黑河腾冲线", "胡焕庸线"), ("400毫米等降水量线", "四百毫米等降水量线"))
    for names in aliases:
        if variants.intersection(names):
            matches = [layer for layer in project.layers if any(name in layer.name for name in names)]
            if len(matches) == 1:
                return matches, ""
            if len(matches) > 1:
                return [], f"“{target}”匹配多个图层，请提供完整名称。"
    parts = re.split(r"和|及|、", target)
    if len(parts) > 1:
        layers = []
        for part in parts:
            found, error = resolve_layers(part, project, allow_all=False)
            if error:
                return [], error
            layers.extend(found)
        return list({layer.layer_id: layer for layer in layers}.values()), ""
    return [], f"没有找到图层“{target}”，未改动其他图层。请提供完整名称。"


def plan_layer_command(message, project, color_for, opacity_for):
    text = re.sub(r"^(?:请|麻烦|帮我|帮忙)+", "", message.strip())
    text = re.sub(r"[。！!]+$", "", text).strip()
    relevant = any(layer.name and layer.name in text for layer in project.layers) or bool(re.search(r"图层|胡线|胡焕庸|黑河腾冲|降水量线|透明度", text))
    if not relevant:
        return None
    if re.fullmatch(r"(?:打开|显示|叠加)(?:.+对比图|人口分布图|人口密度分布图|人口密度图)", text):
        return None
    if re.search(r"底图|面板|管理器|工作流|模板|缓冲|分级|对比分析", text):
        return None
    if re.search(r"为什么|怎么|是否|吗[？?]?$|呢[？?]?$|还是|仍然|没(?:有|能)?(?:显示|隐藏|删除|变化)|不对", text):
        return {"actions": [], "stop_planning": True, "assistant_message": "收到，这是图层状态询问或效果反馈，本次未修改图层。请明确需要执行的动作和图层名称。"}
    # An anchored grammar consumes the main verb and the entire target/value.
    patterns = [
        ("delete", r"(?:删除|删掉|移除|清除|清空)(.+)"),
        ("delete", r"(?:把|将)(.+?)(?:删除|删掉|移除|清除|清空)(?:掉)?"),
        ("toggle", r"(取消隐藏|取消叠加|显示|打开|叠加|隐藏|关闭)(.+)"),
        ("toggle_post", r"(?:把|将)(.+?)(取消隐藏|取消叠加|显示|打开|叠加|隐藏|关闭)(?:起来|掉)?"),
        ("reorder", r"(?:把|将)?(.+?)(?:移到|放到|移至)?(置顶|置底|最上面|最上层|顶层|最下面|最底层|最下层|底层)"),
        ("focus", r"(?:定位|聚焦|缩放|放大)(?:到|至)?(.+图层)"),
        ("style", r"(?:把|将)?(.+?)(?:颜色)?(?:改成|改为|换成|调成|设为|涂成|变成|变为)(.+)"),
        ("opacity", r"(?:把|将)?(.*?)(?:的)?透明度(?:调到|调成|设置为|设为|改成|改为|变为)(.+)"),
        ("opacity", r"(?:把|将)?(.+?)(?:调到|调成|设置为|设为|改成|改为|变为)(半透明|全透明|完全透明|不透明|一半|百分之[一二三四五六七八九十百\d]+|\d+(?:\.\d+)?%|0(?:\.\d+)?|1(?:\.0+)?)"),
    ]
    op = target = value = ""
    for kind, pattern in patterns:
        match = re.fullmatch(pattern, text)
        if not match:
            continue
        op = kind
        target = match[1]
        value = match[2] if match.lastindex > 1 else ""
        if op == "toggle":
            value, target = target, value
        elif op == "toggle_post":
            op = "toggle"
        if op == "style" and ("透明" in value or target.endswith("透明度")):
            op = "opacity"
            target = target.removesuffix("透明度").rstrip("的")
        break
    if not op:
        # Do not fall back into the legacy keyword parser for an unsupported
        # layer operation (export/rename/constraints/compound goals).
        return {"actions": [], "assistant_message": "需要理解完整的图层要求，暂未执行任何操作。"}
    if re.search(r"除|以外|之外|保留|除了|仅当|如果", target):
        return {"actions": [], "assistant_message": "需要理解完整的图层范围与约束，暂未执行任何操作。"}
    if op == "delete" and target == "图层" and text.startswith("清空"):
        target = "所有图层"
    if op == "opacity" and target in {"", "图层"}:
        target = "当前图层"
    layers, error = resolve_layers(target, project, allow_all=True)
    if error:
        return {"actions": [], "stop_planning": True, "assistant_message": error}
    if not layers:
        return {"actions": [], "stop_planning": True, "assistant_message": "当前没有符合范围的图层，未执行操作。"}
    names = "、".join(f"“{layer.name}”" for layer in layers)
    if op == "delete":
        return {"assistant_message": f"准备从当前项目删除 {len(layers)} 个图层：{names}。确认后执行；数据库源数据和素材保留。",
                "actions": [{"tool_name": "delete_layers", "tool_params": {"layer_ids": [layer.layer_id for layer in layers]}}]}
    params = {}
    tool = ""
    if op == "toggle":
        tool, params = "toggle_layer", {"visible": value in {"显示", "打开", "叠加", "取消隐藏"}}
    elif op == "focus":
        if len(layers) != 1:
            return {"actions": [], "stop_planning": True, "assistant_message": "请指定一个要定位的图层。"}
        tool = "focus_layer"
    elif op == "reorder":
        top = value in {"置顶", "最上面", "最上层", "顶层"}
        z = [layer.z_index for layer in project.layers] or [0]
        tool, params = "reorder_layer", {"z_index": max(z)+10 if top else min(z)-10}
    elif op == "opacity":
        opacity = opacity_for("透明度" + value)
        if opacity is None or not re.fullmatch(r"半透明|全透明|完全透明|不透明|一半|百分之[一二三四五六七八九十百\d]+|\d+(?:\.\d+)?%|0(?:\.\d+)?|1(?:\.0+)?", value):
            return {"actions": [], "assistant_message": "需要核对完整的透明度要求，暂未执行操作。"}
        tool, params = "set_layer_opacity", {"opacity": opacity}
    elif op == "style":
        color = color_for(value)
        if not color or not re.fullmatch(r"(?:深|浅)?(?:红|蓝|绿|黄|橙|紫|黑|白|灰)(?:色)?", value):
            return {"actions": [], "assistant_message": "需要核对完整的样式要求，暂未执行操作。"}
        tool, params = "style_layer", {"style": {"fillColor": color, "strokeColor": "#ffffff"}}
    return {"assistant_message": f"准备更新图层：{names}。", "actions": [
        {"tool_name": tool, "tool_params": {"layer_id": layer.layer_id, **params}} for layer in layers]}
