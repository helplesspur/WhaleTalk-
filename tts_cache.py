"""固定话术烘焙：把常用固定台词预先合成成 wav，播的时候直接读文件，不再等合成。

- 缓存按「文字 + 当前音色签名」匹配；换了模型/参考音频/语速/采样步数，旧缓存自动失效。
- 烘焙清单自动从这些地方来：
  · games.py 里 self._say / self._say_wait 的纯固定字符串
  · 回复规则里不含变量的模板
  · 固定回复里不含变量的回复
  · 【语音设置】里额外填写的固定话术（tts.bake_extra）
"""
import ast
import asyncio
import json
import logging
import os
import re
import time
import wave

import numpy as np

from config import BASE_DIR, RES_DIR

log = logging.getLogger("tts")

CACHE_DIR = os.path.join(BASE_DIR, "tts_cache")
INDEX_PATH = os.path.join(CACHE_DIR, "index.json")
SIG_KEYS = ("gsv_dir", "gpt_weights", "sovits_weights", "ref_audio", "ref_text", "text_lang", "ref_lang",
            "speed", "temperature", "top_k", "top_p", "sample_steps")


def _sha(text):
    import hashlib
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def voice_signature(cfg_tts):
    raw = "|".join(f"{k}={cfg_tts.get(k)}" for k in SIG_KEYS)
    return _sha(raw)[:12]


def _read_wav(path):
    with wave.open(path, "rb") as w:
        sr, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
        if sw != 2:
            raise RuntimeError("缓存音频位宽不对")
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype=np.int16).reshape(-1, ch), sr


def _write_wav(path, pcm, sr):
    with wave.open(path, "wb") as w:
        w.setnchannels(int(pcm.shape[1]))
        w.setsampwidth(2)
        w.setframerate(int(sr))
        w.writeframes(pcm.astype(np.int16).tobytes())


class TTSCache:
    def __init__(self):
        self.entries = {}
        self._mem = {}
        self.load()

    # ---------- 索引 ----------
    def load(self):
        try:
            with open(INDEX_PATH, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d.get("entries"), dict):
                self.entries = d["entries"]
        except (OSError, ValueError):
            self.entries = {}

    def save(self):
        try:
            os.makedirs(CACHE_DIR, exist_ok=True)
            tmp = INDEX_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"version": 1, "entries": self.entries}, f, ensure_ascii=False, indent=1)
            os.replace(tmp, INDEX_PATH)
        except OSError as e:
            log.warning("写缓存索引失败：%s", e)

    # ---------- 查询 / 写入 ----------
    def has(self, text, cfg_tts):
        e = self.entries.get(_sha((text or "").strip()))
        return bool(e and e.get("sig") == voice_signature(cfg_tts) and e.get("file"))

    def get(self, text, cfg_tts):
        key = _sha((text or "").strip())
        e = self.entries.get(key)
        if not e or e.get("sig") != voice_signature(cfg_tts) or not e.get("file"):
            return None
        path = os.path.join(CACHE_DIR, e["file"])
        try:
            st = os.stat(path)
        except OSError:
            return None
        hit = self._mem.get(path)
        if hit and hit[0] == st.st_mtime:
            return hit[1], hit[2]
        try:
            pcm, sr = _read_wav(path)
        except Exception as e:
            log.warning("读缓存音频失败 %s：%s", e, path)
            return None
        if len(self._mem) > 40:
            self._mem.clear()
        self._mem[path] = (st.st_mtime, pcm, sr)
        return pcm, sr

    def put(self, text, cfg_tts, pcm, sr):
        text = (text or "").strip()
        if not text or pcm is None:
            return None
        key = _sha(text)
        os.makedirs(CACHE_DIR, exist_ok=True)
        name = f"{key}.wav"
        path = os.path.join(CACHE_DIR, name)
        try:
            _write_wav(path, pcm, sr)
        except Exception as e:
            log.warning("写缓存音频失败：%s", e)
            return None
        self.entries[key] = {"text": text, "file": name, "sig": voice_signature(cfg_tts),
                             "ts": int(time.time()), "dur": round(len(pcm) / max(1, sr), 2)}
        self.save()
        return path

    def remove_missing(self):
        changed = False
        for key, e in list(self.entries.items()):
            if not os.path.exists(os.path.join(CACHE_DIR, e.get("file") or "")):
                self.entries.pop(key, None)
                changed = True
        if changed:
            self.save()

    def clear(self):
        n = 0
        for e in list(self.entries.values()):
            try:
                os.remove(os.path.join(CACHE_DIR, e.get("file") or ""))
                n += 1
            except OSError:
                pass
        self.entries.clear()
        self._mem.clear()
        self.save()
        return n

    def info(self, cfg_tts):
        self.remove_missing()
        sig = voice_signature(cfg_tts)
        total = stale = size = 0
        for e in self.entries.values():
            total += 1
            if e.get("sig") != sig:
                stale += 1
            try:
                size += os.path.getsize(os.path.join(CACHE_DIR, e["file"]))
            except OSError:
                pass
        return {"cached": total, "stale": stale, "size_mb": round(size / 1048576, 2), "sig": sig}


CACHE = TTSCache()


# ---------- 固定话术清单 ----------
def _literals(node):
    """把「纯固定字符串」的可能形式都拆出来：字面量、全常量 f-string、random.choice([...])。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr) and all(isinstance(v, ast.Constant) for v in node.values):
        return ["".join(str(v.value) for v in node.values)]
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
            and node.func.attr in ("choice", "choices", "sample") and node.args:
        seq = node.args[0]
        if isinstance(seq, (ast.List, ast.Tuple, ast.Set)):
            out = []
            for elt in seq.elts:
                out += _literals(elt)
            return out
    return []


# 打包成 exe 后没有 games.py 源码，这里放一份内置的固定台词兜底。
# 改了 games.py 里的固定台词后，把这几个字符串同步一下（源码运行时会自动扫源码，不受影响）。
BUILTIN_LINES = [
    "来玩贪吃蛇！它会自己找吃的，你们发 上 下 左 右 帮它转向，喂到食物的人加一分！",
    "来玩 2048！AI 会自己算方向，你们也可以发 上 下 左 右 指挥。合出 64 以上的新数字，操作的人加两分！",
    "来玩数字炸弹！一到一百之间埋了一个炸弹，大家轮流报数，每报一个数范围就会缩小，谁报到炸弹谁就被炸飞！谁先来？",
    "猜拳对决开始！石头剪刀布随便出，赢我一次加两分，快来！",
    "冷知识时间到！",
    "来听个笑话，先热热身！",
    "有没有人来指挥一下？发 上 下 左 右 帮它转向！",
    "有没有人想翻一格？发 3,5 就是第3行第5列，来帮 AI 一把！",
    "有没有人来发个方向？上 下 左 右 都行，帮 AI 想想！",
    "不对哦，再想想！",
    "还差一点，换个思路！",
    "吃到啦！这波操作漂亮！",
    "咕噜，真好吃，再来一个！",
    "吃到啦！",
]

_GLUE_RE = re.compile(r"[\s，。！？、；：,.!?;:~～…·\-—\"'“”‘’（）()《》「」『』【】\[\]]+")
_GAME_CACHE = {"mtime": 0.0, "lines": [], "tpls": []}


def _is_glue(text):
    return not text or bool(_GLUE_RE.fullmatch(text))


def _joined_parts(node):
    parts = []
    for v in node.values:
        if isinstance(v, ast.Constant) and isinstance(v.value, str):
            parts.append(("s", v.value))
        elif isinstance(v, ast.FormattedValue):
            parts.append(("v", None))
    return parts


def _template_parts(node):
    """从 _say 的参数里提取「带变量的模板」：f-string 或 random.choice([...]) 里的 f-string。"""
    if isinstance(node, ast.JoinedStr):
        parts = _joined_parts(node)
        return [parts] if any(k == "v" for k, _ in parts) else []
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
            and node.func.attr in ("choice", "choices", "sample") and node.args:
        seq = node.args[0]
        if isinstance(seq, (ast.List, ast.Tuple, ast.Set)):
            out = []
            for elt in seq.elts:
                out += _template_parts(elt)
            return out
    return []


def _games_source_path():
    """源码运行时读根目录的 games.py；打包后读随 exe 带上的 srcdata/games.py。"""
    for p in (os.path.join(BASE_DIR, "games.py"), os.path.join(RES_DIR, "srcdata", "games.py")):
        if os.path.exists(p):
            return p
    return ""


def _scan_games():
    """扫 games.py 里 self._say / _say_wait 的固定台词与带变量模板（按文件修改时间缓存）。"""
    path = _games_source_path()
    if not path:
        return [], []
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return [], []
    if mtime == _GAME_CACHE["mtime"]:
        return _GAME_CACHE["lines"], _GAME_CACHE["tpls"]
    try:
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
    except (OSError, SyntaxError):
        return [], []
    lines, tpls = [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in ("_say", "_say_wait") and node.args:
            arg = node.args[0]
            lines += _literals(arg)
            tpls += _template_parts(arg)
    _GAME_CACHE.update(mtime=mtime, lines=lines, tpls=tpls)
    return lines, tpls


def _game_lines():
    return _scan_games()[0]


def _game_template_parts():
    return _scan_games()[1]


def _brace_parts(line):
    parts, idx = [], 0
    for m in re.finditer(r"\{[^{}]*\}", line):
        if m.start() > idx:
            parts.append(("s", line[idx:m.start()]))
        parts.append(("v", None))
        idx = m.end()
    if idx < len(line):
        parts.append(("s", line[idx:]))
    return parts


def _cfg_template_lines(cfg):
    lines = []
    for ev in (cfg.get("events") or {}).values():
        lines += [s for s in str(ev.get("templates") or "").splitlines() if s.strip()]
    for rule in cfg.get("fixed_replies") or []:
        if isinstance(rule, dict) and rule.get("enabled", True):
            lines += [s for s in str(rule.get("reply") or "").splitlines() if s.strip()]
    songs = cfg.get("songs") or {}
    for key in ("tpl_add", "tpl_similar", "tpl_pin", "tpl_play", "tpl_fail", "tpl_need", "tpl_full"):
        if songs.get(key):
            lines.append(str(songs[key]))
    lines += [s for s in str((cfg.get("tts") or {}).get("bake_extra") or "").splitlines() if s.strip()]
    return lines


def _all_template_parts(cfg):
    out = [_brace_parts(line) for line in _cfg_template_lines(cfg) if "{" in line]
    out += _game_template_parts()
    seen, uniq = set(), []
    for parts in out:
        key = tuple(parts)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(parts)
    return uniq


def collect_phrases(cfg):
    """返回这次能烘焙的音频片段：固定台词 + 模板里不含变量的静态片段。"""
    out, seen = [], set()

    def add(text):
        text = (text or "").strip()
        if not (2 <= len(text) <= 120) or text in seen:
            return
        if "{" in text or "}" in text or _is_glue(text):
            return
        seen.add(text)
        out.append(text)

    for s in _game_lines() + BUILTIN_LINES:
        add(s)
    for line in _cfg_template_lines(cfg):
        add(line)  # 不含变量的整句模板
    for parts in _all_template_parts(cfg):
        for kind, text in parts:
            if kind == "s":
                add(text)  # 模板里的固定片段（按变量拆段烘焙用）
    for line in str((cfg.get("tts") or {}).get("bake_extra") or "").splitlines():
        add(line)
    return out


# ---------- 按变量拆段：把一句话拆成「读缓存 / 现场合成」的片段 ----------
_TPL = {"key": None, "tpls": []}


def _templates(cfg):
    path = _games_source_path()
    try:
        mtime = os.path.getmtime(path) if path else 0.0
    except OSError:
        mtime = 0.0
    key = (mtime, tuple(_cfg_template_lines(cfg)))
    if _TPL["key"] == key:
        return _TPL["tpls"]
    tpls = []
    for parts in _all_template_parts(cfg):
        statics = [t for k, t in parts if k == "s" and not _is_glue(t)]
        if sum(len(t) for t in statics) < 4:
            continue
        if not any(k == "v" for k, _ in parts):
            continue
        pattern = "^" + "".join(re.escape(t) if k == "s" else "(.*?)" for k, t in parts) + "$"
        try:
            rx = re.compile(pattern, re.S)
        except re.error:
            continue
        tpls.append((sum(len(t) for t in statics), parts, rx))
    tpls.sort(key=lambda x: -x[0])
    _TPL.update(key=key, tpls=tpls)
    return tpls


def _chunks(expanded):
    """把 [('s', 文本) / ('v', 值)] 变成 [('cache', 片段) / ('synth', 文本)]。"""
    staged = []
    for kind, text in expanded:
        if kind == "s" and _is_glue(text):
            staged.append(("glue", text))
        else:
            staged.append((kind, text))
    res = []
    for kind, text in staged:
        if kind == "glue":
            if res and res[-1][0] == "v":
                res[-1] = ("v", res[-1][1] + text)
            else:
                res.append(("glue_next", text))
            continue
        if kind == "v" and res and res[-1][0] == "glue_next":
            res[-1] = ("v", res[-1][1] + text)
        else:
            res.append((kind, text))
    items = [(k, t) for k, t in res if k in ("s", "v") and t.strip()]
    chunks = [(("cache" if k == "s" else "synth"), t) for k, t in items]

    def merge_synth(seq):
        out = []
        for kind, text in seq:
            if out and out[-1][0] == "synth" and kind == "synth":
                out[-1] = ("synth", out[-1][1] + text)
            else:
                out.append((kind, text))
        return out

    # 单字静态片段（如“个”）并到相邻合成片段，少一点拼接痕迹
    out = []
    for kind, text in chunks:
        if kind == "cache" and len(text.strip()) <= 1 and out and out[-1][0] == "synth":
            out[-1] = ("synth", out[-1][1] + text)
        else:
            out.append((kind, text))
    if len(out) > 1 and out[0][0] == "cache" and len(out[0][1].strip()) <= 1 and out[1][0] == "synth":
        out[1] = ("synth", out[0][1] + out[1][1])
        out.pop(0)
    out = merge_synth(out)
    if not out or len(out) > 8:
        return None
    return out


def segments(text, cfg):
    """给一句话找模板；能拆就返回片段列表，否则 None（调用方退回整句合成）。"""
    tts = cfg.get("tts") or {}
    if not tts.get("segment_bake", True):
        return None
    text = (text or "").strip()
    if not text or "{" in text or "}" in text:
        return None
    for _, parts, rx in _templates(cfg):
        m = rx.fullmatch(text)
        if not m:
            continue
        vals, vi = list(m.groups()), 0
        expanded = []
        for kind, t in parts:
            if kind == "s":
                expanded.append(("s", t))
            else:
                expanded.append(("v", vals[vi] or ""))
                vi += 1
        chunks = _chunks(expanded)
        if not chunks:
            continue
        if not any(k == "synth" for k, _ in chunks):
            return chunks  # 变量是空的，整句就是静态片段
        if any(k == "cache" and not CACHE.has(t, tts) for k, t in chunks):
            continue  # 静态片段还没烘焙，换下一个模板 / 退回整句
        return chunks
    return None


class Baker:
    """一键烘焙：串行合成固定话术并写入缓存。"""

    def __init__(self):
        self.task = None
        self.state = {"running": False, "total": 0, "done": 0, "failed": 0, "skipped": 0,
                      "current": "", "error": "", "started": 0.0, "finished": 0.0}

    @property
    def running(self):
        return bool(self.task and not self.task.done())

    def stop(self):
        if self.running:
            self.task.cancel()
            return True
        return False

    def start(self, app, phrases):
        if self.running:
            return False
        self.state = {"running": True, "total": len(phrases), "done": 0, "failed": 0, "skipped": 0,
                      "current": "准备中…", "error": "", "started": time.time(), "finished": 0.0}
        self.task = asyncio.create_task(self._run(app, phrases))
        return True

    async def _run(self, app, phrases):
        cfg = app.cfg["tts"]
        push = lambda m: app.push("log", {"level": "info", "msg": m})
        try:
            if not cfg.get("enabled", True):
                self.state.update(running=False, error="语音已关闭，先在【语音设置】里启用语音")
                return
            if await app.engine.alive(cfg["api_url"]) is False:
                push("烘焙需要语音引擎，正在启动 GPT-SoVITS…")
                ok = await app.engine.start(cfg, push)
                if not ok:
                    self.state.update(running=False, error="语音引擎启动失败，先手动点【启动引擎】")
                    return
            push(f"开始烘焙固定话术，共 {len(phrases)} 条…")
            for text in phrases:
                if self.task is None:
                    break
                self.state["current"] = text
                if CACHE.has(text, cfg):
                    self.state["skipped"] += 1
                    self.state["done"] += 1
                    continue
                try:
                    pcm, sr = await app.engine.synth(cfg, text)
                    if CACHE.put(text, cfg, pcm, sr) is None:
                        raise RuntimeError("写文件失败")
                    self.state["done"] += 1
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    self.state["failed"] += 1
                    self.state["done"] += 1
                    log.warning("烘焙失败：%s（%s）", text, e)
                await asyncio.sleep(0)
            st = self.state
            if st["failed"]:
                push(f"烘焙完成：成功 {st['done'] - st['failed'] - st['skipped']} 条，"
                     f"跳过已有 {st['skipped']} 条，失败 {st['failed']} 条")
            else:
                push(f"烘焙完成：新增 {st['done'] - st['skipped']} 条，跳过已有 {st['skipped']} 条")
        except asyncio.CancelledError:
            self.state["error"] = "已停止"
            push("已停止烘焙")
        except Exception as e:
            log.exception("烘焙出错")
            self.state["error"] = str(e)[:200]
            app.push("log", {"level": "error", "msg": f"烘焙出错：{e}"})
        finally:
            self.state["running"] = False
            self.state["current"] = ""
            self.state["finished"] = time.time()
            self.task = None
