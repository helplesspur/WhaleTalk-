import asyncio
import collections
import ctypes
import json
import logging
import os
import socket
import subprocess
import sys
import time
import webbrowser

from aiohttp import web, WSMsgType

import config
import live2d
from bili import BiliLive, QrLogin
from brain import Brain, default_qoder_exe, list_qoder_models
from pipeline import Pipeline
from songs import SongManager
from tts import GsvEngine, Player

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
        if record.name in ("ai", "tts", "bili", "app"):
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
        self.pipe = Pipeline(self)
        self.songs = SongManager(self)
        self.qr = QrLogin()
        self.status = {}
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
        self.pipe.on_event(ev)

    # ---------- 后台任务 ----------
    async def status_loop(self):
        while True:
            tts = self.cfg["tts"]
            if not tts.get("enabled", True):
                eng = "已关闭"
            elif self.engine.lock.locked():
                eng = "合成中"
            else:
                a = await self.engine.alive(tts["api_url"])
                eng = {True: "在线", None: "忙碌", False: "未启动"}[a]
            ai = self.cfg["ai"]
            self.status = {
                "bili": ("已连接 " + str(self.bili.room_id)) if self.bili.connected else ("连接中…" if self.bili.client else "未连接"),
                "login": self.bili.login_name or "未登录",
                "ai": f"Qoder · {ai.get('qoder_model') or '默认'}" if ai.get("backend") != "openai" else f"API · {ai.get('openai_model')}",
                "engine": eng,
                "queue": len(self.pipe.jobs),
                "paused": self.pipe.paused,
                "speaking": bool(self.pipe.current),
            }
            self.push("status", {"status": self.status})
            await asyncio.sleep(2)

    async def startup(self):
        self.pipe.start()
        self.tasks = [asyncio.create_task(self.status_loop()), asyncio.create_task(self.songs.run()),
                      asyncio.create_task(self.brain.warm(self.cfg))]
        if self.cfg["tts"].get("enabled") and self.cfg["tts"].get("auto_start"):
            asyncio.create_task(self.engine.start(self.cfg["tts"], lambda m: self.push("log", {"level": "info", "msg": m})))
        if self.cfg.get("auto_connect") and self.cfg.get("room_id"):
            asyncio.create_task(self.connect())

    async def connect(self):
        self.push("log", {"level": "info", "msg": f"正在连接直播间 {self.cfg['room_id']} …"})
        try:
            await self.bili.start(self.cfg["room_id"], self.cfg.get("bili_cookie", ""))
        except Exception as e:
            self.push("log", {"level": "error", "msg": f"连接直播间失败：{e}"})

    async def shutdown(self):
        # 先让直播画面立刻隐藏，再收拾后台
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
        for t in getattr(self, "tasks", []) + getattr(self.pipe, "tasks", []):
            try:
                await asyncio.wait_for(t, 0.5)
            except (Exception, asyncio.CancelledError):
                pass
        for coro in (self.bili.stop(), self.brain.close()):
            try:
                await asyncio.wait_for(coro, 3)
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
        await ws.send_str(json.dumps({"kind": "hello", "history": list(app.history), "status": app.status}, ensure_ascii=False))
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
        app.cfg = config.merge(app.cfg, patch)
        config.save(app.cfg)
        if "live2d" in patch:
            app.push("l2d_config", {})
        if "songs" in patch:
            app.songs._apply_volume()
        if str(app.cfg.get("room_id")) != str(old_room) and app.bili.client:
            asyncio.create_task(app.connect())
        return ok()

    @routes.post("/api/bili/connect")
    async def bili_connect(_):
        asyncio.create_task(app.connect())
        return ok()

    @routes.post("/api/bili/disconnect")
    async def bili_disconnect(_):
        await app.bili.stop()
        app.push("log", {"level": "info", "msg": "已断开直播间"})
        return ok()

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
                return web.json_response({"ok": False, "error": str(e)})
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
            return web.json_response({"ok": False, "error": str(e)})

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
            else:
                models = await list_qoder_models(ai)
            return ok(models=models)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e) or type(e).__name__})

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

    @routes.post("/api/tts/start")
    async def tts_start(_):
        asyncio.create_task(app.engine.start(app.cfg["tts"], lambda m: app.push("log", {"level": "info", "msg": m})))
        return ok()

    @routes.post("/api/tts/stop")
    async def tts_stop(_):
        if app.engine.proc:
            app.engine.stop()
            app.push("log", {"level": "info", "msg": "已关闭 GPT-SoVITS 引擎"})
            return ok()
        return web.json_response({"ok": False, "error": "引擎不是本软件启动的，请在它自己的窗口关闭"})

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


def open_ui(url):
    edge = find_edge()
    if edge:
        subprocess.Popen([edge, f"--app={url}", "--window-size=1320,900"])
    else:
        webbrowser.open(url)


def port_in_use(port):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


async def amain(app: App):
    app.loop = asyncio.get_running_loop()
    app.stop_event = asyncio.Event()
    port = int(app.cfg.get("web_port", 8787))
    runner = web.AppRunner(build_web(app), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", port, reuse_address=False).start()
    url = f"http://127.0.0.1:{port}/"
    log.info("界面地址：%s    OBS 字幕：%soverlay", url, url)
    await app.startup()
    if app.cfg.get("open_ui", True) and "--no-ui" not in sys.argv:
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


def main():
    if sys.platform == "win32":
        ctypes.windll.kernel32.SetConsoleTitleW("鲸语 WhaleTalk - 关闭此窗口即退出")
    cfg = config.load()
    port = int(cfg.get("web_port", 8787))
    if port_in_use(port):
        print("程序已经在运行，直接打开界面。")
        open_ui(f"http://127.0.0.1:{port}/")
        return
    print("=" * 60)
    print(" 鲸语 WhaleTalk  ·  B站直播 AI 语音助手   关闭此窗口即退出程序")
    print("=" * 60)
    app = App()
    try:
        asyncio.run(amain(app))
    except KeyboardInterrupt:
        pass
    logging.shutdown()
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
