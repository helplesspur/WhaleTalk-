import copy
import json
import os
import sys
import threading

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
    RES_DIR = getattr(sys, "_MEIPASS", BASE_DIR)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    RES_DIR = BASE_DIR

CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
LOG_DIR = os.path.join(BASE_DIR, "logs")
WEB_DIR = os.path.join(RES_DIR, "web")

DEFAULT_PERSONA = (
    "你是一位活泼可爱、说话自然的虚拟主播，正在直播。"
    "观众的进场、弹幕、礼物、粉丝团等消息会发给你，你要像真人主播一样用口语回应。"
)

DEFAULTS = {
    "platform": "bilibili",
    "ui": {"native": True, "width": 1400, "height": 940},
    "session": {"auto_start": False},
    "room_id": 0,
    "bili_cookie": "",
    "douyin": {
        "mode": "browser",
        "web_rid": "",
        "room_url": "",
        "browser_exe": "",
        "debug_port": 9333,
        "profile_dir": "",
        "keep_browser": True,
        "headless": False,
        "gift_prices": "小心心=1\n玫瑰=1\n大啤酒=2\n加油鸭=5\n抖音1号=10001",
    },
    "auto_connect": False,
    "web_port": 8787,
    "open_ui": True,
    "events": {
        "enter": {
            "enabled": True, "mode": "template", "cooldown_user": 600, "merge_window": 4, "max_names": 3,
            "templates": "欢迎{name}来到直播间！\n{name}来啦，欢迎欢迎！\n欢迎{name}，找个位置坐下吧！",
            "ai_prompt": "观众{name}进入了直播间，请热情地欢迎。",
        },
        "follow": {
            "enabled": True, "mode": "template", "cooldown_user": 3600, "merge_window": 4, "max_names": 3,
            "templates": "谢谢{name}的关注！\n感谢{name}关注，以后常来玩哦！",
            "ai_prompt": "观众{name}关注了主播，请表示感谢。",
        },
        "danmaku": {
            "enabled": True, "mode": "ai", "cooldown_user": 8, "probability": 100,
            "trigger_words": "", "ignore_emoticon": True, "read_original": False,
            "templates": "{name}说：{text}",
            "ai_prompt": "观众{name}发弹幕说：「{text}」。请直接回应这条弹幕。",
        },
        "gift": {
            "enabled": True, "mode": "ai", "merge_window": 3, "min_value": 0, "thank_free": True,
            "templates": "谢谢{name}送的{num}个{gift}！\n感谢{name}的{gift}，破费啦！",
            "ai_prompt": "观众{name}送出了{num}个{gift}（约{value}元）。请真诚地感谢。",
        },
        "guard": {
            "enabled": True, "mode": "ai",
            "templates": "感谢{name}开通{guard}！欢迎上船！",
            "ai_prompt": "观众{name}开通了{num}个月的{guard}。这是很大的支持，请隆重、激动地感谢并欢迎上船。",
        },
        "superchat": {
            "enabled": True, "mode": "ai",
            "templates": "谢谢{name}的{price}元醒目留言！{name}说：{text}",
            "ai_prompt": "观众{name}发送了{price}元的醒目留言：「{text}」。先感谢，再认真回应留言内容。",
        },
        "like": {
            "enabled": False, "mode": "template", "cooldown_user": 600, "merge_window": 5, "max_names": 3,
            "templates": "谢谢{name}的点赞！",
            "ai_prompt": "观众{name}给直播间点了赞，请简短感谢。",
        },
    },
    "filter": {
        "blocklist": "",
        "ignore_users": "",
        "ignore_owner": True,
        "max_queue": 6,
        "max_wait": 60,
        "name_max_len": 12,
        "rename_default": True,
    },
    "ai": {
        "backend": "qoder",
        "qoder_exe": "",
        "qoder_model": "Fast",
        "recycle_after": 60,
        "persona": DEFAULT_PERSONA,
        "max_chars": 40,
        "openai_base": "https://api.deepseek.com/v1",
        "openai_key": "",
        "openai_model": "deepseek-chat",
        "openai_mode": "responses",
        "thinking": "default",
        "timeout": 30,
    },
    "cli": {
        "preset": "",
        "exe": "",
        "args": [],
        "env": "",
        "cwd": "",
        "json_field": "",
        "timeout": 90,
    },
    "zcode": {
        "proxy_url": "http://127.0.0.1:17899",
        "plugin_dir": r"D:\tools\bonus-plan",
        "node_exe": r"D:\tools\node\node.exe",
        "autostart": True,
        "model": "GLM-5.3-Flash",
    },
    "tts": {
        "enabled": True,
        "gsv_dir": "",
        "api_url": "http://127.0.0.1:9880",
        "auto_start": True,
        "stop_on_exit": True,
        "gpt_weights": "GPT_SoVITS/pretrained_models/s1v3.ckpt",
        "sovits_weights": "GPT_SoVITS/pretrained_models/v2Pro/s2Gv2Pro.pth",
        "ref_audio": "",
        "ref_text": "",
        "ref_lang": "zh",
        "text_lang": "zh",
        "speed": 1.0,
        "temperature": 1.0,
        "top_k": 15,
        "top_p": 1.0,
        "sample_steps": 32,
        "bake_extra": "",
        "segment_bake": True,
    },
    "audio": {"device": "", "volume": 80},
    "overlay": {"seconds": 8},
    "stats": {
        "token_label": "本场已用 Token",
        "title": "",
        "show_tokens": True,
        "show_duration": True,
        "show_gifts": True,
        "gift_list": True,
        "gift_rows": 4,
        "font_size": 24,
        "position": "top-left",
    },
    "songs": {
        "enabled": True,
        "require_gift": True,
        "song_gifts": "小花花",
        "song_gift_count": 1,
        "pin_gifts": "人气票",
        "pin_gift_count": 1,
        "max_queue": 20,
        "max_per_user": 2,
        "max_minutes": 8,
        "volume": 45,
        "duck": 30,
        "netease_cookie": "",
        "autoplay": {"enabled": False, "playlist_id": "", "playlist_name": "", "mode": "shuffle",
                     "interrupt": True, "max_fail": 3},
        "announce_add": True,
        "announce_similar": True,
        "announce_pin": True,
        "announce_play": True,
        "announce_fail": True,
        "announce_need": True,
        "announce_full": True,
        "tpl_add": "收到{name}点的《{song}》，排在第{pos}首！",
        "tpl_similar": "原版暂时放不了，给{name}找了相似的《{song}》，排在第{pos}首。",
        "tpl_pin": "{name}的《{song}》插队成功，排到最前面啦！",
        "tpl_play": "下面播放{name}点的《{song}》。",
        "tpl_fail": "抱歉{name}，没找到能播放的《{query}》。",
        "tpl_need": "{name}，送{num}个{gift}就可以点歌哦！",
        "tpl_full": "{name}，歌单排满啦，等前面的播完再点吧！",
    },
    "games": {
        "enabled": True,
        "auto": False,
        "interval": 180,
        "guess_max": 8,
        "snake_speed_ms": 350,
        "mines": 10,
        "arcade_delay": 2.5,
        "lottery_winners": 1,
        "lottery_seconds": 45,
        "choices": {
            "guess_number": True,
            "number_bomb": True,
            "quiz": True,
            "word_chain": True,
            "poll": True,
            "snake": True,
            "minesweeper": True,
            "game2048": True,
            "rps": True,
            "lottery": True,
            "feihualing": True,
            "fact": True,
            "story": True,
            "riddle": True,
            "joke": True,
        },
    },
    "fixed_replies": [
        {"enabled": True, "keywords": "晚安", "match": "contains", "reply": "{name}晚安，做个好梦！", "emotion": "开心"},
        {"enabled": True, "keywords": "生日快乐", "match": "contains", "reply": "谢谢{name}！你也要天天开心哦！", "emotion": "感谢"},
    ],
    "live2d": {
        "enabled": False,
        "model_dir": "",
        "model_file": "",
        "scale": 1.0,
        "x": 0.5,
        "y": 0.0,
        "breath": True,
        "blink": True,
        "sway": False,
        "lipsync": True,
        "lip_gain": 1.2,
        "idle_motion": "",
        "base_expressions": [],
        "expr_hold": 3,
        "bubble": True,
        "bubble_x": 0.28,
        "bubble_y": 0.12,
        "bubble_font": 26,
        "bubble_width": 420,
        "bubble_bg": "#ffffff",
        "bubble_color": "#333333",
        "bubble_border": "#fb7299",
        "bubble_hold": 4,
        "emotions": [
            {"name": "开心", "expressions": ["开心兴奋"], "motion": "", "keywords": "哈哈,开心,太好了,好耶,欢迎"},
            {"name": "感谢", "expressions": ["爱心眼"], "motion": "", "keywords": "谢谢,感谢,爱你,比心,破费"},
            {"name": "害羞", "expressions": ["脸红"], "motion": "", "keywords": "害羞,不好意思,讨厌啦,夸我"},
            {"name": "惊讶", "expressions": ["感叹号"], "motion": "", "keywords": "哇,天哪,真的吗,居然,上舰,上船"},
            {"name": "期待", "expressions": ["星星眼"], "motion": "", "keywords": "期待,好想,超想,一起"},
            {"name": "疑惑", "expressions": ["问号"], "motion": "", "keywords": "为什么,咦,什么意思"},
            {"name": "调皮", "expressions": ["吐舌"], "motion": "chuipaopao", "keywords": "嘿嘿,略略略,才不"},
            {"name": "生气", "expressions": ["生气"], "motion": "", "keywords": "哼,生气,气死"},
            {"name": "难过", "expressions": ["悲伤"], "motion": "", "keywords": "难过,伤心,呜呜"},
            {"name": "尴尬", "expressions": ["流汗"], "motion": "", "keywords": "尴尬,呃,汗"},
            {"name": "晕", "expressions": ["晕晕"], "motion": "", "keywords": "晕,头晕,好累"},
            {"name": "无语", "expressions": ["呆呆眼"], "motion": "", "keywords": "无语,啊这"},
        ],
    },
}

_lock = threading.Lock()


def _merge(base, override):
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load():
    data = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            os.replace(CONFIG_PATH, CONFIG_PATH + ".broken")
    cfg = _merge(DEFAULTS, data)
    save(cfg)
    return cfg


def save(cfg):
    with _lock:
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_PATH)


def merge(cfg, patch):
    return _merge(cfg, patch)
