import json
import logging
import re

import aiohttp

log = logging.getLogger("song")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
BASE = "https://music.163.com"


class NetEase:
    def __init__(self, get_cookie):
        self.get_cookie = get_cookie

    def _headers(self):
        h = {"User-Agent": UA, "Referer": BASE + "/"}
        cookie = (self.get_cookie() or "").strip()
        if cookie:
            if "=" not in cookie:
                cookie = f"MUSIC_U={cookie}"
            h["Cookie"] = cookie + "; os=pc"
        return h

    async def _get(self, path, params=None, raw=False):
        async with aiohttp.ClientSession(headers=self._headers()) as s:
            async with s.get(BASE + path, params=params, timeout=aiohttp.ClientTimeout(total=15)) as r:
                data = await r.json(content_type=None)
                return (data, r) if raw else data

    async def search(self, kw, limit=15):
        d = await self._get("/api/search/get/web", {"s": kw, "type": 1, "limit": limit, "offset": 0})
        out = []
        for s in (d.get("result") or {}).get("songs") or []:
            out.append({"id": s["id"], "name": s["name"],
                        "artist": "、".join(a["name"] for a in s.get("artists") or []),
                        "album": (s.get("album") or {}).get("name", ""), "dur": round((s.get("duration") or 0) / 1000)})
        return out

    async def urls(self, ids, br=320000):
        d = await self._get("/api/song/enhance/player/url", {"ids": json.dumps(ids), "br": br})
        out = {}
        for it in d.get("data") or []:
            ok = bool(it.get("url")) and not it.get("freeTrialInfo")
            out[it["id"]] = it["url"] if ok else None
        return out

    async def url(self, song_id):
        return (await self.urls([song_id])).get(song_id)

    async def find(self, query, max_dur=0):
        """搜索并返回最匹配且能完整播放的歌；原词找不到就逐步放宽关键词找相似的。"""
        tried = []
        for kw in _variants(query):
            if kw in tried:
                continue
            tried.append(kw)
            try:
                songs = await self.search(kw)
                if max_dur:
                    songs = [s for s in songs if not s["dur"] or s["dur"] <= max_dur]
                if not songs:
                    continue
                playable = await self.urls([s["id"] for s in songs])
            except Exception as e:
                log.warning("搜索“%s”出错：%s", kw, e)
                continue
            ok = [s for s in songs if playable.get(s["id"])]
            if ok:
                best = max(ok, key=lambda s: _score(query, s))
                best["exact"] = _score(query, best) >= 2
                return best
        return None

    async def search_with_status(self, kw):
        songs = await self.search(kw, limit=20)
        if songs:
            playable = await self.urls([s["id"] for s in songs])
            for s in songs:
                s["playable"] = bool(playable.get(s["id"]))
        return songs

    async def download(self, url):
        async with aiohttp.ClientSession(headers={"User-Agent": UA}) as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=120)) as r:
                r.raise_for_status()
                return await r.read()

    # ---------- 登录 ----------
    async def qr_key(self):
        d = await self._get("/api/login/qrcode/unikey", {"type": 1})
        key = d["unikey"]
        return key, f"https://music.163.com/login?codekey={key}"

    async def qr_poll(self, key):
        d, r = await self._get("/api/login/qrcode/client/login", {"key": key, "type": 1}, raw=True)
        code = d.get("code")
        msg = {800: "二维码已过期", 801: "等待扫码", 802: "已扫码，请在手机上确认", 803: "登录成功"}.get(code, d.get("message", str(code)))
        cookie = ""
        if code == 803:
            cookie = "; ".join(f"{k}={v.value}" for k, v in r.cookies.items() if v.value)
            if "MUSIC_U" not in cookie and d.get("cookie"):
                cookie = "; ".join(p.split(";")[0] for p in re.split(r";\s*(?=[A-Za-z_]+=)", d["cookie"]) if "=" in p)
        return code, msg, cookie

    async def account(self):
        d = await self._get("/api/nuser/account/get")
        prof, acc = d.get("profile") or {}, d.get("account") or {}
        if not prof:
            return None
        return {"nickname": prof.get("nickname", ""), "vip": int(acc.get("vipType") or prof.get("vipType") or 0),
                "uid": prof.get("userId")}

    async def my_playlists(self):
        acc = await self.account()
        if not acc:
            raise RuntimeError("网易云未登录（点歌页 → 扫码登录）")
        d = await self._get("/api/user/playlist", {"uid": acc["uid"], "limit": 100, "offset": 0})
        out = []
        for p in d.get("playlist") or []:
            out.append({"id": p["id"], "name": p.get("name", ""),
                        "count": p.get("trackCount") or 0,
                        "mine": bool(p.get("creator") and p["creator"].get("userId") == acc["uid"])})
        return {"account": acc, "playlists": out}

    async def playlist_tracks(self, pid, limit=1000):
        d = await self._get("/api/v6/playlist/detail", {"id": pid, "n": limit})
        pl = d.get("playlist") or {}
        tracks = []
        for t in pl.get("tracks") or []:
            if not t or not t.get("id"):
                continue
            tracks.append({"id": t["id"], "name": t.get("name", ""),
                           "artist": "、".join(a.get("name", "") for a in t.get("ar") or []),
                           "dur": round((t.get("dt") or 0) / 1000)})
        return {"name": pl.get("name", ""), "tracks": tracks}


def _tokens(q):
    q = re.sub(r"[《》「」『』\"'“”]", " ", q.lower())
    return [p for p in re.split(r"\s*[-—–/|,，\s]+\s*", q) if p]


def _score(query, s):
    """2=歌名和歌手都对上（或没指定歌手），1=只有歌名对上，0=相似；翻唱/伴奏扣分。同分保留搜索排序。"""
    parts = _tokens(query)
    if not parts:
        return 2
    name, artist = s["name"].lower(), s["artist"].lower()
    if parts[0] not in name:
        return 0
    score = 2 if all(p in artist for p in parts[1:]) else 1
    if any(w in name for w in ("翻唱", "cover", "原唱", "伴奏", "dj", "remix")):
        score -= 0.5
    if re.sub(r"[（(\[【].*?[）)\]】]", "", name).strip() == parts[0]:
        score += 0.1
    return score


def _variants(q):
    q = q.strip()
    yield q
    plain = re.sub(r"[《》「」『』\"'“”]", " ", q).strip()
    yield plain
    parts = [p for p in re.split(r"\s*[-—–/|,，\s]+\s*", plain) if p]
    if len(parts) > 1:
        yield parts[0]
        yield " ".join(parts[:2])
    no_paren = re.sub(r"[（(\[【].*?[）)\]】]", "", plain).strip()
    if no_paren:
        yield no_paren
