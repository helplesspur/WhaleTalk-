# 第三方组件与许可

本项目的**自有代码**以 MIT 发布（见 [LICENSE](LICENSE)）。
下面列出运行时实际使用、随仓库或随安装包分发的第三方组件，以及它们各自的许可。
**Live2D Cubism Core 不是 MIT**，请特别注意。

## 随仓库分发

| 组件 | 位置 | 许可 | 说明 |
|---|---|---|---|
| **Live2D Cubism Core** | `web/vendor/live2dcubismcore.min.js` | Live2D 专有软件许可协议（Redistributable Code） | Copyright (C) Live2D Inc. 该文件以“可再分发代码”形式随应用分发，受 [Live2D Proprietary Software License Agreement](https://www.live2d.com/eula/live2d-proprietary-software-license-agreement_en.html) 约束；不得单独再分发或用于其他目的。Live2D Cubism SDK 的商用条件请以 Live2D 官方条款为准。 |
| PixiJS | `web/vendor/pixi.min.js` | MIT | © PixiJS contributors |
| pixi-live2d-display（lipsyncpatch 分支） | `web/vendor/cubism4.min.js` | MIT | © guansss 及分支作者；本项目使用的是支持 PixiJS 7 的社区分支 |
| blivedm | `blivedm/` | MIT | © xfgryujk，见 `blivedm/LICENSE`；本项目内置其源码并保持原许可与署名 |

## 运行时依赖（Python，通过 pip 安装，未内置于仓库）

| 包 | 许可 | 用途 |
|---|---|---|
| aiohttp / yarl / multidict / frozenlist | Apache-2.0 | HTTP 与 WebSocket |
| Brotli | MIT | WebSocket 压缩 |
| pure-protobuf | MIT | 部分直播消息解析 |
| numpy | BSD-3-Clause | 音频处理 |
| sounddevice | MIT | 音频输出（其分发的 PortAudio 亦为 MIT） |
| miniaudio (Python 绑定) | MIT / Public Domain | mp3 解码 |
| qrcode | BSD-3-Clause | 二维码生成 |
| PyInstaller（仅打包时） | GPL-2.0-with-exception | 生成 exe |

## 外部程序与服务（不属于本项目，不随仓库分发）

| 项目 | 许可/性质 | 说明 |
|---|---|---|
| GPT-SoVITS | MIT（代码）；权重按其发布页条款 | 本项目只调用其 `api_v2.py`，不包含引擎与权重 |
| Qoder CLI | Qoder 官方专有工具 | 由用户自行安装并登录，使用其账号额度 |
| B 站直播 / 通行证接口 | 非官方使用 | 受 B 站用户协议约束，接口可能变化 |
| 网易云音乐接口 | 非官方使用 | 仅用于搜索与播放用户有权访问的音频；曲库版权归权利人所有 |
| 大肥鱼（自调少女音色）中文语音数据集 | **CC BY-NC 4.0**，作者：尹紫鹭幻想社（Bilibili） | 本项目仅把它作为**示例音色**的演示来源，**不随仓库分发**；如需使用请遵守其非商业条款并署名 |

## 素材与模型（不随仓库分发）

- **Live2D 皮套模型**（如 DS 鲸鱼娘）：版权归原作者所有，本项目不分发，也不代表原作者授权。
- **GPT-SoVITS 权重 / 参考音频 / 训练数据**：由使用者自行提供，需确保拥有相应权利。

## 使用提示

1. 合成语音可能被误认为真人发声，对外直播时建议说明其为 AI 合成。
2. 请勿未经授权克隆、模仿他人声音。
3. 直播中播放音乐、使用第三方模型、调用平台接口的合规责任由使用者承担。
