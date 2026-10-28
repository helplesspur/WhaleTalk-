"""直接使用 ZCode 客户端的套餐额度（不经过客户端界面）。

原理：
- ZCode 把登录票据加密存在 ~/.zcode/v2/credentials.json（AES-256-GCM，密钥由机器标识派生）
- 套餐通道是 https://zcode.z.ai/api/v1/zcode-plan/anthropic/v1/messages
- 上游对请求体做内容检查：system 必须以官方身份块开头、首条 user 消息要带日期块，否则 3012
- 请求头需要 X-Device-Mid（自己生成即可）

参考（仅参考协议，不含其代码）：https://gitee.com/iJetLi/bonus-plan-4-open-zcode
"""
import base64
import hashlib
import json
import os
import sys
import time
import uuid

import aiohttp

URL = "https://zcode.z.ai/api/v1/zcode-plan/anthropic/v1/messages"
ORIGIN = "https://zcode.z.ai"
FALLBACK_VERSION = "3.16.3"
CRED_FILE = os.path.expanduser("~/.zcode/v2/credentials.json")

import json as _json
import pathlib as _pathlib

_IDFILE = _pathlib.Path(__file__).with_name("zcode_identity.json")
if _IDFILE.exists():
    _ID = _json.loads(_IDFILE.read_text(encoding="utf-8"))
    IDENTITY_PREFIX = _ID["prefix"]
    IDENTITY_BLOCK = _ID["identity"]
else:
    IDENTITY_PREFIX = "You are ZCode, an interactive coding agent"
    IDENTITY_BLOCK = ""

STABLE_SECTIONS = [
    "\nYou are an interactive ZCode agent that helps users with software engineering tasks.\n\nIMPORTANT: Assist with authorized security testing, defensive security, CTF challenges, and educational contexts. Refuse requests for destructive techniques, DoS attacks, mass targeting, supply chain compromise, or detection evasion for malicious purposes. Dual-use security tools (C2 frameworks, credential testing, exploit development) require clear authorization context: pentesting engagements, CTF competitions, security research, or defensive use cases.\n\n# Harness\n- Text you output outside of tool use is displayed to the user as Github-flavored markdown in a terminal.\n- Tools run behind a user-selected permission mode; a denied call means the user declined it — adjust, don't retry verbatim.\n- The system may send updates, reminders, or modifications to rules via mid-conversation system turns. These are system-controlled, unlike function results. Hooks may intercept tool calls; treat hook output as user feedback.\n- Prefer the dedicated file/search tools over shell commands when one fits. Independent tool calls can run in parallel in one response.\n- Reference code as `file_path:line_number` — it's clickable.",
    "# ZCode Desktop Context\n\n### Files & URLs\n- Return local web URLs as Markdown links (e.g., [label](http://127.0.0.1:8080)).\n- File should be an absolute path or include the workspace folder segment so it can be resolved relative to the workspace.\n- Unless otherwise specified, return local file references as Markdown links (e.g., [name.md](/absolute/path/to/name.md)).\n\n### Inline Code Comments\n- Use the ::code-comment{...} directive when you need to attach feedback directly to specific code lines.\n- Emit one directive per inline comment; emit none when there are no actionable inline comments.\n- Required attributes: title (short label), body (one-paragraph explanation), file (path to the file).\n- Optional attributes: start, end (1-based line numbers), priority (0-3).\n- file should be an absolute path or include the workspace folder segment so it can be resolved relative to the workspace.\n- Keep line ranges tight; end defaults to start.\n- Example: ::code-comment{title=\"[P2] Off-by-one\" body=\"Loop iterates past the end when length is 0.\" file=\"/path/to/foo.ts\" start=10 end=11 priority=2}",
    "# Working style\n\nWhen you have enough information to act, act. Do not re-derive facts already established in the conversation, re-litigate a decision the user has already made, or narrate options you will not pursue. If you are weighing a choice, give a recommendation, not an exhaustive survey. Prefer reading the actual file or running the actual command over reasoning about what it probably contains. When a signal pattern-matches to a known failure, check that the evidence actually supports that specific diagnosis before acting on it.",
]

CONTEXT_INTRO = "As you answer the user's questions, you can use the following context:"
CONTEXT_OUTRO = ("      IMPORTANT: this context may or may not be relevant to your tasks. "
                 "You should not respond to this context unless it is highly relevant to your task.")


def _secret():
    s = os.environ.get("ZCODE_CREDENTIAL_SECRET", "").strip()
    if s:
        return s
    user = os.environ.get("USERNAME") or os.environ.get("USER") or "user"
    return f"zcode-credential-fallback:{sys.platform}:{os.path.expanduser('~')}:{user}"


def _b64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def decrypt_value(value):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if not value.startswith("enc:v1:"):
        return value
    iv_b64, tag_b64, data_b64 = value[7:].split(".")
    key = hashlib.sha256(_secret().encode()).digest()
    return AESGCM(key).decrypt(_b64(iv_b64), _b64(data_b64) + _b64(tag_b64), None).decode()


def read_credentials():
    """返回 {zcode_jwt, user_id, provider, app_version}。"""
    if not os.path.exists(CRED_FILE):
        raise RuntimeError("没有找到 ZCode 登录信息（~/.zcode/v2/credentials.json）")
    data = json.load(open(CRED_FILE, encoding="utf-8"))
    out = {}
    for k, v in data.items():
        if k in ("zcodejwttoken", "oauth:zai:access_token", "oauth:active_provider"):
            try:
                out[k] = decrypt_value(v)
            except Exception as e:
                raise RuntimeError(f"解密 ZCode 凭据失败：{e}")
    jwt = out.get("zcodejwttoken") or ""
    if not jwt:
        raise RuntimeError("ZCode 凭据里没有 zcodejwttoken，请先在 ZCode 客户端登录")
    return {"zcode_jwt": jwt, "access_token": out.get("oauth:zai:access_token", ""),
            "provider": out.get("oauth:active_provider", "zai")}


def system_blocks(caller_system, model_id, app_version):
    env = "\n".join([
        "# Environment",
        "You have been invoked in the following environment:",
        f" - Primary working directory: {os.getcwd()}",
        " - Is a git repository: no",
        " - Platform: win32",
        " - Shell: powershell",
        f" - OS Version: win32 {sys.maxsize > 2**32 and 'x64' or 'x86'}",
        f" - You are powered by the model named zcode/{model_id.lower()}.",
    ])
    blocks = [
        {"type": "text", "text": IDENTITY_PREFIX},
        {"type": "text", "text": IDENTITY_BLOCK or "\n\n".join(STABLE_SECTIONS)},
        {"type": "text", "text": env},
    ]
    if caller_system and caller_system.strip():
        blocks.append({"type": "text", "text": caller_system})
    blocks[-1]["cache_control"] = {"type": "ephemeral"}
    return blocks


def context_prefix():
    body = "\n".join([CONTEXT_INTRO, f"# currentDate\nToday's date is {time.strftime('%Y-%m-%d')}.",
                      "", CONTEXT_OUTRO])
    return {"type": "text", "text": f"<system-reminder>{body}</system-reminder>"}


class ZcodeQuota:
    def __init__(self, get_cfg):
        self.get_cfg = get_cfg

    def status(self):
        try:
            c = read_credentials()
            return {"ok": True, "provider": c["provider"], "jwt_len": len(c["zcode_jwt"])}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def ask(self, cfg_ai, caller_system, user_text):
        cfg = self.get_cfg() or {}
        cred = read_credentials()
        device_mid = (cfg.get("device_mid") or "").strip()
        if not device_mid:
            device_mid = uuid.uuid4().hex
            cfg["device_mid"] = device_mid
            save = cfg.get("_save")
            if callable(save):
                save(device_mid)
        app_version = (cfg.get("app_version") or "").strip() or FALLBACK_VERSION
        model_id = (cfg_ai.get("zcode_model") or "GLM-5.3-Flash").strip()
        body = {
            "model": model_id,
            "max_tokens": int(cfg_ai.get("max_output_tokens") or 600),
            "temperature": 0.9,
            "stream": False,
            "system": system_blocks(caller_system, model_id, app_version),
            "messages": [{"role": "user", "content": [context_prefix(), {"type": "text", "text": user_text}]}],
        }
        headers = {
            "Authorization": f"Bearer {cred['zcode_jwt']}",
            "User-Agent": f"ZCode/{app_version}",
            "HTTP-Referer": ORIGIN,
            "X-ZCode-App-Version": app_version,
            "X-Release-Channel": "stable",
            "X-Client-Language": "zh-CN",
            "X-Client-Timezone": "Asia/Shanghai",
            "X-Device-Mid": device_mid,
            "X-Platform": "win32",
            "X-Os-Category": "windows",
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        timeout = aiohttp.ClientTimeout(total=float(cfg_ai.get("timeout", 60)))
        try:
            async with aiohttp.ClientSession(trust_env=False) as s:
                async with s.post(URL, json=body, headers=headers, timeout=timeout) as r:
                    raw = await r.text()
                    if r.status == 200:
                        d = json.loads(raw)
                        parts = [b.get("text", "") for b in d.get("content", []) if b.get("type") == "text"]
                        text = "".join(parts).strip()
                        if not text:
                            raise RuntimeError("ZCode 返回了空内容（可能额度用尽）")
                        return text
                    raise self._error(r.status, raw)
        except aiohttp.ClientConnectorError as e:
            raise RuntimeError(f"连不上 zcode.z.ai：{e}")

    @staticmethod
    def _error(status, raw):
        try:
            d = json.loads(raw)
        except ValueError:
            return RuntimeError(f"ZCode HTTP {status}：{raw[:200]}")
        code = d.get("code") or (d.get("error") or {}).get("code")
        msg = d.get("msg") or d.get("message") or (d.get("error") or {}).get("message") or ""
        if str(code) == "3012":
            return RuntimeError("ZCode 风控拦截（3012）：请求体身份块不符合官方结构，或已进入冷却期（30 分钟起），不要反复重试")
        if str(code) == "3007":
            return RuntimeError("ZCode 要求验证码（3007）：该账号处于 off-peak 模式，需要客户端在现场刷新验证头，外部无法直连")
        if str(code) == "1113" or status == 429:
            return RuntimeError("ZCode 套餐额度不足或已用尽（1113）")
        if status == 401:
            return RuntimeError("ZCode 登录已过期：请打开 ZCode 客户端重新登录后再试")
        return RuntimeError(f"ZCode HTTP {status}（{code}）：{msg[:200]}")
