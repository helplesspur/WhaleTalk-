import glob
import json
import os


def safe_path(base, rel):
    base = os.path.realpath(base)
    full = os.path.realpath(os.path.join(base, rel))
    if full.startswith(base + os.sep) and os.path.isfile(full):
        return full
    return None


def _stem(path, suffix):
    name = os.path.basename(path)
    return name[: -len(suffix)] if name.endswith(suffix) else name


def _rel(base, path):
    return os.path.relpath(path, base).replace("\\", "/")


def _vts_names(model_dir):
    names = {}
    if not model_dir or not os.path.isdir(model_dir):
        return names
    for f in glob.glob(os.path.join(model_dir, "**", "*.vtube.json"), recursive=True):
        try:
            with open(f, "r", encoding="utf-8") as fp:
                for h in json.load(fp).get("Hotkeys", []):
                    if h.get("File") and h.get("Name"):
                        names[os.path.basename(h["File"])] = h["Name"]
        except (OSError, ValueError):
            pass
    return names


def _json_names(model_dir, model_file):
    """model3.json 里 FileReferences.Expressions[].Name 是最权威的表情名，优先用。"""
    names = {}
    path = safe_path(model_dir, model_file) if model_file else None
    if not path:
        return names
    try:
        with open(path, "r", encoding="utf-8") as fp:
            for e in json.load(fp).get("FileReferences", {}).get("Expressions", []):
                if e.get("Name") and e.get("File"):
                    names[os.path.basename(e["File"])] = e["Name"]
    except (OSError, ValueError):
        pass
    return names


# 情绪识别规则：越具体的排前面，命中即停。做成不区分大小写的子串匹配，
# 中文皮套（微笑/脸红/吐舌）、英文皮套（smile/blush/tongue）、VTS 导出（中文 Hotkey 名）都能覆盖。
EMOTION_RULES = [
    ("害羞", ("害羞", "脸红", "羞", "照れ", "blush", "shy", "embarrass")),
    ("惊讶", ("惊讶", "震惊", "吃惊", "感叹", "惊", "surprise", "shock", "驚")),
    ("生气", ("生气", "愤怒", "怒", "angry", "anger", "mad")),
    ("难过", ("难过", "悲伤", "伤心", "哭", "泪", "sad", "cry", "tear", "悲")),
    ("疑惑", ("疑惑", "问号", "疑问", "confus", "question")),
    ("尴尬", ("尴尬", "流汗", "汗", "sweat")),
    ("无语", ("无语", "呆", "deadpan", "blank")),
    ("晕", ("晕", "dizzy", "sleepy")),
    ("开心", ("开心", "高兴", "快乐", "兴奋", "笑", "喜", "smile", "happy", "joy", "laugh")),
    ("感谢", ("爱心", "比心", "爱", "love", "heart")),
    ("期待", ("星星", "期待", "star", "sparkle")),
    ("调皮", ("吐舌", "舌", "tongue", "wink", "眨", "tease")),
]
EMOTION_ORDER = [n for n, _ in EMOTION_RULES]


def classify(text):
    t = (text or "").strip()
    if t in EMOTION_ORDER:  # 表情名正好就叫“调皮”“生气”这种，直接认
        return t
    t = t.lower()
    for name, keys in EMOTION_RULES:
        for k in keys:
            if k in t:
                return name
    return None


def list_model_files(model_dir):
    if not model_dir or not os.path.isdir(model_dir):
        return []
    return sorted(_rel(model_dir, f) for f in glob.glob(os.path.join(model_dir, "**", "*.model3.json"), recursive=True))


def pick_model_file(model_dir, want=""):
    """在目录里挑一个可用的模型文件。want 失效时自动兜底，这是换皮套读不到模型的根因。"""
    files = list_model_files(model_dir)
    if not files:
        return ""
    if want and want in files:
        return want
    if want:
        base = os.path.basename(want)
        for f in files:  # 换了目录但文件名没变
            if os.path.basename(f) == base:
                return f
    for f in files:  # “皮套名/皮套名.model3.json” 这种标准结构
        d = os.path.dirname(f)
        if d and os.path.basename(d) == _stem(os.path.basename(f), ".model3.json"):
            return f
    return files[0]


def list_assets(model_dir, model_file=""):
    if not model_dir or not os.path.isdir(model_dir):
        return [], []
    vts = _vts_names(model_dir)
    vts.update(_json_names(model_dir, model_file))
    exprs, motions = [], []

    def label_of(f, sid):
        name = vts.get(os.path.basename(f), "")
        return f"{name}（{sid}）" if name and name != sid else sid

    for f in sorted(glob.glob(os.path.join(model_dir, "**", "*.exp3.json"), recursive=True)):
        sid = _stem(f, ".exp3.json")
        label = label_of(f, sid)
        exprs.append({"id": sid, "file": _rel(model_dir, f), "label": label,
                      "tag": classify(label + " " + sid) or ""})
    for f in sorted(glob.glob(os.path.join(model_dir, "**", "*.motion3.json"), recursive=True)):
        sid = _stem(f, ".motion3.json")
        label = label_of(f, sid)
        meta = motion_meta(model_dir, _rel(model_dir, f))
        motions.append({"id": sid, "file": _rel(model_dir, f), "label": label,
                        "tag": classify(label + " " + sid) or "",
                        "loop": meta.get("loop", False), "duration": meta.get("duration", 0.0)})
    return exprs, motions


def motion_meta(model_dir, rel):
    path = safe_path(model_dir, rel)
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            meta = json.load(f).get("Meta", {})
        return {"loop": bool(meta.get("Loop")), "duration": float(meta.get("Duration") or 0.0)}
    except (OSError, ValueError):
        return {}


def auto_emotions(exprs, motions, current=None):
    """按当前皮套实际的表情/动作重建情绪映射，关键词沿用旧配置（那是业务逻辑，和皮套无关）。"""
    old = {e.get("name"): e for e in (current or []) if isinstance(e, dict)}
    expr_ids = {e["id"] for e in exprs}
    motion_ids = {m["id"] for m in motions}

    by_expr, by_motion = {}, {}
    for e in exprs:
        tag = e.get("tag") or ""
        if tag:
            by_expr.setdefault(tag, []).append(e["id"])
    for m in motions:
        tag = m.get("tag") or ""
        if tag:
            by_motion.setdefault(tag, []).append(m["id"])

    # 保持用户原来的情绪顺序，新识别出来的追加在后面
    order = [e.get("name") for e in (current or []) if isinstance(e, dict) and e.get("name")]
    order += [n for n in EMOTION_ORDER if n not in order]

    out = []
    for name in order:
        prev = old.get(name, {})
        hit = by_expr.get(name, [])
        keep = [x for x in prev.get("expressions", []) if x in expr_ids]
        if not hit and not keep:
            continue
        motion = prev.get("motion", "")
        if motion and motion not in motion_ids:
            motion = ""
        if not motion:
            motion = (by_motion.get(name) or [""])[0]
        # 原配置还能用的表情优先保留（用户亲手调过的），全失效了才用自动识别补
        out.append({"name": name, "expressions": keep or hit[:3], "motion": motion,
                    "keywords": prev.get("keywords", "")})
    return out


def build_model_json(l2d):
    model_dir = l2d["model_dir"]
    want = l2d.get("model_file", "")
    rel = pick_model_file(model_dir, want)
    if not rel:
        raise FileNotFoundError("文件夹里没有找到 .model3.json")
    path = safe_path(model_dir, rel)
    if not path:
        raise FileNotFoundError("找不到模型文件")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    sub = os.path.dirname(rel)
    refs = data.setdefault("FileReferences", {})

    def fix(p):
        return f"{sub}/{p}" if sub else p

    for key in ("Moc", "Physics", "Pose", "DisplayInfo", "UserData"):
        if refs.get(key):
            refs[key] = fix(refs[key])
    refs["Textures"] = [fix(t) for t in refs.get("Textures", [])]
    refs.pop("Expressions", None)
    _, motions = list_assets(model_dir, rel)
    groups = {m["id"]: [{"File": m["file"], "FadeInTime": 0.3, "FadeOutTime": 0.3}] for m in motions}
    idle = l2d.get("idle_motion")
    if idle and idle in groups:
        groups["Idle"] = groups[idle]
    refs["Motions"] = groups
    return data
