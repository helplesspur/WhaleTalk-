# 参与贡献

感谢你愿意改进鲸语（WhaleTalk）。这个项目刻意保持“单体、少依赖、本机运行”，提交前请先看几条约定。

## 开发环境

```powershell
uv venv --python 3.12 .venv
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python main.py          # 调试运行
build.bat                              # 打包 dist\WhaleTalk.exe
```

- 需要 Windows（audio 播放与进程管理用到了 Win32 API）
- 语音需要本机 GPT-SoVITS；AI 需要 Qoder CLI 登录或一个 OpenAI 兼容接口
- 没有环境也能开发 UI：启动后所有页面都能打开，只是没有声音/AI

## 代码约定

- 不引入前端框架和构建步骤，`web/` 就是普通 HTML/CSS/JS
- Python 只用 asyncio + aiohttp，避免加重量级依赖
- 新功能优先做成“可配置”，不要写死礼物名、模型路径、文案
- 日志与界面提示用中文，代码标识符用英文
- 不要提交任何 Cookie、Key、模型、权重、音频、训练数据（见 `.gitignore`）

## 提交前自检

1. `python -m py_compile *.py` 无错误
2. 启动后能连上直播间；【控制台】的“模拟测试”能跑通进房/弹幕/礼物/上舰
3. 改动涉及界面的话，用浏览器打开 `http://127.0.0.1:8787/`、`/live2d`、`/songs` 各看一遍
4. 退出程序后，`/live2d`、`/songs` 页面会自动隐藏

## Pull Request

- 一个 PR 只做一件事，说明“为什么改”，附上复现/验证步骤
- 涉及第三方接口（B 站、网易云）的改动，请说明接口来源与失败时的降级行为
- 修改界面文案时保持与现有风格一致（简洁、口语化）

## 一些适合入手的方向

- 直播姬/网页直播间的更多事件（如红包、粉丝团）
- 歌词同步显示到皮套页
- 多音色/多模型快速切换
- 非 Windows 平台的音频与进程适配
- 英文界面
