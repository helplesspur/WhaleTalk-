"""内嵌窗口：用 WebView2 打开管理界面，不启动外部浏览器。

pywebview 在 Windows 上走 Edge WebView2 运行时（Win10/11 基本都自带），
窗口是独立应用窗口，没有地址栏/标签页；界面仍是 web/ 里的网页，改动 UI 不用改这里。
如果这台机器没有 WebView2，main.py 会自动退回 Edge 应用窗口。
"""
import logging
import os
import sys

log = logging.getLogger("ui")

TITLE = "鲸语 WhaleTalk"


def available():
    if sys.platform != "win32":
        return False
    try:
        import webview  # noqa: F401
        return True
    except Exception as e:  # 没装 / 依赖缺
        log.warning("内嵌窗口不可用（%s），将使用浏览器窗口", e)
        return False


def run(url, on_close=None, width=1400, height=940, icon=None):
    """在当前（主）线程打开窗口，关掉窗口后返回。"""
    import webview

    if icon and not os.path.exists(icon):
        icon = None
    log.info("创建应用窗口…")
    win = webview.create_window(
        TITLE, url,
        width=width, height=height, min_size=(1120, 720),
        background_color="#0b0d13", text_select=True, zoomable=True, confirm_close=False,
    )
    if on_close:
        def _closed():
            try:
                on_close()
            except Exception:
                log.exception("窗口关闭回调出错")
        win.events.closed += _closed
    log.info("窗口已创建，启动 WebView2…")
    webview.start(gui="edgechromium", debug=False, icon=icon)
    log.info("窗口已关闭")
    return True
