# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""General web tabs, isolated from Anki's privileged webviews."""

from __future__ import annotations

from typing import TYPE_CHECKING

from aqt import gui_hooks
from aqt.qt import *
from aqt.utils import openLink

if TYPE_CHECKING:
    from aqt.ankigpt.focus import FocusSession
    from aqt.main import AnkiQt


def website_url(text: str) -> QUrl | None:
    text = text.strip()
    if not text or any(c.isspace() for c in text):
        return None
    if "://" not in text and ":" not in text:
        text = "https://" + text
    url = QUrl(text)
    if (
        url.isValid()
        and url.scheme() in {"http", "https"}
        and url.host()
        and not url.userInfo()
    ):
        return url
    return None


class WebsitePage(QWebEnginePage):
    def acceptNavigationRequest(
        self,
        url: QUrl,
        navigation_type: QWebEnginePage.NavigationType,
        is_main_frame: bool,
    ) -> bool:
        return url.scheme() in {"http", "https"} or url.toString() == "about:blank"


class WebsiteView(QWebEngineView):
    def __init__(self, owner: BrowserTabs, parent: QWidget) -> None:
        super().__init__(parent)
        self.owner = owner
        self.setPage(WebsitePage(owner.profile, self))

    def createWindow(self, window_type: QWebEnginePage.WebWindowType) -> QWebEngineView:
        return self.owner.new_tab().view


class WebsiteTab(QWidget):
    def __init__(self, owner: BrowserTabs) -> None:
        super().__init__(owner.tabs)
        self.owner = owner
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        self.view = WebsiteView(owner, self)
        row = QHBoxLayout()
        for label, callback in [
            ("Back", self.view.back),
            ("Forward", self.view.forward),
            ("Reload", self.view.reload),
            ("Stop", self.view.stop),
        ]:
            button = QPushButton(label)
            qconnect(button.clicked, callback)
            row.addWidget(button)
        self.address = QLineEdit()
        self.address.setPlaceholderText("Enter a website address")
        self.address.setAccessibleName("Website address")
        qconnect(self.address.returnPressed, self.navigate)
        row.addWidget(self.address, 1)
        self.mute = QCheckBox("Mute tab")
        qconnect(self.mute.toggled, self.view.page().setAudioMuted)
        row.addWidget(self.mute)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.bookmarks = QComboBox()
        row.addWidget(self.bookmarks, 1)
        for label, callback in [
            ("Open bookmark", self.open_bookmark),
            ("Bookmark page", self.add_bookmark),
            ("Remove bookmark", self.remove_bookmark),
            ("Open externally", self.open_external),
        ]:
            button = QPushButton(label)
            qconnect(button.clicked, callback)
            row.addWidget(button)
        layout.addLayout(row)
        self.status = QLabel(
            "Enter an address or open a bookmark. Browser audio continues when you return to Study."
        )
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addWidget(self.view, 1)
        qconnect(self.view.urlChanged, lambda url: self.address.setText(url.toString()))
        qconnect(self.view.titleChanged, self.update_title)
        qconnect(self.view.loadStarted, lambda: self.status.setText("Loading…"))
        qconnect(self.view.loadFinished, self.loaded)
        qconnect(
            self.view.page().windowCloseRequested,
            lambda: owner.close_tab(owner.tabs.indexOf(self)),
        )
        shortcut = QShortcut(QKeySequence("Ctrl+L"), self)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        qconnect(shortcut.activated, self.select_address)
        self.refresh_bookmarks()

    def select_address(self) -> None:
        self.address.setFocus()
        self.address.selectAll()

    def navigate(self) -> None:
        url = website_url(self.address.text())
        if url is None:
            self.status.setText("Enter an HTTP or HTTPS website address.")
            return
        self.view.load(url)

    def loaded(self, ok: bool) -> None:
        self.status.setText(
            ""
            if ok
            else "Could not load this page. Check the address or try Open externally."
        )

    def update_title(self, title: str) -> None:
        index = self.owner.tabs.indexOf(self)
        self.owner.tabs.setTabText(index, (title or "Browser").replace("&", "&&")[:32])
        self.owner.tabs.setTabToolTip(index, title)

    def refresh_bookmarks(self) -> None:
        self.bookmarks.clear()
        for title, url in self.owner.bookmarks():
            self.bookmarks.addItem(title, url)

    def open_bookmark(self) -> None:
        if url := website_url(self.bookmarks.currentData() or ""):
            self.view.load(url)

    def add_bookmark(self) -> None:
        if url := website_url(self.view.url().toString()):
            entries = self.owner.bookmarks()
            value = url.toString()
            if not any(item[1] == value for item in entries):
                entries.append([self.view.title() or value, value])
                self.owner.save_bookmarks(entries)

    def remove_bookmark(self) -> None:
        value = self.bookmarks.currentData()
        self.owner.save_bookmarks(
            [item for item in self.owner.bookmarks() if item[1] != value]
        )

    def open_external(self) -> None:
        if url := website_url(self.view.url().toString()):
            openLink(url.toString())


class BrowserTabs:
    def __init__(self, mw: AnkiQt) -> None:
        self.mw = mw
        self.tabs = QTabWidget(mw)
        self.study = mw.takeCentralWidget()
        self.tabs.addTab(self.study, "Study")
        mw.setCentralWidget(self.tabs)
        self.tabs.setTabsClosable(True)
        self.tabs.tabBar().setTabButton(0, QTabBar.ButtonPosition.RightSide, None)
        self.tabs.tabBar().setTabButton(0, QTabBar.ButtonPosition.LeftSide, None)
        self.profile = QWebEngineProfile(self.tabs)
        # Off-the-record website session, shared between browser tabs only.
        # No Anki API interceptor, injected scripts, or QWebChannel.
        qconnect(self.profile.downloadRequested, self.download)
        self.disabled_shortcuts: list[QShortcut] = []
        self.paused_session: FocusSession | None = None
        self.closed_tabs: list[WebsiteTab] = []
        plus = QPushButton("+ New browser tab")
        qconnect(plus.clicked, lambda: self.new_tab())
        self.tabs.setCornerWidget(plus)
        qconnect(self.tabs.tabCloseRequested, self.close_tab)
        qconnect(self.tabs.currentChanged, self.tab_changed)
        gui_hooks.state_did_change.append(self.state_changed)

    def bookmarks(self) -> list[list[str]]:
        profile = self.mw.pm.profile
        saved = (profile or {}).get(
            "ankigptBrowserBookmarks", [["myNoise", "https://mynoise.net/"]]
        )
        entries = [
            list(item)
            for item in saved
            if isinstance(item, (list, tuple))
            and len(item) == 2
            and all(isinstance(v, str) for v in item)
            and website_url(item[1])
        ]
        # Add the new default once, including profiles with saved bookmarks.
        # Persist the migration so removing the bookmark remains possible.
        if profile is not None and not profile.get("ankigptStudyBookmarkAdded", False):
            url = "https://how-to-study.com/"
            if not any(item[1].rstrip("/") == url.rstrip("/") for item in entries):
                entries.append(["How to Study", url])
            profile["ankigptBrowserBookmarks"] = entries
            profile["ankigptStudyBookmarkAdded"] = True
        return entries

    def save_bookmarks(self, entries: list[list[str]]) -> None:
        if self.mw.pm.profile is not None:
            self.mw.pm.profile["ankigptBrowserBookmarks"] = entries
        for index in range(1, self.tabs.count()):
            tab = self.tabs.widget(index)
            if isinstance(tab, WebsiteTab):
                tab.refresh_bookmarks()

    def new_tab(self, url: str = "") -> WebsiteTab:
        tab = WebsiteTab(self)
        self.tabs.addTab(tab, "Browser")
        self.tabs.setCurrentWidget(tab)
        if target := website_url(url):
            tab.view.load(target)
        else:
            tab.select_address()
        return tab

    def close_tab(self, index: int) -> None:
        if index <= 0:
            return
        tab = self.tabs.widget(index)
        self.tabs.removeTab(index)
        if isinstance(tab, WebsiteTab):
            tab.view.stop()
            tab.view.page().setAudioMuted(True)
            self.closed_tabs.append(tab)
            tab.deleteLater()

    def tab_changed(self, _index: int = 0) -> None:
        from aqt.ankigpt import audio, focus

        browsing = self.tabs.currentIndex() > 0
        if browsing:
            if self.mw.state == "review":
                self.mw.reviewer._clear_auto_advance_timers()
                self.mw.reviewer.ankigpt._cancel_auto_submit()
            for shortcut in self.mw.findChildren(
                QShortcut, options=Qt.FindChildOption.FindDirectChildrenOnly
            ):
                if shortcut.isEnabled():
                    shortcut.setEnabled(False)
                    self.disabled_shortcuts.append(shortcut)
            if (session := focus.current()) and session.paused_at is None:
                self.paused_session = session
                session.pause()
                audio.focus_paused()
        else:
            for shortcut in self.disabled_shortcuts:
                if not sip.isdeleted(shortcut):
                    shortcut.setEnabled(True)
            self.disabled_shortcuts.clear()
            if (
                self.paused_session is not None
                and focus.current() is self.paused_session
            ):
                self.paused_session.resume()
                audio.focus_resumed()
            self.paused_session = None
        if self.mw.state == "review" and focus.current() is not None:
            self.mw.reviewer.ankigpt._sync_focus_bar()

    def state_changed(self, _state: str, _old: str) -> None:
        self.tab_changed()

    def download(self, request: QWebEngineDownloadRequest) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self.mw, "Save download", request.downloadFileName()
        )
        if not path:
            request.cancel()
            return
        info = QFileInfo(path)
        request.setDownloadDirectory(info.absolutePath())
        request.setDownloadFileName(info.fileName())
        request.accept()

    def dispose(self) -> None:
        self.tabs.setCurrentIndex(0)
        gui_hooks.state_did_change.remove(self.state_changed)
        for index in range(self.tabs.count() - 1, 0, -1):
            tab = self.tabs.widget(index)
            self.tabs.removeTab(index)
            if isinstance(tab, WebsiteTab):
                tab.view.stop()
                # Destroy pages before their profile, including audio renderers.
                sip.delete(tab)
        for tab in self.closed_tabs:
            if not sip.isdeleted(tab):
                sip.delete(tab)
        self.tabs.removeTab(0)
        self.study.setParent(self.mw)
        self.mw.takeCentralWidget()
        self.mw.setCentralWidget(self.study)
        sip.delete(self.profile)
        self.tabs.deleteLater()


_browser: BrowserTabs | None = None


def show_browser(mw: AnkiQt, url: str = "") -> None:
    global _browser
    if mw.pm.profile is None:
        return
    if _browser is None:
        _browser = BrowserTabs(mw)
    _browser.new_tab(url)


def close_browser() -> None:
    global _browser
    if _browser is not None:
        _browser.dispose()
        _browser = None
