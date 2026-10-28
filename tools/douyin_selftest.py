"""抖音抓取自测：起一个“假直播间”网页，验证 浏览器抓取 → 文本识别 → 事件 这条链路。

用法（源码目录下）：
    .venv\\Scripts\\python.exe tools\\douyin_selftest.py

不会访问真实抖音，也不会改写 config.json；只会临时启动一个无头 Edge（调试端口 9334）。
"""
import asyncio
import os
import sys
import tempfile
import time

from aiohttp import web

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import douyin  # noqa: E402

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>测试主播的直播间 - 抖音直播</title></head>
<body>
<h1>假直播间（自测用）</h1>
<div class="webcast-chatroom___items" id="list"></div>
<script>
const list = document.getElementById('list');
const lines = [
  '小明 来了',
  '小红 关注了主播',
  '小刚 为主播点赞了',
  '小李 送出了 小心心 ×5',
  '小美 加入了粉丝团',
  '小张：主播晚上好呀',
  '小王：今天播到几点',
  '小刘：我送出了玫瑰×2',
];
let i = 0;
setInterval(() => {
  const line = lines[i % lines.length];
  const div = document.createElement('div');
  div.className = 'webcast-chatroom___item';
  const sep = line.indexOf('：');
  if (sep > 0) {
    const n = document.createElement('span');
    n.className = 'webcast-chatroom___user-name';
    n.textContent = line.slice(0, sep);
    const b = document.createElement('span');
    b.className = 'webcast-chatroom___content-with-emoji-text';
    b.textContent = line.slice(sep);
    div.append(n, b);
  } else {
    div.textContent = line;
  }
  list.appendChild(div);
  while (list.children.length > 20) list.firstChild.remove();
  i++;
}, 350);
</script>
</body></html>"""

PORT = 8899


async def main():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text=PAGE, content_type="text/html"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", PORT).start()

    events, statuses = [], []
    dy = douyin.DouyinLive(lambda e: events.append(e), lambda m: statuses.append(m))
    cfg = {
        "mode": "browser",
        "room_url": f"http://127.0.0.1:{PORT}/",
        "debug_port": 9334,
        "profile_dir": os.path.join(tempfile.gettempdir(), "whaletalk_douyin_selftest"),
        "keep_browser": False,
        "headless": True,
        "gift_prices": "小心心=1\n玫瑰=1",
    }
    print("启动无头浏览器抓取假直播间…")
    await dy.start(cfg)
    deadline = time.time() + 40
    while time.time() < deadline and len({e["type"] for e in events}) < 6:
        await asyncio.sleep(0.4)
    await dy.stop(keep=False)
    await runner.cleanup()

    print("\n状态：")
    for s in statuses:
        print("  -", s)
    print("\n事件：")
    for e in events[:14]:
        print("  ", e)
    kinds = {e["type"] for e in events}
    need = {"danmaku", "enter", "follow", "like", "gift", "guard"}
    print("\n识别到的类型：", ", ".join(sorted(kinds)) or "（无）")
    print("结果：", "OK" if need <= kinds else "FAIL 缺少 " + ", ".join(sorted(need - kinds)))
    return 0 if need <= kinds else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
