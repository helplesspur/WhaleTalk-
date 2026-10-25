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
    for f in glob.glob(os.path.join(model_dir, "*.vtube.json")):
        try:
            with open(f, "r", encoding="utf-8") as fp:
                for h in json.load(fp).get("Hotkeys", []):
                    if h.get("File") and h.get("Name"):
                        names[os.path.basename(h["File"])] = h["Name"]
        except (OSError, ValueError):
            pass
    return names


def list_model_files(model_dir):
    return sorted(_rel(model_dir, f) for f in glob.glob(os.path.join(model_dir, "**", "*.model3.json"), recursive=True))


def list_assets(model_dir):
    vts = _vts_names(model_dir)
    exprs, motions = [], []
    for f in sorted(glob.glob(os.path.join(model_dir, "**", "*.exp3.json"), recursive=True)):
        sid = _stem(f, ".exp3.json")
        label = vts.get(os.path.basename(f), sid)
        exprs.append({"id": sid, "file": _rel(model_dir, f), "label": label if label == sid else f"{label}（{sid}）"})
    for f in sorted(glob.glob(os.path.join(model_dir, "**", "*.motion3.json"), recursive=True)):
        sid = _stem(f, ".motion3.json")
        label = vts.get(os.path.basename(f), sid)
        motions.append({"id": sid, "file": _rel(model_dir, f), "label": label if label == sid else f"{label}（{sid}）"})
    return exprs, motions


def build_model_json(l2d):
    model_dir = l2d["model_dir"]
    path = safe_path(model_dir, l2d["model_file"])
    if not path:
        raise FileNotFoundError("找不到模型文件")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    sub = os.path.dirname(_rel(model_dir, path))
    refs = data.setdefault("FileReferences", {})

    def fix(p):
        return f"{sub}/{p}" if sub else p

    for key in ("Moc", "Physics", "Pose", "DisplayInfo", "UserData"):
        if refs.get(key):
            refs[key] = fix(refs[key])
    refs["Textures"] = [fix(t) for t in refs.get("Textures", [])]
    refs.pop("Expressions", None)
    _, motions = list_assets(model_dir)
    groups = {m["id"]: [{"File": m["file"], "FadeInTime": 0.3, "FadeOutTime": 0.3}] for m in motions}
    idle = l2d.get("idle_motion")
    if idle and idle in groups:
        groups["Idle"] = groups[idle]
    refs["Motions"] = groups
    return data
