# 大肥鱼音色 · 交接说明（给另一个 AI / 剪辑用）

> 音色是**微调过的 GPT-SoVITS 模型**，不是某个云端音色 ID。
> 所以：能跑本机命令的 AI 才能用它合成；纯云端视频 AI（可灵 / 即梦 / Sora / Runway 等）**不能直接选它**，
> 要么先在本地合成再对轨，要么只能用它们自带的 TTS（那就不再是大肥鱼的声音）。

## 一、音色文件在哪

| 资产 | 路径 |
|---|---|
| GPT 模型（音色主干） | `D:\DDL\GPT-SoVITS-v2pro-20250604\GPT-SoVITS-v2pro-20250604\GPT_weights_v2Pro\dfy-e15.ckpt` |
| SoVITS 模型（音质/音高） | `D:\DDL\GPT-SoVITS-v2pro-20250604\GPT-SoVITS-v2pro-20250604\SoVITS_weights_v2Pro\dfy_e10_s560.pth` |
| 参考音频（6 秒） | `D:\DDL\voice_data\da-fei-yu-girl-voice-zh\train\audio\dwg_0031.wav` |
| 参考音频文本（必须一字不差） | `今天的海水温度刚刚好，特别适合一边摸鱼，一边认真工作。` |
| 训练数据（56 条，可重训） | `D:\DDL\voice_data\da-fei-yu-girl-voice-zh\train\`（`metadata.csv` + `audio\`） |
| GPT-SoVITS 引擎 | `D:\DDL\GPT-SoVITS-v2pro-20250604\GPT-SoVITS-v2pro-20250604\` |

> 鲸语软件里就是这三项：**语音设置 → GPT 模型 / SoVITS 模型 / 参考音频 + 参考音频文本**。
> 存在软件目录 `config.json` 的 `tts.gpt_weights`、`tts.sovits_weights`、`tts.ref_audio`、`tts.ref_text`。

## 二、三种用法

### 方式 A：命令行工具（推荐，任何 AI 都能调用）

```powershell
cd <鲸语源码目录>
.venv\Scripts\python tools\tts_cli.py ^
  --gsv-dir "D:\DDL\GPT-SoVITS-v2pro-20250604\GPT-SoVITS-v2pro-20250604" ^
  --gpt GPT_weights_v2Pro/dfy-e15.ckpt ^
  --sovits SoVITS_weights_v2Pro/dfy_e10_s560.pth ^
  --ref "D:\DDL\voice_data\da-fei-yu-girl-voice-zh\train\audio\dwg_0031.wav" ^
  --ref-text "今天的海水温度刚刚好，特别适合一边摸鱼，一边认真工作。" ^
  --file lines.txt --out voice --mp3
```

- `lines.txt` 每行一句，输出 `01_xxx.wav`、`02_xxx.wav`…（`--mp3` 额外转 mp3）
- 也可以直接 `--text "一句话"`；`--speed 1.0`、`--steps 32` 可调
- 引擎没启动会自动拉起，合成完随进程退出

### 方式 B：直接调 HTTP API

```powershell
cd "D:\DDL\GPT-SoVITS-v2pro-20250604\GPT-SoVITS-v2pro-20250604"
runtime\python.exe api_v2.py -a 127.0.0.1 -p 9880 -c GPT_SoVITS/configs/tts_infer.yaml
```

先切权重（GET，路径要绝对路径）：

```
http://127.0.0.1:9880/set_gpt_weights?weights_path=D:\DDL\...\GPT_weights_v2Pro\dfy-e15.ckpt
http://127.0.0.1:9880/set_sovits_weights?weights_path=D:\DDL\...\SoVITS_weights_v2Pro\dfy_e10_s560.pth
```

再合成（POST `/tts`，返回 WAV 字节）：

```json
{
  "text": "要念的这句话",
  "text_lang": "zh",
  "ref_audio_path": "D:/DDL/voice_data/da-fei-yu-girl-voice-zh/train/audio/dwg_0031.wav",
  "prompt_text": "今天的海水温度刚刚好，特别适合一边摸鱼，一边认真工作。",
  "prompt_lang": "zh",
  "text_split_method": "cut5",
  "media_type": "wav",
  "streaming_mode": false,
  "sample_steps": 32,
  "speed_factor": 1.0,
  "temperature": 1.0,
  "top_k": 15,
  "top_p": 1.0
}
```

输出为 **32kHz 单声道 WAV**。注意 `prompt_text` 必须和参考音频内容一致，留空会非常慢。

### 方式 C：GPT-SoVITS WebUI（人手操作）

`runtime\python.exe webui.py` → 1-GPT-SoVITS-TTS → 推理页 → 选 `dfy-e15.ckpt` 与 `dfy_e10_s560.pth`，
参考音频/文本按上表填，输入台词即可试听和导出。

## 三、可以直接粘给另一个 AI 的任务说明

```
你要给一个宣传视频配音，使用本机已训练好的 GPT-SoVITS 音色「大肥鱼」，不要用任何云端 TTS。

引擎目录：D:\DDL\GPT-SoVITS-v2pro-20250604\GPT-SoVITS-v2pro-20250604
GPT 权重：GPT_weights_v2Pro\dfy-e15.ckpt
SoVITS 权重：SoVITS_weights_v2Pro\dfy_e10_s560.pth
参考音频：D:\DDL\voice_data\da-fei-yu-girl-voice-zh\train\audio\dwg_0031.wav
参考文本：今天的海水温度刚刚好，特别适合一边摸鱼，一边认真工作。
采样率：32000，单声道，sample_steps 32，speed_factor 1.0。

做法（二选一）：
A. 已在鲸语源码目录配好 .venv 时：
   .venv\Scripts\python tools\tts_cli.py --gsv-dir "<上面引擎目录>" \
     --gpt GPT_weights_v2Pro/dfy-e15.ckpt --sovits SoVITS_weights_v2Pro/dfy_e10_s560.pth \
     --ref "<上面参考音频>" --ref-text "<上面参考文本>" --file lines.txt --out voice --mp3
B. 直接起 api_v2.py（127.0.0.1:9880），先 GET set_gpt_weights / set_sovits_weights 切权重，
   再 POST /tts（JSON 参数见本文件），把返回的 WAV 存盘。

硬性要求：
- 一句一个文件，文件名 01_序号_内容.wav，不要拼接、不要加音乐、不要变速变调
- 每次合成前确认权重是 dfy-e15.ckpt + dfy_e10_s560.pth，不要回落到预训练权重
- 台词用中文口语；数字与英文尽量少；长句拆成短句，每句 ≤ 25 字
- 生成后报告每句时长，方便对轴
- 这个音色来源于 CC BY-NC 4.0 数据集（作者：尹紫鹭幻想社），视频里请注明来源，商业使用需另行授权
```

## 四、常见问题

- **报「找不到参考音频」**：`ref_audio` 必须是**引擎所在机器**能读到的绝对路径，别用引号包错。
- **声音不像 / 像男的**：权重没切成功。先 `set_gpt_weights`、`set_sovits_weights`，再合成。
- **第一次特别慢**：模型要加载，首句 10~30 秒正常，之后每句 2~4 秒。
- **发音怪**：把长句拆短、少用数字/英文、参考文本务必一字不差。
- **不要用零样本**：只给参考音频而不切权重，出来的是预训练模型的音色，不是大肥鱼。
