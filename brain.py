import asyncio
import collections
import json
import logging
import os
import random
import re
import time

import aiohttp

import procutil
from config import BASE_DIR

log = logging.getLogger("ai")

RULES = (
    "\n\n【输出规则】每次只输出主播要说出口的一段话，不超过{max_chars}个字；"
    "纯口语中文，不要表情符号、颜文字、Markdown、引号、括号或动作描写；"
    "不要自称AI，不要解释，不要复述规则；观众名字最多提一次；"
    "遇到辱骂、引战、政治、色情或违规内容就俏皮地转移话题。"
)


THINKING_LEVELS = ("default", "off", "low", "medium", "high", "auto")
THINKING_LABELS = {"default": "跟随模型默认", "off": "关闭思考", "low": "低", "medium": "中",
                   "high": "高", "auto": "自动"}
_THINKING_BUDGET = {"low": 1024, "medium": 4096, "high": 12288}


def thinking_level(cfg_ai):
    level = str((cfg_ai or {}).get("thinking") or "default").strip().lower()
    return level if level in THINKING_LEVELS else "default"


def err_text(e, limit=300):
    """异常 → 能看懂的失败原因。str(e) 可能为空（TimeoutError 之类），不要只留一个冒号。"""
    msg = str(e).strip()
    if not msg:
        msg = ("等待超时，服务端一直没有返回结果" if isinstance(e, asyncio.TimeoutError)
               else type(e).__name__)
    if len(msg) > limit:
        msg = msg[:limit].rstrip() + "…"
    return msg


def default_qoder_exe():
    return os.path.join(os.path.expanduser("~"), ".qoder", "bin", "qodercli", "qodercli.exe")


def norm_usage(u):
    """把各家 usage 字段归一成 {prompt, completion, total}，认不出就返回 None。"""
    if not isinstance(u, dict):
        return None
    p = u.get("input_tokens", u.get("prompt_tokens"))
    c = u.get("output_tokens", u.get("completion_tokens"))
    t = u.get("total_tokens")
    if p is None and c is None and t is None:
        return None
    p, c = int(p or 0), int(c or 0)
    t = int(t or (p + c))
    if not t:
        return None
    return {"prompt": p, "completion": c, "total": t}


def sum_model_usage(mu):
    """qodercli 的 result 事件里可能只有 modelUsage：{模型: {input_tokens, ...}}。"""
    if not isinstance(mu, dict):
        return None
    p = c = 0
    for v in mu.values():
        u = norm_usage(v)
        if u:
            p += u["prompt"]
            c += u["completion"]
    return {"prompt": p, "completion": c, "total": p + c} if (p or c) else None


async def list_qoder_models(cfg_ai):
    exe = cfg_ai.get("qoder_exe") or default_qoder_exe()
    if not os.path.exists(exe):
        raise RuntimeError(f"找不到 qodercli：{exe}")
    p = await asyncio.create_subprocess_exec(
        exe, "--list-models", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env=procutil.clean_env(), creationflags=procutil.CREATE_NO_WINDOW)
    out, err = await asyncio.wait_for(p.communicate(), 60)
    text = out.decode("utf-8", "replace")
    models = []
    for line in text.splitlines():
        name = re.split(r"\s{2,}", line.strip())[0] if line.strip() else ""
        if name and name.upper() != "MODEL" and not name.startswith(("-", "=")):
            models.append(name)
    if not models:
        msg = (err.decode("utf-8", "replace") or text).strip()
        raise RuntimeError(("qodercli 未登录，请运行 qoder_login.bat。" if "login" in msg.lower() else "") + msg[-300:])
    return models


class QoderSession:
    """常驻 qodercli 进程（stream-json 双向流），首句约 3 秒，之后每句约 1.5 秒，并保留对话上下文。"""

    def __init__(self):
        self.proc = None
        self.turns = 0
        self.sig = None
        self.lock = asyncio.Lock()
        self.workdir = os.path.join(BASE_DIR, "qoder_workdir")
        self.last_usage = None
        self.queue = {}      # 最近一次 model_queue_status 事件
        self.started = 0.0   # 本次请求开始时间，用于算实际等了多久

    async def close(self):
        p, self.proc = self.proc, None
        if p and p.returncode is None:
            try:
                p.stdin.close()
            except Exception:
                pass
            try:
                await asyncio.wait_for(p.wait(), 1)
            except asyncio.TimeoutError:
                p.kill()

    async def _spawn(self, cfg_ai, system_prompt):
        exe = cfg_ai.get("qoder_exe") or default_qoder_exe()
        if not os.path.exists(exe):
            raise RuntimeError(f"找不到 qodercli：{exe}（请先安装 Qoder CLI）")
        os.makedirs(self.workdir, exist_ok=True)
        args = [exe, "-p", "--input-format", "stream-json", "--output-format", "stream-json",
                "--max-turns", "1", "--tools", "", "--setting-sources", "", "--strict-mcp-config",
                "--no-session-persistence", "--system-prompt", system_prompt]
        if cfg_ai.get("qoder_model"):
            args += ["-m", cfg_ai["qoder_model"]]
        level = thinking_level(cfg_ai)
        if level == "off":
            args += ["--thinking", "disabled"]
        elif level == "auto":
            args += ["--thinking", "auto"]
        elif level in _THINKING_BUDGET:
            args += ["--reasoning-effort", level]
        self.proc = await asyncio.create_subprocess_exec(
            *args, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, cwd=self.workdir, env=procutil.clean_env(),
            creationflags=procutil.CREATE_NO_WINDOW, limit=4 * 1024 * 1024)
        procutil.bind_to_app(self.proc.pid)
        self.turns = 0
        log.info("qodercli 会话已启动 pid=%s", self.proc.pid)

    async def warm(self, cfg_ai, system_prompt):
        async with self.lock:
            if self.proc is None or self.proc.returncode is not None:
                await self._spawn(cfg_ai, system_prompt)
                self.sig = (cfg_ai.get("qoder_exe"), cfg_ai.get("qoder_model"), thinking_level(cfg_ai), system_prompt)

    async def ask(self, cfg_ai, system_prompt, user_text):
        async with self.lock:
            sig = (cfg_ai.get("qoder_exe"), cfg_ai.get("qoder_model"), thinking_level(cfg_ai), system_prompt)
            if (self.proc is None or self.proc.returncode is not None or sig != self.sig
                    or self.turns >= max(1, int(cfg_ai.get("recycle_after", 60)))):
                await self.close()
                await self._spawn(cfg_ai, system_prompt)
                self.sig = sig
            msg = {"type": "user", "message": {"role": "user", "content": user_text}, "parent_tool_use_id": None}
            self.last_usage = None
            self.queue = {}
            self.started = time.monotonic()
            timeout = float(cfg_ai.get("timeout", 30))
            try:
                self.proc.stdin.write((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))
                await self.proc.stdin.drain()
                result = await asyncio.wait_for(self._read_result(), timeout)
            except asyncio.TimeoutError:
                waited = max(0.0, time.monotonic() - self.started)
                await self.close()
                raise RuntimeError(self._timeout_text(cfg_ai, timeout, waited)) from None
            except Exception:
                await self.close()
                raise
            self.turns += 1
            return result

    def _timeout_text(self, cfg_ai, timeout, waited):
        """超时的时候给一句能定位问题的原因：到底在排队、服务繁忙，还是单纯太慢。"""
        model = cfg_ai.get("qoder_model") or "默认模型"
        level = thinking_level(cfg_ai)
        q = self.queue or {}
        parts = [f"Qoder 超时：等了 {int(waited)} 秒没有结果（超时设置 {timeout:g} 秒），"
                 f"模型 {model}，思考程度“{THINKING_LABELS.get(level, level)}”"]
        if q:
            state = "仍在服务端排队" if q.get("status") == "queued" else f"状态 {q.get('status') or '未知'}"
            busy = "服务繁忙" if not q.get("service_available", True) else "服务可用"
            parts.append(f"{state}、{busy}")
            est = float(q.get("wait_time_ms") or 0) / 1000
            if not q.get("service_available", True) and est > 0:
                parts.append(f"服务端预估排队 {est:.0f} 秒")
        if level in _THINKING_BUDGET:
            parts.append("低/中/高思考档位会走 Qoder 的推理队列，繁忙时一直排："
                         "把“思考程度”改成“跟随模型默认”或“关闭”通常几秒就能回复，"
                         "或把“超时秒数”调到 120 秒以上继续等")
        else:
            parts.append("Qoder 高峰期排队常见 1~3 分钟：可把“AI 设置→超时秒数”调到 120 秒以上重试，"
                         "或换一个模型")
        return "；".join(parts)

    async def _read_result(self):
        while True:
            line = await self.proc.stdout.readline()
            if not line:
                err = (await self.proc.stderr.read()).decode("utf-8", "replace").strip()
                if "login" in err.lower():
                    err = "qodercli 未登录，请先运行 qoder_login.bat 登录。" + err
                raise RuntimeError(err[-500:] or "qodercli 意外退出")
            try:
                m = json.loads(line)
            except ValueError:
                continue
            if m.get("type") == "system" and m.get("subtype") == "model_queue_status":
                self.queue = m
                if m.get("status") == "queued":
                    log.info("Qoder 排队中：模型 %s，服务%s，已排队 %.0f 秒",
                             m.get("model_key") or "-", "可用" if m.get("service_available") else "繁忙",
                             float(m.get("queue_wait_elapsed_ms") or 0) / 1000)
                continue
            if m.get("type") == "result":
                if m.get("subtype") != "success" or m.get("is_error"):
                    raise RuntimeError(f"Qoder 返回错误：{m.get('subtype')} {m.get('errors') or m.get('result')}")
                self.last_usage = norm_usage(m.get("usage")) or sum_model_usage(m.get("modelUsage"))
                return m.get("result") or ""


class _ApiError(RuntimeError):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


class OpenAIChat:
    def __init__(self):
        self.history = collections.deque(maxlen=16)
        self.last_usage = None
        self._fallback_key = None  # 已知某接口不支持 Responses 时，本次运行直接用 Chat

    @staticmethod
    async def list_models(cfg_ai):
        base = cfg_ai["openai_base"].rstrip("/")
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{base}/models", headers={"Authorization": f"Bearer {cfg_ai['openai_key']}"},
                             timeout=aiohttp.ClientTimeout(total=15)) as r:
                d = await r.json(content_type=None)
                if r.status != 200:
                    raise RuntimeError(f"API 错误 {r.status}: {str(d)[:300]}")
        return sorted(m["id"] for m in d.get("data", []) if m.get("id"))

    @staticmethod
    def mode_of(cfg_ai):
        mode = str(cfg_ai.get("openai_mode") or "responses").strip().lower()
        return mode if mode in ("responses", "chat") else "responses"

    @staticmethod
    def _payload(cfg_ai, mode, msgs, max_tokens):
        level = thinking_level(cfg_ai)
        if mode == "chat":
            body = {"model": cfg_ai["openai_model"], "messages": msgs,
                    "temperature": 0.9, "max_tokens": max_tokens}
            if level in _THINKING_BUDGET:
                body["reasoning_effort"] = level
            elif level == "off":
                body["reasoning_effort"] = "minimal"
            return body
        system = next((m["content"] for m in msgs if m.get("role") == "system"), "")
        # Responses 的推理模型只接受默认 temperature，这里干脆不传；输出上限给推理留点余量
        body = {"model": cfg_ai["openai_model"], "instructions": system,
                "input": [m for m in msgs if m.get("role") != "system"],
                "max_output_tokens": max(max_tokens, 256)}
        if level in _THINKING_BUDGET:
            body["reasoning"] = {"effort": level}
        elif level == "off":
            body["reasoning"] = {"effort": "minimal"}
        return body

    @staticmethod
    def _extract(mode, d):
        if mode == "chat":
            try:
                return d["choices"][0]["message"]["content"] or ""
            except (KeyError, IndexError, TypeError):
                raise RuntimeError(f"接口返回格式不对：{str(d)[:200]}")
        text = d.get("output_text")
        if isinstance(text, str) and text.strip():
            return text
        parts = []
        for item in d.get("output") or []:
            for c in item.get("content") or []:
                if c.get("type") in ("output_text", "text") and c.get("text"):
                    parts.append(c["text"])
        return "".join(parts).strip()

    async def _send(self, cfg_ai, mode, body, timeout=None):
        base = cfg_ai["openai_base"].rstrip("/")
        url = f"{base}/{'chat/completions' if mode == 'chat' else 'responses'}"
        total = float(timeout or cfg_ai.get("timeout", 30))
        label = "Chat Completions" if mode == "chat" else "Responses"
        model = cfg_ai.get("openai_model") or "未填模型名"
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(url, headers={"Authorization": f"Bearer {cfg_ai['openai_key']}"},
                                  json=body, timeout=aiohttp.ClientTimeout(total=total)) as r:
                    raw = await r.text()
                    if r.status == 200:
                        try:
                            return json.loads(raw)
                        except ValueError:
                            raise RuntimeError(f"接口返回的不是 JSON（{label}）：{raw[:200]}")
                    raise _ApiError(r.status, f"HTTP {r.status}（{label}，{url}，模型 {model}）：{raw[:300]}")
        except (RuntimeError, _ApiError):
            raise
        except asyncio.TimeoutError:
            raise RuntimeError(
                f"{label} 请求超时（{total:g} 秒）：{url}，模型 {model}。"
                f"接口排队或网络太慢，可在“AI 设置→超时秒数”调大，或先点“测试接口”看是否连得通") from None
        except aiohttp.ClientConnectorError as e:
            raise RuntimeError(
                f"连不上接口 {url}：{e}。检查地址是否要带 /v1、域名/DNS、代理或防火墙") from None
        except aiohttp.ClientError as e:
            raise RuntimeError(f"{type(e).__name__}：{e}（{url}）") from None
        except OSError as e:
            raise RuntimeError(f"{type(e).__name__}：{e}（{url}）") from None

    async def _ask_chat(self, cfg_ai, msgs, max_tokens, timeout=None):
        body = self._payload(cfg_ai, "chat", msgs, max_tokens)
        for attempt in (0, 1):
            try:
                return await self._send(cfg_ai, "chat", body, timeout)
            except _ApiError as e:
                # 有些 OpenAI 兼容服务不认 reasoning_effort：去掉再试一次，别把回复搞挂
                if (attempt == 0 and "reasoning_effort" in body and e.status in (400, 422)
                        and "reasoning" in str(e).lower()):
                    log.warning("该接口不支持 reasoning_effort，已去掉后重试：%s", str(e)[:160])
                    body.pop("reasoning_effort", None)
                    continue
                raise

    @staticmethod
    def _responses_unsupported(e):
        msg = str(e).lower()
        if e.status in (404, 405):
            return True
        if e.status in (400, 422):
            return any(k in msg for k in ("responses", "not supported", "unsupported",
                                          "unknown", "not found", "invalid url",
                                          "instructions", "max_output_tokens"))
        return False

    async def ask(self, cfg_ai, system_prompt, user_text, use_history=True, max_tokens=200):
        base = cfg_ai["openai_base"].rstrip("/")
        history = self.history if use_history else []
        msgs = [{"role": "system", "content": system_prompt}, *history, {"role": "user", "content": user_text}]
        mode = self.mode_of(cfg_ai)
        key = (base, cfg_ai.get("openai_model"))
        used = mode
        if mode == "chat" or self._fallback_key == key:
            used = "chat"
            d = await self._ask_chat(cfg_ai, msgs, max_tokens)
        else:
            try:
                d = await self._send(cfg_ai, "responses", self._payload(cfg_ai, "responses", msgs, max_tokens))
            except _ApiError as e:
                if not self._responses_unsupported(e):
                    raise
                self._fallback_key = key
                log.warning("接口不支持 Responses，已自动改用 Chat Completions：%s", str(e)[:160])
                used = "chat"
                d = await self._ask_chat(cfg_ai, msgs, max_tokens)
        text = self._extract(used, d)
        self.last_usage = norm_usage(d.get("usage"))
        if use_history:
            self.history.extend([{"role": "user", "content": user_text}, {"role": "assistant", "content": text}])
        return text

    async def probe(self, cfg_ai, mode, timeout=15):
        """发一个很小的请求，只测接口模式通不通；不带历史、不带思考程度。"""
        msgs = [{"role": "system", "content": "You are a health check. Reply with OK only."},
                {"role": "user", "content": "ping"}]
        cfg2 = dict(cfg_ai, thinking="default")
        if mode == "chat":
            d = await self._ask_chat(cfg2, msgs, 8, timeout=timeout)
        else:
            d = await self._send(cfg2, "responses",
                                 self._payload(cfg2, "responses", msgs, 8), timeout=timeout)
        return self._extract(mode, d)


CLI_PRESETS = {
    "workbuddy": {
        "label": "WorkBuddy（CodeBuddy Code）",
        "exe": r"D:\workbuddya\WorkBuddy.exe",
        "args": [r"D:\workbuddya\resources\app.asar.unpacked\cli\dist\codebuddy-lite-wb.mjs",
                 "-p", "{prompt}", "--output-format", "json", "--tools", ""],
        "env": "ELECTRON_RUN_AS_NODE=1",
        "json_field": "result",
        "login_args": [r"D:\workbuddya\resources\app.asar.unpacked\cli\dist\codebuddy-lite-wb.mjs"],
        "models": ["auto", "glm-5.1", "glm-5.0-turbo", "glm-5.0", "glm-4.7", "glm-4.6",
                   "kimi-k2.5", "minimax-m2.7", "deepseek-v3-2-volc"],
        "hint": "第一次用要先在 CLI 里登录一次（点“登录 / 打开 CLI”）；登录信息存在 ~/.codebuddy。",
    },
    "zcode": {
        "label": "ZCode（Z.ai，实验）",
        "exe": r"S:\zcode\ZCode.exe",
        "args": [],
        "env": "ELECTRON_RUN_AS_NODE=1",
        "json_field": "",
        "login_args": ["login"],
        "models": ["GLM-5.3", "GLM-5.1", "GLM-4.7", "GLM-4.7-Flash", "GLM-4.6"],
        "hint": "ZCode 自带的 CLI 是应用内部用的，需要应用注入 provider 配置和模型选择，"
                "目前只能当作实验项；建议改用它的 API Key（OpenAI 兼容）或在 ZCode 里手动配置后再试。",
    },
}


def _parse_env(text):
    out = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _json_field(data, path):
    cur = data
    for part in [p for p in (path or "").split(".") if p]:
        if isinstance(cur, list):
            cur = cur[-1] if cur else None
        cur = cur.get(part) if isinstance(cur, dict) else None
    return cur


class CLIChat:
    """调用任意“-p 单次问答”的外部 CLI（WorkBuddy / ZCode / 自备命令）。"""

    def __init__(self):
        self.workdir = os.path.join(BASE_DIR, "cli_workdir")
        self.last_usage = None

    async def ask(self, cfg_ai, cfg_cli, user_text):
        self.last_usage = None
        exe = (cfg_cli.get("exe") or "").strip().strip('"')
        if not exe or not os.path.exists(exe):
            raise RuntimeError(f"找不到 CLI 程序：{exe or '（未设置）'}")
        raw_args = cfg_cli.get("args") or []
        args = [str(a).replace("{prompt}", user_text) for a in raw_args]
        if not any("{prompt}" in str(a) for a in raw_args):
            args.append(user_text)
        cwd = (cfg_cli.get("cwd") or "").strip() or self.workdir
        os.makedirs(cwd, exist_ok=True)
        env = procutil.clean_env(_parse_env(cfg_cli.get("env")))
        proc = await asyncio.create_subprocess_exec(
            exe, *args, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, cwd=cwd, env=env, creationflags=procutil.CREATE_NO_WINDOW)
        try:
            out, err = await asyncio.wait_for(proc.communicate(), float(cfg_cli.get("timeout", 90)))
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(f"CLI 超时（{cfg_cli.get('timeout', 90)} 秒）")
        stdout = out.decode("utf-8", "replace").strip()
        stderr = err.decode("utf-8", "replace").strip()
        if "Authentication required" in stdout + stderr or "Please use /login" in stdout + stderr:
            raise RuntimeError("CLI 未登录，请先运行一次登录（AI 设置 → 登录 / 打开 CLI）")
        if proc.returncode != 0 and not stdout:
            raise RuntimeError(f"CLI 退出码 {proc.returncode}：{stderr[-300:]}")
        field = (cfg_cli.get("json_field") or "").strip()
        if field:
            text = ""
            for line in reversed(stdout.splitlines()):
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    data = json.loads(line)
                except ValueError:
                    continue
                self.last_usage = norm_usage(data.get("usage")) or self.last_usage
                val = _json_field(data, field)
                if isinstance(val, str) and val.strip():
                    text = val.strip()
                    break
            if not text:
                raise RuntimeError(f"CLI 输出里没有字段 {field}：{stdout[-300:] or stderr[-300:]}")
            return text
        lines = [l for l in stdout.splitlines() if l.strip()]
        if not lines:
            raise RuntimeError(f"CLI 没有输出：{stderr[-300:]}")
        return "\n".join(lines)


class ZcodeProxyChat:
    """通过 bonus-plan 本地代理使用 ZCode 客户端套餐（Anthropic 协议）。"""

    def __init__(self):
        self.proc = None
        self.last_usage = None

    @staticmethod
    def _discovery_files():
        base = os.path.join(os.path.expanduser("~"), ".zcode", "cli", "plugins", "data", "zcode-bonus-plan")
        return [os.path.join(base, "proxy.json")]

    def _token(self):
        for p in self._discovery_files():
            try:
                with open(p, encoding="utf-8") as f:
                    d = json.load(f)
                return d.get("token", "")
            except (OSError, ValueError):
                continue
        return ""

    async def alive(self, url):
        try:
            async with aiohttp.ClientSession(trust_env=False) as s:
                async with s.get(url.rstrip("/") + "/ui", timeout=aiohttp.ClientTimeout(total=2)) as r:
                    return r.status < 500
        except Exception:
            return False

    async def ensure(self, cfg_zc, on_status):
        url = cfg_zc["proxy_url"]
        if await self.alive(url):
            return True
        if not cfg_zc.get("autostart", True):
            return False
        plugin = cfg_zc.get("plugin_dir", "")
        node = cfg_zc.get("node_exe", "node")
        entry = os.path.join(plugin, "plugin.mjs")
        if not (plugin and node and os.path.exists(entry)):
            on_status("ZCode 代理未运行，且找不到插件目录（AI 设置 → ZCode 客户端额度）")
            return False
        env = procutil.clean_env()
        try:
            self.proc = await asyncio.create_subprocess_exec(
                node, "plugin.mjs", "--proxy-only", cwd=plugin, env=env,
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL, creationflags=procutil.CREATE_NO_WINDOW)
            procutil.bind_to_app(self.proc.pid)
        except Exception as e:
            on_status(f"启动 ZCode 代理失败：{e}")
            return False
        for _ in range(40):
            await asyncio.sleep(0.5)
            if await self.alive(url):
                on_status("ZCode 代理已就绪（客户端套餐额度）")
                return True
        on_status("ZCode 代理启动超时")
        return False

    async def ask(self, cfg, user_system, user_text):
        self.last_usage = None
        zc = cfg.get("zcode", {})
        url = zc.get("proxy_url", "").rstrip("/")
        token = self._token()
        if not token:
            raise RuntimeError("没有找到 ZCode 代理的 token（先让代理跑起来）")
        body = {"model": zc.get("model") or "GLM-5.3-Flash", "max_tokens": 500, "temperature": 0.9,
                "system": user_system,
                "messages": [{"role": "user", "content": user_text}]}
        level = thinking_level(cfg.get("ai") or {})
        if level == "off":
            body["thinking"] = {"type": "disabled"}
        elif level in _THINKING_BUDGET:
            body["thinking"] = {"type": "enabled", "budget_tokens": _THINKING_BUDGET[level]}
        headers = {"Authorization": f"Bearer {token}", "anthropic-version": "2023-06-01"}
        timeout = aiohttp.ClientTimeout(total=float(cfg["ai"].get("timeout", 60)))
        async with aiohttp.ClientSession(trust_env=False) as s:
            for attempt in (0, 1):
                async with s.post(url + "/v1/messages", json=body, headers=headers, timeout=timeout) as r:
                    raw = await r.text()
                    if r.status == 200:
                        d = json.loads(raw)
                        text = "".join(b.get("text", "") for b in d.get("content", [])
                                       if b.get("type") == "text").strip()
                        if not text:
                            raise RuntimeError("ZCode 返回空内容（可能额度用尽）")
                        self.last_usage = norm_usage(d.get("usage"))
                        return text
                    if (attempt == 0 and "thinking" in body and r.status in (400, 422)
                            and "thinking" in raw.lower()):
                        log.warning("ZCode 不支持 thinking 参数，已去掉后重试：%s", raw[:160])
                        body.pop("thinking", None)
                        continue
                    try:
                        err = json.loads(raw).get("error", {})
                        msg = err.get("message") or raw[:200]
                    except ValueError:
                        msg = raw[:200]
                    raise RuntimeError(f"ZCode 代理：{msg}")


class _SafeDict(dict):
    def __missing__(self, key):
        return ""


def fill(template, ev):
    return template.format_map(_SafeDict(ev))


_EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]")
_BRACKETS = re.compile(r"[（(【\[〔*][^）)】\]〕*]{0,20}[）)】\]〕*]")


def clean_reply(text, max_chars):
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    text = _EMOJI.sub("", text)
    text = _BRACKETS.sub("", text)
    text = re.sub(r"[\"“”'‘’「」『』#*_`>|]", "", text)
    text = re.sub(r"[~～]+", "！", text)
    text = re.sub(r"\s*\n\s*", "，", text.strip())
    text = re.sub(r"[ \t\u3000]+", " ", text)
    text = re.sub(r"[，,]{2,}", "，", text).strip("，, ")
    limit = int(max_chars * 1.5) + 5
    if len(text) > limit:
        cut = max(text.rfind(p, 0, limit) for p in "。！？!?；")
        text = text[:cut + 1] if cut > 5 else text[:limit]
    return text


GAME_SYSTEM = (
    "你是B站直播间的游戏主持人，同时扮演虚拟主播，说话活泼自然、口语化。"
    "严格按用户要求的格式输出纯文本，不要 Markdown、代码块、表情符号或额外解释。"
)


class Brain:
    def __init__(self):
        self.qoder = QoderSession()
        self.qoder_game = QoderSession()
        self.openai = OpenAIChat()
        self.cli = CLIChat()
        self.zcode = ZcodeProxyChat()
        # 本场累计用量（会话内，不落盘）
        self.usage = {"prompt": 0, "completion": 0, "total": 0, "calls": 0, "est_calls": 0}

    def _acc_usage(self, usage, prompt_chars, reply_chars):
        self.usage["calls"] += 1
        if usage:
            self.usage["prompt"] += usage["prompt"]
            self.usage["completion"] += usage["completion"]
            self.usage["total"] += usage["total"]
            return
        # 后端没给用量：按字数估算（中文大约 1.5 字/token），界面上会标 ≈
        p = max(1, int(prompt_chars / 1.5))
        c = max(1, int(reply_chars / 1.5))
        self.usage["prompt"] += p
        self.usage["completion"] += c
        self.usage["total"] += p + c
        self.usage["est_calls"] += 1

    @staticmethod
    def emotion_names(cfg):
        l2d = cfg.get("live2d", {})
        if not l2d.get("enabled"):
            return []
        return [e["name"] for e in l2d.get("emotions", []) if e.get("name")]

    def system_prompt(self, cfg):
        cfg_ai = cfg["ai"]
        sp = cfg_ai.get("persona", "") + RULES.format(max_chars=cfg_ai.get("max_chars", 40))
        names = self.emotion_names(cfg)
        if names:
            sp += ("\n【表情】在回复的最开头用【】标出你说这句话时的表情，只能从这些里选一个："
                   + "、".join(names) + "。例如：【开心】欢迎欢迎！表情标签不算字数。")
        return sp

    async def ai(self, cfg, prompt):
        """返回 (文本, 表情名或空)。"""
        cfg_ai = cfg["ai"]
        sp = self.system_prompt(cfg)
        backend = cfg_ai.get("backend")
        if backend == "openai":
            obj = self.openai
            raw = await obj.ask(cfg_ai, sp, prompt)
        elif backend == "cli":
            obj = self.cli
            raw = await obj.ask(cfg_ai, cfg.get("cli", {}), sp + "\n\n" + prompt)
        elif backend == "zcode":
            obj = self.zcode
            raw = await obj.ask(cfg, sp, prompt)
        else:
            obj = self.qoder
            raw = await obj.ask(cfg_ai, sp, prompt)
        self._acc_usage(obj.last_usage, len(sp) + len(prompt), len(raw or ""))
        raw = re.sub(r"<think>.*?</think>", "", raw or "", flags=re.S).strip()
        emotion = ""
        m = re.match(r"^\s*[【\[]([^】\]]{1,8})[】\]]", raw)
        if m:
            emotion = m.group(1).strip()
            raw = raw[m.end():]
        if emotion not in self.emotion_names(cfg):
            emotion = ""
        return clean_reply(raw, int(cfg_ai.get("max_chars", 40))), emotion

    async def raw(self, cfg, prompt, timeout=60.0):
        """给游戏生成内容：不套主播人设、不做口语清洗，保留 AI 的原始分行格式。"""
        cfg_ai = cfg["ai"]
        ai = {**cfg_ai, "timeout": max(float(cfg_ai.get("timeout", 30)), timeout)}
        backend = ai.get("backend", "qoder")
        if backend == "openai":
            obj = self.openai
            raw = await obj.ask(ai, GAME_SYSTEM, prompt, use_history=False, max_tokens=400)
        elif backend == "cli":
            obj = self.cli
            raw = await obj.ask(ai, cfg.get("cli", {}), GAME_SYSTEM + "\n\n" + prompt)
        elif backend == "zcode":
            obj = self.zcode
            raw = await obj.ask(cfg, GAME_SYSTEM, prompt)
        else:
            obj = self.qoder_game
            raw = await obj.ask(ai, GAME_SYSTEM, prompt)
        self._acc_usage(obj.last_usage, len(GAME_SYSTEM) + len(prompt), len(raw or ""))
        return re.sub(r"<think>.*?</think>", "", raw or "", flags=re.S).strip()

    async def reply(self, cfg, ev_cfg, ev):
        """返回 (文本, 来源, 表情)。AI 失败时自动退回模板。"""
        lines = [l.strip() for l in ev_cfg.get("templates", "").splitlines() if l.strip()]
        template_text = fill(random.choice(lines), ev) if lines else ""
        if ev_cfg.get("mode") == "ai":
            try:
                text, emotion = await self.ai(cfg, fill(ev_cfg.get("ai_prompt", ""), ev))
                if text:
                    if ev["type"] == "danmaku" and ev_cfg.get("read_original"):
                        text = f"{ev['name']}说：{ev['text']}。{text}"
                    return text, "AI", emotion
            except Exception as e:
                reason = err_text(e, 260)
                log.warning("AI 生成失败，改用模板：%s", reason)
                return template_text, f"模板(AI失败:{reason})", ""
        return template_text, "模板", ""

    async def warm(self, cfg):
        if cfg["ai"].get("backend") == "qoder":
            try:
                await self.qoder.warm(cfg["ai"], self.system_prompt(cfg))
            except Exception as e:
                log.warning("Qoder 预热失败：%s", err_text(e))

    async def close(self):
        await self.qoder.close()
        await self.qoder_game.close()
