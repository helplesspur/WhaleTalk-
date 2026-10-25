import asyncio
import itertools
import logging
import random
import re
import time

from brain import fill
from tts import ENV_FPS, envelope

log = logging.getLogger("pipe")

TYPE_NAMES = {"enter": "进房", "follow": "关注", "danmaku": "弹幕", "gift": "礼物", "guard": "上舰",
              "superchat": "醒目留言", "like": "点赞", "manual": "手动"}
PRIORITY = {"manual": 0, "superchat": 0, "guard": 0, "gift": 1, "danmaku": 2, "follow": 2, "enter": 3, "like": 4}
MERGE_BY_TYPE = ("enter", "follow", "like")
_seq = itertools.count(1)


def _split(s):
    return [x.strip() for x in re.split(r"[\n,，;；]", s or "") if x.strip()]


def describe(ev):
    t = ev["type"]
    n = ev.get("name", "")
    if t == "danmaku":
        return f"{n}：{ev.get('text', '')}"
    if t == "gift":
        v = f"（{ev['value']}元）" if ev.get("value") else "（免费）"
        return f"{n} 送出 {ev.get('gift')} ×{ev.get('num')}{v}"
    if t == "guard":
        return f"{n} 开通 {ev.get('guard')} ×{ev.get('num')}个月"
    if t == "superchat":
        return f"{n} 醒目留言 ¥{ev.get('price')}：{ev.get('text', '')}"
    return f"{n} {TYPE_NAMES.get(t, t)}"


class Pipeline:
    def __init__(self, app):
        self.app = app
        self.jobs = []
        self.has_job = asyncio.Event()
        self.synth_q = asyncio.Queue(maxsize=1)
        self.play_q = asyncio.Queue(maxsize=1)
        self.paused = False
        self.last_seen = {}
        self.merging = {}
        self.current = None
        self.tasks = []

    @property
    def cfg(self):
        return self.app.cfg

    def start(self):
        self.tasks = [asyncio.create_task(c()) for c in (self._ticker, self._gen_worker, self._synth_worker, self._play_worker)]

    # ---------- 事件入口 ----------
    def _display_name(self, name):
        f = self.cfg["filter"]
        name = (name or "").strip()
        if f.get("rename_default", True) and (not name or "*" in name or re.fullmatch(r"bili_\d+", name)):
            name = "新朋友"
        return name[: int(f.get("name_max_len", 12))]

    def _reject(self, ev):
        """返回拒绝原因，None 表示通过。"""
        t = ev["type"]
        ec = self.cfg["events"].get(t)
        fixed = ev.get("fixed_rule") is not None
        if not ec or not (ec.get("enabled") or fixed):
            return "该类型未启用"
        f = self.cfg["filter"]
        ignore = _split(f.get("ignore_users"))
        if ev.get("raw_name") in ignore or str(ev.get("uid")) in ignore:
            return "忽略名单"
        if f.get("ignore_owner") and ev.get("uid") and ev.get("uid") == self.app.bili.owner_uid and not ev.get("test"):
            return "主播本人"
        text = ev.get("text", "")
        if any(w in text or w in ev.get("raw_name", "") for w in _split(f.get("blocklist"))):
            return "屏蔽词"
        if t == "danmaku" and not fixed:
            if ec.get("ignore_emoticon") and ev.get("emoticon"):
                return "表情弹幕"
            trig = _split(ec.get("trigger_words"))
            if trig and not any(w in text for w in trig):
                return "未含触发词"
            if not ev.get("test") and random.random() * 100 >= float(ec.get("probability", 100)):
                return "按概率跳过"
        if t == "gift":
            if not ev.get("paid") and not ec.get("thank_free", True):
                return "免费礼物"
        cd = float(ec.get("cooldown_user", 0) or 0)
        if t == "guard":
            cd = 30
        if cd > 0 and not ev.get("test"):
            key = (t, ev.get("uid") or ev.get("raw_name"), ev.get("level"))
            now = time.time()
            if now - self.last_seen.get(key, 0) < cd:
                return "冷却中"
            self.last_seen[key] = now
        return None

    def match_fixed(self, text):
        text = (text or "").strip()
        for rule in self.cfg.get("fixed_replies", []):
            if not rule.get("enabled", True) or not rule.get("keywords", "").strip() or not rule.get("reply", "").strip():
                continue
            mode = rule.get("match", "contains")
            if mode == "regex":
                try:
                    hit = re.search(rule["keywords"], text) is not None
                except re.error:
                    hit = False
            elif mode == "exact":
                hit = text in _split(rule["keywords"])
            else:
                hit = any(k in text for k in _split(rule["keywords"]))
            if hit:
                return rule
        return None

    def detect_emotion(self, text):
        l2d = self.cfg.get("live2d", {})
        if not l2d.get("enabled"):
            return ""
        for emo in l2d.get("emotions", []):
            if any(k in text for k in _split(emo.get("keywords"))):
                return emo.get("name", "")
        return ""

    def on_event(self, ev):
        ev["raw_name"] = ev.get("name", "")
        ev["name"] = self._display_name(ev.get("name"))
        if ev["type"] == "gift":
            self.app.songs.on_gift(ev)
        if ev["type"] == "danmaku" and self.app.songs.on_danmaku(ev):
            self.app.push("event", {"type": "danmaku", "tname": "点歌", "desc": describe(ev), "skip": None,
                                    "test": bool(ev.get("test"))})
            return
        if ev["type"] == "danmaku":
            rule = self.match_fixed(ev.get("text"))
            if rule:
                ev["fixed_rule"] = dict(rule)
        reason = "已暂停" if self.paused else self._reject(ev)
        self.app.push("event", {"type": ev["type"], "tname": TYPE_NAMES.get(ev["type"], ev["type"]),
                                "desc": describe(ev) + ("（命中固定回复）" if ev.get("fixed_rule") else ""),
                                "skip": reason, "test": bool(ev.get("test"))})
        if reason:
            return
        t = ev["type"]
        ec = self.cfg["events"][t]
        win = float(ec.get("merge_window", 0) or 0)
        now = time.time()
        if t in MERGE_BY_TYPE and win > 0:
            m = self.merging.get(t)
            if m:
                if ev["name"] not in m["names"]:
                    m["names"].append(ev["name"])
            else:
                self.merging[t] = {"ev": dict(ev), "names": [ev["name"]], "deadline": now + win, "first": now}
            return
        if t == "gift" and win > 0:
            key = ("gift", ev.get("uid") or ev["raw_name"], ev.get("gift"))
            m = self.merging.get(key)
            if m:
                m["ev"]["num"] += ev.get("num", 0)
                m["ev"]["value"] = round(m["ev"].get("value", 0) + ev.get("value", 0), 2)
                m["deadline"] = min(now + win, m["first"] + win * 3)
            else:
                self.merging[key] = {"ev": dict(ev), "deadline": now + win, "first": now}
            return
        self._enqueue(ev)

    def _flush_merge(self, key, m):
        ev = m["ev"]
        if "names" in m:
            names = m["names"]
            k = int(self.cfg["events"][ev["type"]].get("max_names", 3))
            shown = names[:k]
            ev["name"] = "、".join(shown[:-1]) + ("和" if len(shown) > 1 else "") + shown[-1]
            if len(names) > k:
                ev["name"] += f"等{len(names)}位朋友"
        if ev["type"] == "gift":
            minv = float(self.cfg["events"]["gift"].get("min_value", 0) or 0)
            if ev.get("paid") and ev.get("value", 0) < minv:
                self.app.push("log", {"level": "info", "msg": f"礼物价值 {ev['value']} 元低于设定的 {minv} 元，不感谢"})
                return
        self._enqueue(ev)

    async def _ticker(self):
        while True:
            await asyncio.sleep(0.2)
            now = time.time()
            for key, m in list(self.merging.items()):
                if now >= m["deadline"]:
                    del self.merging[key]
                    self._flush_merge(key, m)

    def _enqueue(self, ev, text=None):
        job = {"id": next(_seq), "type": ev["type"], "ev": ev, "text": text, "ts": time.time(),
               "prio": PRIORITY.get(ev["type"], 3)}
        self.jobs.append(job)
        limit = max(1, int(self.cfg["filter"].get("max_queue", 6)))
        while len(self.jobs) > limit:
            victim = max(self.jobs, key=lambda j: (j["prio"], -j["ts"]))
            self.jobs.remove(victim)
            self.app.push("log", {"level": "warn", "msg": f"队列已满，丢弃：{describe(victim['ev'])}"})
        self.has_job.set()
        self._push_queue()

    def say(self, text, emotion=""):
        self._enqueue({"type": "manual", "name": "", "text": text, "emotion": emotion}, text=text)

    def clear(self):
        self.jobs.clear()
        self.merging.clear()
        self._push_queue()

    def _push_queue(self):
        self.app.push("queue", {"items": [f"[{TYPE_NAMES.get(j['type'], j['type'])}] {describe(j['ev']) if j['type'] != 'manual' else j['text']}"
                                          for j in sorted(self.jobs, key=lambda j: (j["prio"], j["ts"]))]})

    # ---------- 工作线 ----------
    async def _gen_worker(self):
        while True:
            await self.has_job.wait()
            if not self.jobs:
                self.has_job.clear()
                continue
            job = min(self.jobs, key=lambda j: (j["prio"], j["ts"]))
            self.jobs.remove(job)
            if not self.jobs:
                self.has_job.clear()
            self._push_queue()
            max_wait = float(self.cfg["filter"].get("max_wait", 60))
            if job["prio"] == 0:
                max_wait *= 3
            if time.time() - job["ts"] > max_wait:
                self.app.push("log", {"level": "warn", "msg": f"等待超过 {int(max_wait)} 秒，放弃：{describe(job['ev'])}"})
                continue
            try:
                emotion = ""
                rule = job["ev"].get("fixed_rule")
                if job["text"] is not None:
                    text, src, emotion = job["text"], "手动", job["ev"].get("emotion", "")
                elif rule:
                    lines = [l.strip() for l in rule["reply"].splitlines() if l.strip()]
                    text, src, emotion = fill(random.choice(lines), job["ev"]), "固定回复", rule.get("emotion", "")
                else:
                    t0 = time.time()
                    text, src, emotion = await self.app.brain.reply(self.cfg, self.cfg["events"][job["type"]], job["ev"])
                    src += f" {time.time() - t0:.1f}s"
            except Exception as e:
                log.exception("生成回复失败")
                self.app.push("log", {"level": "error", "msg": f"生成回复失败：{e}"})
                continue
            if not text:
                continue
            emotion = emotion or self.detect_emotion(text)
            item = {"id": job["id"], "type": job["type"], "text": text, "src": src, "emotion": emotion,
                    "desc": describe(job["ev"]) if job["type"] != "manual" else ""}
            self.app.push("reply", item)
            await self.synth_q.put(item)

    async def _synth_worker(self):
        while True:
            item = await self.synth_q.get()
            tts = self.cfg["tts"]
            if tts.get("enabled", True):
                try:
                    t0 = time.time()
                    item["pcm"], item["sr"] = await self.app.engine.synth(tts, item["text"])
                    item["synth_s"] = round(time.time() - t0, 1)
                except Exception as e:
                    self.app.push("log", {"level": "error", "msg": f"语音合成失败：{e}"})
                    item["pcm"] = None
            await self.play_q.put(item)

    async def _play_worker(self):
        loop = asyncio.get_running_loop()
        while True:
            item = await self.play_q.get()
            self.current = item
            pcm = item.get("pcm")
            self.app.push("speak", {"text": item["text"], "id": item["id"], "synth_s": item.get("synth_s"),
                                    "emotion": item.get("emotion", ""), "fps": ENV_FPS,
                                    "env": envelope(pcm, item["sr"]) if pcm is not None else None,
                                    "dur": round(len(pcm) / item["sr"], 2) if pcm is not None else None})
            try:
                if item.get("pcm") is not None:
                    a = self.cfg["audio"]
                    await loop.run_in_executor(None, self.app.player.play_blocking, item["pcm"], item["sr"],
                                               a.get("device", ""), float(a.get("volume", 80)))
                else:
                    await asyncio.sleep(min(8, 1 + len(item["text"]) * 0.2))
            except Exception as e:
                self.app.push("log", {"level": "error", "msg": f"播放失败：{e}"})
            finally:
                self.current = None
                self.app.push("speak_end", {"id": item["id"]})
