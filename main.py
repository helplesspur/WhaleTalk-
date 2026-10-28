import asyncio
import collections
import ctypes
import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser

from aiohttp import web, WSMsgType

import config
import live2d
from bili import BiliLive, QrLogin
from brain import Brain, CLI_PRESETS, default_qoder_exe, err_text, list_qoder_models
from douyin import DouyinLive, find_browser
from games import CATALOG, GameManager
from pipeline import Pipeline
from songs import SongManager
from tts import GsvEngine, Player
from tts_cache import CACHE as TTS_CACHE, Baker, collect_phrases

if sys.stdout is None:  # 无控制台打包（--windowed）时 print/logging 也要能跑
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = sys.stdout

os.makedirs(config.LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    handlers=[logging.FileHandler(os.path.join(config.LOG_DIR, "app.log"), encoding="utf-8"),
              logging.StreamHandler(sys.stdout)])
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
log = logging.getLogger("app")


class UiLogHandler(logging.Handler):
    def __init__(self, app):
        super().__init__(logging.WARNING)
        self.app = app

    def emit(self, record):
        if record.name in ("ai", "tts", "bili", "douyin", "app"):
            self.app.push("log", {"level": "warn" if record.levelno < logging.ERROR else "error",
                                  "msg": record.getMessage()})


class App:
    def __init__(self):
        self.cfg = config.load()
        self.loop = None
        self.ws = set()
        self.history = collections.deque(maxlen=300)
        self.brain = Brain()
        self.engine = GsvEngine()
        self.player = Player()
        self.bili = BiliLive(self.on_event, lambda m: self.push("log", {"level": "info", "msg": m}))
        self.douyin = DouyinLive(self.on_event, lambda m: self.push("log", {"level": "info", "msg": m}))
        self.pipe = Pipeline(self)
        self.songs = SongManager(self)
        self.games = GameManager(self)
        self.qr = QrLogin()
        self.baker = Baker()
        self.session_active = False
        self.status = {}
        self.session = {"live_since": None, "live_total": 0.0, "gifts": [], "gift_count": 0,
                        "gift_value": 0.0, "gift_by": {}}
        logging.getLogger().addHandler(UiLogHandler(self))

    # ---------- 推送到界面 ----------
    def push(self, kind, data):
        msg = {"kind": kind, "t": time.strftime("%H:%M:%S"), **data}
        if kind in ("event", "reply", "log"):
            self.history.append(msg)
        if kind == "log":
            print(f"[{msg['t']}] {data.get('msg')}", flush=True)
        elif kind == "reply":
            log.info("回复[%s] %s  <- %s", data.get("src"), data.get("text"), data.get("desc"))
        text = json.dumps(msg, ensure_ascii=False)
        for ws in list(self.ws):
            if not ws.closed:
                asyncio.ensure_future(ws.send_str(text))

    def on_event(self, ev):
        if ev.get("type") == "gift" and not ev.get("test"):
            self.add_gift(ev)
        self.pipe.on_event(ev)

    # ---------- 平台 ----------
    @property
    def platform(self):
        return "douyin" if str(self.cfg.get("platform") or "").lower() == "douyin" else "bilibili"

    @property
    def live(self):
        """当前正在用的弹幕源（B站 / 抖音）。"""
        return self.douyin if self.platform == "douyin" else self.bili

    @property
    def owner_uid(self):
        return getattr(self.live, "owner_uid", None)

    @property
    def live_connected(self):
        return bool(getattr(self.live, "connected", False))

    # ---------- 本场统计（时长 / 礼物 / Token） ----------
    def _live_seconds(self):
        total = self.session["live_total"]
        if self.session["live_since"]:
            total += time.time() - self.session["live_since"]
        return int(total)

    def _track_live(self, connected):
        since = self.session["live_since"]
        now = time.time()
        if connected and since is None:
            self.session["live_since"] = now
        elif not connected and since is not None:
            self.session["live_total"] += now - since
            self.session["live_since"] = None

    def add_gift(self, ev):
        num = int(ev.get("num") or 1)
        value = float(ev.get("value") or 0)
        gift = ev.get("gift") or "礼物"
        s = self.session
        s["gifts"].append({"t": time.strftime("%H:%M:%S"), "name": ev.get("name") or "",
                           "gift": gift, "num": num, "value": round(value, 2),
                           "paid": bool(ev.get("paid"))})
        if len(s["gifts"]) > 300:
            del s["gifts"][:-300]
        s["gift_count"] += num
        s["gift_value"] = round(s["gift_value"] + value, 2)
        it = s["gift_by"].setdefault(gift, {"name": gift, "count": 0, "value": 0.0})
        it["count"] += num
        it["value"] = round(it["value"] + value, 2)

    def stats_payload(self):
        s = self.session
        items = sorted(s["gift_by"].values(), key=lambda x: (-x["value"], -x["count"], x["name"]))[:8]
        return {
            "duration": self._live_seconds(),
            "live": self.live_connected,
            "tokens": dict(self.brain.usage),
            "token_label": (self.cfg.get("stats") or {}).get("token_label") or "本场已用 Token",
            "gifts": {"count": s["gift_count"], "value": round(s["gift_value"], 2),
                      "items": items, "recent": list(reversed(s["gifts"][-20:]))},
        }

    def reset_stats(self):
        self.session.update({"live_since": time.time() if self.live_connected else None,
                             "live_total": 0.0, "gifts": [], "gift_count": 0,
                             "gift_value": 0.0, "gift_by": {}})
        self.brain.usage.update({"prompt": 0, "completion": 0, "total": 0, "calls": 0, "est_calls": 0})

    async def stats_loop(self):
        """0.5 秒跟一次连接状态，直播时长停得准一点。"""
        while True:
            self._track_live(self.live_connected)
            await asyncio.sleep(0.5)

    # ---------- 后台任务 ----------
    async def status_loop(self):
        while True:
            self._track_live(self.live_connected)
            tts = self.cfg["tts"]
            if not tts.get("enabled", True):
                eng = "已关闭"
            elif self.engine.lock.locked():
                eng = "合成中"
            else:
                a = await self.engine.alive(tts["api_url"])
                eng = {True: "在线", None: "忙碌", False: "未启动"}[a]
            ai = self.cfg["ai"]
            live = self.live
            douyin = self.platform == "douyin"
            if douyin:
                if live.connected:
                    where = "已连接 " + str(live.room_id or "抖音直播间")
                elif live.client:
                    where = "连接中…"
                else:
                    where = "未连接"
                who = live.login_name or ("未登录" if live.connected else "未连接")
            else:
                where = ("已连接 " + str(live.room_id)) if live.connected else ("连接中…" if live.client else "未连接")
                who = live.login_name or "未登录"
            self.status = {
                "platform": "douyin" if douyin else "bilibili",
                "live": where,
                "account": who,
                "bili": where,
                "login": who,
                "ai": f"Qoder · {ai.get('qoder_model') or '默认'}" if ai.get("backend") != "openai" else f"API · {ai.get('openai_model')}",
                "engine": eng,
                "queue": len(self.pipe.jobs),
                "paused": self.pipe.paused,
                "speaking": bool(self.pipe.current),
                "session": bool(self.session_active),
                "stats": self.stats_payload(),
            }
            self.push("status", {"status": self.status})
            await asyncio.sleep(2)

    async def startup(self):
        self.pipe.start()
        self.tasks = [asyncio.create_task(self.status_loop()), asyncio.create_task(self.stats_loop()),
                      asyncio.create_task(self.songs.run()), asyncio.create_task(self.games.run())]
        if (self.cfg.get("session") or {}).get("auto_start"):
            await self.start_session(auto=True)
        else:
            self.push("log", {"level": "info",
                              "msg": "已就绪，等待开始：点控制台顶部「开始」后，会按设置启动连接 / 语音 / 歌单 / 游戏"})

    # ---------- 开播总开关 ----------
    async def start_session(self, auto=False):
        """按设置启动：语音引擎、连接直播间、自动歌单、游戏轮换。"""
        if self.session_active:
            return []
        self.session_active = True
        cfg = self.cfg
        started = []
        if cfg["tts"].get("enabled") and cfg["tts"].get("auto_start"):
            asyncio.create_task(self.engine.start(cfg["tts"], lambda m: self.push("log", {"level": "info", "msg": m})))
            started.append("语音引擎")
        if cfg.get("auto_connect") and self._has_room():
            asyncio.create_task(self.connect())
            started.append("直播间")
        if (cfg.get("songs") or {}).get("autoplay", {}).get("enabled"):
            self.songs.wake.set()
            started.append("自动歌单")
        if (cfg.get("games") or {}).get("enabled") and (cfg.get("games") or {}).get("auto"):
            self.games.next_at = time.time() + 20
            started.append("游戏轮换")
        asyncio.create_task(self.brain.warm(cfg))
        if cfg["ai"].get("backend") == "zcode":
            asyncio.create_task(self.brain.zcode.ensure(cfg["zcode"],
                                                        lambda m: self.push("log", {"level": "info", "msg": m})))
        msg = f"已开始（{'自动' if auto else '手动'}）：" + ("、".join(started) if started else "没有勾选任何启动项")
        self.push("log", {"level": "info", "msg": msg})
        self.push("session", {"active": True, "started": started})
        return started

    async def stop_session(self):
        """停止：断开直播间、停掉音乐和当前游戏（设置不变，下次开始继续用）。"""
        if not self.session_active:
            return False
        self.session_active = False
        await self.disconnect()
        self.pipe.clear()
        self.player.skip()
        self.songs.control("skip")
        self.games.stop()
        self.push("log", {"level": "info", "msg": "已停止：直播间已断开，音乐与游戏已停"})
        self.push("session", {"active": False, "started": []})
        return True

    def _has_room(self):
        if self.platform == "douyin":
            dy = self.cfg.get("douyin") or {}
            return bool((dy.get("web_rid") or "").strip() or (dy.get("room_url") or "").strip()
                        or (dy.get("mode") or "browser") == "relay")
        return bool(self.cfg.get("room_id"))

    async def connect(self):
        self.session_active = True  # 手动点连接也算开播，自动歌单/游戏轮换随之生效
        if self.platform == "douyin":
            self.push("log", {"level": "info", "msg": "正在连接抖音直播间 …"})
            try:
                await self.douyin.start(self.cfg.get("douyin") or {})
            except Exception as e:
                self.push("log", {"level": "error", "msg": f"连接抖音直播间失败：{e}"})
            return
        self.push("log", {"level": "info", "msg": f"正在连接直播间 {self.cfg['room_id']} …"})
        try:
            await self.bili.start(self.cfg["room_id"], self.cfg.get("bili_cookie", ""))
        except Exception as e:
            self.push("log", {"level": "error", "msg": f"连接直播间失败：{e}"})

    async def disconnect(self):
        await self.bili.stop()
        await self.douyin.stop()
        self._track_live(False)
        self.push("log", {"level": "info", "msg": "已断开直播间"})

    async def reconnect(self):
        await self.bili.stop()
        await self.douyin.stop(keep=False)
        await self.connect()

    async def shutdown(self):
        # 先让直播画面立刻隐藏，再收拾后台
        if self.baker.running:
            self.baker.stop()
        log.info("通知 %d 个显示页面退出", len(self.ws))
        for ws in list(self.ws):
            if not ws.closed:
                try:
                    await asyncio.wait_for(ws.send_str(json.dumps({"kind": "bye"})), 1)
                except (Exception, asyncio.CancelledError):
                    pass
        await asyncio.sleep(0.15)
        for ws in list(self.ws):
            try:
                await asyncio.wait_for(ws.close(), 1)
            except (Exception, asyncio.CancelledError):
                pass
        self.ws.clear()
        for t in getattr(self, "tasks", []):
            t.cancel()
        pending = list(getattr(self, "tasks", [])) + list(getattr(self.pipe, "tasks", []))
        if self.games.task and not self.games.task.done():
            self.games.task.cancel()
            pending.append(self.games.task)
        for t in pending:
            try:
                await asyncio.wait_for(t, 0.5)
            except (Exception, asyncio.CancelledError):
                pass
        for coro in (self.bili.stop(), self.douyin.stop(keep=False), self.brain.close()):
            try:
                await asyncio.wait_for(coro, 4)
            except (Exception, asyncio.CancelledError):
                pass
        self.player.close()
        if self.cfg["tts"].get("stop_on_exit", True):
            self.engine.stop()


# ---------- HTTP ----------
def pick_path(kind, initial=""):
    import tkinter
    from tkinter import filedialog
    root = tkinter.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        if kind == "dir":
            return filedialog.askdirectory(initialdir=initial or None, title="选择文件夹")
        types = [("音频文件", "*.wav *.mp3 *.flac *.ogg *.m4a"), ("所有文件", "*.*")] if kind == "audio" \
            else [("程序", "*.exe"), ("所有文件", "*.*")]
        return filedialog.askopenfilename(initialdir=initial or None, filetypes=types, title="选择文件")
    finally:
        root.destroy()


def build_web(app: App):
    routes = web.RouteTableDef()

    @web.middleware
    async def guard(request, handler):
        host = request.host.split(":")[0]
        if host not in ("127.0.0.1", "localhost"):
            return web.Response(status=403, text="forbidden")
        if request.method == "POST" and request.headers.get("X-BVB") != "1":
            return web.Response(status=403, text="missing header")
        return await handler(request)

    def ok(**kw):
        return web.json_response({"ok": True, **kw})

    def page(name):
        return web.FileResponse(os.path.join(config.WEB_DIR, name), headers={"Cache-Control": "no-cache"})

    @routes.get("/")
    async def index(_):
        return page("index.html")

    @routes.get("/overlay")
    async def overlay(_):
        return page("overlay.html")

    @routes.get("/live2d")
    async def live2d_page(_):
        return page("live2d.html")

    @routes.get("/game")
    async def game_page(_):
        return page("game.html")

    @routes.get("/stats")
    async def stats_page(_):
        return page("stats.html")

    @routes.get("/favicon.ico")
    async def favicon(_):
        f = os.path.join(config.WEB_DIR, "favicon.ico")
        if not os.path.exists(f):
            return web.Response(status=204)
        return web.FileResponse(f, headers={"Cache-Control": "max-age=86400"})

    @routes.get("/l2d/model/{path:.*}")
    async def l2d_file(request):
        l2d = app.cfg["live2d"]
        rel = request.match_info["path"]
        if rel == "auto.model3.json":
            try:
                return web.json_response(live2d.build_model_json(l2d))
            except Exception as e:
                return web.json_response({"error": str(e)}, status=404)
        full = live2d.safe_path(l2d["model_dir"], rel)
        if not full:
            return web.Response(status=404)
        return web.FileResponse(full)

    @routes.get("/api/l2d/info")
    async def l2d_info(_):
        l2d = app.cfg["live2d"]
        try:
            exprs, motions = live2d.list_assets(l2d["model_dir"])
            err = "" if os.path.exists(os.path.join(l2d["model_dir"], l2d["model_file"])) else "找不到模型文件"
        except Exception as e:
            exprs, motions, err = [], [], str(e)
        return web.json_response({"cfg": l2d, "expressions": exprs, "motions": motions, "error": err,
                                  "model_files": live2d.list_model_files(l2d["model_dir"])})

    @routes.post("/api/l2d/test")
    async def l2d_test(request):
        d = await request.json()
        app.push("l2d_test", {"expressions": d.get("expressions", []), "motion": d.get("motion", ""),
                              "emotion": d.get("emotion", ""), "text": d.get("text", "")})
        return ok()

    @routes.get("/ws")
    async def ws_handler(request):
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        app.ws.add(ws)
        await ws.send_str(json.dumps({"kind": "hello", "history": list(app.history), "status": app.status,
                                      "game": app.games.state()}, ensure_ascii=False))
        try:
            async for msg in ws:
                if msg.type == WSMsgType.ERROR:
                    break
        finally:
            app.ws.discard(ws)
        return ws

    @routes.get("/api/config")
    async def get_config(_):
        c = json.loads(json.dumps(app.cfg))
        c["_qoder_default"] = default_qoder_exe()
        c["_browser_default"] = find_browser()
        c["_logged_in"] = bool(app.cfg.get("bili_cookie"))
        c.pop("bili_cookie", None)
        c["songs"]["_ne_logged_in"] = bool(c["songs"].pop("netease_cookie", ""))
        return web.json_response(c)

    @routes.post("/api/config")
    async def set_config(request):
        patch = await request.json()
        patch.pop("bili_cookie", None)
        if isinstance(patch.get("songs"), dict):
            patch["songs"].pop("netease_cookie", None)
            patch["songs"].pop("_ne_logged_in", None)
        old_room = app.cfg.get("room_id")
        old_platform = app.platform
        app.cfg = config.merge(app.cfg, patch)
        config.save(app.cfg)
        if "live2d" in patch:
            app.push("l2d_config", {})
        if "songs" in patch:
            app.songs._apply_volume()
        if "games" in patch:
            if not app.cfg["games"].get("enabled", True):
                app.games.stop()
            app.games.push()
        if app.platform != old_platform:
            name = "抖音直播" if app.platform == "douyin" else "B站直播"
            if app.cfg.get("auto_connect") and app._has_room():
                app.push("log", {"level": "info", "msg": f"已切换弹幕来源：{name}，正在重连…"})
                asyncio.create_task(app.reconnect())
            else:
                app.push("log", {"level": "info", "msg": f"已切换弹幕来源：{name}，填好直播间后点「保存并重连」"})
                asyncio.create_task(app.disconnect())
        elif str(app.cfg.get("room_id")) != str(old_room) and app.bili.client:
            asyncio.create_task(app.connect())
        return ok()

    @routes.post("/api/bili/connect")
    async def bili_connect(_):
        asyncio.create_task(app.connect())
        return ok()

    @routes.post("/api/bili/disconnect")
    async def bili_disconnect(_):
        await app.disconnect()
        return ok()

    # ---------- 抖音 ----------
    @routes.post("/api/douyin/connect")
    async def douyin_connect(_):
        asyncio.create_task(app.connect())
        return ok()

    @routes.post("/api/douyin/disconnect")
    async def douyin_disconnect(_):
        await app.disconnect()
        return ok()

    @routes.get("/api/douyin/health")
    async def douyin_health(_):
        return web.json_response(app.douyin.health())

    @routes.post("/api/douyin/ingest")
    async def douyin_ingest(request):
        data = await request.json()
        n = app.douyin.ingest(data)
        return ok(count=n)

    @routes.get("/ingest/douyin")
    async def douyin_ingest_ws(request):
        ws = web.WebSocketResponse(heartbeat=25)
        await ws.prepare(request)
        app.push("log", {"level": "info", "msg": "外部弹幕工具已连接 /ingest/douyin"})
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    app.douyin.ingest(json.loads(msg.data))
                except (ValueError, TypeError) as e:
                    await ws.send_str(json.dumps({"ok": False, "error": f"格式错误：{e}"}, ensure_ascii=False))
        finally:
            return ws

    @routes.post("/api/bili/qr")
    async def bili_qr(_):
        import qrcode
        import qrcode.image.svg
        url, key = await app.qr.generate()
        img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=8)
        return ok(svg=img.to_string(encoding="unicode"), key=key)

    @routes.post("/api/bili/qrpoll")
    async def bili_qrpoll(request):
        key = (await request.json())["key"]
        code, msg, cookie = await app.qr.poll(key)
        if code == 0 and cookie:
            app.cfg["bili_cookie"] = cookie
            config.save(app.cfg)
            asyncio.create_task(app.connect())
        return ok(code=code, msg=msg)

    @routes.post("/api/bili/cookie")
    async def bili_cookie(request):
        app.cfg["bili_cookie"] = (await request.json()).get("cookie", "").strip()
        config.save(app.cfg)
        asyncio.create_task(app.connect())
        return ok()

    @routes.post("/api/bili/logout")
    async def bili_logout(_):
        app.cfg["bili_cookie"] = ""
        config.save(app.cfg)
        asyncio.create_task(app.connect())
        return ok()

    @routes.post("/api/test_event")
    async def test_event(request):
        ev = await request.json()
        ev.update({"test": True, "ts": time.time(), "uid": 0})
        for k, d in (("num", 1), ("value", 0.0), ("price", 30)):
            if k in ev:
                ev[k] = type(d)(ev[k] or d)
        if ev["type"] == "gift":
            ev["paid"] = ev.get("value", 0) > 0
        if ev["type"] == "superchat":
            ev["value"] = float(ev.get("price", 30))
        app.on_event(ev)
        return ok()

    @routes.post("/api/say")
    async def say(request):
        d = await request.json()
        text = (d.get("text") or "").strip()
        if not text:
            return ok()
        if d.get("ai"):
            try:
                text, emotion = await app.brain.ai(app.cfg, text)
            except Exception as e:
                log.error("手动让 AI 说话失败：%s", err_text(e), exc_info=True)
                return web.json_response({"ok": False, "error": err_text(e)})
        else:
            emotion = ""
        app.pipe.say(text, emotion)
        return ok(text=text)

    @routes.post("/api/ai/test")
    async def ai_test(request):
        prompt = (await request.json()).get("prompt", "")
        t0 = time.time()
        try:
            text, emotion = await app.brain.ai(app.cfg, prompt)
            return ok(text=text, emotion=emotion, seconds=round(time.time() - t0, 1))
        except Exception as e:
            log.error("AI 测试失败：%s", err_text(e), exc_info=True)
            return web.json_response({"ok": False, "error": err_text(e),
                                      "seconds": round(time.time() - t0, 1)})

    @routes.post("/api/ai/test_openai")
    async def ai_test_openai(_):
        ai = app.cfg["ai"]
        if not (ai.get("openai_base") or "").strip():
            return web.json_response({"ok": False, "error": "还没有填接口地址"})
        timeout = min(15.0, max(5.0, float(ai.get("timeout", 15))))
        results = []
        for mode in ("responses", "chat"):
            t0 = time.time()
            try:
                text = await app.brain.openai.probe(ai, mode, timeout=timeout)
                results.append({"mode": mode, "ok": True, "reply": (text or "")[:60],
                                "ms": int((time.time() - t0) * 1000)})
            except Exception as e:
                results.append({"mode": mode, "ok": False, "error": err_text(e, 240),
                                "ms": int((time.time() - t0) * 1000)})
        return ok(mode=app.brain.openai.mode_of(ai), results=results)

    @routes.post("/api/ai/reset")
    async def ai_reset(_):
        await app.brain.close()
        app.brain.openai.history.clear()
        return ok()

    @routes.get("/api/ai/models")
    async def ai_models(_):
        ai = app.cfg["ai"]
        try:
            if ai.get("backend") == "openai":
                models = await app.brain.openai.list_models(ai)
            elif ai.get("backend") == "cli":
                preset = CLI_PRESETS.get(app.cfg["cli"].get("preset", ""), {})
                models = preset.get("models", [])
                if not models:
                    return web.json_response({"ok": False, "error": "这个 CLI 没有预设模型列表，直接把 --model 写进参数里"})
            elif ai.get("backend") == "zcode":
                models = ["GLM-5.3-Flash", "GLM-5.3"]
            else:
                models = await list_qoder_models(ai)
            return ok(models=models)
        except Exception as e:
            return web.json_response({"ok": False, "error": err_text(e)})

    @routes.get("/api/ai/cli/presets")
    async def cli_presets(_):
        return web.json_response({k: {kk: vv for kk, vv in v.items()} for k, v in CLI_PRESETS.items()})

    @routes.post("/api/ai/cli/login")
    async def cli_login(request):
        d = await request.json()
        cli = app.cfg["cli"]
        preset = CLI_PRESETS.get(d.get("preset") or cli.get("preset", ""), {})
        exe = (d.get("exe") or cli.get("exe") or preset.get("exe") or "").strip()
        env = d.get("env") or cli.get("env") or preset.get("env") or ""
        # 登录用 TUI/登录子命令，绝不带 -p 这类单次问答参数
        if "login_args" in preset:
            args = preset["login_args"]
        else:
            args = [a for a in (d.get("login_args") or []) if a and "{prompt}" not in a]
        if not exe:
            return web.json_response({"ok": False, "error": "没有可用的 CLI 路径"})
        bat = os.path.join(config.BASE_DIR, "_cli_login.bat")
        body = ["@echo off", "chcp 65001 >nul", "title CodeBuddy login"]
        for line in env.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                body.append(f'set "{k.strip()}={v.strip()}"')
        argv = " ".join(f'"{a}"' for a in [exe, *args] if a != "")
        body += ["echo.", f"echo  Run this CLI, type: /login  (and press Enter), finish auth in browser.", "echo.",
                 argv, "echo.", "echo ==== CLI exited ====", "pause"]
        with open(bat, "w", encoding="utf-8") as f:
            f.write("\n".join(body) + "\n")
        subprocess.Popen(["cmd", "/c", "start", "CodeBuddy login", bat])
        return ok(message="已打开登录窗口：在窗口里输入 /login 回车，按提示在浏览器完成登录，然后关掉窗口")

    # ---------- 点歌 ----------
    @routes.get("/songs")
    async def songs_page(_):
        return page("songs.html")

    @routes.get("/api/songs/state")
    async def songs_state(_):
        return web.json_response(app.songs.state())

    @routes.post("/api/songs/control")
    async def songs_control(request):
        d = await request.json()
        app.songs.control(d.get("action"), d.get("qid"))
        return ok()

    @routes.post("/api/songs/search")
    async def songs_search(request):
        q = ((await request.json()).get("q") or "").strip()
        try:
            return ok(songs=await app.songs.ne.search_with_status(q) if q else [])
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)})

    @routes.post("/api/songs/add")
    async def songs_add(request):
        d = await request.json()
        app.songs.add(d["song"], d.get("by") or "主播", "__host__")
        return ok()

    @routes.get("/api/songs/playlists")
    async def songs_playlists(_):
        try:
            return ok(**await app.songs.ne.my_playlists())
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)})

    @routes.post("/api/songs/autoplay")
    async def songs_autoplay(request):
        d = await request.json()
        ap = app.cfg["songs"]["autoplay"]
        if "enabled" in d:
            ap["enabled"] = bool(d["enabled"])
        if "playlist_id" in d:
            ap["playlist_id"] = str(d["playlist_id"] or "")
            ap["playlist_name"] = str(d.get("playlist_name") or "")
        if "mode" in d:
            ap["mode"] = d["mode"] if d["mode"] in ("shuffle", "order") else "shuffle"
        if "interrupt" in d:
            ap["interrupt"] = bool(d["interrupt"])
        config.save(app.cfg)
        app.songs._auto_tracks = []
        app.songs._auto_pid = None
        app.songs._auto_bag = []
        app.songs.wake.set()
        app.songs.push()
        return ok(autoplay=ap)

    @routes.post("/api/songs/give")
    async def songs_give(request):
        d = await request.json()
        app.songs.give(d.get("key"), int(d.get("song", 0)), int(d.get("pin", 0)))
        return ok()

    @routes.post("/api/songs/qr")
    async def songs_qr(_):
        import qrcode
        import qrcode.image.svg
        key, url = await app.songs.ne.qr_key()
        img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=8)
        return ok(svg=img.to_string(encoding="unicode"), key=key)

    @routes.post("/api/songs/qrpoll")
    async def songs_qrpoll(request):
        key = (await request.json())["key"]
        code, msg, cookie = await app.songs.ne.qr_poll(key)
        if code == 803 and cookie:
            app.cfg["songs"]["netease_cookie"] = cookie
            config.save(app.cfg)
            await app.songs.refresh_account()
        return ok(code=code, msg=msg)

    @routes.post("/api/songs/cookie")
    async def songs_cookie(request):
        app.cfg["songs"]["netease_cookie"] = ((await request.json()).get("cookie") or "").strip()
        config.save(app.cfg)
        await app.songs.refresh_account()
        return ok(account=app.songs.account)

    # ---------- AI 游戏 ----------
    @routes.get("/api/games/catalog")
    async def games_catalog(_):
        choices = app.cfg["games"].get("choices", {})
        return web.json_response({"games": [{"id": k, **v, "enabled": bool(choices.get(k, True))}
                                            for k, v in CATALOG.items()]})

    @routes.get("/api/games/state")
    async def games_state(_):
        return web.json_response(app.games.state())

    @routes.post("/api/games/start")
    async def games_start(request):
        gid = ((await request.json()).get("id") or "").strip()
        err = app.games.start(gid, manual=True)
        return web.json_response({"ok": not err, **({"error": err} if err else {})})

    @routes.post("/api/games/stop")
    async def games_stop(_):
        return ok(stopped=app.games.stop())

    @routes.post("/api/games/reset")
    async def games_reset(_):
        app.games.reset_board()
        return ok()

    @routes.post("/api/tts/start")
    async def tts_start(_):
        asyncio.create_task(app.engine.start(app.cfg["tts"], lambda m: app.push("log", {"level": "info", "msg": m})))
        return ok()

    @routes.get("/api/tts/bake")
    async def bake_status(_):
        info = TTS_CACHE.info(app.cfg["tts"])
        phrases = collect_phrases(app.cfg)
        return ok(bake=dict(app.baker.state), phrases=len(phrases), sample=phrases[:6], **info)

    @routes.post("/api/tts/bake")
    async def bake_start(_):
        phrases = collect_phrases(app.cfg)
        if not phrases:
            return web.json_response({"ok": False, "error": "没有可烘焙的固定话术"})
        if app.baker.running:
            return web.json_response({"ok": False, "error": "正在烘焙中，等这一轮结束"})
        app.baker.start(app, phrases)
        return ok(total=len(phrases))

    @routes.post("/api/tts/bake/stop")
    async def bake_stop(_):
        return ok(stopped=app.baker.stop())

    @routes.post("/api/tts/bake/clear")
    async def bake_clear(_):
        n = TTS_CACHE.clear()
        app.push("log", {"level": "info", "msg": f"已清空 {n} 条固定话术缓存"})
        return ok(removed=n, **TTS_CACHE.info(app.cfg["tts"]))

    @routes.post("/api/tts/stop")
    async def tts_stop(_):
        if app.engine.proc:
            app.engine.stop()
            app.push("log", {"level": "info", "msg": "已关闭 GPT-SoVITS 引擎"})
            return ok()
        return web.json_response({"ok": False, "error": "引擎不是本软件启动的，请在它自己的窗口关闭"})

    @routes.post("/api/session/start")
    async def session_start(_):
        started = await app.start_session()
        return ok(started=started, active=app.session_active)

    @routes.post("/api/session/stop")
    async def session_stop(_):
        stopped = await app.stop_session()
        return ok(stopped=stopped, active=app.session_active)

    @routes.get("/api/tts/weights")
    async def tts_weights(_):
        gpt, sovits = app.engine.list_weights(app.cfg["tts"]["gsv_dir"])
        return web.json_response({"gpt": gpt, "sovits": sovits})

    @routes.get("/api/tts/log")
    async def tts_log(_):
        return web.Response(text=app.engine.tail_log(80))

    @routes.get("/api/audio/devices")
    async def devices(_):
        return web.json_response(Player.devices())

    @routes.post("/api/control")
    async def control(request):
        action = (await request.json()).get("action")
        if action == "pause":
            app.pipe.paused = True
        elif action == "resume":
            app.pipe.paused = False
        elif action == "skip":
            app.player.skip()
        elif action == "clear":
            app.pipe.clear()
        app.push("log", {"level": "info", "msg": {"pause": "已暂停自动回复", "resume": "已恢复自动回复",
                                                  "skip": "已跳过当前语音", "clear": "已清空待回复队列"}.get(action, action)})
        return ok()

    @routes.post("/api/pick")
    async def pick(request):
        d = await request.json()
        path = await asyncio.get_running_loop().run_in_executor(None, pick_path, d.get("kind", "file"), d.get("initial", ""))
        return ok(path=(path or "").replace("/", "\\"))

    @routes.post("/api/stats/reset")
    async def stats_reset(_):
        app.reset_stats()
        app.push("log", {"level": "info", "msg": "本场统计已重置（直播时长、礼物、Token）"})
        return ok(stats=app.stats_payload())

    @routes.post("/api/quit")
    async def quit_(_):
        asyncio.get_running_loop().call_later(0.3, app.stop_event.set)
        return ok()

    wapp = web.Application(middlewares=[guard])
    wapp.add_routes(routes)
    wapp.router.add_static("/static", config.WEB_DIR)
    return wapp


def find_edge():
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            p = os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe")
            if os.path.exists(p):
                return p
    return None


def open_ui(url, on_close=None, native=True):
    """优先用内嵌 WebView2 窗口；不行再退回 Edge 应用窗口 / 默认浏览器。"""
    try:
        if native:
            import desktop
            if desktop.available():
                icon = os.path.join(config.WEB_DIR, "favicon.ico")
                desktop.run(url, on_close=on_close, width=int(cfg_ui_size()[0]),
                            height=int(cfg_ui_size()[1]), icon=icon if os.path.exists(icon) else None)
                return "native"
    except Exception as e:
        log.warning("内嵌窗口启动失败，改用浏览器窗口：%s", e)
    edge = find_edge()
    if edge:
        subprocess.Popen([edge, f"--app={url}", "--window-size=1320,900"])
        return "edge"
    webbrowser.open(url)
    return "browser"


def cfg_ui_size():
    try:
        ui = config.load().get("ui") or {}
        return ui.get("width", 1400), ui.get("height", 940)
    except Exception:
        return 1400, 940


def port_in_use(port):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


async def amain(app: App, open_window=True):
    app.loop = asyncio.get_running_loop()
    app.stop_event = asyncio.Event()
    port = int(app.cfg.get("web_port", 8787))
    runner = web.AppRunner(build_web(app), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", port, reuse_address=False).start()
    url = f"http://127.0.0.1:{port}/"
    log.info("界面地址：%s    OBS 字幕：%soverlay", url, url)
    await app.startup()
    if open_window and app.cfg.get("open_ui", True) and "--no-ui" not in sys.argv:
        open_ui(url)
    try:
        await app.stop_event.wait()
    finally:
        log.info("正在退出…")
        try:
            await asyncio.wait_for(asyncio.shield(asyncio.ensure_future(app.shutdown())), 12)
        except (Exception, asyncio.CancelledError) as e:
            log.warning("退出清理未完全完成：%r", e)
        try:
            await asyncio.wait_for(runner.cleanup(), 1)
        except (Exception, asyncio.CancelledError):
            pass
        log.info("已退出")


def _msgbox(text, title="鲸语 WhaleTalk"):
    try:
        ctypes.windll.user32.MessageBoxW(0, text, title, 0x10)
    except Exception:
        pass


def _console_hwnd():
    try:
        fn = ctypes.windll.kernel32.GetConsoleWindow
        fn.restype = ctypes.c_void_p
        return fn() or 0
    except Exception:
        return 0


def _hide_console():
    h = _console_hwnd()
    if h:
        ctypes.windll.user32.ShowWindow(ctypes.c_void_p(h), 0)


def _show_console():
    h = _console_hwnd()
    if h:
        ctypes.windll.user32.ShowWindow(ctypes.c_void_p(h), 5)


def _wait_port(port, timeout=30.0):
    end = time.time() + timeout
    while time.time() < end:
        if port_in_use(port):
            return True
        time.sleep(0.15)
    return False


def _backend_thread(app):
    try:
        asyncio.run(amain(app, open_window=False))
    except Exception:
        log.exception("后台服务异常退出")


def _request_stop(app):
    for _ in range(30):
        loop = getattr(app, "loop", None)
        if loop and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(app.stop_event.set)
                return
            except RuntimeError:
                return
        time.sleep(0.1)


def main():
    if sys.platform == "win32":
        ctypes.windll.kernel32.SetConsoleTitleW("鲸语 WhaleTalk - 关闭此窗口即退出")
    cfg = config.load()
    port = int(cfg.get("web_port", 8787))
    if port_in_use(port):
        print("程序已经在运行，直接打开界面。")
        _hide_console()
        if open_ui(f"http://127.0.0.1:{port}/") != "native":
            _show_console()
        return
    print("=" * 60)
    print(" 鲸语 WhaleTalk  ·  B站 / 抖音直播 AI 语音助手   关闭此窗口即退出程序")
    print("=" * 60)
    app = App()

    # 原生窗口：后台跑服务，主线程跑 WebView2 窗口
    native = (sys.platform == "win32" and cfg.get("ui", {}).get("native", True)
              and "--no-ui" not in sys.argv and "--browser-ui" not in sys.argv)
    if native:
        try:
            import desktop
            native = desktop.available()
        except Exception as e:
            log.warning("内嵌窗口不可用：%s", e)
            native = False

    if native:
        th = threading.Thread(target=_backend_thread, args=(app,), daemon=True, name="wt-backend")
        th.start()
        if not _wait_port(port, 30):
            log.error("后台服务启动失败")
            _msgbox("后台服务启动失败，请查看 logs/app.log 并把日志发给开发者。")
            return
        mode = "none"
        _hide_console()
        try:
            mode = open_ui(f"http://127.0.0.1:{port}/", on_close=lambda: _request_stop(app))
        except Exception:
            log.exception("打开界面失败")
        if mode != "native":
            _show_console()  # 退回浏览器窗口时把控制台还回来，方便看日志/退出
        if mode == "native":
            _request_stop(app)
            th.join(timeout=25)
        else:
            th.join()  # 退回浏览器时，等控制台关闭 / 后台退出
        logging.shutdown()
        sys.stdout.flush()
        os._exit(0)

    try:
        asyncio.run(amain(app))
    except KeyboardInterrupt:
        pass
    logging.shutdown()
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.exception("启动失败")
        _msgbox(f"启动失败：{e}\n\n详情见 logs/app.log")
        raise
