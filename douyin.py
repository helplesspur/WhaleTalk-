"""抖音直播弹幕接入。

抖音网页直播的弹幕走的是需要 signature 的私有 WebSocket，纯 Python 复现很容易失效。
所以这里换个思路：让 Edge / Chrome 自己去连（浏览器有完整的签名逻辑），
我们通过 DevTools 协议往页面里注入一段小脚本，把弹幕、礼物、进场、关注、点赞的
文本读出来，再归一化成和 B 站一样的内部事件。

两条可选路径（config.json → douyin.mode）：
  browser  启动一个独立的浏览器窗口打开直播间网页，自动抓取（默认，开箱即用）
  relay    不打开浏览器，等外部弹幕工具把事件 POST 到 /api/douyin/ingest

浏览器用独立的用户数据目录（默认 程序目录/douyin_profile），
在里面登录一次抖音，之后开播都不需要再登录。
"""
import asyncio
import collections
import json
import logging
import os
import re
import subprocess
import sys
import time
import zlib

import aiohttp

log = logging.getLogger("douyin")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")

LIVE_URL = "https://live.douyin.com/{}"

# 页面里注入的采集脚本：只负责把“看起来像一条消息”的文本丢进队列，判断逻辑在 Python 里，
# 这样改规则不用重开浏览器，也方便单测。
INJECT_JS = r"""
(() => {
  if (window.__wtHook) return;
  window.__wtHook = 1;
  const Q = (window.__wtQueue = window.__wtQueue || []);
  const seen = new Map();
  const norm = s => (s || '')
    .replace(/\u00a0/g, ' ')
    .replace(/[\u200b-\u200d\ufeff]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
  const ITEM_SEL = '[class*="chatroom"][class*="item"],[data-e2e="chat-message"]';
  const NAME_SEL = '[class*="user-name"],[class*="nickname"],[class*="userName"],[class*="nick-name"]';
  const BODY_SEL = '[class*="content-with-emoji"],[class*="chat-content"],[class*="chatContent"]';
  let hits = 0, last = '';
  const push = el => {
    const text = norm(el.innerText);
    if (text.length < 2 || text.length > 160) return;
    const k = text.toLowerCase(), now = Date.now();
    if (seen.has(k) && now - seen.get(k) < 3500) return;
    seen.set(k, now);
    if (seen.size > 400) { for (const [kk, t] of seen) if (now - t > 10000) seen.delete(kk); }
    const nEl = el.querySelector(NAME_SEL), bEl = el.querySelector(BODY_SEL);
    hits++; last = text;
    Q.push({text: text, name: norm(nEl && nEl.innerText), body: norm(bEl && bEl.innerText),
            title: document.title, url: location.href, at: now});
    if (Q.length > 300) Q.splice(0, Q.length - 300);
  };
  const nearChat = el => {
    for (let p = el, i = 0; p && i < 6; p = p.parentElement, i++) {
      const cls = (p.className || '') + ' ' + (p.getAttribute && (p.getAttribute('data-e2e') || '') + ' ' + (p.getAttribute('aria-label') || ''));
      if (/chat|danmu|danmaku|barrage|comment|消息|弹幕|聊天/i.test(String(cls))) return true;
    }
    return false;
  };
  const scan = el => {
    if (!el || el.nodeType !== 1) return;
    if (el.matches && el.matches(ITEM_SEL)) { push(el); return; }
    if (el.querySelectorAll) {
      const found = el.querySelectorAll(ITEM_SEL);
      if (found.length) { found.forEach(push); return; }
    }
    const p = el.parentElement;
    if (p && p !== document.body && norm(p.innerText).length <= 160 && p.childElementCount <= 8 && nearChat(p)) push(p);
  };
  new MutationObserver(muts => {
    for (const m of muts) for (const n of m.addedNodes) scan(n);
  }).observe(document.documentElement, {childList: true, subtree: true});
  window.__wtHealth = () => ({url: location.href, title: document.title, hits: hits, last: last, at: Date.now()});
})();
"""

# ---------- 文本识别 ----------
_RE_GIFT = re.compile(
    r"^(?P<name>.+?)\s*(?:送出了|送出|送给主播|赠送|投喂)\s*(?P<gift>.+?)\s*(?:[×xX*]\s*(?P<num>\d+))?\s*$")
_RE_GIFT_BODY = re.compile(
    r"^(?:送出了|送出|送给主播|赠送|投喂)\s*(?P<gift>.+?)\s*(?:[×xX*]\s*(?P<num>\d+))?\s*$")
_RE_ENTER = re.compile(r"^(?P<name>.+?)\s*(?:来了|进入了直播间|进入直播间|来到直播间)\s*$")
_RE_FOLLOW = re.compile(r"^(?P<name>.+?)\s*关注了(?:主播|直播间)\s*$")
_RE_LIKE = re.compile(r"^(?P<name>.+?)\s*(?:为主播点赞了?|点亮了|点赞了)\s*$")
_RE_GUARD = re.compile(r"^(?P<name>.+?)\s*(?:加入|开通|续费|购买)了?\s*(?P<guard>粉丝团|会员|灯牌)\s*$")
_RE_EMOJI = re.compile(r"^(?:\[[^\]]{1,8}\])+$")
_RE_BADGE = re.compile(r"^(?:[\[【『（(][^\]】』）)]{1,10}[\]】』）)]\s*)+")
_RE_TAIL = re.compile(r"\s*(?:粉丝团|会员|灯牌)\s*\d*$")
_BAD_NAMES = {"抖音", "抖音直播", "抖音小助手", "系统", "直播间", "管理员", "提示", "公告", "本场榜", "欢迎"}


def norm(s):
    return re.sub(r"\s+", " ", str(s or "")).replace("\u00a0", " ").strip()


def clean_name(s):
    """去掉昵称前面的『粉丝团』标签和末尾的粉丝团等级。"""
    s = _RE_BADGE.sub("", norm(s))
    s = _RE_TAIL.sub("", s)
    return s.strip()


def uid_of(name):
    """抖音不给观众 uid，用昵称算一个稳定的数字，冷却/忽略名单照样能用。"""
    return zlib.crc32((name or "").encode("utf-8")) & 0x7FFFFFFF or 1


def parse_prices(text):
    """礼物价格表：每行 礼物名=抖币。"""
    out = {}
    for line in (text or "").replace("，", "=").splitlines():
        line = line.strip()
        if not line:
            continue
        if "=" in line:
            k, v = line.split("=", 1)
        elif ":" in line:
            k, v = line.split(":", 1)
        else:
            continue
        try:
            out[norm(k)] = float(v.strip())
        except ValueError:
            continue
    return out


def _gift_event(name, gift, num, prices):
    name = clean_name(name)
    if (not name or name in _BAD_NAMES or len(name) > 24
            or not gift or len(gift) > 24 or "：" in gift or ":" in gift
            or "：" in name or ":" in name):
        return None
    try:
        num = max(1, int(num or 1))
    except (TypeError, ValueError):
        num = 1
    coins = float(prices.get(gift, 0) or 0)
    value = round(coins * num / 10.0, 2)  # 1 元 = 10 抖币
    return {"type": "gift", "name": name, "gift": gift, "num": num,
            "value": value, "paid": value > 0}


def _pattern_event(s, name_default, prices):
    """非聊天类事件：礼物 / 进场 / 关注 / 点赞 / 粉丝团。"""
    s = norm(s)
    m = _RE_GIFT.match(s)
    if m:
        ev = _gift_event(name_default or norm(m.group("name")), norm(m.group("gift")),
                         m.group("num"), prices)
        if ev:
            return ev
    m = _RE_GIFT_BODY.match(s)
    if m and name_default:
        ev = _gift_event(name_default, norm(m.group("gift")), m.group("num"), prices)
        if ev:
            return ev
    for regex, kind in ((_RE_ENTER, "enter"), (_RE_FOLLOW, "follow"), (_RE_GUARD, "guard"),
                        (_RE_LIKE, "like")):
        m = regex.match(s)
        if not m:
            continue
        name = clean_name(m.group("name"))
        if not name or name in _BAD_NAMES:
            continue
        if kind == "guard":
            return {"type": "guard", "name": name, "level": 3,
                    "guard": norm(m.group("guard")), "num": 1, "value": 0.0}
        return {"type": kind, "name": name}
    return None


def classify(raw, prices=None):
    """把页面里的一行文本变成内部事件；认不出来返回 None。"""
    text = norm(raw.get("text"))
    if not text:
        return None
    name_hint = clean_name(raw.get("name"))
    body_hint = norm(raw.get("body"))
    prices = prices or {}

    cands = []
    for s in (text, norm(f"{name_hint} {body_hint}"), body_hint):
        if s and s not in cands:
            cands.append(s)
    for s in cands:
        ev = _pattern_event(s, name_hint, prices)
        if ev:
            return ev

    # 普通聊天：昵称 + 冒号 + 内容
    for s in (text, body_hint):
        for sep in ("：", ":"):
            if sep in s:
                name, _, content = s.partition(sep)
                name, content = clean_name(name), norm(content)
                if content and name and name not in _BAD_NAMES and len(name) <= 24:
                    return {"type": "danmaku", "name": name, "text": content,
                            "emoticon": bool(_RE_EMOJI.match(content)), "guard_level": 0}
                break
    if name_hint and body_hint and name_hint not in _BAD_NAMES:
        return {"type": "danmaku", "name": name_hint, "text": body_hint,
                "emoticon": bool(_RE_EMOJI.match(body_hint)), "guard_level": 0}
    return None


def room_url(cfg):
    url = norm(cfg.get("room_url"))
    if url:
        if not url.startswith("http"):
            url = "https://" + url
        return url
    rid = norm(cfg.get("web_rid"))
    if not rid:
        return ""
    m = re.search(r"live\.douyin\.com/(\d+)", rid)
    if m:
        return LIVE_URL.format(m.group(1))
    return LIVE_URL.format(rid.lstrip("/"))


def find_browser():
    cands = []
    if sys.platform == "win32":
        for env in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
            base = os.environ.get(env)
            if base:
                cands += [os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"),
                          os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")]
    for p in cands:
        if os.path.exists(p):
            return p
    return ""


class _Cdp:
    """极简 DevTools 协议客户端（只用 Runtime.evaluate）。"""

    def __init__(self, ws_url, session):
        self.ws_url = ws_url
        self.session = session
        self.ws = None
        self._id = 0
        self._pending = {}
        self._reader = None

    async def connect(self):
        self.ws = await self.session.ws_connect(self.ws_url, heartbeat=20, max_msg_size=0)
        self._reader = asyncio.create_task(self._read())

    async def _read(self):
        try:
            async for msg in self.ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    if msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        break
                    continue
                data = json.loads(msg.data)
                mid = data.get("id")
                if mid is not None and mid in self._pending:
                    fut = self._pending.pop(mid)
                    if not fut.done():
                        fut.set_result(data)
        except Exception:
            pass
        finally:
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(RuntimeError("浏览器页面已断开"))
            self._pending.clear()

    @property
    def closed(self):
        return self.ws is None or self.ws.closed

    async def send(self, method, **params):
        if self.closed:
            raise RuntimeError("浏览器页面已断开")
        self._id += 1
        mid = self._id
        fut = asyncio.get_running_loop().create_future()
        self._pending[mid] = fut
        await self.ws.send_str(json.dumps({"id": mid, "method": method, "params": params}))
        data = await asyncio.wait_for(fut, 15)
        if data.get("error"):
            raise RuntimeError(str(data["error"].get("message") or data["error"]))
        return data.get("result") or {}

    async def js(self, expr):
        r = await self.send("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        if r.get("exceptionDetails"):
            raise RuntimeError(str(r["exceptionDetails"].get("text") or "页面脚本出错"))
        return (r.get("result") or {}).get("value")


class _PageClosed(RuntimeError):
    """用户把浏览器窗口关掉了，不用再自动重开。"""


class DouyinLive:
    def __init__(self, on_event, on_status):
        self.on_event = on_event
        self.on_status = on_status
        self.connected = False
        self.client = None          # 兼容界面里的“连接中…”判断
        self.room_id = None
        self.owner_uid = None
        self.owner_name = ""
        self.login_name = ""
        self.mode = "browser"
        self.last_error = ""
        self.browser_info = {}
        self.raw = collections.deque(maxlen=80)
        self.counts = collections.Counter()
        self._task = None
        self._cdp = None
        self._session = None
        self._stop = None
        self._port = 0
        self._started_at = 0.0
        self._cfg = {}
        self._launched_at = 0.0

    # ---------- 生命周期 ----------
    async def start(self, cfg):
        await self.stop(keep=False)
        self._cfg = dict(cfg)
        self._stop = asyncio.Event()
        self._started_at = time.time()
        self.last_error = ""
        self.raw.clear()
        self.counts.clear()
        self._port = int(cfg.get("debug_port") or 9333)
        self.mode = (cfg.get("mode") or "browser").strip()
        self._session = aiohttp.ClientSession(headers={"User-Agent": UA})
        if self.mode == "relay":
            self.connected = True
            self.room_id = norm(cfg.get("web_rid")) or "转发模式"
            self.login_name = "外部转发"
            self.on_status("抖音模式：已就绪，等待外部弹幕工具转发事件")
            return
        url = room_url(cfg)
        if not url:
            self.connected = False
            self.client = None
            self.last_error = "请先填写抖音直播间链接或房间号"
            self.on_status("抖音连接失败：" + self.last_error)
            await self._close_session()
            return
        self.client = True
        self.on_status(f"正在打开抖音直播间：{url}")
        self._task = asyncio.create_task(self._run(url))

    async def stop(self, keep=None):
        if self._stop:
            self._stop.set()
        task, self._task = self._task, None
        if task and not task.done():
            task.cancel()
            try:
                await asyncio.wait_for(task, 2)
            except (Exception, asyncio.CancelledError):
                pass
        keep = bool(self._cfg.get("keep_browser", True)) if keep is None else keep
        cdp, self._cdp = self._cdp, None
        if cdp:
            try:
                if not keep:
                    await asyncio.wait_for(cdp.send("Browser.close"), 2)
            except (Exception, asyncio.CancelledError):
                pass
            try:
                if cdp.ws and not cdp.ws.closed:
                    await cdp.ws.close()
                if cdp._reader:
                    cdp._reader.cancel()
            except (Exception, asyncio.CancelledError):
                pass
        self.connected = False
        self.client = None
        await self._close_session()

    async def _close_session(self):
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

    async def _session_ok(self):
        if not self._session or self._session.closed:
            self._session = aiohttp.ClientSession(headers={"User-Agent": UA})
        return self._session

    # ---------- 浏览器 + CDP ----------
    async def _run(self, url):
        fails = 0
        while not self._stop.is_set():
            try:
                await self._ensure_browser(url)
                await self._attach(url)
                fails = 0
                await self._poll()
            except asyncio.CancelledError:
                raise
            except _PageClosed as e:
                self.connected = False
                self.client = None
                self.last_error = str(e)
                self.on_status("抖音的浏览器窗口已关闭，点「保存并连接」可以重新打开")
                break
            except Exception as e:
                self.connected = False
                fails += 1
                self.last_error = str(e) or type(e).__name__
                self.on_status(f"抖音连接失败（第 {fails} 次）：{self.last_error}")
                log.warning("douyin loop: %s", e)
                if fails >= 6:
                    self.client = None
                    self.on_status("抖音连接连续失败，已停止重试；检查房间号、浏览器路径或网络后点「保存并连接」")
                    break
            self.connected = False
            if self._stop.is_set():
                break
            await asyncio.sleep(3)

    async def _targets(self):
        s = await self._session_ok()
        async with s.get(f"http://127.0.0.1:{self._port}/json/list",
                         timeout=aiohttp.ClientTimeout(total=3)) as r:
            return await r.json(content_type=None)

    async def _ensure_browser(self, url):
        try:
            await self._targets()
            return
        except Exception:
            pass
        if time.time() - self._launched_at < 25:
            raise RuntimeError("浏览器正在启动，稍等…")
        exe = norm(self._cfg.get("browser_exe")) or find_browser()
        if not exe:
            raise RuntimeError("找不到 Edge / Chrome，请在【直播间 / 登录】里手动选择浏览器")
        profile = norm(self._cfg.get("profile_dir")) or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "douyin_profile")
        os.makedirs(profile, exist_ok=True)
        args = [exe, f"--remote-debugging-port={self._port}", f"--user-data-dir={profile}",
                "--no-first-run", "--no-default-browser-check", "--disable-popup-blocking",
                "--disable-blink-features=AutomationControlled", "--mute-audio", f"--app={url}"]
        if self._cfg.get("headless"):
            args.insert(1, "--headless=new")
        try:
            subprocess.Popen(args, close_fds=True)
            self._launched_at = time.time()
        except OSError as e:
            raise RuntimeError(f"启动浏览器失败：{e}")
        for _ in range(150):
            if self._stop.is_set():
                return
            await asyncio.sleep(0.2)
            try:
                await self._targets()
                return
            except Exception:
                continue
        raise RuntimeError("浏览器没有在 30 秒内打开调试端口，可能被杀毒软件拦了")

    async def _attach(self, url):
        targets = await self._targets()
        pages = [t for t in targets if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
        want = url.split("//", 1)[-1].split("/")[0]
        chosen = next((t for t in pages if want and want in (t.get("url") or "")), None)
        if not chosen:
            chosen = next((t for t in pages if "chat" not in (t.get("url") or "")), None)
        s = await self._session_ok()
        if not chosen:
            # 没有可用页签就新建一个（新版 Chrome 要求 PUT）
            try:
                async with s.put(f"http://127.0.0.1:{self._port}/json/new?{url}") as r:
                    chosen = await r.json(content_type=None)
            except Exception:
                async with s.get(f"http://127.0.0.1:{self._port}/json/new?{url}") as r:
                    chosen = await r.json(content_type=None)
        if not chosen or not chosen.get("webSocketDebuggerUrl"):
            raise RuntimeError("浏览器里找不到可用的页面")
        cdp = _Cdp(chosen["webSocketDebuggerUrl"], s)
        await cdp.connect()
        await cdp.send("Runtime.enable")
        await cdp.send("Page.enable")
        try:
            await cdp.send("Page.addScriptToEvaluateOnNewDocument", source=INJECT_JS)
        except Exception:
            pass
        current = chosen.get("url") or ""
        if want and want not in current:
            await cdp.send("Page.navigate", url=url)
            await asyncio.sleep(2)
        await cdp.js(INJECT_JS)
        self._cdp = cdp
        self.browser_info = {"url": current or url, "port": self._port}
        log.info("抖音页面已接管：%s", self.browser_info["url"])

    async def _poll(self):
        miss = 0
        while not self._stop.is_set():
            await asyncio.sleep(0.25)
            cdp = self._cdp
            if not cdp or cdp.closed:
                raise _PageClosed("浏览器页面已关闭")
            try:
                raw = await cdp.js("JSON.stringify((window.__wtQueue||[]).splice(0,200))")
            except Exception as e:
                miss += 1
                if miss >= 3:
                    raise RuntimeError(str(e) or "抓取脚本失效，可能页面被刷新")
                continue
            miss = 0
            for item in json.loads(raw or "[]"):
                self._handle_raw(item)
            try:
                health = json.loads(await cdp.js("JSON.stringify((window.__wtHealth||(()=>({})))())") or "{}")
                self.browser_info.update(health)
                if not self.connected and health:
                    self._on_page_ready(health)
            except Exception:
                pass

    def _on_page_ready(self, health):
        title = health.get("title") or ""
        self._detect_owner(title)
        self.connected = True
        self.room_id = self.owner_name or self._cfg.get("web_rid") or "抖音直播间"
        self.login_name = "网页抓取"
        where = f"{self.owner_name}的直播间" if self.owner_name else "抖音直播间"
        self.on_status(f"已连接{where}（浏览器抓取，首次使用请在这个浏览器窗口里登录抖音）")

    def _detect_owner(self, title):
        if self.owner_name:
            return
        m = re.match(r"^(.+?)(?:的直播间|正在直播|直播中)", title or "")
        if m:
            name = norm(m.group(1))
            if name and name not in _BAD_NAMES and len(name) <= 24:
                self.owner_name = name
                self.owner_uid = uid_of(name)
                self.login_name = "网页抓取"
                log.info("抖音主播昵称：%s", name)

    # ---------- 事件归一化 ----------
    def _handle_raw(self, item):
        text = norm(item.get("text"))
        prices = parse_prices(self._cfg.get("gift_prices"))
        ev = classify(item, prices)
        if not ev:
            self.raw.appendleft({"t": time.strftime("%H:%M:%S"), "text": text, "kind": ""})
            return
        self.raw.appendleft({"t": time.strftime("%H:%M:%S"), "text": text, "kind": ev["type"]})
        self._detect_owner(item.get("title"))
        self._emit(ev)

    def _emit(self, ev):
        ev["platform"] = "douyin"
        ev["ts"] = time.time()
        ev["uid"] = ev.get("uid") or uid_of(ev.get("name"))
        self.counts[ev["type"]] += 1
        try:
            self.on_event(ev)
        except Exception:
            log.exception("event handler failed")

    def ingest(self, data):
        """外部转发入口：接受单个事件或 {events:[...]}，字段尽量宽松。"""
        items = data.get("events") if isinstance(data, dict) and isinstance(data.get("events"), list) else [data]
        out = 0
        for d in items:
            if not isinstance(d, dict):
                continue
            kind = str(d.get("type") or d.get("event") or d.get("cmd") or "").lower()
            name = clean_name(d.get("name") or d.get("nickname") or d.get("user") or d.get("uname"))
            text = norm(d.get("text") or d.get("content") or d.get("msg") or d.get("message"))
            if not name and text:
                ev = classify({"text": text}, parse_prices(self._cfg.get("gift_prices")))
                if ev:
                    self.raw.appendleft({"t": time.strftime("%H:%M:%S"), "text": text, "kind": ev["type"]})
                    self._emit(ev)
                    out += 1
                continue
            if not name:
                continue
            alias = {"chat": "danmaku", "message": "danmaku", "comment": "danmaku", "member": "enter",
                     "join": "enter", "enter_room": "enter", "social": "follow", "like_msg": "like"}
            kind = alias.get(kind, kind)
            if kind in ("", "danmaku", "chat"):
                if not text:
                    continue
                ev = {"type": "danmaku", "name": name, "text": text,
                      "emoticon": bool(_RE_EMOJI.match(text)), "guard_level": 0}
            elif kind == "gift":
                gift = norm(d.get("gift") or d.get("gift_name") or d.get("giftName"))
                try:
                    num = int(d.get("num") or d.get("count") or 1)
                except (TypeError, ValueError):
                    num = 1
                if not gift:
                    continue
                value = d.get("value")
                if value is None:
                    coins = float(parse_prices(self._cfg.get("gift_prices")).get(gift, 0) or 0)
                    value = round(coins * max(1, num) / 10.0, 2)
                ev = {"type": "gift", "name": name, "gift": gift, "num": max(1, num),
                      "value": round(float(value or 0), 2), "paid": float(value or 0) > 0}
            elif kind == "guard":
                ev = {"type": "guard", "name": name, "guard": norm(d.get("guard") or "粉丝团"),
                      "num": int(d.get("num") or 1), "level": 3, "value": 0.0}
            elif kind in ("enter", "follow", "like"):
                ev = {"type": kind, "name": name}
            elif kind == "superchat":
                ev = {"type": "superchat", "name": name, "text": text,
                      "price": int(d.get("price") or d.get("value") or 0),
                      "value": float(d.get("price") or d.get("value") or 0)}
            else:
                continue
            self.raw.appendleft({"t": time.strftime("%H:%M:%S"), "text": text or kind,
                                 "kind": ev["type"]})
            if d.get("uid"):
                ev["uid"] = d["uid"]
            self._emit(ev)
            out += 1
        return out

    # ---------- 状态 ----------
    def health(self):
        return {"running": bool(self._task and not self._task.done()), "mode": self.mode,
                "connected": self.connected, "room": self.room_id, "owner": self.owner_name,
                "error": self.last_error, "browser": self.browser_info,
                "counts": dict(self.counts), "raw": list(self.raw)[:40],
                "port": self._port, "uptime": int(time.time() - self._started_at) if self._started_at else 0}
