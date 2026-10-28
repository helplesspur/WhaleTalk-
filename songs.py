import asyncio
import itertools
import logging
import re
import time

from brain import fill
from netease import NetEase

log = logging.getLogger("song")

CMD = re.compile(r"^\s*[/／]?\s*(?:点歌|點歌)\s*[:：]?\s*(.+?)\s*$")
_qid = itertools.count(1)


def _split(s):
    return [x.strip() for x in re.split(r"[\n,，;；]", s or "") if x.strip()]


class SongManager:
    def __init__(self, app):
        self.app = app
        self.ne = NetEase(lambda: self.cfg.get("netease_cookie", ""))
        self.queue = []
        self.current = None
        self.paused = False
        self.credits = {}
        self.wake = asyncio.Event()
        self.end = asyncio.Event()
        self.last_hint = {}
        self.account = None
        self._auto_tracks = []
        self._auto_bag = []
        self._auto_pid = None
        self._auto_fail = 0
        self._auto_backoff = 0

    @property
    def cfg(self):
        return self.app.cfg["songs"]

    # ---------- 状态 ----------
    def state(self):
        pos, dur = self.app.player.music_progress()
        cur = dict(self.current, pos=round(pos), total=round(dur) or self.current.get("dur", 0),
                   paused=self.paused) if self.current else None
        return {"current": cur, "queue": self.queue,
                "credits": [dict(v, key=k) for k, v in self.credits.items() if v["song"] or v["pin"] or v["song_prog"] or v["pin_prog"]],
                "account": self.account,
                "autoplay": {"enabled": bool(self.cfg.get("autoplay", {}).get("enabled")),
                             "playlist_name": self.cfg.get("autoplay", {}).get("playlist_name", ""),
                             "tracks": len(self._auto_tracks),
                             "left": len(self._auto_bag)}}

    def push(self):
        self.app.push("songs", self.state())

    def say(self, key, **kw):
        c = self.cfg
        if not c.get(f"announce_{key}", True):
            return
        tpl = c.get(f"tpl_{key}", "")
        if tpl:
            self.app.pipe.say(fill(tpl, kw), kw.get("emotion", "开心"))

    def _rec(self, key, name):
        rec = self.credits.setdefault(key, {"name": name, "song": 0, "pin": 0, "song_prog": 0, "pin_prog": 0})
        if name:
            rec["name"] = name
        return rec

    @staticmethod
    def _key(ev):
        return str(ev.get("uid") or ev.get("raw_name") or ev.get("name"))

    # ---------- 弹幕 / 礼物 ----------
    def on_gift(self, ev):
        c = self.cfg
        if not c.get("enabled"):
            return
        gift, num = ev.get("gift", ""), int(ev.get("num") or 1)
        key, rec = self._key(ev), None
        for kind in ("song", "pin"):
            names = _split(c.get(f"{kind}_gifts"))
            if not names or not ("*" in names or gift in names):
                continue
            rec = rec or self._rec(key, ev.get("name"))
            per = max(1, int(c.get(f"{kind}_gift_count", 1) or 1))
            rec[f"{kind}_prog"] += num
            got = rec[f"{kind}_prog"] // per
            rec[f"{kind}_prog"] %= per
            rec[kind] += got
            if got:
                self.app.push("log", {"level": "info", "msg": f"{ev.get('name')} 获得{'点歌' if kind == 'song' else '插队'}券 ×{got}"})
        if rec and rec["pin"] > 0:
            self._apply_pin(key, rec)
        if rec:
            self.push()

    def _apply_pin(self, key, rec):
        """用户已经有排队中的歌：用掉一张插队券，把它置顶。"""
        for i, s in enumerate(self.queue):
            if s["key"] == key and not s["pinned"]:
                rec["pin"] -= 1
                self.queue.pop(i)
                self._insert_pinned(s)
                self.say("pin", name=rec["name"], song=s["name"], artist=s["artist"], emotion="惊讶")
                return True
        return False

    def _insert_pinned(self, s):
        s["pinned"] = True
        n = sum(1 for x in self.queue if x["pinned"])
        self.queue.insert(n, s)

    def on_danmaku(self, ev):
        """是点歌指令就返回 True（这条弹幕不再走 AI 回复）。"""
        c = self.cfg
        if not c.get("enabled"):
            return False
        m = CMD.match(ev.get("text", ""))
        if not m:
            return False
        query = m.group(1)[:60]
        key = self._key(ev)
        rec = self._rec(key, ev.get("name"))
        gift_names = "、".join(_split(c.get("song_gifts"))) or "礼物"
        if c.get("require_gift", True) and rec["song"] <= 0:
            if time.time() - self.last_hint.get(key, 0) > 60:
                self.last_hint[key] = time.time()
                self.say("need", name=ev["name"], gift=gift_names, query=query, num=c.get("song_gift_count", 1))
            return True
        mine = sum(1 for s in self.queue if s["key"] == key) + (1 if self.current and self.current["key"] == key else 0)
        if mine >= int(c.get("max_per_user", 2)) or len(self.queue) >= int(c.get("max_queue", 20)):
            self.say("full", name=ev["name"], query=query)
            return True
        if c.get("require_gift", True):
            rec["song"] -= 1
        asyncio.create_task(self._request(key, ev["name"], query, c.get("require_gift", True)))
        self.push()
        return True

    async def _request(self, key, name, query, paid):
        rec = self._rec(key, name)
        try:
            song = await self.ne.find(query, int(float(self.cfg.get("max_minutes", 8)) * 60))
        except Exception as e:
            log.warning("搜索失败：%s", e)
            song = None
        if not song:
            if paid:
                rec["song"] += 1
            self.say("fail", name=name, query=query, emotion="难过")
            self.push()
            return
        self.add(song, name, key, query)

    def add(self, song, name, key="__host__", query=""):
        rec = self._rec(key, name)
        s = {"qid": next(_qid), "id": song["id"], "name": song["name"], "artist": song.get("artist", ""),
             "dur": song.get("dur", 0), "by": name, "key": key, "query": query, "pinned": False,
             "similar": not song.get("exact", True)}
        if rec["pin"] > 0:
            rec["pin"] -= 1
            self._insert_pinned(s)
            self.say("pin", name=name, song=s["name"], artist=s["artist"], emotion="惊讶")
        else:
            self.queue.append(s)
            pos = len(self.queue) + (1 if self.current else 0)
            self.say("similar" if s["similar"] else "add", name=name, song=s["name"], artist=s["artist"], pos=pos, query=query)
        self.app.push("log", {"level": "info", "msg": f"点歌：{name} → 《{s['name']}》- {s['artist']}"
                                                      + ("（相似）" if s["similar"] else "")})
        self.wake.set()
        self.push()
        ap = self.cfg.get("autoplay", {})
        if ap.get("interrupt", True) and self.current and self.current.get("auto"):
            self.app.player.stop_music()
            self.end.set()

    # ---------- 无人点歌时自动播放歌单 ----------
    async def _next_auto(self):
        ap = self.cfg.get("autoplay", {})
        if not ap.get("enabled") or not ap.get("playlist_id"):
            return None
        if time.time() < self._auto_backoff:
            return None
        if self._auto_pid != ap["playlist_id"] or not self._auto_tracks:
            try:
                info = await self.ne.playlist_tracks(ap["playlist_id"])
                self._auto_tracks = info["tracks"]
                self._auto_pid = ap["playlist_id"]
                self._auto_bag = []
                if info["name"] and info["name"] != ap.get("playlist_name"):
                    ap["playlist_name"] = info["name"]
                self.app.push("log", {"level": "info", "msg": f"自动歌单《{info['name']}》已加载，共 {len(self._auto_tracks)} 首"})
            except Exception as e:
                self.app.push("log", {"level": "error", "msg": f"读取歌单失败：{e}"})
                self._auto_backoff = time.time() + 300
                return None
        if not self._auto_tracks:
            return None
        if not self._auto_bag:
            self._auto_bag = list(self._auto_tracks)
            if ap.get("mode", "shuffle") == "shuffle":
                import random as _r
                _r.shuffle(self._auto_bag)
        t = self._auto_bag.pop(0)
        return {"qid": next(_qid), "id": t["id"], "name": t["name"], "artist": t["artist"],
                "dur": t.get("dur", 0), "by": ap.get("playlist_name") or "歌单", "key": "__auto__",
                "query": "", "pinned": False, "similar": False, "auto": True}

    # ---------- 播放 ----------
    async def run(self):
        loop = asyncio.get_running_loop()
        asyncio.create_task(self._ticker())
        asyncio.create_task(self.refresh_account())
        while True:
            if not self.cfg.get("enabled") or self.paused:
                self.wake.clear()
                await self.wake.wait()
                continue
            if self.queue:
                s = self.queue.pop(0)
            elif getattr(self.app, "session_active", False):
                s = await self._next_auto()  # 只有点了「开始」才自动放歌单
            else:
                s = None
            if not s:
                self.wake.clear()
                await self.wake.wait()
                continue
            self.current = s
            self.push()
            dev = self.app.cfg["audio"].get("device", "")
            try:
                url = await self.ne.url(s["id"])
                if not url:
                    raise RuntimeError("这首歌现在不能播放（可能需要VIP或已下架）")
                data = await self.ne.download(url)
                pcm, sr = await loop.run_in_executor(None, self.app.player.decode_music, data, dev)
            except Exception as e:
                self.app.push("log", {"level": "error", "msg": f"播放《{s['name']}》失败：{e}"})
                self.current = None
                if s.get("auto"):
                    self._auto_fail += 1
                    if self._auto_fail >= int(self.cfg.get("autoplay", {}).get("max_fail", 3)):
                        self._auto_backoff = time.time() + 600
                        self._auto_fail = 0
                        self.app.push("log", {"level": "warn", "msg": "自动歌单连续播放失败，10 分钟后再试"})
                continue
            self._auto_fail = 0
            self._apply_volume()
            self.end.clear()
            if not s.get("auto"):
                self.say("play", name=s["by"], song=s["name"], artist=s["artist"])
            self.app.player.play_music(pcm, sr, dev, lambda: loop.call_soon_threadsafe(self.end.set))
            self.push()
            await self.end.wait()
            self.current = None
            self.push()

    async def _ticker(self):
        while True:
            await asyncio.sleep(1)
            if self.current:
                self.push()

    def _apply_volume(self):
        self.app.player.set_music(float(self.cfg.get("volume", 50)), float(self.cfg.get("duck", 30)))

    async def refresh_account(self):
        if not self.cfg.get("netease_cookie"):
            self.account = None
        else:
            try:
                self.account = await self.ne.account()
            except Exception as e:
                log.warning("网易云账号检查失败：%s", e)
        self.push()

    # ---------- 控制 ----------
    def control(self, action, qid=None):
        idx = next((i for i, s in enumerate(self.queue) if s["qid"] == qid), None)
        if action == "skip":
            self.app.player.stop_music()
            self.end.set()
        elif action == "pause":
            self.paused = True
            self.app.player.pause_music(True)
        elif action == "resume":
            self.paused = False
            self.app.player.pause_music(False)
            self.wake.set()
        elif action == "clear":
            self.queue.clear()
        elif idx is not None:
            s = self.queue[idx]
            if action == "remove":
                self.queue.pop(idx)
            elif action == "pin":
                self.queue.pop(idx)
                self._insert_pinned(s)
            elif action == "unpin":
                self.queue.pop(idx)
                s["pinned"] = False
                self.queue.insert(sum(1 for x in self.queue if x["pinned"]), s)
            elif action in ("up", "down"):
                j = idx - 1 if action == "up" else idx + 1
                if 0 <= j < len(self.queue):
                    self.queue[idx], self.queue[j] = self.queue[j], self.queue[idx]
        self.push()

    def give(self, key, song=0, pin=0):
        rec = self.credits.get(key)
        if rec:
            rec["song"] = max(0, rec["song"] + song)
            rec["pin"] = max(0, rec["pin"] + pin)
            if pin > 0:
                self._apply_pin(key, rec)
        self.push()
