import asyncio
import http.cookies
import logging
import time

import aiohttp
import yarl

import blivedm
import blivedm.models.web as wm

log = logging.getLogger("bili")
logging.getLogger("blivedm").setLevel(logging.ERROR)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
GUARD_NAMES = {1: "总督", 2: "提督", 3: "舰长"}
QR_GEN = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
QR_POLL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
NAV = "https://api.bilibili.com/x/web-interface/nav"


def parse_cookie(s):
    s = (s or "").strip()
    if s and "=" not in s:
        return {"SESSDATA": s}
    out = {}
    for part in s.split(";"):
        if "=" in part:
            k, v = part.strip().split("=", 1)
            if k:
                # 浏览器“显示已解码”复制出来的 SESSDATA 带逗号，原样发送会被加引号导致无效
                out[k.strip()] = v.strip().strip('"').replace(",", "%2C")
    return out


def make_session(cookie_str):
    # 必须带 domain，否则 aiohttp 当成 bilibili.com 的 host-only cookie，api.bilibili.com 等子域名收不到
    jar = aiohttp.CookieJar()
    sc = http.cookies.SimpleCookie()
    for k, v in parse_cookie(cookie_str).items():
        sc[k] = v
        sc[k]["domain"] = "bilibili.com"
        sc[k]["path"] = "/"
    if sc:
        jar.update_cookies(sc)
    return aiohttp.ClientSession(cookie_jar=jar, headers={"User-Agent": UA})


class _Handler(blivedm.BaseHandler):
    _CMD_CALLBACK_DICT = blivedm.BaseHandler._CMD_CALLBACK_DICT.copy()

    def __init__(self, emit):
        self.emit = emit

    def _like(self, client, command):
        d = command.get("data") or {}
        self.emit({"type": "like", "uid": d.get("uid", 0), "name": d.get("uname", "")})

    _CMD_CALLBACK_DICT["LIKE_INFO_V3_CLICK"] = _like

    def _on_danmaku(self, client, m: wm.DanmakuMessage):
        self.emit({"type": "danmaku", "uid": m.uid, "name": m.uname, "text": m.msg,
                   "emoticon": m.dm_type == 1, "guard_level": m.privilege_type})

    def _on_gift(self, client, m: wm.GiftMessage):
        paid = m.coin_type == "gold"
        self.emit({"type": "gift", "uid": m.uid, "name": m.uname, "gift": m.gift_name, "num": m.num,
                   "value": round(m.total_coin / 1000, 2) if paid else 0.0, "paid": paid})

    def _on_user_toast_v2(self, client, m: wm.UserToastV2Message):
        if m.source == 2:
            return
        self.emit({"type": "guard", "uid": m.uid, "name": m.username, "level": m.guard_level,
                   "guard": GUARD_NAMES.get(m.guard_level, "舰长"), "num": m.num or 1,
                   "value": round(m.price / 1000, 2)})

    def _on_buy_guard(self, client, m: wm.GuardBuyMessage):
        self.emit({"type": "guard", "uid": m.uid, "name": m.username, "level": m.guard_level,
                   "guard": GUARD_NAMES.get(m.guard_level, "舰长"), "num": m.num or 1,
                   "value": round(m.price / 1000, 2)})

    def _on_super_chat(self, client, m: wm.SuperChatMessage):
        self.emit({"type": "superchat", "uid": m.uid, "name": m.uname, "text": m.message,
                   "price": m.price, "value": float(m.price)})

    def _on_interact_word_v2(self, client, m: wm.InteractWordV2Message):
        kind = {1: "enter", 2: "follow", 5: "follow"}.get(m.msg_type)
        if kind:
            self.emit({"type": kind, "uid": m.uid, "name": m.username})


class BiliLive:
    def __init__(self, on_event, on_status):
        self.on_event = on_event
        self.on_status = on_status
        self.session = None
        self.client = None
        self.room_id = None
        self.owner_uid = None
        self.login_uid = None
        self.login_name = ""
        self.login_error = ""
        self.connected = False
        self._watch = None

    def _emit(self, ev):
        ev["ts"] = time.time()
        if ev.get("name"):
            ev["name"] = str(ev["name"]).strip()
        try:
            self.on_event(ev)
        except Exception:
            log.exception("event handler failed")

    async def start(self, room_id, cookie):
        await self.stop()
        self.session = make_session(cookie)
        if parse_cookie(cookie):
            await self.refresh_login()
            if self.login_name:
                self.on_status(f"B站登录成功：{self.login_name}（UID {self.login_uid}）")
            else:
                self.on_status(f"B站登录无效：{self.login_error or 'Cookie 已过期或不完整'}，请重新扫码登录")
        self.client = blivedm.BLiveClient(int(room_id), session=self.session)
        self.client.set_handler(_Handler(self._emit))
        self.client.start()
        self._watch = asyncio.create_task(self._watch_init(room_id))

    async def _watch_init(self, room_id):
        for _ in range(100):
            await asyncio.sleep(0.2)
            if self.client and self.client.room_owner_uid:
                break
        if not self.client:
            return
        self.room_id = self.client.room_id
        self.owner_uid = self.client.room_owner_uid
        self.connected = bool(self.owner_uid)
        if self.connected:
            who = f"已登录：{self.login_name}" if self.login_name else "未登录B站（观众名字会被打码）"
            self.on_status(f"已连接直播间 {self.room_id}，{who}")
        else:
            self.on_status(f"连接直播间 {room_id} 失败，请检查房间号或网络")

    async def stop(self):
        if self._watch:
            self._watch.cancel()
            self._watch = None
        if self.client:
            try:
                await self.client.stop_and_close()
            except Exception:
                pass
            self.client = None
        if self.session:
            await self.session.close()
            self.session = None
        self.connected = False

    async def refresh_login(self):
        self.login_uid, self.login_name, self.login_error = None, "", ""
        try:
            async with self.session.get(NAV, timeout=aiohttp.ClientTimeout(total=10)) as r:
                j = await r.json(content_type=None)
            d = j.get("data") or {}
            if d.get("isLogin"):
                self.login_uid, self.login_name = d.get("mid"), d.get("uname", "")
            else:
                self.login_error = f"B站返回 {j.get('code')} {j.get('message', '')}".strip()
        except Exception as e:
            self.login_error = f"检查登录失败：{e}"
            log.warning("nav check failed: %s", e)


class QrLogin:
    """B站网页扫码登录：生成二维码 -> 轮询 -> 拿到 Cookie。"""

    async def generate(self):
        async with aiohttp.ClientSession(headers={"User-Agent": UA}) as s:
            async with s.get(QR_GEN, timeout=aiohttp.ClientTimeout(total=10)) as r:
                d = (await r.json(content_type=None))["data"]
        return d["url"], d["qrcode_key"]

    async def poll(self, key):
        async with aiohttp.ClientSession(headers={"User-Agent": UA}) as s:
            async with s.get(QR_POLL, params={"qrcode_key": key}, timeout=aiohttp.ClientTimeout(total=10)) as r:
                d = (await r.json(content_type=None))["data"]
                code = d.get("code")
                if code != 0:
                    msg = {86101: "等待扫码", 86090: "已扫码，请在手机上确认", 86038: "二维码已过期"}.get(code, d.get("message", ""))
                    return code, msg, ""
                cookies = {k: v.value for k, v in r.cookies.items()}
        if not cookies.get("SESSDATA"):
            raw = yarl.URL(d.get("url", "")).raw_query_string
            q = dict(p.split("=", 1) for p in raw.split("&") if "=" in p)
            cookies = {k: q[k] for k in ("DedeUserID", "DedeUserID__ckMd5", "SESSDATA", "bili_jct") if k in q}
        return 0, "登录成功", "; ".join(f"{k}={v}" for k, v in cookies.items())
