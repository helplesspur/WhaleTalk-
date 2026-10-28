# 鲸语 WhaleTalk · 宣传视频脚本与 AI 生成提示词

> 参考风格：《我做了个开源工具，让大肥鱼当上了B站UP主》（BV1bwnF6eEe8，75s）
> 拆解到的特征：深色星空/粒子底、聊天气泡叙事、真实界面录屏 + Q 版角色叠层、命令行打字动画、
> 节奏卡点的短字幕、结尾 logo + 安装命令 + 「这条视频就是她自己投的」meta 梗。
> 鲸语要保留这套「科技感 + 活性」的骨架，但把主题从「CLI 工具」换成「会说话的直播间」。

---

## 一、软件描述

### 1. 一句话（封面 / 简介首行）

> **鲸语 WhaleTalk：让 B 站直播间的弹幕，变成她亲口说出的回应。**

备选：
- 给 Live2D 皮套装上耳朵、嘴和脑子。
- 一条弹幕进来，一句人话出去——声音和皮套都是你自己的。

### 2. 短描述（60~80 字，用于 GitHub About / 视频简介开头）

鲸语（WhaleTalk）是一个开源的 B 站直播 AI 语音助手：实时读取弹幕、礼物、上舰、醒目留言，
交给大模型生成回复，再用本机的 GPT-SoVITS 合成音色说出来，驱动 Live2D 皮套对口型、换表情、
冒气泡。还支持礼物点歌、歌单插队、OBS 浏览器源。全部跑在本地，MIT 开源。

### 3. 长描述（200~300 字，用于 B 站视频简介 / 专栏）

主播在直播间最常做的三件事是：看弹幕、说话、感谢礼物。鲸语把这三件事串成了一条自动流水线：

弹幕、礼物、上舰、醒目留言实时进来 → 过滤、合并、按优先级排队 → 交给 Qoder 大模型
（或任何 OpenAI 兼容接口）生成一句像人说的话 → 用你自己训练或参考的 GPT-SoVITS 音色合成 →
推给 Live2D 皮套：嘴型跟着音量开合，表情按情绪切换，头顶冒出气泡字幕。

它不是「念稿机」：礼物连击会合并成一次感谢，多人进房会合成一句欢迎，过期消息会主动丢弃；
它也不是「贴图机」：呼吸、眨眼、口型、表情都活着。观众送指定礼物后发 `点歌:歌名`，
它会去网易云找歌、排进歌单，插队礼物可以直接置顶，自己说话时还会把背景音乐压下去。

所有东西都跑在你自己电脑上：模型、音色、皮套、登录信息，一样都不上传。代码 MIT 开源。

### 4. B 站视频简介模板

```
给 Live2D 皮套装上耳朵、嘴和脑子，她就能自己直播了。

鲸语 WhaleTalk 是一个开源的 B 站直播 AI 语音助手：
弹幕 / 礼物 / 上舰 / SC → 大模型回复 → GPT-SoVITS 合成 → Live2D 对口型 + 表情 + 气泡
还支持礼物点歌、歌单插队、OBS 浏览器源，全部本地运行。

开源地址（MIT）：https://github.com/helplesspur/WhaleTalk-
下载：Releases 里的 WhaleTalk-v0.1.0-win64.zip
需要自备：Qoder 账号（或任意 OpenAI 兼容接口）、GPT-SoVITS、参考音频、Live2D 模型

#B站直播 #Live2D #AI主播 #GPTSoVITS #开源 #虚拟主播
```

---

## 二、视频创意简报

| 项 | 设定 |
|---|---|
| 时长 | 75 秒（可裁 60 秒版） |
| 比例 | 16:9（横屏主版）；短视频版另出 9:16，只取「钩子 + 情绪 + 点歌」三镜 |
| 基调 | 深色科技感 + 角色活性：冷色 UI、粒子、数据流，角色却软乎乎、会害羞会撒娇 |
| 叙事 | 第一人称「她」在直播；画外音是主播本人或她的合成音；字幕承担主要信息 |
| 节奏 | 0-6s 钩子；6-14s 产品揭示；14-40s 三个能力；40-50s 点歌；50-58s 技术；58-75s 收尾 |
| 音乐 | 轻电子 / lo-fi tech，80~100 BPM；每 4 秒一个卡点，转场用 glitch / whoosh |
| 旁白 | 女声（建议直接用鲸语自己的音色合成，结尾的 meta 梗才成立） |
| 字幕 | 白色无衬线，关键词用霓虹粉 #fb7299 / 蓝 #23ade5；底部居中，关键词放大 1.2 倍 |
| 画面组成 | AI 生成：角色、氛围、抽象数据流 / 真实录屏：界面、弹幕、皮套、点歌、终端 |
| 禁止 | 不要出现 B 站官方 logo 变形、不要伪造真实观众 ID、不要把未实现的功能画出来 |

> 关键原则：**AI 生成负责「好看」，真实录屏负责「可信」**。
> 纯 AI 视频画不出能读的界面和准确的中文 UI，所有产品细节必须用录屏或后期合成。

---

## 三、分镜脚本（75s）

每镜标注：【AI】= 交给视频模型生成，【录屏】= 真实屏幕录制，【合成】= 后期 AE / 剪映完成。

### 镜头 1 ｜ 0:00–0:06 ｜ 钩子：她张不开嘴
- 画面：黑场 → 星点浮现。直播间画面淡入：弹幕一条条刷过「主播说句话呀」「是哑巴吗」。
  皮套安静地站着，只有呼吸和眨眼。一只手从画外伸进来，指尖轻轻点了下她的头顶。
- 动作：她被点得一愣 → 眨眼 → 张嘴 → 头顶弹出气泡「我在呢！」
- 运镜：缓推 + 轻微手持感；点到头顶瞬间一个 2 帧白闪。
- 屏幕文字：`给哑巴皮套，装一张会说话的嘴`
- 音效：电流底噪、弹幕「叮」、白闪 whoosh。
- 归类：【AI】角色与手部镜头 + 【合成】真实弹幕 UI + 文字

### 镜头 2 ｜ 0:06–0:14 ｜ 产品揭示
- 画面：镜头穿进气泡，进入深色数据空间；「鲸语 WhaleTalk」logo 由霓虹描边逐步点亮，
  三个标签依次出现：`听懂弹幕` `自己开口` `有表情`。
- 运镜：一镜到底穿气泡 + 轻微失焦再合焦。
- 屏幕文字：`鲸语 WhaleTalk` / `B站直播 AI 语音助手`
- 音效：低频 riser + 三声清脆的 UI 音。
- 归类：【AI】抽象空间与光效 +【合成】logo 与文字（logo 用矢量素材，别让 AI 画字）

### 镜头 3 ｜ 0:14–0:24 ｜ 一条弹幕，她真的听懂了
- 画面：真实录屏。左侧弹幕面板滚动，一条「主播今天吃什么」被高亮；右侧 AI 回复打字机式出现；
  皮套头顶气泡同步弹出这句话，嘴型随语音波形开合。
- 运镜：录屏缓慢放大到气泡，再切回全身。
- 屏幕文字：`一条弹幕，她真的听懂了`
- 音效：键盘敲击 + 她的真实合成语音（这句一定要真声音）
- 归类：【录屏】+【合成】

### 镜头 4 ｜ 0:24–0:32 ｜ 会害羞，会惊讶，会撒娇
- 画面：三条弹幕快速连击，每种触发一个表情：
  ①「谢谢老板」→ 爱心眼；②「哇上舰了」→ 感叹号；③「主播是不是傻」→ 吐舌 + 泡泡糖动作。
  镜头围绕她小半圈，每次切换配一个表情色光。
- 运镜：环绕（orbit）+ 三次快速 punch-in。
- 屏幕文字：`会害羞 · 会惊讶 · 会撒娇`
- 音效：三声卡通音效 + 音乐卡点。
- 归类：【AI】表情特写（用参考图锁角色）+【录屏】真实表情演示

### 镜头 5 ｜ 0:32–0:40 ｜ 礼物、上舰、SC，一个都不落
- 画面：礼物连击刷屏 → 合并成一句「谢谢老板的 10 个小心心」；舰长上舰特效 + 她激动地站起来；
  SC 出现，她先念金额再回答问题。
- 运镜：快切 + 轻微抖动，节奏跟音乐。
- 屏幕文字：`礼物连击合并 · 上舰隆重感谢 · SC 先谢再答`
- 归类：【录屏】为主 +【AI】她激动反应的 1 秒插入镜头

### 镜头 6 ｜ 0:40–0:50 ｜ 观众点歌，自己排队
- 画面：弹幕「点歌:起风了」→ 右侧歌单浮层滑入，曲目依次排队；一个「插队」标签把某首歌顶到第一位；
  播放中背景音乐波形下降，她的说话声盖在上面。
- 运镜：UI 浮层跟拍 + 进度条推进。
- 屏幕文字：`点歌排队 · 插队置顶 · 说话时音乐自动压低`
- 音效：音乐渐入、插队「叮」，压低的瞬间可听见明显的音量变化。
- 归类：【录屏】+【合成】波形可视化

### 镜头 7 ｜ 0:50–0:58 ｜ 全部跑在你自己的电脑上
- 画面：深色架构线框：`弹幕 → 大模型 → GPT-SoVITS → Live2D`，节点依次点亮、连线流动；
  右下角小字 `本地运行 · MIT 开源`。
- 运镜：等距视角缓慢横移。
- 屏幕文字：`弹幕 → AI → 语音 → 皮套` / `本地跑 · 开源免费`
- 归类：【AI】数据流氛围（不要出现真实命令行文字）+【合成】节点与文字

### 镜头 8 ｜ 0:58–1:08 ｜ 声音、皮套、数据，都是你自己的
- 画面：三个盾形图标依次亮起：`数据本机` `自备音色` `任意模型`；
  背景是她的皮套半透明剪影。
- 屏幕文字：`不上传 · 不锁定 · 声音和皮套都是你的`
- 归类：【合成】图形动画 +【AI】剪影

### 镜头 9 ｜ 1:08–1:15 ｜ meta 收尾
- 画面：她对着镜头挥手，气泡打出：「这条视频的配音，也是我自己合成的」。
  logo + GitHub 地址 + `v0.1.0` 收尾，最后一帧是她眨眼。
- 运镜：固定 + 结尾轻轻拉远。
- 屏幕文字：`鲸语 WhaleTalk · 开源 MIT` / `github.com/helplesspur/WhaleTalk-`
- 音效：音乐收束 + 一声鲸鸣。
- 归类：【AI】角色 +【合成】文字

---

## 四、给 AI 视频模型的提示词

### 4.1 全局风格（所有镜头都带上）

**中文：**
> 深色科技感与柔软动画的混合质感：背景为近黑的深海军蓝，漂浮细小星点与气泡，霓虹粉与电光蓝作为唯一强调色；
> 主体是 Q 版二次元少女（约 2.5 头身），深蓝短发、白色蕾丝头饰、蓝色蝴蝶结、头顶一只小鲸鱼、白色水手裙、
> 身后小鲸鱼尾；线条干净、赛璐璐上色；真实手部为写实皮肤质感，与二次元角色形成反差。
> 电影级柔和打光，浅景深，24fps，轻微胶片颗粒，画面干净无杂字、无水印。

**English:**
> A blend of sleek dark tech and soft anime charm: near-black navy background with floating dust motes and
> translucent bubbles, neon pink (#fb7299) and electric blue (#23ade5) as the only accent colors. Subject is a
> chibi anime girl (about 2.5 heads tall) with navy-blue bob hair, a white frilly headdress, small blue bows,
> a tiny round whale ornament on her head, a white sailor dress and a small whale tail behind her; clean lineart,
> flat cel shading. Any human hand is photorealistic with real skin texture, creating comedic contrast.
> Cinematic soft lighting, shallow depth of field, 24fps, subtle film grain, clean frame, no watermark.

### 4.2 角色一致性（把参考图一起上传）

**中文：**
> 角色参考：第一张图是设定参考，第二张是表情参考。保持发色（深蓝 + 浅蓝挑染）、白色蕾丝头饰、
> 两侧蓝色蝴蝶结、头顶小鲸鱼发饰、白色水手裙、身后小鲸鱼尾不变；只改变表情、动作、镜头与光。
> 不要新增服装、不要改变脸型与瞳色。

> 参考图文件见 [`docs/promo/refs/`](refs/README.md)：
> 设计基准用 `01_live2d_front.png`，委屈表情用 `08_sticker_aggrieved.png`，
> 构图参考用 `13_hand_meme.png`。各镜头的图片组合见该目录 README。

**English:**
> Character reference: image 1 is the design reference, image 2 the expression reference. Keep the same
> navy-blue bob hair with light-blue highlights, white frilly headdress, blue bows on both sides, tiny whale
> ornament on top, white sailor dress with small whale tail; change only expression, pose, camera and lighting.
> Do not add new clothing; do not alter the face shape or eye color.

### 4.3 逐镜提示词

**镜头 1（钩子）**
> EN: Dark navy void slowly filling with dust motes. A chibi anime whale girl stands still in a vertical
> livestream frame, only breathing and blinking, a faint neon rim light behind her. A photorealistic adult hand
> enters from the right edge and gently taps her head with one fingertip. She startles, blinks twice, then opens
> her mouth; a small round speech bubble pops above her head. Slow push-in, subtle handheld camera, 2-frame
> white flash on the tap, cinematic, 16:9, 6 seconds.
>
> 中文：深海军蓝虚空，尘埃缓缓浮现；Q 版鲸鱼娘站在竖屏直播画面里静止，只有呼吸与眨眼，背后一圈霓虹轮廓光。
> 一只写实的手从右侧入画，指尖轻点她的头顶；她愣了一下、眨眼两下，然后张开嘴，头顶弹出一个小圆形气泡。
> 缓慢推进、轻微手持、点触瞬间两帧白闪，电影感，16:9，6 秒。

**镜头 2（产品揭示）**
> EN: Camera flies through a translucent speech bubble into a vast dark data space. Neon pink and cyan light
> streaks trace a clean logo shape out of thin air, particles converging, shallow depth of field, slight
> focus pull, holographic UI panels fading in and out, cinematic sci-fi, 16:9, 8 seconds. No text.
>
> 中文：镜头穿过半透明气泡，进入广阔的深色数据空间；霓虹粉与青色光带凭空勾出一个干净的 logo 轮廓，
> 粒子汇聚，浅景深、轻微变焦，全息 UI 面板淡入淡出，科幻电影感，16:9，8 秒。画面中不要出现文字。

**镜头 3（听懂弹幕）**
> EN: Medium close-up of the chibi whale girl in a softly lit dark studio, listening; her eyes track an
> off-screen stream of glowing message panels scrolling on the left. She tilts her head, then speaks: mouth
> opens and closes naturally, small speech bubble glowing above her. Slow push-in from full body to chest-up.
> 16:9, 8 seconds.
>
> 中文：中近景，柔和暗光直播间里，Q 版鲸鱼娘在听；她的眼睛跟着左侧滚动的发光消息面板移动，歪头，
> 然后开口说话，嘴型自然开合，头顶气泡发光。从全身缓慢推到半身，16:9，8 秒。

**镜头 4（三种情绪）**
> EN: Three quick expression beats of the same chibi whale girl, camera orbiting a quarter turn:
> (1) heart-shaped eyes and blushing, hands on cheeks; (2) shocked, wide eyes, exclamation mark flash;
> (3) cheeky tongue-out with a pink bubble gum pop, playful head tilt. Each beat lit by a different accent
> color (pink / cyan / warm white). Snappy 1-second cuts inside a continuous orbit, 16:9, 8 seconds.
>
> 中文：同一个 Q 版鲸鱼娘的三次表情快切，镜头环绕四分之一圈：①心形眼、脸红、双手捧脸；②震惊瞪眼、感叹号闪光；
> ③调皮吐舌吹出粉色泡泡糖、歪头。每次切换用不同强调色（粉 / 青 / 暖白）打光。连续环绕里做 1 秒快切，16:9，8 秒。

**镜头 5（礼物上舰）**
> EN: The chibi whale girl jumps up excitedly, eyes sparkling, hands clasped, while golden confetti-like light
> particles burst in the dark room; background shows rows of glowing gift cards flying upward. Fast dolly-in,
> slight camera shake matching a beat drop, warm golden rim light contrasting the cool background, 16:9, 6 seconds.
>
> 中文：Q 版鲸鱼娘兴奋地跳起来，眼睛发亮、双手合十，暗色房间里金色光粒像彩带一样爆开；背景一排排发光礼物卡片上浮。
> 快速推近，随鼓点轻微抖动，暖金色轮廓光与冷色背景对比，16:9，6 秒。

**镜头 6（点歌）**
> EN: Over-the-shoulder view of the whale girl in a dark room; a translucent playlist panel slides in from the
> right, glowing rows of tracks; one row lights up and jumps to the top. Behind, a music waveform visibly
> ducks down while her voice waveform rises. Smooth lateral camera move, UI glow reflections, 16:9, 8 seconds.
> No readable text.
>
> 中文：过肩视角，暗房间里鲸鱼娘在前；一块半透明歌单面板从右侧滑入，发光曲目行滚动；其中一行亮起并跳到最上方。
> 背景音乐波形明显压低，她的说话波形升起。平稳横移镜头，UI 反光，16:9，8 秒。不要出现可读文字。

**镜头 7（架构）**
> EN: Isometric view of a dark holographic flow diagram: four glowing nodes connected by light streams that
> pulse in sequence, particles flowing along the connections, tiny ripples on a reflective floor, camera slowly
> pans right. Sci-fi data visualization, no text, 16:9, 8 seconds.
>
> 中文：等距视角的深色全息流程图：四个发光节点由光流连接，依次脉冲，粒子沿连线流动，地面有微弱反射与涟漪，
> 镜头缓慢右移。科幻数据可视化，不要文字，16:9，8 秒。

**镜头 8（盾牌）**
> EN: Three minimal shield-shaped holograms light up one after another in a dark space, each with a soft ripple;
> behind them, a translucent silhouette of the chibi whale girl fades in like a watermark. Slow parallax push,
> clean, premium, no text, 16:9, 6 seconds.
>
> 中文：深色空间中三枚极简盾形全息图标依次亮起，各带一圈柔和涟漪；它们背后，Q 版鲸鱼娘的半透明剪影像水印一样淡入。
> 缓慢视差推进，干净高级，无文字，16:9，6 秒。

**镜头 9（收尾）**
> EN: Full-body chibi whale girl waving at the camera in a dark starry room, a speech bubble glowing above her;
> camera slowly pulls back and the lights dim to a single pink rim light. Warm, friendly, cinematic, 16:9, 7 seconds.
>
> 中文：全身镜头，Q 版鲸鱼娘在深色星空房间里对镜头挥手，头顶气泡发光；镜头缓慢拉远，灯光收成一圈粉色轮廓光。
> 温暖友好，电影感，16:9，7 秒。

### 4.4 负面提示词（Negative prompt）

> 额外人物、多余的手指、畸形的手、文字乱码、水印、logo 变形、低清、过曝、噪点过多、塑料感皮肤、
> 真实人脸、写实场景、3D 渲染感过强、角色服装变化、发色变化
>
> extra characters, deformed hands, extra fingers, garbled text, watermark, distorted logos, low resolution,
> overexposed, plastic skin, real human face, photoreal environment, overly 3D-rendered look, changed outfit,
> changed hair color

### 4.5 单条长提示词（只支持一段提示的工具用）

> 75 秒横屏科技感宣传片，主角是 Q 版二次元鲸鱼娘（深蓝短发、白色蕾丝头饰、蓝色蝴蝶结、头顶小鲸鱼、白色水手裙、
> 小鲸鱼尾），配色为近黑深海军蓝 + 霓虹粉 #fb7299 + 电光蓝 #23ade5。风格：深色星点粒子背景、柔和电影打光、
> 干净赛璐璐上色、轻微胶片颗粒；出现的手必须是写实皮肤质感，与二次元角色形成反差。
> 结构：①一只手点她头顶，她愣住、眨眼、开口、头顶冒出气泡；②镜头穿进气泡进入数据空间，光带勾出 logo；
> ③她听弹幕、歪头、说话；④三种情绪表情快切（爱心眼/震惊/吐舌吹泡泡）；⑤礼物光粒爆发、她兴奋跳起；
> ⑥半透明歌单面板滑入、音乐波形被压低；⑦等距全息架构图，四个节点依次点亮；⑧三枚盾牌图标亮起，她的剪影淡入；
> ⑨她挥手告别，镜头拉远。全程不要出现可读文字、不要水印、不要真实人脸，16:9，24fps。

---

## 五、素材与后期

### 5.1 需要准备的真实素材

| 素材 | 用途 | 来源 |
|---|---|---|
| 角色立绘 / 表情包 | 喂给视频模型保持一致性 | [`docs/promo/refs/`](refs/README.md)：`01_live2d_front.png`（设计）、`08_sticker_aggrieved.png`（委屈）、`13_hand_meme.png`（构图）、封面 `14`/`15` |
| 弹幕面板滚动 | 镜头 3、5 | 鲸语界面录屏（可开模拟测试制造事件） |
| 皮套说话 + 气泡 | 镜头 3 | `/live2d` 页面录屏（开 OBS 录制，绿幕抠像） |
| 表情切换 | 镜头 4 | 设置页的「试播表情」逐个点 |
| 歌单排队 + 插队 | 镜头 6 | `/songs` + 点歌页录屏 |
| 终端安装 | 镜头 7 可选 | 真实的 `git clone` / 解压命令，录制打字动画 |

录屏建议：OBS 输出 1920×1080、60fps；UI 录屏用 125% 缩放保证文字清晰；皮套单独录一条带 alpha 的素材（绿幕 + 抠像）。

### 5.2 后期合成顺序

1. 定剪：先按上面的时间轴把每一镜占位排好，卡点对齐音乐。
2. 贴素材：真实录屏铺在 AI 镜头之上；AI 镜头负责开场、转场、情绪特写、结尾。
3. 加文字：所有中文字幕、logo、GitHub 地址都用矢量素材叠加，**不要让 AI 生成文字**。
4. 调色：统一到深蓝底 + 粉蓝强调；录屏画面压暗、加一点辉光，融入 AI 画面。
5. 声音：音乐 + UI 音效 + 她的真实合成语音；结尾那句 meta 台词必须用软件自己的音色。

---

## 六、可选替换文案

- 标题 A：`我给皮套装了张嘴，她开始自己直播了`
- 标题 B：`一条弹幕进来，一句人话出去`
- 标题 C：`开源一个 B 站直播 AI 嘴替：弹幕→大模型→她的声音→Live2D`
- 封面主文案：`你去直播！`（配合已生成的封面）
- 结尾句：`这条视频的配音，也是她自己合成的。`
