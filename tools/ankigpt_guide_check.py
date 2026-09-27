# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Validate and render the bundled How To in the actual unprivileged browser page."""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
sys.path.extend(["pylib", "qt", "out/pylib", "out/qt"])

from bs4 import BeautifulSoup  # noqa: E402

from aqt.ankigpt.browser import (  # noqa: E402
    WebsitePage,
    WebsiteView,
    browser_url,
    guide_url,
)
from aqt.qt import (  # noqa: E402
    QApplication,
    QFont,
    QFontDatabase,
    QPoint,
    Qt,
    QUrl,
    QWebEngineProfile,
    QWebEngineView,
    sip,
)


def main() -> None:
    guide = Path(guide_url().toLocalFile())
    soup = BeautifulSoup(guide.read_text(encoding="utf-8"), "html.parser")
    ids = {tag["id"] for tag in soup.select("[id]")}
    for tag in soup.select("[src], [href]"):
        target = str(tag.get("src") or tag.get("href"))
        if target.startswith("#"):
            assert target[1:] in ids, target
        else:
            assert (guide.parent / target).is_file(), target
    assert not soup.select("script"), "Guide must work without scripts."
    assert len(soup.select("section")) == 15
    assert all(figure.select_one(".mark") for figure in soup.select("figure"))
    app = QApplication.instance() or QApplication(["ankigpt-guide-check"])
    assert isinstance(app, QApplication)
    font = "C:/Windows/Fonts/segoeui.ttf"
    if Path(font).exists():
        QFontDatabase.addApplicationFont(font)
        app.setFont(QFont("Segoe UI", 10))
    view = QWebEngineView()
    profile = QWebEngineProfile(view)
    page = WebsitePage(profile, view)
    view.setPage(page)

    def pump(condition: Callable[[], bool], timeout: float = 20) -> None:
        started = time.monotonic()
        while not condition():
            app.processEvents()
            time.sleep(0.02)
            if time.monotonic() - started > timeout:
                raise TimeoutError("Guide rendering timed out")

    def javascript(script: str) -> object:
        result: list[object] = []
        page.runJavaScript(script, result.append)
        pump(lambda: bool(result))
        return result[0]

    finished: list[bool] = []
    view.loadFinished.connect(finished.append)
    view.resize(1280, 900)
    view.show()
    view.load(guide_url())
    pump(lambda: bool(finished))
    assert finished[-1], "Guide did not load"
    output = Path("out/guide-check")
    output.mkdir(parents=True, exist_ok=True)
    for width in (1280, 680):
        view.resize(width, 900)
        pump(lambda: javascript("window.innerWidth") == width)
        assert javascript(
            "Array.from(document.images).every(i => i.complete && i.naturalWidth > 0)"
        )
        assert javascript(
            "document.documentElement.scrollWidth <= window.innerWidth"
        ), "Horizontal overflow"
        assert (
            javascript(
                "getComputedStyle(document.querySelector('header')).backgroundColor"
            )
            == "rgb(20, 45, 82)"
        )
        for anchor in ("start", "setup", "study", "visuals", "browser"):
            javascript(
                f"document.getElementById('{anchor}').scrollIntoView({{behavior:'instant'}})"
            )
            # Give Chromium time to paint after scrolling.
            until = time.monotonic() + 0.4
            pump(lambda: time.monotonic() >= until)
            assert view.grab().save(str(output / f"{width}-{anchor}.png"))
    # Full-size screenshots must remain navigable in the same restricted page.
    image_url = guide_url()
    image_url.setPath(image_url.path().replace("index.html", "images/01-deck-list.png"))
    assert browser_url(image_url.toString()) is not None
    finished.clear()
    view.load(image_url)
    pump(lambda: bool(finished))
    assert finished[-1]
    finished.clear()
    view.back()
    pump(lambda: bool(finished))
    assert finished[-1] and page.url().toLocalFile() == guide_url().toLocalFile()
    check_popups(profile, view, pump)
    check_ad_filter(profile, view, pump, javascript)
    view.close()
    sip.delete(page)
    sip.delete(profile)
    print(
        f"PASS: guide rendering, screenshot navigation, popup blocking, and in-page ad filtering. QA: {output}"
    )


def check_popups(
    profile: QWebEngineProfile,
    parent: QWebEngineView,
    pump: Callable[..., None],
) -> None:
    from PyQt6.QtTest import QTest

    owner = MagicMock()
    owner.profile = profile
    source = WebsiteView(owner, parent)
    target = QWebEngineView(parent)
    target.setPage(WebsitePage(profile, target))
    owner.new_tab.return_value.view = target
    loaded: list[bool] = []
    requests: list[bool] = []
    source.loadFinished.connect(loaded.append)
    source.page().newWindowRequested.connect(
        lambda request: requests.append(request.isUserInitiated())
    )
    source.resize(500, 200)
    source.show()
    source.load(QUrl("about:blank"))
    pump(lambda: bool(loaded))
    assert loaded[-1]
    ready: list[object] = []
    source.page().runJavaScript(
        'document.body.innerHTML = \'<a href="about:blank" target="_blank" '
        'style="display:block;height:100px">Open a tab</a>\'',
        ready.append,
    )
    pump(lambda: bool(ready))
    source.page().runJavaScript("window.open('about:blank')")
    pump(lambda: bool(requests))
    assert requests == [False]
    owner.new_tab.assert_not_called()
    # PyQt's stub declares an instance method, but QTest is a C++ namespace.
    QTest.mouseClick(  # type: ignore[call-overload]
        source.focusProxy(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(50, 30),
    )
    pump(lambda: owner.new_tab.called)
    assert requests == [False, True]
    owner.new_tab.assert_called_once_with(background=False)
    sip.delete(source)
    sip.delete(target)


def check_ad_filter(
    profile: QWebEngineProfile,
    view: QWebEngineView,
    pump: Callable[..., None],
    javascript: Callable[[str], object],
) -> None:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    from aqt.ankigpt.adfilter import AdFilter

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = b"""<!doctype html><html><head><title>Ad filter test</title></head>
            <body><h1 id="content">Study content</h1>
            <div class="ad-banner" id="banner">Banner advertisement</div>
            <div role="dialog" id="dialog">Ordinary dialog</div>
            <button id="button" onclick="this.textContent='Clicked'">Click me</button>
            <script>setTimeout(() => {
                const ad = document.createElement('div');
                ad.className = 'ad-overlay'; ad.id = 'late-ad';
                ad.textContent = 'Late advertisement'; document.body.append(ad);
            }, 50);</script></body></html>"""
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    ad_filter = AdFilter(profile)
    loaded: list[bool] = []
    view.loadFinished.connect(loaded.append)
    try:
        url = QUrl(f"http://127.0.0.1:{server.server_port}/")
        for allow in (False, True, False):
            ad_filter.allow_site("127.0.0.1", allow)
            loaded.clear()
            view.load(url)
            pump(lambda: bool(loaded))
            assert loaded[-1]
            pump(lambda: javascript("!!document.getElementById('late-ad')"))
            for element in ("banner", "late-ad"):
                hidden = javascript(
                    f"getComputedStyle(document.getElementById('{element}')).display === 'none'"
                )
                assert hidden == (not allow), (element, allow)
            assert javascript(
                "getComputedStyle(document.getElementById('content')).display !== 'none'"
            )
            assert javascript(
                "getComputedStyle(document.getElementById('dialog')).display !== 'none'"
            )
            javascript("document.getElementById('button').click()")
            assert (
                javascript("document.getElementById('button').textContent") == "Clicked"
            )
        restored = AdFilter(profile, ["127.0.0.1", None, "invalid/path"])
        assert restored.allowed == frozenset({"127.0.0.1"})
    finally:
        profile.setUrlRequestInterceptor(None)
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    main()
