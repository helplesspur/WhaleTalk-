# 鲸语 WhaleTalk · 工作交接文档

> 面向接手的 AI / 开发者。最后更新：2026-10-31，对应版本 **v0.3.0**。
> 建议阅读顺序：本文 → `README.md` → `CHANGELOG.md` → 需要改的模块。

---

## 0. 先看这几条（容易踩）

1. **项目不在 CodeBuddy 工作区内**。工作区 `C:/Users/Administrator/CodeBuddy/20261027221214` 是空的，
   所有文件操作必须用绝对路径：
   `C:\Users\Administrator\Documents\Qoder\2026-10-25\46567a23\BiliVoiceBot`
   （`open_result_view` 会因为“不在工作区”拒绝，预览请用 `preview_url` 或截图）。
2. **系统没有全局 git**。用便携版：`D:\tools\MinGit\cmd\git.exe`（2.56.0）。
3. **C 盘空间紧张**（写作时约 5 GB）。onefile 的 exe 每次启动要往 `%TEMP%` 解压约 90 MB，
   空间不足会直接起不来；PyInstaller 还会留下 `%TEMP%\_MEI*`，可安全清理。
4. **`config.json`、`release\鲸语 WhaleTalk\config.json`、`zcode_identity.json`、`logs/`、各种 workdir 都是个人数据**，
   已在 `.gitignore` 里排除，**绝对不要提交、不要贴到聊天/日志里**。
5. 用户的语言是中文；界面文案、提交信息、Release 说明都用中文。

---

## 1. 项目概览

**鲸语 WhaleTalk**：Windows 桌面端直播助手。

```
B站/抖音弹幕、礼物、上舰、SC
        ↓
   pipeline（过滤/合并/冷却/固定回复/队列）
        ↓
   brain（Qoder CLI / OpenAI 兼容 / 外部 CLI / ZCode）
        ↓
   tts（GPT-SoVITS，本机 9880）+ 固定话术缓存
        ↓
   播放 + Live2D 口型/表情 + OBS 浏览器源
```

- 界面：`web/` 静态页，后端 aiohttp `127.0.0.1:8787`，WebSocket `/ws` 推送日志/回复
- 窗口：pywebview + WebView2（`desktop.py`）；没有 WebView2 时退回 Edge `--app` 窗口
- 打包：PyInstaller `--onefile --windowed`，产物 `WhaleTalk.exe`
- Python：`.venv\Scripts\python.exe`（3.12.14）

### 版本与仓库

| 项 | 值 |
|---|---|
| GitHub | https://github.com/helplesspur/WhaleTalk- |
| 当前 main | `9a85327`（build: 发布版 exe，v0.3.0） |
| 提交链 | `e02e312` v0.1.0 → `a0dd41d` 源码 → `d21e49c` exe → `ad07f4e` v0.2.0 → `5e0e6fc` 源码 → `9a85327` exe |
| Tag | `v0.1.0`、`v0.2.0`（`ad07f4e`）、`v0.3.0`（见下文 docs 提交） |
| Release | v0.3.0（Latest）：https://github.com/helplesspur/WhaleTalk-/releases/tag/v0.3.0 |
| 发布 exe | `release\鲸语 WhaleTalk\WhaleTalk.exe`，42,568,394 字节 |
| 本地配置 | `config.json`（根目录，9.5 KB，未提交） |

Release 资产：`WhaleTalk-v0.3.0-win64.zip`、`WhaleTalk.exe`、`Tutorial-CN.txt`、`SHA256SUMS.txt`。

---

## 2. 目录与模块

| 路径 | 行数量级 | 职责 / 入口 |
|---|---|---|
| `main.py` | ~1.1k | `App` 全局状态；aiohttp 路由；启动/停止；窗口；WS 推送；单实例（端口检查） |
| `brain.py` | ~800 | AI 后端：`QoderSession`、`OpenAIChat`、`CLIChat`、`ZcodeProxyChat`；`Brain.ai/raw/reply`；`err_text()` |
| `pipeline.py` | ~450 | 事件过滤、固定回复、合并/冷却、优先级队列、生成→合成→播放 worker |
| `tts.py` | ~400 | GPT-SoVITS 引擎管理（api_v2）、合成、播放器、口型包络 |
| `tts_cache.py` | ~540 | 固定话术烘焙：`CACHE`、`voice_signature()`、`segments()`、`Baker` |
| `bili.py` | ~250 | B 站 WS（blivedm 内置在 `blivedm/`）+ 扫码登录 |
| `douyin.py` | ~650 | 抖音：DevTools 抓取（`mode=browser`）或外部转发（`mode=relay`）+ 文本解析 |
| `games.py` | ~1.4k | 15 个 AI 游戏、`GameManager`、计分、自动轮换、`mute_chat()` |
| `arcade_games.py` | ~410 | 贪吃蛇 / 扫雷 / 2048 的棋盘与 AI 操作 |
| `songs.py` / `netease.py` | ~350 / ~200 | 点歌队列、礼物门槛、无人点歌自动歌单、网易云 API |
| `live2d.py` | ~80 | 模型 JSON、表情/动作扫描 |
| `config.py` | ~290 | `DEFAULTS`、merge、save；`BASE_DIR/RES_DIR/WEB_DIR` |
| `desktop.py` | ~50 | pywebview 窗口；`icon=` 用 `web/favicon.ico` |
| `procutil.py` | ~70 | Job Object（子进程随主程序退出）、`clean_env()`（剥掉 Qoder 环境变量） |
| `zcode_quota.py` | ~195 | ZCode 客户端套餐额度（本地代理，实验性） |
| `web/index.html` | ~101 KB | 管理界面（10 个页签）；`web/game.html`、`web/stats.html`、`web/live2d.html`、`web/overlay.html`、`web/songs.html` |
| `tools/` | — | `tts_cli.py`（命令行合成）、`douyin_selftest.py`（假页面自测） |
| `docs/` | — | `使用教程.md`、`promo/`（宣传素材，`refs/*` 图片默认不进仓库） |

UI 页签：控制台 / 直播间·登录 / 回复规则 / 固定回复 / 点歌 / AI 游戏 / AI 设置 / 语音设置 / Live2D / OBS 字幕。

---

## 3. 运行与调试

```powershell
cd "C:\Users\Administrator\Documents\Qoder\2026-10-25\46567a23\BiliVoiceBot"

.\.venv\Scripts\python.exe main.py              # 原生 WebView2 窗口
.\.venv\Scripts\python.exe main.py --no-ui      # 只跑后端，浏览器开 http://127.0.0.1:8787/
.\.venv\Scripts\python.exe main.py --browser-ui # 强制 Edge 应用窗口
```

- 单实例：`main()` 先探测 8787；端口被占用就只打开界面，不再起第二个后端。
- 日志：`logs\app.log`（UTF-8）。PowerShell 读取要加 `-Encoding utf8`，否则中文乱码。
- 配置：`GET/POST /api/config`，POST 传嵌套 patch（如 `{"ai":{"thinking":"default"}}`），服务端 merge + 立即保存。
- 常用冒烟接口：

```powershell
# 配置
Invoke-RestMethod http://127.0.0.1:8787/api/config -Headers @{'X-BVB'='1'}
# AI 测试（会真的调用模型）
Invoke-RestMethod http://127.0.0.1:8787/api/ai/test -Method Post -ContentType 'application/json' `
  -Headers @{'X-BVB'='1'} -Body '{"prompt":"ping"}'
# 接口模式测试（Responses / Chat 各发一个极小请求）
Invoke-RestMethod http://127.0.0.1:8787/api/ai/test_openai -Method Post -Headers @{'X-BVB'='1'} -Body '{}'
```

- 页面截图（无需打开窗口）：

```powershell
& 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe' --headless=new --disable-gpu `
  --user-data-dir="$env:TEMP\wt_profile" --window-size=1400,1000 `
  --screenshot="$env:TEMP\ui.png" http://127.0.0.1:8787/
```

- 所有 POST 需要头 `X-BVB: 1`（`guard` 中间件）；WS 在 `/ws`。
- 浏览器源：`/live2d`、`/songs`、`/overlay`、`/game`、`/stats`。

---

## 4. AI 后端（`brain.py`）

`cfg["ai"]["backend"]` 四选一：`qoder`（默认）/ `openai` / `cli` / `zcode`。

### Qoder（默认）

- 常驻 `qodercli` 进程，stream-json 双向；启动参数：
  `-p --input-format stream-json --output-format stream-json --max-turns 1 --tools "" --setting-sources "" --strict-mcp-config --no-session-persistence --system-prompt <人设>`，模型 `-m <qoder_model>`。
- 思考程度：`off → --thinking disabled`、`auto → --thinking auto`、`low/medium/high → --reasoning-effort`。
- 超时用 `ai.timeout`（默认 30 秒）；超时会杀会话（上下文丢失），下次重建。
- `qodercli` 会发 `system/model_queue_status`：`status=queued/ready`、`service_available`、`queue_wait_elapsed_ms`、`wait_time_ms`。
  低/中/高思考档位会走推理队列，高峰期可能排队数分钟（实测有一次 196 秒才 ready）。
- 超时文案见 `QoderSession._timeout_text()`：包含实际等待、超时设置、模型、思考档位、队列状态和建议。
- 用户 `release\鲸语 WhaleTalk\config.json` 是**个人运行配置，随时可能改**（交接时读到的是 OpenAI 兼容 `chat`、超时 30 秒，
  同时保留着 Qoder 模型 `Sonus` 的记录）。不要假设当前后端，先 `GET /api/config` 看；也不要擅自改用户配置。

### OpenAI 兼容

- `ai.openai_mode`：`responses`（默认）或 `chat`。
- Responses 不被支持（404/405，或 400/422 且报文含 unsupported 等）时自动降级 chat，本次运行记住 `_fallback_key`。
- `_send()` 把超时/连不上/HTTP 非 200 包装成带 URL、模型、状态码、响应体片段的中文错误。
- `probe()` 供 `/api/ai/test_openai` 使用，两种模式各发一个小请求。

### 外部 CLI / ZCode

- `CLIChat`：任意 `-p` 单次问答 CLI，参数、cwd、env、json 字段、超时在 `cfg["cli"]`。
- `ZcodeProxyChat`：走 `zcode_quota.py` 本地代理（`zcode.proxy_url`），实验性。

### 失败兜底

- `Brain.reply()` 捕获异常 → `err_text(e, 260)` → 返回模板 + `模板(AI失败:原因)`，界面“AI 回复”能看到原因。
- `main.py` 的 `/api/ai/test`、`/api/say` 返回 `error` 字段（+ `seconds`），前端显示在 `#aiOut` / `#sayOut`。
- **不要**再把异常只写 `str(e)[:80]`：`TimeoutError()` 的 `str` 是空，会变成“失败：”没有原因（这个 bug 已修）。

---

## 5. 其他关键实现

### 5.1 流水线（`pipeline.py`）

`on_event` → 过滤（屏蔽词/忽略名单/主播自己/概率/冷却）→ 合并（进房/礼物/点赞）→ 固定回复匹配 → 入队 →
`_gen_worker`（调 `Brain.reply/raw`，失败用模板）→ TTS（整句或拆段）→ 播放。
`filter.max_wait`（默认 60 秒）是**出队前**的过期判断；AI 生成很慢时这一条仍会播，但后面的会被丢。

### 5.2 固定话术烘焙（`tts_cache.py`）

- 缓存目录 `tts_cache/`（gitignored），索引 `index.json`；键 = 文本 + 音色签名（模型/参考音频/语速/温度/采样步数）。
- `tts.segment_bake=true` 时 `segments()` 把带 `{name}` 等变量的台词拆成“固定片段 + 变量”，固定片段读缓存、变量现场合成。
- 界面在【语音设置】底部：烘焙/停止/清空；接口 `/api/tts/bake`、`/api/tts/bake/stop`、`/api/tts/bake/clear`。

### 5.3 抖音（`douyin.py`）

- `douyin.mode`：`browser`（启动本机 Edge/Chrome + DevTools 端口 9333 抓页面）或 `relay`（不启动浏览器，等外部工具转发）。
- 转发入口：`POST /api/douyin/ingest`、`WS /ingest/douyin`；健康检查 `GET /api/douyin/health`。
- 识别弹幕/礼物（`douyin.gift_prices`）/进场/关注/点赞/粉丝团；主播自己的消息不回复。

### 5.4 AI 游戏（`games.py` / `arcade_games.py`）

- `CATALOG` 15 个：猜数字、数字炸弹、抢答、词语接龙、投票、贪吃蛇、扫雷、2048、猜拳、抽奖、飞花令、
  冷知识、故事连载、脑筋急转弯、讲笑话。
- `GameManager.on_danmaku(ev)` 返回 `True` 表示这条弹幕被游戏消费；`mute_chat()` 在单人节目期间让普通弹幕跳过。
- 接口 `/api/games/catalog|state|start|stop|reset`；棋盘页面 `/game`。
- 积分只在本次运行内累计。

### 5.5 点歌 / 本场数据

- 点歌：礼物门槛、插队、相似歌曲、网易云扫码；`songs.autoplay` 支持无人点歌时自动放歌单（随机/顺序）。
- 本场数据：Token/时长/礼物；`/stats` 页面由 `stats.*` 配置控制样式；`POST /api/stats/reset` 清零。

### 5.6 配置（`config.py`）

主要分节：`platform`、`ui`、`session`、`room_id`/`bili_cookie`、`douyin`、`events`、`filter`、`ai`、`cli`、`zcode`、
`tts`、`audio`、`overlay`、`stats`、`songs`、`games`、`live2d`。
`config.load()` 会 merge 默认值并**立即回写** `config.json`；新增配置项记得加到 `DEFAULTS`，否则被丢弃。

---

## 6. 打包与发布

### 6.1 构建 exe

```powershell
cd "C:\Users\Administrator\Documents\Qoder\2026-10-25\46567a23\BiliVoiceBot"
.\.venv\Scripts\pyinstaller.exe --noconfirm --clean --onefile --windowed --name WhaleTalk `
  --icon "web\favicon.ico" --add-data "web;web" --add-data "games.py;srcdata" `
  --collect-all webview --hidden-import clr --hidden-import qrcode.image.svg `
  --hidden-import miniaudio --exclude-module matplotlib --exclude-module PyQt5 main.py
```

- `build.bat` 是同样命令（带 pause）；`WhaleTalk.spec` / `BiliVoiceBot.spec` 已提交。
- `web/` 必须一起打包（`config.RES_DIR` 指向 `_MEIPASS`）；`games.py` 打到 `srcdata`。
- 图标：`web/favicon.ico`（多尺寸 16~256）、`web/icon.png`（侧边栏/网页图标）。
- 拷贝发布：`Copy-Item dist\WhaleTalk.exe "release\鲸语 WhaleTalk\WhaleTalk.exe" -Force`
- 校验打包内容：`pyi-archive_viewer.exe -l dist\WhaleTalk.exe | Select-String 'favicon|index.html'`
- 校验 exe 图标：`[System.Drawing.Icon]::ExtractAssociatedIcon(exe)` 存 PNG 看。
- 构建后清理 `%TEMP%\_MEI*`（被杀掉的 onefile 进程会残留，每个约 86 MB）。

### 6.2 Git

```powershell
$g = 'D:\tools\MinGit\cmd\git.exe'
& $g -c safe.directory='*' status
& $g -c safe.directory='*' add -A
& $g -c safe.directory='*' commit -m "..."
```

推送走 HTTPS，必须带代理（系统代理 `127.0.0.1:7897`，git 不读系统代理）：

```powershell
& $g -c safe.directory='*' -c http.proxy=http://127.0.0.1:7897 `
     -c https.proxy=http://127.0.0.1:7897 -c http.version=HTTP/1.1 push origin main
```

认证：Windows 凭据管理器里有 `git:https://github.com`（用户 `helplesspur`，scopes: `gist, repo, workflow`）。
**安全红线**：token 只在内存里用于 `Authorization: Basic ...`（或 `http.extraHeader` 环境变量），
不要打印、不要写进文件/命令行/日志/提交。取不到或 401 就让用户提供 PAT 或重新登录，不要猜。

### 6.3 GitHub Release

- 用 API 创建：`POST /repos/helplesspur/WhaleTalk-/releases`（`tag_name`、`target_commitish=main`、`name`、`body`）。
- 上传资产：`POST https://uploads.github.com/repos/.../releases/{id}/assets?name=<urlencode>`，
  `Content-Type: application/octet-stream`；单文件 <100 MB。
- v0.2.0 的资产：zip（exe + `qoder_login.bat` + 使用教程 + README）、exe、`Tutorial-CN.txt`、`SHA256SUMS.txt`。
- 压缩包里**不能有 config.json / logs / workdir**。
- 网络偶发 `SSL: UNEXPECTED_EOF` / `Connection reset`：重试、代理和直连交替即可。

---

## 7. 个人数据与 `.gitignore`

以下**永远不要提交/上传**：

```
config.json                  # 用户配置：Cookie、API Key、人设、房间号
config.json.bak
release/*/config.json
zcode_identity.json          # ZCode 身份
logs/                        # app.log、gsv_engine.log、Cookie 痕迹
qoder_workdir/  cli_workdir/  ui_profile/  douyin_profile/  tts_cache/
.venv/  build/  dist/
docs/promo/refs/*            # 角色皮套/表情参考图，版权归作者（README 除外）
```

`release/` 用**白名单**：只放行 `WhaleTalk.exe`、`qoder_login.bat`、`鲸语 WhaleTalk 使用教程.txt`。
新增发布文件时必须同步改 `.gitignore`，否则 `git add -A` 会漏。

提交前自检：

```powershell
& $g -c safe.directory='*' diff --cached --name-only | Select-String 'config\.json|identity|logs/|workdir|\.venv'
```

---

## 8. 已知问题 / 坑

1. **Qoder 排队**：低/中/高思考档位走推理队列，30 秒超时必失败；已把用户的 `thinking` 改回 `default`。
   文案会提示“改默认/关闭或把超时调到 120 秒以上”。这是服务端队列，不是本机 bug。
2. **磁盘**：C 盘长期吃紧（写作时约 5 GB）。onefile 启动需 ~90 MB 临时空间；`_MEI*` 残留要清。
3. **超时语义**：Qoder 是总超时（不是空闲超时），排队心跳间隔约 32 秒，30 秒设置可能连心跳都等不到。
4. **流水线过期**：`filter.max_wait=60` 是出队前判断；AI 慢时回复会晚到，属预期。
5. **WebView2**：系统没装时退回 Edge `--app`；`--browser-ui` 可强制。
6. **打包依赖**：`--collect-all webview`、`clr`、`qrcode.image.svg`、`miniaudio` 缺一不可；
   排除 `matplotlib`/`PyQt5` 控制体积。
7. **编码**：代码/文档 UTF-8；Windows PowerShell 5.1 默认 GBK，读日志/JSON 要 `-Encoding utf8`，
   否则看到“鑻辫”这类乱码是显示问题，不是文件坏了。
8. **CRLF**：MinGit 系统配置 `core.autocrlf=true`，仓库索引是 LF；混合工作区属正常，不要全局改行尾。
9. **端口 8787**：被占用时新进程只开界面不复用后端；测试前先确认没有残留 `python main.py --no-ui`。
10. **配置热更新**：改模型/思考档位会让 Qoder 会话重启；改音色会让烘焙缓存失效。
11. **zcode**：实验性，依赖本机 `D:\tools\bonus-plan` 与 `D:\tools\node\node.exe`，没装就别开。
12. **仓库体积**：exe 已进仓库（+42 MB）。以后建议只把 exe 放 Release 资产，仓库留源码（可选优化）。

---

## 9. 最近改动（2026-10-31，v0.3.0）

- **Live2D 通用皮套适配**：`live2d.py` 新增 `EMOTION_RULES` / `classify()` / `auto_emotions()` /
  `motion_meta()` / `pick_model_file()`。换任何皮套都能用：模型文件三级兜底、表情按关键词归类到 12 种情绪、
  一键重建「情绪 → 表情/动作」映射（保持原顺序和 keywords，可用表情优先保留）。
- **动作自动收尾**：实测某皮套 8 个动作全是 `Meta.Loop=true`，播完永不停、参数一直盖住表情。
  新增 `live2d.motion_hold`（默认 15 秒），到点 `stopAllMotions()` + 清临时表情。
- **语音模型浏览**：`/api/tts/weights/pick`，资源管理器选 `.ckpt`/`.pth` 后自动应用，
  目录内存相对路径、目录外记 `tts.custom_gpt` / `custom_sovits`（不复制文件）。
- **修复**：选完皮套目录模型列表不刷新（`data-pick` 赋值不触发 change）、`model_file` 沿用旧名、
  空目录递归扫到程序自身。
- 代码提交 2 个 + Release v0.3.0（4 个资产）。

---

## 10. 接手后的第一步

1. `& $g -c safe.directory='*' status --porcelain` → 应为空；`log --oneline -3` 应为 `9a85327 / 5e0e6fc / ad07f4e`。
2. 确认 `release\鲸语 WhaleTalk\WhaleTalk.exe` 存在（42,568,394 字节）且 `config.json` **未被修改/外传**。
3. `python main.py --no-ui` 起服务，`GET /api/config` 通 → 说明后端正常。
4. 需要改 UI 时改 `web/index.html`，**改完必须重新打包**，exe 里是 `_MEIPASS` 的副本。
5. 需要发布时：构建 → 复制到 `release` → 提交（源码/产物分开）→ 打 tag → 建 Release + 传资产 → 验证下载。
6. 任何删除（旧 exe、release-assets、缓存、`_MEI*`）先确认不是用户唯一副本；C 盘紧张时优先清临时目录。
