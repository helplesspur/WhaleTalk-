"""用鲸语的音色批量合成语音（给剪辑、视频 AI、其他脚本用）。

两种用法：
  1) 直接读软件目录的 config.json（最省事，用你在界面里配好的音色）
       python tools/tts_cli.py --file lines.txt --out voice
  2) 手动指定模型和参考音频
       python tools/tts_cli.py --gsv-dir <GPT-SoVITS目录> --gpt <ckpt> --sovits <pth> \
           --ref <参考音频.wav> --ref-text "参考音频里的文字" --file lines.txt --out voice

lines.txt 每行一句，空行忽略；输出 01_xxx.wav、02_xxx.wav……（--mp3 会额外转 mp3）。
引擎没在跑会自动启动（--no-start 可关闭）。
"""
import argparse
import asyncio
import os
import re
import subprocess
import sys
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402
from tts import GsvEngine  # noqa: E402


def slug(text):
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "_", text).strip("_")
    return s[:18] or "line"


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="*", help="直接给一句或多句文本")
    ap.add_argument("--file", help="文本文件，每行一句")
    ap.add_argument("--out", default="voice", help="输出目录")
    ap.add_argument("--config", default=os.path.join(config.BASE_DIR, "config.json"))
    ap.add_argument("--gsv-dir")
    ap.add_argument("--gpt")
    ap.add_argument("--sovits")
    ap.add_argument("--ref")
    ap.add_argument("--ref-text")
    ap.add_argument("--ref-lang", default="zh")
    ap.add_argument("--lang", default="zh")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--steps", type=int, default=32)
    ap.add_argument("--prefix", default="")
    ap.add_argument("--mp3", action="store_true", help="同时转成 mp3")
    ap.add_argument("--no-start", action="store_true", help="引擎没启动时不自动启动")
    a = ap.parse_args()

    cfg = config.load() if os.path.exists(a.config) else dict(config.DEFAULTS)
    tts = cfg["tts"]
    if a.gsv_dir:
        tts["gsv_dir"] = a.gsv_dir
    tts.update({k: v for k, v in {"gpt_weights": a.gpt, "sovits_weights": a.sovits,
                                  "ref_audio": a.ref, "ref_text": a.ref_text,
                                  "ref_lang": a.ref_lang, "speed": a.speed,
                                  "sample_steps": a.steps}.items() if v})
    if not tts.get("gsv_dir"):
        sys.exit("没有 GPT-SoVITS 目录：用 --gsv-dir 指定，或在软件里设置后重试")
    if not tts.get("ref_audio") or not os.path.exists(tts["ref_audio"]):
        sys.exit(f"参考音频不存在：{tts.get('ref_audio')!r}（用 --ref 指定）")

    lines = list(a.text)
    if a.file:
        with open(a.file, encoding="utf-8") as f:
            lines += [l.strip() for l in f if l.strip()]
    if not lines:
        sys.exit("没有要合成的文本")

    eng = GsvEngine()
    if not a.no_start and await eng.start(tts, lambda m: print("[引擎]", m, flush=True)) is False:
        sys.exit("引擎启动失败")

    os.makedirs(a.out, exist_ok=True)
    for i, text in enumerate(lines, 1):
        pcm, sr = await eng.synth(tts, text)
        name = f"{a.prefix}{i:02d}_{slug(text)}.wav"
        path = os.path.join(a.out, name)
        with wave.open(path, "wb") as w:
            w.setnchannels(pcm.shape[1])
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(pcm.astype("int16").tobytes())
        dur = len(pcm) / sr
        print(f"{name}  {dur:.2f}s", flush=True)
        if a.mp3:
            ff = os.path.join(tts["gsv_dir"], "runtime", "ffmpeg.exe")
            if os.path.exists(ff):
                subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y", "-i", path,
                                "-b:a", "192k", path[:-4] + ".mp3"], check=False)


asyncio.run(main())
