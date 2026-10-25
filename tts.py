import asyncio
import glob
import io
import logging
import os
import subprocess
import threading
import time
import wave

import aiohttp
import numpy as np
import sounddevice as sd

import procutil
from config import LOG_DIR

log = logging.getLogger("tts")

PRETRAINED_GPT = [
    "GPT_SoVITS/pretrained_models/s1v3.ckpt",
    "GPT_SoVITS/pretrained_models/gsv-v2final-pretrained/s1bert25hz-5kh-longer-epoch=12-step=369668.ckpt",
    "GPT_SoVITS/pretrained_models/s1bert25hz-2kh-longer-epoch=68e-step=50232.ckpt",
]
PRETRAINED_SOVITS = [
    "GPT_SoVITS/pretrained_models/v2Pro/s2Gv2Pro.pth",
    "GPT_SoVITS/pretrained_models/v2Pro/s2Gv2ProPlus.pth",
    "GPT_SoVITS/pretrained_models/gsv-v2final-pretrained/s2G2333k.pth",
    "GPT_SoVITS/pretrained_models/s2Gv3.pth",
    "GPT_SoVITS/pretrained_models/gsv-v4-pretrained/s2Gv4.pth",
]


def _abs(gsv_dir, p):
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(gsv_dir, p))


ENV_FPS = 30


def envelope(pcm, sr):
    """口型用的音量包络：每秒 30 帧，0~1。"""
    x = np.abs(pcm[:, 0].astype(np.float32))
    hop = max(1, sr // ENV_FPS)
    n = len(x) // hop
    if n == 0:
        return []
    e = x[: n * hop].reshape(n, hop).mean(axis=1)
    ref = float(np.percentile(e, 95)) or 1.0
    return [round(float(v), 2) for v in np.clip(e / ref, 0, 1)]


class GsvEngine:
    def __init__(self):
        self.proc = None
        self.applied = (None, None)
        self.lock = asyncio.Lock()
        self.log_path = os.path.join(LOG_DIR, "gsv_engine.log")

    @staticmethod
    def _session():
        return aiohttp.ClientSession(trust_env=False)

    async def alive(self, url):
        """True=在线, False=连不上, None=有监听但忙（合成中会阻塞 /control）。"""
        try:
            async with self._session() as s:
                async with s.get(url.rstrip("/") + "/control", timeout=aiohttp.ClientTimeout(total=3)):
                    return True
        except asyncio.TimeoutError:
            return None
        except Exception:
            self.applied = (None, None)
            return False

    def list_weights(self, gsv_dir):
        gpt, sovits = [], []
        for p in PRETRAINED_GPT:
            if os.path.exists(_abs(gsv_dir, p)):
                gpt.append(p)
        for p in PRETRAINED_SOVITS:
            if os.path.exists(_abs(gsv_dir, p)):
                sovits.append(p)
        for d in sorted(glob.glob(os.path.join(gsv_dir, "GPT_weights*"))):
            gpt += [os.path.relpath(f, gsv_dir).replace("\\", "/") for f in sorted(glob.glob(os.path.join(d, "*.ckpt")))]
        for d in sorted(glob.glob(os.path.join(gsv_dir, "SoVITS_weights*"))):
            sovits += [os.path.relpath(f, gsv_dir).replace("\\", "/") for f in sorted(glob.glob(os.path.join(d, "*.pth")))]
        return gpt, sovits

    async def start(self, cfg_tts, on_status):
        url = cfg_tts["api_url"]
        if await self.alive(url) is not False:
            return True
        gsv = cfg_tts["gsv_dir"]
        if not gsv:
            on_status("还没有设置 GPT-SoVITS 目录：请在【语音设置】里选择 GPT-SoVITS 所在的文件夹")
            return False
        py = os.path.join(gsv, "runtime", "python.exe")
        if not os.path.exists(py) or not os.path.exists(os.path.join(gsv, "api_v2.py")):
            on_status(f"GPT-SoVITS 目录无效：{gsv}")
            return False
        if self.proc is None or self.proc.poll() is not None:
            hostport = url.split("://", 1)[-1].rstrip("/")
            host, _, port = hostport.partition(":")
            os.makedirs(LOG_DIR, exist_ok=True)
            logf = open(self.log_path, "w", encoding="utf-8")
            env = procutil.clean_env({"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "NO_PROXY": "*"})
            self.proc = subprocess.Popen(
                [py, "api_v2.py", "-a", host or "127.0.0.1", "-p", port or "9880",
                 "-c", "GPT_SoVITS/configs/tts_infer.yaml"],
                cwd=gsv, stdout=logf, stderr=subprocess.STDOUT, env=env,
                creationflags=procutil.CREATE_NO_WINDOW)
            logf.close()
            if cfg_tts.get("stop_on_exit", True):
                procutil.bind_to_app(self.proc.pid)
            on_status("正在启动 GPT-SoVITS 引擎（首次约 20~60 秒）…")
        for _ in range(180):
            await asyncio.sleep(1)
            if self.proc and self.proc.poll() is not None:
                on_status("GPT-SoVITS 引擎启动失败，请查看 logs/gsv_engine.log")
                return False
            if await self.alive(url):
                on_status("GPT-SoVITS 引擎已就绪")
                return True
        on_status("GPT-SoVITS 引擎启动超时")
        return False

    def stop(self):
        if self.proc and self.proc.poll() is None:
            procutil.kill_tree(self.proc.pid)
        self.proc = None
        self.applied = (None, None)

    def tail_log(self, n=60):
        try:
            with open(self.log_path, "r", encoding="utf-8", errors="replace") as f:
                return "".join(f.readlines()[-n:])
        except OSError:
            return ""

    async def _apply_weights(self, s, cfg_tts):
        want = (cfg_tts["gpt_weights"], cfg_tts["sovits_weights"])
        if want == self.applied:
            return
        base = cfg_tts["api_url"].rstrip("/")
        gsv = cfg_tts["gsv_dir"]
        for ep, path in (("set_gpt_weights", want[0]), ("set_sovits_weights", want[1])):
            if not path:
                continue
            async with s.get(f"{base}/{ep}", params={"weights_path": _abs(gsv, path)},
                             timeout=aiohttp.ClientTimeout(total=120)) as r:
                if r.status != 200:
                    raise RuntimeError(f"切换权重失败 {ep}: {(await r.text())[:200]}")
        self.applied = want

    async def synth(self, cfg_tts, text):
        ref = cfg_tts.get("ref_audio", "").strip().strip('"')
        if not ref or not os.path.exists(ref):
            raise RuntimeError("还没有设置参考音频（语音设置 → 参考音频）")
        body = {
            "text": text, "text_lang": cfg_tts.get("text_lang", "zh"),
            "ref_audio_path": os.path.abspath(ref), "prompt_text": cfg_tts.get("ref_text", ""),
            "prompt_lang": cfg_tts.get("ref_lang", "zh"), "text_split_method": "cut5",
            "batch_size": 1, "media_type": "wav", "streaming_mode": False,
            "speed_factor": float(cfg_tts.get("speed", 1.0)), "temperature": float(cfg_tts.get("temperature", 1.0)),
            "top_k": int(cfg_tts.get("top_k", 15)), "top_p": float(cfg_tts.get("top_p", 1.0)),
            "sample_steps": int(cfg_tts.get("sample_steps", 32)), "repetition_penalty": 1.35,
        }
        async with self.lock:
            async with self._session() as s:
                await self._apply_weights(s, cfg_tts)
                async with s.post(cfg_tts["api_url"].rstrip("/") + "/tts", json=body,
                                  timeout=aiohttp.ClientTimeout(total=180)) as r:
                    data = await r.read()
                    if r.status != 200:
                        raise RuntimeError(f"合成失败 HTTP {r.status}: {data[:300].decode('utf-8', 'replace')}")
        with wave.open(io.BytesIO(data)) as w:
            sr, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
            raw = w.readframes(w.getnframes())
        if sw != 2:
            raise RuntimeError(f"不支持的采样位宽 {sw}")
        pcm = np.frombuffer(raw, dtype=np.int16).reshape(-1, ch)
        return pcm, sr


def _resample(x, sr_from, sr_to):
    """x: (n, ch)。线性插值重采样，语音/音乐够用。"""
    if sr_from == sr_to or len(x) == 0:
        return x
    n = int(round(len(x) * sr_to / sr_from))
    src = np.arange(len(x), dtype=np.float64)
    dst = np.linspace(0, len(x) - 1, n)
    return np.stack([np.interp(dst, src, x[:, c]) for c in range(x.shape[1])], axis=1).astype(x.dtype)


def _stereo(x):
    return np.repeat(x, 2, axis=1) if x.shape[1] == 1 else x[:, :2]


class Player:
    """单路输出混音器：一条常驻音频流，同时放背景音乐和语音；说话时自动压低音乐。"""

    def __init__(self):
        self.lock = threading.Lock()
        self.open_lock = threading.Lock()
        self.stream = None
        self.dev_name = None
        self.sr = 48000
        self.voice = None
        self.vpos = 0
        self.voice_vol = 0.8
        self.voice_done = threading.Event()
        self.voice_done.set()
        self._abort = threading.Event()
        self.music = None
        self.mpos = 0
        self.music_paused = False
        self.music_vol = 0.6
        self.duck = 0.3
        self.mgain = 1.0
        self.on_music_end = None

    @staticmethod
    def devices():
        out = []
        apis = sd.query_hostapis()
        for d in sd.query_devices():
            if d["max_output_channels"] > 0:
                out.append(f"{d['name']} [{apis[d['hostapi']]['name']}]")
        return out

    @staticmethod
    def _resolve(name):
        if not name:
            return None
        apis = sd.query_hostapis()
        for i, d in enumerate(sd.query_devices()):
            if d["max_output_channels"] > 0 and f"{d['name']} [{apis[d['hostapi']]['name']}]" == name:
                return i
        return None

    def ensure(self, device_name):
        with self.open_lock:
            self._ensure(device_name)

    def _ensure(self, device_name):
        with self.lock:
            if self.stream is not None and self.stream.active and device_name == self.dev_name:
                return
        if self.stream is not None:
            try:
                self.stream.close()
            except Exception:
                pass
            self.stream = None
        idx = self._resolve(device_name)
        info = sd.query_devices(idx) if idx is not None else sd.query_devices(kind="output")
        sr = int(info["default_samplerate"]) or 48000
        with self.lock:
            if sr != self.sr:
                if self.music is not None:
                    pos = self.mpos
                    self.music = _resample(self.music, self.sr, sr)
                    self.mpos = int(pos * sr / self.sr)
                if self.voice is not None:
                    self.voice = None
                    self.voice_done.set()
            self.sr = sr
        self.stream = sd.OutputStream(samplerate=sr, channels=2, dtype="float32", device=idx,
                                      callback=self._callback, latency="high")
        self.stream.start()
        self.dev_name = device_name

    def _callback(self, outdata, frames, _time, _status):
        out = np.zeros((frames, 2), np.float32)
        ended = None
        with self.lock:
            target = self.duck if self.voice is not None else 1.0
            g0 = self.mgain
            g1 = g0 + (target - g0) * min(1.0, frames / (self.sr * 0.25))
            if self.music is not None and not self.music_paused:
                n = min(frames, len(self.music) - self.mpos)
                ramp = np.linspace(g0, g1, n, dtype=np.float32)[:, None]
                out[:n] += self.music[self.mpos:self.mpos + n].astype(np.float32) * (ramp * (self.music_vol / 32768.0))
                self.mpos += n
                if self.mpos >= len(self.music):
                    self.music = None
                    ended, self.on_music_end = self.on_music_end, None
            self.mgain = g1
            if self.voice is not None:
                n = min(frames, len(self.voice) - self.vpos)
                out[:n] += self.voice[self.vpos:self.vpos + n] * self.voice_vol
                self.vpos += n
                if self.vpos >= len(self.voice):
                    self.voice = None
                    self.voice_done.set()
        np.clip(out, -1, 1, out=out)
        outdata[:] = out
        if ended:
            ended()

    # ---------- 语音 ----------
    def play_blocking(self, pcm, sr, device_name, volume):
        self.ensure(device_name)
        data = _stereo(_resample(pcm.astype(np.float32) / 32768.0, sr, self.sr))
        self._abort.clear()
        with self.lock:
            self.voice, self.vpos = data, 0
            self.voice_vol = max(0, min(200, volume)) / 100.0
            self.voice_done.clear()
        while not self.voice_done.wait(0.05):
            if self._abort.is_set():
                with self.lock:
                    self.voice = None
                    self.voice_done.set()

    def skip(self):
        self._abort.set()

    @property
    def playing(self):
        return not self.voice_done.is_set()

    # ---------- 音乐 ----------
    def decode_music(self, data, device_name):
        import miniaudio
        self.ensure(device_name)
        sr = self.sr
        d = miniaudio.decode(data, output_format=miniaudio.SampleFormat.SIGNED16, nchannels=2, sample_rate=sr)
        return np.frombuffer(d.samples, dtype=np.int16).reshape(-1, 2), sr

    def play_music(self, pcm, sr, device_name, on_end):
        self.ensure(device_name)
        if sr != self.sr:
            pcm = _resample(pcm, sr, self.sr)
        with self.lock:
            self.music, self.mpos, self.music_paused = pcm, 0, False
            self.on_music_end = on_end

    def stop_music(self):
        with self.lock:
            self.music = None
            self.on_music_end = None

    def pause_music(self, paused):
        with self.lock:
            self.music_paused = paused

    def set_music(self, volume, duck):
        with self.lock:
            self.music_vol = max(0, min(150, volume)) / 100.0
            self.duck = max(0, min(100, duck)) / 100.0

    def music_progress(self):
        with self.lock:
            if self.music is None:
                return 0, 0
            return self.mpos / self.sr, len(self.music) / self.sr

    def close(self):
        if self.stream is not None:
            try:
                self.stream.close()
            except Exception:
                pass
            self.stream = None

