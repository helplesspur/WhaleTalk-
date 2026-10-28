import asyncio
import logging
import random
import re
import time

from arcade_games import (DIRS, OPPOSITE, Game2048, MinesweeperGame, SnakeGame,
                          choose_snake_direction, parse_cell, parse_direction)

log = logging.getLogger("game")

CATALOG = {
    "guess_number": {"name": "猜数字", "cat": "interactive",
                     "desc": "AI 想一个 1~100 的数字，观众发弹幕猜，AI 提示大了还是小了。"},
    "number_bomb": {"name": "数字炸弹", "cat": "interactive",
                    "desc": "AI 在 1~100 里埋一个炸弹，观众轮流报数缩小范围，踩中炸弹的人被炸飞。"},
    "quiz": {"name": "抢答问答", "cat": "interactive",
             "desc": "AI 出一道趣味知识题，第一个答对的观众得 3 分。"},
    "word_chain": {"name": "词语接龙", "cat": "interactive",
                   "desc": "用一个词的最后一个字开头继续接，观众接得越多分越高。"},
    "poll": {"name": "观众投票", "cat": "interactive",
             "desc": "二选一投票，支持第一个选项发 1，支持第二个发 2。"},
    "snake": {"name": "AI 贪吃蛇", "cat": "interactive",
              "desc": "AI 自己找食物，观众发 上/下/左/右 帮它转向；喂到食物的人得分。"},
    "minesweeper": {"name": "AI 扫雷", "cat": "interactive",
                    "desc": "AI 推理翻格，观众发 3,5 可以帮它翻开第 3 行第 5 列。"},
    "game2048": {"name": "2048", "cat": "interactive",
                 "desc": "AI 计算方向，观众发 上/下/左/右 指挥，合出大数字拿奖励分。"},
    "rps": {"name": "猜拳对决", "cat": "interactive",
            "desc": "观众发 石头 / 剪刀 / 布 挑战 AI，赢一局 2 分，平局 1 分。"},
    "lottery": {"name": "幸运抽奖", "cat": "interactive",
                "desc": "观众发 1 参加，倒计时结束抽幸运观众，中奖加 5 分。"},
    "feihualing": {"name": "飞花令", "cat": "interactive",
                   "desc": "AI 定一个令字，观众发含这个字的诗句，接一句 1 分。"},
    "fact": {"name": "冷知识播报", "cat": "solo",
             "desc": "AI 分享两条有趣的冷知识，一个人也能聊起来。"},
    "story": {"name": "故事连载", "cat": "solo",
              "desc": "AI 连载《鲸鱼娘的海底电台》，每局续写一段。"},
    "riddle": {"name": "脑筋急转弯", "cat": "solo",
               "desc": "AI 出谜语，给观众几秒思考，再自己公布答案。"},
    "joke": {"name": "AI 讲笑话", "cat": "solo",
             "desc": "AI 讲一个干净的小笑话，铺垫完再抖包袱。"},
}

QUIZ_BANK = [
    ("太阳系里体积最大的行星是哪一个？", "木星", "木星的体积能装下一千三百多个地球。"),
    ("床前明月光的下一句是什么？", "疑是地上霜", "出自李白的静夜思。"),
    ("一年中白昼最长的节气是哪一个？", "夏至", "夏至这天北半球的白昼最长。"),
    ("世界上最长的河流是哪一条？", "尼罗河", "尼罗河全长约六千七百公里。"),
    ("熊猫平时主要吃什么？", "竹子", "竹子占了熊猫食物的九成以上。"),
    ("彩虹按常见说法有几种颜色？", "七种", "红橙黄绿蓝靛紫。"),
    ("企鹅生活在哪个半球？", "南半球", "北极没有野生的企鹅。"),
    ("三个臭皮匠的下一句是什么？", "顶个诸葛亮", "这句老话是说人多智慧多。"),
    ("地球上面积最大的海洋是哪一个？", "太平洋", "太平洋面积比所有陆地加起来还大。"),
    ("键盘上 Ctrl 加 C 通常是做什么？", "复制", "配合 Ctrl 加 V 就能粘贴。"),
    ("孙悟空用的兵器叫什么？", "金箍棒", "如意金箍棒，重一万三千五百斤。"),
    ("蜜蜂采花粉主要是为了做什么？", "蜂蜜", "酿好的蜂蜜可以保存很久很久。"),
    ("一公斤等于多少克？", "1000", "一千克，也就是两斤。"),
    ("猫的胡须主要用来做什么？", "测量", "胡须能帮猫判断缝隙能不能钻过去。"),
]

RIDDLE_BANK = [
    ("什么东西天气越热，它爬得越高？", "温度计"),
    ("什么东西越洗越脏？", "水"),
    ("什么门永远关不上？", "球门"),
    ("什么布永远剪不断？", "瀑布"),
    ("什么东西有牙齿，却咬不动人？", "梳子"),
    ("什么东西有眼睛，却看不见？", "针"),
    ("什么车寸步难行？", "风车"),
    ("什么东西打破了，大家反而叫好？", "纪录"),
    ("什么东西只能增加，不能减少？", "年龄"),
    ("什么东西明明是你的，别人却用得比你多？", "名字"),
]

POLL_BANK = [
    ("你是甜粽派还是咸粽派？", "甜粽子", "咸粽子"),
    ("你是猫派还是狗派？", "猫猫", "狗狗"),
    ("你更喜欢夏天还是冬天？", "夏天", "冬天"),
    ("你是早起派还是熬夜派？", "早起", "熬夜"),
    ("火锅和烧烤，你选哪个？", "火锅", "烧烤"),
    ("周末更想去海边还是山里？", "海边", "山里"),
    ("奶茶和咖啡，你更需要哪个？", "奶茶", "咖啡"),
    ("空闲时更爱看剧还是打游戏？", "看剧", "打游戏"),
]

FACT_BANK = [
    "蜂蜜几乎永远不会变质，古埃及墓里发现过三千年前的蜂蜜。",
    "章鱼有三颗心脏，血液是蓝色的。",
    "香蕉其实是浆果，草莓反而不算浆果。",
    "长颈鹿的舌头是蓝紫色的，长度接近五十厘米。",
    "蜗牛可以一觉睡上三年。",
    "一朵普通的云可能重达五百吨。",
    "袋鼠不会倒退着走路。",
    "北极熊的皮肤是黑色的，毛其实是透明的。",
    "猫鼻子上的纹路像指纹一样，每只都不一样。",
    "月亮正在慢慢远离地球，每年大约三点八厘米。",
    "人的胃酸强到能溶解金属，但胃壁会不断更新保护自己。",
    "一张纸最多对折大约七次，就很难再折下去。",
]

JOKE_BANK = [
    ("我问冰箱：你冷不冷？", "冰箱说：我不冷，我只是在保持高冷。"),
    ("我问电风扇：你累不累？", "它一句话没说，只是一直摇头。"),
    ("小明考了零分，回家对妈妈说：", "妈妈，我这次的进步空间特别大！"),
    ("一只北极熊在冰上拔毛，拔完以后说了什么？", "好冷。"),
    ("为什么程序员总分不清万圣节和圣诞节？", "因为 Oct 31 等于 Dec 25。"),
    ("蜗牛为什么爬得那么慢？", "因为它背着房子上班，通勤压力太大了。"),
]

START_WORDS = ["一心一意", "万事如意", "年年有余", "马到成功", "开开心心", "顺顺利利", "海阔天空", "水到渠成"]
PARTICLES = "啊呀吧呢吗哦啦哈嘛呗咯"

# 猜拳：value 表示“观众出这个能赢的 AI 招式”
RPS_BEATS = {"石头": "剪刀", "剪刀": "布", "布": "石头"}
RPS_ALIAS = {"石头": "石头", "拳头": "石头", "锤子": "石头",
             "剪刀": "剪刀", "剪子": "剪刀",
             "布": "布", "包袱": "布"}
RPS_PREFIX = ("我要出", "我要", "我出", "来个", "来", "出")

# 飞花令
FEIHUA_CHARS = ["春", "月", "花", "风", "山", "水", "雨", "云", "夜", "酒", "江", "雪"]
FEIHUA_LINES = {
    "春": ["春眠不觉晓，处处闻啼鸟", "好雨知时节，当春乃发生", "等闲识得东风面，万紫千红总是春"],
    "月": ["举头望明月，低头思故乡", "海上生明月，天涯共此时", "月落乌啼霜满天，江枫渔火对愁眠"],
    "花": ["待到重阳日，还来就菊花", "忽如一夜春风来，千树万树梨花开", "接天莲叶无穷碧，映日荷花别样红"],
    "风": ["夜来风雨声，花落知多少", "野火烧不尽，春风吹又生", "不知细叶谁裁出，二月春风似剪刀"],
    "山": ["会当凌绝顶，一览众山小", "两岸青山相对出，孤帆一片日边来", "空山不见人，但闻人语响"],
    "水": ["桃花潭水深千尺，不及汪伦送我情", "山重水复疑无路，柳暗花明又一村", "问渠那得清如许，为有源头活水来"],
    "雨": ["清明时节雨纷纷，路上行人欲断魂", "天街小雨润如酥，草色遥看近却无", "好雨知时节，当春乃发生"],
    "云": ["只在此山中，云深不知处", "黄河远上白云间，一片孤城万仞山", "行到水穷处，坐看云起时"],
    "夜": ["露从今夜白，月是故乡明", "春宵一刻值千金，花有清香月有阴", "姑苏城外寒山寺，夜半钟声到客船"],
    "酒": ["劝君更尽一杯酒，西出阳关无故人", "明月几时有，把酒问青天", "借问酒家何处有，牧童遥指杏花村"],
    "江": ["孤帆远影碧空尽，唯见长江天际流", "日出江花红胜火，春来江水绿如蓝", "无边落木萧萧下，不尽长江滚滚来"],
    "雪": ["忽如一夜春风来，千树万树梨花开", "窗含西岭千秋雪，门泊东吴万里船", "孤舟蓑笠翁，独钓寒江雪"],
}


def _norm(text):
    return re.sub(r"[^\u4e00-\u9fffa-z0-9]", "", (text or "").lower())


def _split_lines(raw):
    out = []
    for line in (raw or "").splitlines():
        s = re.sub(r"^\s*(?:[-*]|\d+[.、)])\s*", "", line.strip())
        s = s.strip().strip("`*\"'“”")
        if s:
            out.append(s)
    return out


def _kv(raw):
    pattern = re.compile(r"(题目|问题|谜面|答案|解析|解释|选项一|选项二|选项1|选项2|铺垫|包袱)\s*[：:]\s*")
    hits = list(pattern.finditer(raw or ""))
    out = {}
    for i, m in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(raw)
        val = (raw[m.end():end] or "").strip().strip("。；;").strip()
        out.setdefault(m.group(1), val)
    return out


def _clip(text, limit):
    text = re.sub(r"\s+", " ", (text or "").strip())
    if len(text) <= limit:
        return text
    cut = max(text.rfind(p, 0, limit) for p in "。！？!?；;")
    return text[:cut + 1] if cut > 10 else text[:limit]


def _find_number(text):
    m = re.search(r"\d{1,3}", text or "")
    if m:
        return int(m.group(0))
    core = re.sub(r"[\s，。！？!?,.、~～]", "", text or "")
    if re.fullmatch(r"[零〇一二两三四五六七八九十百]{1,4}", core):
        if core == "一百":
            return 100
        if "十" in core:
            left, _, right = core.partition("十")
            tens = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}.get(left, 1)
            ones = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}.get(right, 0)
            return tens * 10 + ones
        num = 0
        for ch in core:
            num = num * 10 + {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
                              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}[ch]
        return num
    return None


def _has_answer(text, answer):
    t, a = _norm(text), _norm(answer)
    if not a or not t:
        return False
    if a.isdigit():
        return re.search(rf"(?<!\d){re.escape(a)}(?!\d)", t) is not None
    return a in t


def _word_after(text, need):
    for m in re.finditer(re.escape(need) + r"[\u4e00-\u9fff]{1,7}", text or ""):
        word = re.sub(rf"[{PARTICLES}]+$", "", m.group(0))
        if 2 <= len(word) <= 6:
            return word
    return ""


class GameManager:
    def __init__(self, app):
        self.app = app
        self.active = None
        self.result = None
        self.task = None
        self.ticker = None
        self.stop_evt = asyncio.Event()
        self.wake = asyncio.Event()
        self.last_chat = 0.0
        self.next_at = time.time() + 60
        self.board = {}
        self.story = ""
        self._tick_count = 0

    @property
    def cfg(self):
        return self.app.cfg["games"]

    # ---------- 状态 ----------
    @staticmethod
    def _score_list(rec):
        return sorted(({"name": v["name"], "pts": v["pts"]} for v in rec.values()), key=lambda x: -x["pts"])[:8]

    def _board(self):
        return sorted(({"name": v["name"], "pts": v["pts"]} for v in self.board.values()),
                      key=lambda x: -x["pts"])[:8]

    def state(self):
        a = self.active
        av = None
        if a:
            av = {k: a.get(k) for k in ("id", "name", "cat", "phase", "title", "question", "hint", "word",
                                        "need", "last", "plays") if a.get(k) is not None}
            av["left"] = max(0, int(a.get("deadline", time.time()) - time.time()))
            av["scores"] = self._score_list(a.get("scores", {}))
            if a.get("options"):
                av["options"] = [dict(o) for o in a["options"]]
            if a.get("chain"):
                av["chain"] = [dict(c) for c in a["chain"][-6:]]
            if a.get("guesses"):
                av["guesses"] = [dict(g) for g in a["guesses"][-4:]]
            if a.get("board"):
                av["board"] = a["board"]
        r = self.result
        rv = None
        if r and time.time() < r.get("until", 0):
            rv = {k: r.get(k) for k in ("name", "cat", "text", "question") if r.get(k) is not None}
            if r.get("options"):
                rv["options"] = [dict(o) for o in r["options"]]
            if r.get("board"):
                rv["board"] = r["board"]
            rv["scores"] = r.get("scores", [])
            rv["left"] = max(0, int(r["until"] - time.time()))
        return {"active": av, "result": rv, "board": self._board(),
                "enabled": bool(self.cfg.get("enabled", True)), "auto": bool(self.cfg.get("auto")),
                "next_in": max(0, int(self.next_at - time.time())) if self.cfg.get("auto") else None}

    def push(self):
        self.app.push("game", self.state())

    def mute_chat(self):
        return bool(self.active and self.active.get("cat") == "solo")

    def enabled_ids(self, cat=None):
        choices = self.cfg.get("choices", {})
        return [k for k, meta in CATALOG.items()
                if choices.get(k, True) and (cat is None or meta["cat"] == cat)]

    # ---------- 开始 / 停止 ----------
    def start(self, gid, manual=False):
        if gid not in CATALOG:
            return "没有这个游戏"
        if not manual and not self.cfg.get("enabled", True):
            return "游戏总开关没开"
        if self.active:
            return "已经有一局在进行了"
        if self.task and not self.task.done():
            return "上一局还在收尾"
        meta = CATALOG[gid]
        self.result = None
        self.stop_evt = asyncio.Event()
        self.wake = asyncio.Event()
        self.active = {"id": gid, "name": meta["name"], "cat": meta["cat"], "phase": "intro",
                       "title": meta["name"], "question": "正在准备…", "hint": "",
                       "deadline": time.time() + 120, "scores": {}, "participants": {},
                       "user_cd": {}, "last_reply": 0}
        self.task = asyncio.create_task(self._run(gid))
        self.app.push("log", {"level": "info", "msg": f"开始游戏：{meta['name']}"})
        self.push()
        return None

    def stop(self):
        if not self.active:
            return False
        self.stop_evt.set()
        if self.task and self.task is not asyncio.current_task():
            self.task.cancel()
        return True

    def reset_board(self):
        self.board.clear()
        self.push()

    def _schedule_next(self, hold):
        self.next_at = time.time() + hold + max(20, int(self.cfg.get("interval", 180) or 180))

    def _end(self, text, emotion="开心", hold=10, extra=None):
        a = self.active
        if not a:
            return
        self.active = None
        self.stop_evt.set()
        scores = self._score_list(a.get("scores", {}))
        self.result = {"name": a["name"], "cat": a["cat"], "text": text, "scores": scores,
                       "question": a.get("question", ""), "until": time.time() + hold}
        if extra:
            self.result.update(extra)
        self._say(text, emotion)
        self.push()

    async def _run(self, gid):
        try:
            await getattr(self, f"_game_{gid}")()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.exception("游戏出错")
            self.app.push("log", {"level": "error", "msg": f"游戏出错：{e}"})
            board = self.active.get("board") if self.active else None
            self._end("游戏出了点小状况，我们先玩到这里！", "尴尬", hold=6,
                      extra={"board": board} if board else None)
        finally:
            if self.active is not None:
                name = self.active["name"]
                board = self.active.get("board")
                self._end(f"{name}先玩到这里，下次继续！", "", hold=6,
                          extra={"board": board} if board else None)
            self.task = None
            self._schedule_next(8)

    # ---------- 自动轮换 ----------
    async def run(self):
        self.ticker = asyncio.create_task(self._ticker())
        try:
            while True:
                await asyncio.sleep(1)
                try:
                    self._auto_step()
                except Exception:
                    log.exception("游戏调度出错")
        finally:
            self.ticker.cancel()

    def _auto_step(self):
        cfg = self.cfg
        if not cfg.get("enabled", True) or not cfg.get("auto"):
            return
        if self.active or (self.task and not self.task.done()):
            return
        if not getattr(self.app, "session_active", False):
            return
        if self.app.pipe.paused or not self.app.live_connected:
            return
        now = time.time()
        if now < self.next_at:
            return
        if self.result and now < self.result.get("until", 0):
            return
        interactive = self.enabled_ids("interactive")
        solo = self.enabled_ids("solo")
        recent = now - self.last_chat < 240
        pool = (interactive or solo) if recent else (solo or interactive)
        if not pool:
            return
        self.start(random.choice(pool))

    async def _ticker(self):
        while True:
            await asyncio.sleep(1)
            self._tick_count += 1
            if self.result and time.time() >= self.result.get("until", 0):
                self.result = None
                self.push()
            elif self.active or self.result:
                self.push()
            elif self._tick_count % 5 == 0 and self.cfg.get("auto"):
                self.push()

    # ---------- 弹幕分流 ----------
    def _allowed(self, ev):
        if ev.get("test"):
            return True
        if ev.get("uid") and ev.get("uid") == self.app.owner_uid:
            return False
        f = self.app.cfg.get("filter", {})
        name = ev.get("raw_name") or ev.get("name") or ""
        uid = str(ev.get("uid") or "")
        ignored = [x.strip() for x in re.split(r"[\n,，;；]", f.get("ignore_users") or "") if x.strip()]
        if name in ignored or (uid and uid in ignored):
            return False
        blocked = [x.strip() for x in re.split(r"[\n,，;；]", f.get("blocklist") or "") if x.strip()]
        return not any(w in (ev.get("text") or "") or w in name for w in blocked)

    def on_danmaku(self, ev):
        self.last_chat = time.time()
        a = self.active
        if not a or a.get("phase") == "intro" or not self._allowed(ev):
            return False
        text = (ev.get("text") or "").strip()
        if not text:
            return False
        fn = getattr(self, f"_d_{a['id']}", None)
        if fn is None:
            return False
        return bool(fn(a, ev, text))

    # ---------- 公共工具 ----------
    def _say(self, text, emotion=""):
        return self.app.pipe.say(text, emotion)

    async def _say_wait(self, text, emotion="", timeout=0.0):
        jid = self._say(text, emotion)
        await self.app.pipe.wait_spoken(jid, timeout or max(35.0, len(text) * 0.45 + 8))

    async def _sleep_until(self, deadline):
        while time.time() < deadline:
            if self.stop_evt.is_set() or not self.active:
                return False
            await asyncio.sleep(min(0.5, max(0.02, deadline - time.time())))
        return not self.stop_evt.is_set()

    async def _wait_event(self, deadline):
        while time.time() < deadline:
            if self.stop_evt.is_set() or not self.active:
                return False
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=min(0.4, max(0.05, deadline - time.time())))
            except asyncio.TimeoutError:
                continue
            self.wake.clear()
            return True
        return False

    def _score(self, uid, name, pts, a=None):
        a = a or self.active
        if not a:
            return
        key = str(uid or name or "guest")
        rec = a["scores"].setdefault(key, {"name": name or "新朋友", "pts": 0})
        if name:
            rec["name"] = name
        rec["pts"] += pts
        board = self.board.setdefault(key, {"name": rec["name"], "pts": 0})
        if name:
            board["name"] = rec["name"]
        board["pts"] += pts

    def _can_say(self, a, gap=2.0):
        now = time.time()
        if now - a.get("last_reply", 0) < gap:
            return False
        a["last_reply"] = now
        return True

    async def _gen(self, prompt, timeout=30.0):
        try:
            raw = await asyncio.wait_for(self.app.brain.raw(self.app.cfg, prompt), timeout)
        except Exception as e:
            log.warning("游戏内容生成失败：%s", e)
            return ""
        return re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", (raw or "").strip()).replace("**", "").strip()

    # ---------- 猜数字 ----------
    async def _game_guess_number(self):
        a = self.active
        max_tries = int(self.cfg.get("guess_max", 8) or 8)
        a.update({"title": "猜数字", "phase": "playing", "number": random.randint(1, 100),
                  "question": "我心里想了一个 1 到 100 的数字，发弹幕猜猜看！",
                  "lo": 1, "hi": 100, "tries": 0, "max_tries": max_tries,
                  "win": None, "over": False, "guesses": [],
                  "hint": "范围 1 ~ 100", "deadline": time.time() + 90})
        self.push()
        await self._say_wait("来玩猜数字！我心里想了一个一到一百之间的数字，打在弹幕里，"
                             f"我告诉你是大了还是小了。最多回答{max_tries}次，猜中有积分！", "期待")
        if self.active is not a:
            return
        a["deadline"] = time.time() + 90
        self.push()
        while self.active is a and not a.get("win") and not a.get("over") and time.time() < a["deadline"]:
            await self._wait_event(a["deadline"])
            if self.stop_evt.is_set() or not self.active:
                return
        if not self.active:
            return
        if a.get("win"):
            w = a["win"]
            self._score(w["uid"], w["name"], 3, a)
            self._end(f"猜对啦！答案是{a['number']}，{w['name']}一下就猜中了，太厉害了！", "惊讶")
        else:
            for uid, name in a.get("participants", {}).items():
                self._score(uid, name, 1, a)
            self._end(f"时间到！答案是{a['number']}，就差一点点，下次一定猜中！", "难过")

    def _d_guess_number(self, a, ev, text):
        n = _find_number(text)
        if n is None or not 1 <= n <= 100:
            return False
        uid = str(ev.get("uid") or ev.get("raw_name") or ev.get("name"))
        now = time.time()
        if now < a["user_cd"].get(uid, 0) or a.get("win") or a.get("over"):
            return True
        a["user_cd"][uid] = now + 3
        a["tries"] = a.get("tries", 0) + 1
        a["participants"][uid] = ev["name"]
        a["guesses"].append({"name": ev["name"], "n": n})
        a["guesses"] = a["guesses"][-4:]
        target = a["number"]
        if n == target:
            a["win"] = {"uid": uid, "name": ev["name"], "n": n}
            a["phase"] = "result"
            self.push()
            self.wake.set()
            return True
        if n < target:
            a["lo"] = max(a["lo"], n + 1)
            tip = "小了，再往大一点猜！"
        else:
            a["hi"] = min(a["hi"], n - 1)
            tip = "大了，往小一点猜！"
        a["hint"] = f"范围 {a['lo']} ~ {a['hi']}"
        a["last"] = f"{ev['name']} 猜 {n}，{'小了' if n < target else '大了'}"
        if a["tries"] >= a.get("max_tries", 8):
            a["over"] = True
            self.wake.set()
        elif self._can_say(a, 2.0):
            self._say(tip)
        self.push()
        return True

    # ---------- 数字炸弹 ----------
    async def _game_number_bomb(self):
        a = self.active
        a.update({"title": "数字炸弹", "phase": "playing", "number": random.randint(1, 100),
                  "question": "数字炸弹藏在 1 到 100 之间，踩中的人会被炸飞！",
                  "lo": 1, "hi": 100, "exploded": None, "guesses": [],
                  "hint": "范围 1 ~ 100", "deadline": time.time() + 90})
        self.push()
        await self._say_wait("来玩数字炸弹！一到一百之间埋了一个炸弹，大家轮流报数，"
                             "每报一个数范围就会缩小，谁报到炸弹谁就被炸飞！谁先来？", "期待")
        if self.active is not a:
            return
        a["deadline"] = time.time() + 90
        self.push()
        while self.active is a and not a.get("exploded") and time.time() < a["deadline"]:
            await self._wait_event(a["deadline"])
            if self.stop_evt.is_set() or not self.active:
                return
        if not self.active:
            return
        w = a.get("exploded")
        if w:
            survivors = 0
            for uid, name in a.get("participants", {}).items():
                if uid != w["uid"]:
                    self._score(uid, name, 1, a)
                    survivors += 1
            if survivors:
                text = f"{w['name']}踩到炸弹啦！炸弹就是{a['number']}！{survivors}位朋友安全逃生，各加一分！"
            else:
                text = f"{w['name']}一上来就踩中炸弹{a['number']}，这运气也是没谁了！"
            self._end(text, "惊讶")
        else:
            for uid, name in a.get("participants", {}).items():
                self._score(uid, name, 1, a)
            self._end(f"时间到！炸弹是{a['number']}，居然没人踩中，全员安全，各加一分！", "开心")

    def _d_number_bomb(self, a, ev, text):
        n = _find_number(text)
        if n is None:
            return False
        uid = str(ev.get("uid") or ev.get("raw_name") or ev.get("name"))
        now = time.time()
        if now < a["user_cd"].get(uid, 0) or a.get("exploded"):
            return True
        a["user_cd"][uid] = now + 3
        lo, hi = a["lo"], a["hi"]
        if not lo <= n <= hi:
            if self._can_say(a, 6):
                self._say(f"现在范围是{lo}到{hi}哦，{ev['name']}别报出界啦！")
            return True
        a["participants"][uid] = ev["name"]
        a["guesses"].append({"name": ev["name"], "n": n})
        a["guesses"] = a["guesses"][-4:]
        if n == a["number"]:
            a["exploded"] = {"uid": uid, "name": ev["name"], "n": n}
            a["hint"] = f"砰！炸弹是 {n}"
            a["phase"] = "result"
            self.push()
            self.wake.set()
            return True
        if n < a["number"]:
            a["lo"] = n + 1
        else:
            a["hi"] = n - 1
        a["hint"] = f"范围 {a['lo']} ~ {a['hi']}"
        a["last"] = f"{ev['name']} 报了 {n}，安全"
        if self._can_say(a, 2.5):
            self._say(random.choice([
                f"{ev['name']}安全！现在{a['lo']}到{a['hi']}，下一个！",
                f"好险，剩下{a['lo']}到{a['hi']}，谁来踩雷？",
                f"范围缩到{a['lo']}到{a['hi']}了，继续！",
            ]), "期待")
        self.push()
        return True

    # ---------- 贪吃蛇 ----------
    async def _game_snake(self):
        a = self.active
        speed_ms = max(150, min(1000, int(self.cfg.get("snake_speed_ms", 350) or 350)))
        speed = speed_ms / 1000.0
        game = SnakeGame(20, 20)
        a.update({"title": "AI 贪吃蛇", "phase": "playing", "arcade": game,
                  "question": "贪吃蛇正在自动找食物，发 上/下/左/右 帮它转向！",
                  "hint": f"喂到一个食物 +1 分（算给最近的操作员）· 速度 {speed:.2f} 秒/步",
                  "board": game.state(), "prompted": False, "deadline": time.time() + 90})
        self.push()
        self._say("来玩贪吃蛇！它会自己找吃的，你们发 上 下 左 右 帮它转向，"
                  "喂到食物的人加一分！", "期待")
        a["deadline"] = time.time() + 90
        started = time.time()
        self.push()
        while self.active is a and not game.dead and time.time() < a["deadline"]:
            if self.stop_evt.is_set():
                return
            direction = None
            if time.time() < a.get("manual_until", 0):
                manual = a.get("manual_dir")
                if manual and manual != OPPOSITE.get(game.direction):
                    dx, dy = DIRS[manual]
                    head = (game.snake[0][0] + dx, game.snake[0][1] + dy)
                    blocked = set(game.snake[:-1])
                    if 0 <= head[0] < game.w and 0 <= head[1] < game.h and head not in blocked:
                        direction = manual
                    else:
                        a["manual_until"] = 0
                else:
                    a["manual_until"] = 0
            if direction is None:
                direction = choose_snake_direction(game)
            event = game.step(direction)
            a["board"] = game.state()
            if event.get("eat"):
                op = a.get("last_operator")
                if op and time.time() - op["time"] <= 4:
                    self._score(op["uid"], op["name"], 1, a)
                    if self._can_say(a, 3.5):
                        self._say(random.choice([f"{op['name']}喂到啦，加一分！",
                                                 "吃到啦！这波操作漂亮！",
                                                 "咕噜，真好吃，再来一个！"]), "开心")
                elif self._can_say(a, 5):
                    self._say("吃到啦！", "开心")
            if not a.get("prompted") and not a.get("last_operator") and time.time() - started > 22:
                a["prompted"] = True
                self._say("有没有人来指挥一下？发 上 下 左 右 帮它转向！", "期待")
            self.push()
            await asyncio.sleep(speed)
        if not self.active:
            return
        a["board"] = game.state()
        self.push()
        if game.dead:
            self._end(f"贪吃蛇撞到啦！本局吃了{game.score}个食物。", "难过",
                      extra={"board": game.state()})
        else:
            self._end(f"时间到！贪吃蛇存活，一共吃了{game.score}个食物！", "开心",
                      extra={"board": game.state()})

    def _d_snake(self, a, ev, text):
        direction = parse_direction(text)
        if not direction:
            return False
        game = a.get("arcade")
        if not game or game.dead:
            return False
        uid = str(ev.get("uid") or ev.get("raw_name") or ev.get("name"))
        now = time.time()
        if now < a["user_cd"].get(uid, 0):
            return True
        a["user_cd"][uid] = now + 1.5
        if direction == OPPOSITE.get(game.direction):
            if self._can_say(a, 5):
                self._say(f"{ev['name']}，蛇不能原地掉头哦！")
            return True
        a["manual_dir"] = direction
        a["manual_until"] = now + 2.5
        a["last_operator"] = {"uid": uid, "name": ev["name"], "time": now}
        return True

    # ---------- 扫雷 ----------
    async def _game_minesweeper(self):
        a = self.active
        mines = max(5, min(30, int(self.cfg.get("mines", 10) or 10)))
        delay = max(1.0, min(5.0, float(self.cfg.get("arcade_delay", 2.5) or 2.5)))
        game = MinesweeperGame(9, mines)
        a.update({"title": "AI 扫雷", "phase": "playing", "arcade": game,
                  "question": "AI 正在推理扫雷，发 3,5 可以翻开第 3 行第 5 列！",
                  "hint": f"9 行 9 列 · {mines} 颗雷 · 翻到安全格 +1 分",
                  "board": game.state(), "ai_hold_until": 0, "bomb_owner": None,
                  "prompted": False, "deadline": time.time() + 180})
        self.push()
        self._say("来玩扫雷！AI 会一格格推理，你们也可以发 三逗号五 这样的坐标帮它翻。"
                  f"这一局有{mines}颗雷，翻到安全格加一分，踩到雷就炸哦！", "期待")
        a["deadline"] = time.time() + 180
        started = time.time()
        self.push()
        while self.active is a and not game.dead and not game.won and time.time() < a["deadline"]:
            if self.stop_evt.is_set():
                return
            now = time.time()
            if not a.get("prompted") and not a.get("saw_input") and now - started > 20:
                a["prompted"] = True
                self._say("有没有人想翻一格？发 3,5 就是第3行第5列，来帮 AI 一把！", "期待")
            if now >= a.get("ai_hold_until", 0):
                cell = game.ai_move()
                if cell:
                    res = game.reveal(*cell)
                    a["board"] = game.state()
                    opened = res.get("revealed", 0)
                    if res.get("mine"):
                        a["bomb_owner"] = {"uid": "", "name": "AI"}
                    elif opened >= 5 and self._can_say(a, 6):
                        self._say(f"AI 翻开第{cell[0] + 1}行第{cell[1] + 1}列，"
                                  f"一口气开了{opened}格！", "惊讶")
                    a["ai_hold_until"] = time.time() + delay
                    self.push()
                    if game.dead or game.won:
                        break
            await asyncio.sleep(0.2)
        if not self.active:
            return
        a["board"] = game.state()
        self.push()
        if game.won:
            self._end(f"扫雷成功！{mines}颗雷全部避开，太强了！", "开心",
                      extra={"board": game.state()})
        elif game.dead:
            owner = a.get("bomb_owner") or {}
            if owner.get("name") and owner["name"] != "AI":
                self._end(f"{owner['name']}踩到雷啦！本局翻开了{len(game.revealed)}格，下次小心点！",
                          "惊讶", extra={"board": game.state()})
            else:
                self._end(f"AI 自己踩到雷了！本局翻开了{len(game.revealed)}格，这就是扫雷的魅力。",
                          "尴尬", extra={"board": game.state()})
        else:
            left = game.size * game.size - game.mines - len(game.revealed)
            self._end(f"扫雷时间到！还剩{left}格没翻，下次继续！", "期待",
                      extra={"board": game.state()})

    def _d_minesweeper(self, a, ev, text):
        cell = parse_cell(text)
        if not cell:
            return False
        game = a.get("arcade")
        if not game or game.dead or game.won:
            return False
        r, c = cell
        if not (0 <= r < game.size and 0 <= c < game.size):
            return True
        uid = str(ev.get("uid") or ev.get("raw_name") or ev.get("name"))
        now = time.time()
        if now < a["user_cd"].get(uid, 0):
            return True
        a["user_cd"][uid] = now + 1
        a["saw_input"] = True
        if (r, c) in game.revealed:
            if self._can_say(a, 4):
                self._say(f"第{r + 1}行第{c + 1}列已经翻过啦！")
            return True
        res = game.reveal(r, c)
        a["board"] = game.state()
        delay = max(1.0, min(5.0, float(self.cfg.get("arcade_delay", 2.5) or 2.5)))
        a["ai_hold_until"] = now + delay
        if res.get("mine"):
            a["bomb_owner"] = {"uid": uid, "name": ev["name"]}
            a["phase"] = "result"
            self.push()
            return True
        self._score(uid, ev["name"], 1, a)
        opened = res.get("revealed", 0)
        if opened >= 3 and self._can_say(a, 3):
            self._say(f"{ev['name']}翻开第{r + 1}行第{c + 1}列，一口气开了{opened}格，安全！", "惊讶")
        elif self._can_say(a, 6):
            self._say(random.choice([f"第{r + 1}行第{c + 1}列安全！",
                                     f"{ev['name']}翻开了{r + 1}行{c + 1}列，继续！"]), "期待")
        self.push()
        return True

    # ---------- 2048 ----------
    def _apply_2048(self, a, game, direction, name, uid):
        res = game.move(direction)
        if not res["moved"]:
            return False
        a["board"] = game.state()
        new = game.highest
        if new > a.get("best_tile", 0):
            a["best_tile"] = new
            if new >= 64:
                if uid:
                    self._score(uid, name, 2, a)
                    if self._can_say(a, 3):
                        self._say(f"合出{new}了！{name}这一下太关键了！", "惊讶")
                elif self._can_say(a, 6):
                    self._say(f"合出{new}啦！", "开心")
        a["hint"] = f"合出 64 以上的新数字 +2 分 · 当前最高 {new}"
        self.push()
        return True

    async def _game_game2048(self):
        a = self.active
        delay = max(1.0, min(5.0, float(self.cfg.get("arcade_delay", 2.5) or 2.5)))
        game = Game2048()
        a.update({"title": "2048", "phase": "playing", "arcade": game,
                  "question": "AI 正在玩 2048，发 上/下/左/右 帮它操作！",
                  "hint": f"合出 64 以上的新数字 +2 分 · 当前最高 {game.highest}",
                  "board": game.state(), "ai_hold_until": 0, "best_tile": game.highest,
                  "prompted": False, "deadline": time.time() + 120})
        self.push()
        self._say("来玩 2048！AI 会自己算方向，你们也可以发 上 下 左 右 指挥。"
                  "合出 64 以上的新数字，操作的人加两分！", "期待")
        a["deadline"] = time.time() + 120
        started = time.time()
        self.push()
        while self.active is a and not game.over and time.time() < a["deadline"]:
            if self.stop_evt.is_set():
                return
            now = time.time()
            if not a.get("prompted") and not a.get("saw_input") and now - started > 20:
                a["prompted"] = True
                self._say("有没有人来发个方向？上 下 左 右 都行，帮 AI 想想！", "期待")
            if now >= a.get("ai_hold_until", 0):
                direction = game.ai_move()
                if not direction:
                    break
                self._apply_2048(a, game, direction, "AI", "")
                a["ai_hold_until"] = time.time() + delay
            await asyncio.sleep(0.15)
        if not self.active:
            return
        a["board"] = game.state()
        self.push()
        if game.over:
            self._end(f"2048 结束！最高合出{game.highest}，总分{game.score}。", "开心",
                      extra={"board": game.state()})
        else:
            self._end(f"2048 时间到！最高{game.highest}，总分{game.score}，下次再冲更高！", "期待",
                      extra={"board": game.state()})

    def _d_game2048(self, a, ev, text):
        direction = parse_direction(text)
        if not direction:
            return False
        game = a.get("arcade")
        if not game or game.over:
            return False
        now = time.time()
        uid = str(ev.get("uid") or ev.get("raw_name") or ev.get("name"))
        if now < a["user_cd"].get(uid, 0) or now - a.get("last_input_at", 0) < 0.3:
            return True
        a["user_cd"][uid] = now + 0.6
        a["last_input_at"] = now
        a["saw_input"] = True
        if not self._apply_2048(a, game, direction, ev["name"], uid):
            if self._can_say(a, 4):
                self._say(f"{ev['name']}，这个方向动不了哦！")
            return True
        delay = max(1.0, min(5.0, float(self.cfg.get("arcade_delay", 2.5) or 2.5)))
        a["ai_hold_until"] = now + delay
        return True

    # ---------- 抢答问答 ----------
    async def _quiz_content(self):
        raw = await self._gen("出一道适合直播间观众的趣味知识问答题，题目要短，答案一到六个字。"
                              "严格输出三行：\n题目：……\n答案：……\n解析：……")
        kv = _kv(raw)
        q = kv.get("题目") or kv.get("问题")
        ans = kv.get("答案")
        exp = kv.get("解析") or kv.get("解释") or ""
        if not q or not ans:
            parts = [p.strip() for p in _split_lines(raw) if p.strip()]
            if not q and parts:
                q = parts[0]
            if not ans and len(parts) > 1:
                ans = parts[1]
            if not exp and len(parts) > 2:
                exp = parts[2]
        q, ans, exp = (q or "").strip(), (ans or "").strip(), (exp or "").strip()
        if 6 <= len(q) <= 60 and 1 <= len(ans) <= 12:
            return q, ans, _clip(exp, 80) or "记住这个答案，下次就能抢答成功！"
        return random.choice(QUIZ_BANK)

    async def _game_quiz(self):
        a = self.active
        q, ans, exp = await self._quiz_content()
        if not self.active:
            return
        a.update({"title": "抢答问答", "question": q, "answer": ans, "explain": exp,
                  "hint": "第一个答对的人得 3 分", "phase": "playing", "win": None,
                  "deadline": time.time() + 45})
        self.push()
        await self._say_wait(f"抢答时间！{q} 知道答案的直接打在弹幕里，第一个答对的加三分！", "期待")
        if self.active is not a:
            return
        a["deadline"] = time.time() + 45
        self.push()
        while self.active is a and not a.get("win") and time.time() < a["deadline"]:
            await self._wait_event(a["deadline"])
            if self.stop_evt.is_set() or not self.active:
                return
        if not self.active:
            return
        w = a.get("win")
        if w:
            self._score(w["uid"], w["name"], 3, a)
            self._end(f"抢答成功！{w['name']}，答案就是{ans}！{exp}", "惊讶")
        else:
            self._end(f"时间到！答案是{ans}。{exp}", "期待")

    def _d_quiz(self, a, ev, text):
        ans = a.get("answer") or ""
        if a.get("win") or len(text) > 40:
            return False
        if _has_answer(text, ans):
            a["win"] = {"uid": str(ev.get("uid") or ev.get("raw_name") or ev.get("name")), "name": ev["name"]}
            a["phase"] = "result"
            self.push()
            self.wake.set()
            return True
        if len(text) <= 12:
            a["last"] = f"{ev['name']}：{text}"
            if self._can_say(a, 15):
                self._say(random.choice(["不对哦，再想想！", "还差一点，换个思路！"]))
            self.push()
            return True
        return False

    # ---------- 词语接龙 ----------
    async def _game_word_chain(self):
        a = self.active
        word = random.choice(START_WORDS)
        a.update({"title": "词语接龙", "word": word, "need": word[-1],
                  "question": f"下一个词要用「{word[-1]}」开头",
                  "hint": "两个字也行，成语更好，接得越多分越高", "chain": [{"name": "鲸鱼娘", "word": word}],
                  "phase": "playing", "over": False, "accepted": 0, "last_accept": time.time(),
                  "deadline": time.time() + 120})
        self.push()
        await self._say_wait(f"词语接龙开始！我先来：{word}。下一个词要用「{word[-1]}」开头，"
                             "两个字也行，直接发弹幕！", "期待")
        if self.active is not a:
            return
        a["deadline"] = time.time() + 120
        a["last_accept"] = time.time()
        self.push()
        while self.active is a and not a.get("over") and time.time() < a["deadline"]:
            if a.get("accepted", 0) == 0 and time.time() - a.get("last_accept", 0) > 30:
                a["last_accept"] = time.time()
                match = [w for w in START_WORDS if w[0] == a["need"]]
                new = random.choice(match or START_WORDS)
                if match:
                    a["chain"].append({"name": "鲸鱼娘", "word": new})
                else:
                    a["chain"] = [{"name": "鲸鱼娘", "word": new}]
                a["word"], a["need"] = new, new[-1]
                a["question"] = f"下一个词要用「{new[-1]}」开头"
                self.push()
                await self._say_wait(f"这个字有点难，我换个词开个头：{new}。下一个字是{new[-1]}！", "调皮")
                continue
            await self._wait_event(a["deadline"])
            if self.stop_evt.is_set() or not self.active:
                return
        if not self.active:
            return
        top = self._score_list(a.get("scores", {}))
        if top:
            self._end(f"接龙结束！{top[0]['name']}一共接了{top[0]['pts']}个词，太强了！", "开心")
        else:
            self._end("接龙结束！大家下次再战，我等着你们的词！", "期待")

    def _d_word_chain(self, a, ev, text):
        need = a.get("need") or ""
        word = _word_after(text, need) if need else ""
        if not word:
            return False
        used = {c["word"] for c in a.get("chain", [])}
        if word in used:
            return True
        uid = str(ev.get("uid") or ev.get("raw_name") or ev.get("name"))
        now = time.time()
        if now < a["user_cd"].get(uid, 0):
            return True
        a["user_cd"][uid] = now + 2
        a["chain"].append({"name": ev["name"], "word": word})
        a["chain"] = a["chain"][-6:]
        a["word"], a["need"] = word, word[-1]
        a["question"] = f"下一个词要用「{word[-1]}」开头"
        a["accepted"] = a.get("accepted", 0) + 1
        a["last_accept"] = now
        self._score(uid, ev["name"], 1, a)
        if self._can_say(a, 3.0):
            self._say(f"{ev['name']}接上了{word}！下一个字是{word[-1]}，谁来接？", "开心")
        if a["accepted"] >= 8:
            a["over"] = True
            self.wake.set()
        self.push()
        return True

    # ---------- 观众投票 ----------
    async def _poll_content(self):
        raw = await self._gen("设计一个适合直播间观众投票的二选一趣味问题，两个选项都要常见、正面。"
                              "严格输出三行：\n问题：……\n选项一：……\n选项二：……")
        kv = _kv(raw)
        q = kv.get("问题")
        o1 = kv.get("选项一") or kv.get("选项1")
        o2 = kv.get("选项二") or kv.get("选项2")
        q, o1, o2 = _clip(q, 30), _clip((o1 or "").strip("「」"), 8), _clip((o2 or "").strip("「」"), 8)
        if q and o1 and o2 and o1 != o2 and len(q) >= 6:
            return q, o1, o2
        return random.choice(POLL_BANK)

    async def _game_poll(self):
        a = self.active
        q, o1, o2 = await self._poll_content()
        if not self.active:
            return
        a.update({"title": "观众投票", "question": q,
                  "options": [{"label": o1, "votes": 0}, {"label": o2, "votes": 0}],
                  "hint": f"支持{o1}发 1，支持{o2}发 2", "phase": "playing", "voted": {},
                  "deadline": time.time() + 45})
        self.push()
        await self._say_wait(f"投票啦！{q} 支持{o1}发1，支持{o2}发2，一人一票！", "期待")
        if self.active is not a:
            return
        a["deadline"] = time.time() + 45
        self.push()
        mid = time.time() + 22
        if await self._sleep_until(mid) and self.active is a:
            v = [o["votes"] for o in a["options"]]
            self._say(f"还有二十秒！现在{o1}{v[0]}票，{o2}{v[1]}票，快投！", "期待")
        await self._sleep_until(a["deadline"])
        if not self.active:
            return
        opts = a["options"]
        v1, v2 = opts[0]["votes"], opts[1]["votes"]
        if v1 == v2:
            text = f"投票结束！{o1}{v1}票，{o2}{v2}票，居然平票，大家真有默契！"
        else:
            win = 0 if v1 > v2 else 1
            text = f"投票结束！{o1}{v1}票，{o2}{v2}票，看来大家都是{opts[win]['label']}派！"
            for uid, side in a.get("voted", {}).items():
                if side == win:
                    self._score(uid, a.get("voter_names", {}).get(uid, ""), 1, a)
        self._end(text, "开心", extra={"options": [dict(o) for o in opts], "question": q})

    def _d_poll(self, a, ev, text):
        t = _norm(text)
        if not t:
            return False
        opts = a.get("options") or []
        pick = None
        if t in ("1", "a", "一"):
            pick = 0
        elif t in ("2", "b", "二"):
            pick = 1
        else:
            for i, o in enumerate(opts):
                if _norm(o["label"]) and _norm(o["label"]) in t:
                    pick = i
                    break
        if pick is None:
            return False
        uid = str(ev.get("uid") or ev.get("raw_name") or ev.get("name"))
        if uid in a["voted"]:
            return True
        a["voted"][uid] = pick
        a.setdefault("voter_names", {})[uid] = ev["name"]
        opts[pick]["votes"] += 1
        self.push()
        return True

    # ---------- 猜拳对决 ----------
    async def _game_rps(self):
        a = self.active
        a.update({"title": "猜拳对决", "question": "我出什么？发「石头 / 剪刀 / 布」来挑战我！",
                  "hint": "赢我 +2 分，平局 +1 分，输了一分不给", "phase": "playing",
                  "options": [{"label": "AI 赢", "votes": 0}, {"label": "观众赢", "votes": 0}],
                  "plays": [], "deadline": time.time() + 75})
        self.push()
        await self._say_wait("猜拳对决开始！石头剪刀布随便出，赢我一次加两分，快来！", "调皮")
        if self.active is not a:
            return
        a["deadline"] = time.time() + 75
        self.push()
        while self.active is a and time.time() < a["deadline"]:
            await self._wait_event(a["deadline"])
            if self.stop_evt.is_set() or not self.active:
                return
        if not self.active:
            return
        mine, yours = a["options"][0]["votes"], a["options"][1]["votes"]
        top = self._score_list(a.get("scores", {}))
        if mine == yours == 0:
            self._end("猜拳结束，这次没人出手，下次来试试手气！", "期待")
        elif top:
            self._end(f"猜拳结束！我赢{mine}局，你们赢{yours}局，{top[0]['name']}拿了{top[0]['pts']}分！", "开心")
        else:
            self._end(f"猜拳结束！我赢{mine}局，你们赢{yours}局，下次再来！", "开心")

    def _d_rps(self, a, ev, text):
        core = _norm(text)
        if not core or len(core) > 8:
            return False
        for pre in RPS_PREFIX:
            if core.startswith(pre):
                core = core[len(pre):]
                break
        move = RPS_ALIAS.get(core)
        if not move:
            return False
        uid = str(ev.get("uid") or ev.get("raw_name") or ev.get("name"))
        now = time.time()
        if now < a["user_cd"].get(uid, 0):
            return True
        a["user_cd"][uid] = now + 2.5
        mine = random.choice(list(RPS_BEATS))
        if move == mine:
            result, pts = "平局", 1
        elif RPS_BEATS[move] == mine:
            result, pts = "你赢", 2
            a["options"][1]["votes"] += 1
        else:
            result, pts = "我赢", 0
            a["options"][0]["votes"] += 1
        if pts:
            self._score(uid, ev["name"], pts, a)
        a["plays"].append({"name": ev["name"], "text": f"{move} vs {mine} · {result}"})
        a["plays"] = a["plays"][-6:]
        if self._can_say(a, 2.5):
            if result == "你赢":
                self._say(f"{ev['name']}出{move}，赢了我的{mine}，加两分！", "惊讶")
            elif result == "平局":
                self._say(f"都是{move}，平局，给你一分！", "调皮")
            else:
                self._say(f"我出{mine}，赢了{ev['name']}的{move}，嘿嘿！", "开心")
        self.push()
        return True

    # ---------- 幸运抽奖 ----------
    async def _game_lottery(self):
        a = self.active
        n_win = max(1, min(5, int(self.cfg.get("lottery_winners", 1) or 1)))
        win_sec = max(10, min(300, int(self.cfg.get("lottery_seconds", 45) or 45)))
        a.update({"title": "幸运抽奖", "question": "想参加的打个 1，倒计时结束开奖！",
                  "hint": f"中奖 +5 分，抽 {n_win} 位", "phase": "playing",
                  "joined": {}, "options": [{"label": "已参加", "votes": 0}],
                  "deadline": time.time() + win_sec})
        self.push()
        await self._say_wait(f"幸运抽奖开始！想参加的打个 1，{win_sec} 秒后开奖，中奖加五分！", "期待")
        if self.active is not a:
            return
        a["deadline"] = time.time() + win_sec
        self.push()
        if await self._sleep_until(a["deadline"] - min(20, win_sec * 0.45)) and self.active is a:
            n = len(a["joined"])
            left = max(1, int(a["deadline"] - time.time()))
            if n:
                self._say(f"还有{left}秒，现在{n}位参加了，想抽的赶紧打1！", "期待")
            else:
                self._say(f"还有{left}秒，还没人参加呢，打个1就能抽奖，快来！", "调皮")
        await self._sleep_until(a["deadline"])
        if not self.active:
            return
        people = list(a["joined"].values())
        if not people:
            self._end("时间到，这次没人参加抽奖，下次记得打1哦！", "尴尬")
            return
        winners = random.sample(people, min(n_win, len(people)))
        for w in winners:
            self._score(w["uid"], w["name"], 5, a)
        names = "、".join(w["name"] for w in winners)
        self._end(f"开奖啦！中奖的是{names}，各加五分，恭喜恭喜！", "惊讶")

    def _d_lottery(self, a, ev, text):
        t = _norm(text)
        if t not in ("1", "抽", "抽奖", "参加", "参加抽奖", "我要", "报名", "我参加"):
            return False
        uid = str(ev.get("uid") or ev.get("raw_name") or ev.get("name"))
        if uid in a["joined"]:
            return True
        name = ev.get("name") or "新朋友"
        a["joined"][uid] = {"uid": uid, "name": name}
        a["options"][0]["votes"] = len(a["joined"])
        if self._can_say(a, 6.0):
            self._say(f"{name}也参加了，现在{len(a['joined'])}位！", "开心")
        self.push()
        return True

    # ---------- 飞花令 ----------
    async def _game_feihualing(self):
        a = self.active
        ch = random.choice(FEIHUA_CHARS)
        first = random.choice(FEIHUA_LINES[ch])
        a.update({"title": "飞花令", "word": ch, "need": ch,
                  "question": f"令字「{ch}」：发一句带这个字的诗",
                  "hint": "一句 1 分，不能重复，至少五个字",
                  "chain": [{"name": "鲸鱼娘", "word": first}],
                  "used": [_norm(first)], "phase": "playing", "over": False,
                  "accepted": 0, "last_accept": time.time(), "deadline": time.time() + 120})
        self.push()
        await self._say_wait(f"飞花令来啦！今天的令字是「{ch}」，我先来一句：{first}。"
                            "带这个字的诗都行，一句一分！", "期待")
        if self.active is not a:
            return
        a["deadline"] = time.time() + 120
        a["last_accept"] = time.time()
        self.push()
        while self.active is a and not a.get("over") and time.time() < a["deadline"]:
            if time.time() - a.get("last_accept", 0) > 35:
                a["last_accept"] = time.time()
                pool = [x for x in FEIHUA_LINES[ch] if _norm(x) not in a["used"]]
                if pool:
                    line = random.choice(pool)
                    a["used"].append(_norm(line))
                    a["chain"].append({"name": "鲸鱼娘", "word": line})
                    a["chain"] = a["chain"][-6:]
                    self.push()
                    await self._say_wait(f"我再抛一句：{line}。还有带「{ch}」的诗吗？", "调皮")
                    continue
            await self._wait_event(a["deadline"])
            if self.stop_evt.is_set() or not self.active:
                return
        if not self.active:
            return
        top = self._score_list(a.get("scores", {}))
        n = a.get("accepted", 0)
        if top:
            self._end(f"飞花令结束！一共接了{n}句，{top[0]['name']}接得最多，大家的诗词量都好强！", "开心")
        else:
            self._end(f"飞花令结束！这次只接上{n}句，下次我们换个简单的令字！", "期待")

    def _d_feihualing(self, a, ev, text):
        ch = a.get("word") or ""
        line = re.sub(r"[\s，。！？!?,.、~～；;：:\"'“”‘’（）()]", "", text or "")
        if not ch or ch not in line or not (5 <= len(line) <= 30) or len(set(line)) < 4:
            return False
        key = _norm(line)
        if key in a.get("used", []):
            return True
        uid = str(ev.get("uid") or ev.get("raw_name") or ev.get("name"))
        now = time.time()
        if now < a["user_cd"].get(uid, 0):
            return True
        a["user_cd"][uid] = now + 2
        a["used"].append(key)
        a["used"] = a["used"][-200:]
        shown = _clip(line, 18)
        a["chain"].append({"name": ev["name"], "word": shown})
        a["chain"] = a["chain"][-6:]
        a["accepted"] = a.get("accepted", 0) + 1
        a["last_accept"] = now
        self._score(uid, ev["name"], 1, a)
        if self._can_say(a, 3.0):
            self._say(f"{ev['name']}接上「{shown}」，加一分！还有带「{ch}」的诗吗？", "开心")
        if a["accepted"] >= 10:
            a["over"] = True
            self.wake.set()
        self.push()
        return True

    # ---------- 冷知识 ----------
    async def _fact_content(self):
        raw = await self._gen("说两条有趣的冷知识，每条不超过五十字，严格一行一条，不要开场白和编号。")
        lines = [re.sub(r"^\s*\d+[.、)]\s*", "", s).strip() for s in _split_lines(raw)]
        lines = [s for s in lines if 8 <= len(s) <= 100][:2]
        if len(lines) < 2:
            lines = random.sample(FACT_BANK, 2)
        return lines

    async def _game_fact(self):
        a = self.active
        facts = await self._fact_content()
        if not self.active:
            return
        a.update({"title": "冷知识播报", "question": facts[0], "hint": "再送一条",
                  "phase": "playing", "deadline": time.time() + 60})
        self.push()
        await self._say_wait("冷知识时间到！", "开心")
        await self._say_wait(facts[0], "开心")
        if self.active is not a:
            return
        await self._sleep_until(time.time() + 1.5)
        a["question"] = facts[1]
        self.push()
        await self._say_wait("再送大家一条：" + facts[1], "惊讶")
        if self.active is a:
            self._end("今天的冷知识就到这里，我们下次继续涨知识！", "开心")

    # ---------- 故事连载 ----------
    async def _game_story(self):
        a = self.active
        a.update({"title": "故事连载", "question": "《鲸鱼娘的海底电台》正在准备下一段…",
                  "hint": "AI 自编自讲的连续小故事", "phase": "playing", "deadline": time.time() + 90})
        self.push()
        context = self.story[-900:]
        prompt = ("你在给直播间观众讲一个轻松搞笑、适合全年龄的海底小故事，标题是《鲸鱼娘的海底电台》，"
                  "主角是鲸鱼娘和她的海底电台。"
                  + (f"已有剧情：{context}\n请续写下一段，一百二十字左右，结尾留一点悬念。" if context
                     else "这是第一段，一百二十字左右，交代鲸鱼娘和海底电台，结尾留一点悬念。")
                  + "直接输出故事正文，不要标题、不要解释。")
        text = await self._gen(prompt, 40)
        if not self.active:
            return
        text = _clip(re.sub(r"^\s*(第.{1,3}集|续写|故事)[：:]\s*", "", text), 260)
        if len(text) < 30:
            text = ("鲸鱼娘正在海底电台值班，忽然收到一段没有署名的求救信号。她顺着信号游过去，"
                    "发现声音居然来自一个会说话的海螺。海螺说，它知道海底最会唱歌的鲸鱼在哪里。")
        first = not self.story
        self.story = (self.story + "\n" + text)[-1200:]
        a["question"] = text
        self.push()
        await self._say_wait("故事时间！《鲸鱼娘的海底电台》开播啦！" if first
                             else "故事时间！《鲸鱼娘的海底电台》继续！", "期待")
        await self._say_wait(text, "期待")
        if self.active is a:
            self._end("今天的故事先讲到这儿，想知道后面发生了什么，就留下来听下一集！", "调皮")

    # ---------- 脑筋急转弯 ----------
    async def _riddle_content(self):
        raw = await self._gen("出一个适合直播间的中文脑筋急转弯或谜语，答案要短。"
                              "严格输出两行：\n谜面：……\n答案：……")
        kv = _kv(raw)
        r = kv.get("谜面") or kv.get("题目")
        ans = kv.get("答案")
        if not r or not ans:
            parts = [p.strip() for p in _split_lines(raw) if p.strip()]
            if not r and parts:
                r = parts[0]
            if not ans and len(parts) > 1:
                ans = parts[1]
        r, ans = _clip(r, 60), _clip(ans, 14)
        if r and ans:
            return r, ans
        return random.choice(RIDDLE_BANK)

    async def _game_riddle(self):
        a = self.active
        riddle, answer = await self._riddle_content()
        if not self.active:
            return
        a.update({"title": "脑筋急转弯", "question": riddle, "hint": "答案马上公布",
                  "phase": "playing", "deadline": time.time() + 30})
        self.push()
        await self._say_wait("脑筋急转弯来啦！" + riddle + " 大家先猜猜看！", "期待")
        if self.active is not a:
            return
        await self._sleep_until(time.time() + 6)
        if self.active is not a:
            return
        a["hint"] = "答案：" + answer
        self.push()
        self._end(f"答案是{answer}！你猜到了吗？", "惊讶")

    # ---------- 讲笑话 ----------
    async def _joke_content(self):
        raw = await self._gen("讲一个干净、不冒犯任何人的短笑话，适合全年龄直播间。"
                              "严格输出两行：\n铺垫：……\n包袱：……")
        kv = _kv(raw)
        setup = kv.get("铺垫")
        punch = kv.get("包袱")
        if not setup or not punch:
            parts = [p.strip() for p in _split_lines(raw) if p.strip()]
            if len(parts) >= 2:
                setup, punch = parts[0], " ".join(parts[1:])
        setup, punch = _clip(setup, 90), _clip(punch, 90)
        if setup and punch and setup != punch:
            return setup, punch
        return random.choice(JOKE_BANK)

    async def _game_joke(self):
        a = self.active
        setup, punch = await self._joke_content()
        if not self.active:
            return
        a.update({"title": "AI 讲笑话", "question": setup, "hint": "包袱马上就来",
                  "phase": "playing", "deadline": time.time() + 60})
        self.push()
        await self._say_wait("来听个笑话，先热热身！", "开心")
        await self._say_wait(setup, "调皮")
        if self.active is not a:
            return
        await self._sleep_until(time.time() + 1.2)
        a["question"] = punch
        a["hint"] = ""
        self.push()
        await self._say_wait(punch, "开心")
        if self.active is a:
            self._end("好笑的话就给主播点个赞吧，下个笑话马上安排！", "开心")
