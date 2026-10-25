"""用 GPT-SoVITS 官方脚本微调 v2Pro 音色（复刻 webui 的一键三连 + SoVITS/GPT 训练）。

用法（在 GPT-SoVITS 根目录下，用它自带的 runtime\\python.exe 运行）：
    runtime\\python.exe <本文件> --name dfy --data D:\\DDL\\voice_data\\da-fei-yu-girl-voice-zh\\train
data 目录里需要 metadata.csv（file_name,text 两列）和对应音频。
"""
import argparse
import csv
import json
import os
import subprocess
import sys
import time

import yaml

ap = argparse.ArgumentParser()
ap.add_argument("--name", required=True)
ap.add_argument("--data", required=True)
ap.add_argument("--lang", default="zh")
ap.add_argument("--version", default="v2Pro")
ap.add_argument("--sovits-epochs", type=int, default=10)
ap.add_argument("--gpt-epochs", type=int, default=15)
ap.add_argument("--batch", type=int, default=4)
args = ap.parse_args()

ROOT = os.getcwd()
PY = sys.executable
VER = args.version
EXP = f"logs/{args.name}"
TMP = os.path.join(ROOT, "TEMP")
os.makedirs(EXP, exist_ok=True)
os.makedirs(TMP, exist_ok=True)

BASE_ENV = dict(os.environ, version=VER, is_half="True", _CUDA_VISIBLE_DEVICES="0", i_part="0", all_parts="1",
                PYTHONIOENCODING="utf-8", PYTHONUTF8="1", no_proxy="localhost, 127.0.0.1, ::1", all_proxy="",
                TEMP=TMP, hz="25hz")


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def run(script, extra=None, args_=()):
    env = dict(BASE_ENV, **(extra or {}))
    log(f"运行 {script}")
    t = time.time()
    r = subprocess.run([PY, "-s", script, *args_], env=env, cwd=ROOT)
    if r.returncode != 0:
        log(f"失败：{script} 退出码 {r.returncode}")
        sys.exit(r.returncode)
    log(f"完成 {script}（{time.time() - t:.0f}s）")


# ---------- 0. 生成 .list ----------
audio_dir = None
lines = []
with open(os.path.join(args.data, "metadata.csv"), encoding="utf-8", newline="") as f:
    for row in csv.DictReader(f):
        p = os.path.normpath(os.path.join(args.data, row["file_name"]))
        audio_dir = os.path.dirname(p)
        text = row["text"].strip().replace("|", "，")
        if os.path.exists(p) and text:
            lines.append(f"{os.path.basename(p)}|{args.name}|{args.lang}|{text}")
list_path = os.path.join(EXP, f"{args.name}.list")
with open(list_path, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
log(f"{len(lines)} 条数据，音频目录 {audio_dir}")

common = {"inp_text": list_path, "inp_wav_dir": audio_dir, "exp_name": args.name, "opt_dir": EXP}

# ---------- 1a 文本/BERT ----------
if not os.path.exists(f"{EXP}/2-name2text.txt"):
    run("GPT_SoVITS/prepare_datasets/1-get-text.py",
        dict(common, bert_pretrained_dir="GPT_SoVITS/pretrained_models/chinese-roberta-wwm-ext-large"))
    os.replace(f"{EXP}/2-name2text-0.txt", f"{EXP}/2-name2text.txt")

# ---------- 1b HuBERT + 32k wav + 说话人向量 ----------
def _done(sub):
    d = f"{EXP}/{sub}"
    return os.path.isdir(d) and len(os.listdir(d)) >= len(lines)


if not _done("4-cnhubert"):
    run("GPT_SoVITS/prepare_datasets/2-get-hubert-wav32k.py",
        dict(common, cnhubert_base_dir="GPT_SoVITS/pretrained_models/chinese-hubert-base"))
if "Pro" in VER and not _done("7-sv_cn"):
    run("GPT_SoVITS/prepare_datasets/2-get-sv.py",
        dict(common, sv_path="GPT_SoVITS/pretrained_models/sv/pretrained_eres2netv2w24s4ep4.ckpt"))

# ---------- 1c 语义 token ----------
s2_cfg_file = f"GPT_SoVITS/configs/s2{VER}.json" if VER in ("v2Pro", "v2ProPlus") else "GPT_SoVITS/configs/s2.json"
pre_s2g = f"GPT_SoVITS/pretrained_models/v2Pro/s2G{VER}.pth"
if not os.path.exists(f"{EXP}/6-name2semantic.tsv"):
    run("GPT_SoVITS/prepare_datasets/3-get-semantic.py",
        dict(common, pretrained_s2G=pre_s2g, s2config_path=s2_cfg_file))
    with open(f"{EXP}/6-name2semantic-0.tsv", encoding="utf-8") as f:
        body = f.read().strip("\n")
    with open(f"{EXP}/6-name2semantic.tsv", "w", encoding="utf-8") as f:
        f.write("item_name\tsemantic_audio\n" + body + "\n")
    os.remove(f"{EXP}/6-name2semantic-0.tsv")

# ---------- 2. SoVITS ----------
with open(s2_cfg_file, encoding="utf-8") as f:
    s2 = json.load(f)
os.makedirs(f"{EXP}/logs_s2_{VER}", exist_ok=True)
s2["train"].update({
    "batch_size": args.batch, "epochs": args.sovits_epochs, "text_low_lr_rate": 0.4,
    "pretrained_s2G": pre_s2g, "pretrained_s2D": pre_s2g.replace("s2G", "s2D"),
    "if_save_latest": True, "if_save_every_weights": True, "save_every_epoch": args.sovits_epochs,
    "gpu_numbers": "0", "grad_ckpt": False, "lora_rank": 32,
})
s2["model"]["version"] = VER
s2["data"]["exp_dir"] = s2["s2_ckpt_dir"] = EXP
s2["save_weight_dir"] = f"SoVITS_weights_{VER}"
s2["name"] = args.name
s2["version"] = VER
s2_tmp = os.path.join(TMP, "tmp_s2.json")
with open(s2_tmp, "w", encoding="utf-8") as f:
    json.dump(s2, f)
run("GPT_SoVITS/s2_train.py", args_=("--config", s2_tmp))

# ---------- 3. GPT ----------
with open("GPT_SoVITS/configs/s1longer-v2.yaml", encoding="utf-8") as f:
    s1 = yaml.load(f, Loader=yaml.FullLoader)
os.makedirs(f"{EXP}/logs_s1", exist_ok=True)
s1["train"].update({
    "batch_size": args.batch, "epochs": args.gpt_epochs, "save_every_n_epoch": args.gpt_epochs,
    "if_save_every_weights": True, "if_save_latest": True, "if_dpo": False,
    "half_weights_save_dir": f"GPT_weights_{VER}", "exp_name": args.name,
})
s1["pretrained_s1"] = "GPT_SoVITS/pretrained_models/s1v3.ckpt"
s1["train_semantic_path"] = f"{EXP}/6-name2semantic.tsv"
s1["train_phoneme_path"] = f"{EXP}/2-name2text.txt"
s1["output_dir"] = f"{EXP}/logs_s1_{VER}"
s1_tmp = os.path.join(TMP, "tmp_s1.yaml")
with open(s1_tmp, "w", encoding="utf-8") as f:
    yaml.dump(s1, f, default_flow_style=False)
run("GPT_SoVITS/s1_train.py", args_=("--config_file", s1_tmp))

log("全部完成")
for d in (f"SoVITS_weights_{VER}", f"GPT_weights_{VER}"):
    for fn in sorted(os.listdir(d)):
        if fn.startswith(args.name):
            log(f"产出：{d}/{fn}")
