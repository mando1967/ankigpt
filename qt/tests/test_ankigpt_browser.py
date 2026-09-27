# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from unittest.mock import MagicMock, patch

import pytest

from aqt.ankigpt import browser, focus
from aqt.ankigpt.browser import (
    BrowserTabs,
    WebsiteTab,
    WebsiteView,
    browser_url,
    builtin_bookmarks,
    guide_url,
    website_url,
)


@pytest.mark.parametrize(
    "address, expected",
    [
        ("mynoise.net", "https://mynoise.net"),
        (" https://example.org/page?q=1#part ", "https://example.org/page?q=1#part"),
        ("http://localhost:8000", "http://localhost:8000"),
    ],
)
def test_website_addresses(address: str, expected: str) -> None:
    url = website_url(address)
    assert url is not None and url.toString() == expected


@pytest.mark.parametrize(
    "address",
    [
        "",
        "not a website",
        "javascript:alert(1)",
        "file:///C:/private.txt",
        "file:///C:/%00",
        "data:text/html,test",
        "anki://anything",
        "https://user:pass@example.org",
        "https://",
    ],
)
def test_browser_rejects_non_web_addresses(address: str) -> None:
    assert website_url(address) is None
    assert browser_url(address) is None


def test_guide_navigation_is_limited_to_bundled_document() -> None:
    url = guide_url()
    assert browser_url(url.toString()) == url
    url.setFragment("create-course")
    assert browser_url(url.toString()) == url
    assert (
        browser_url(guide_url().toString().replace("index.html", "other.html")) is None
    )
    assert browser_url(guide_url().toString() + "?file=private") is None
    screenshot = guide_url().toString().replace("index.html", "images/01-deck-list.png")
    assert browser_url(screenshot) is not None
    assert (
        browser_url(screenshot.replace("01-deck-list.png", "../../browser.py")) is None
    )


@pytest.mark.parametrize("saved", [None, [["Custom", "https://example.org/"]]])
def test_guide_bookmark_available_without_persisting_install_path(
    saved: object,
) -> None:
    owner = BrowserTabs.__new__(BrowserTabs)
    owner.mw = MagicMock()
    owner.mw.pm.profile = {} if saved is None else {"ankigptBrowserBookmarks": saved}
    owner.tabs = MagicMock()
    owner.tabs.count.return_value = 1
    entries = owner.bookmarks()
    assert entries[0] == ["AnkiGPT How To", guide_url().toString()]
    owner.save_bookmarks(entries)
    assert all(
        not url.startswith("file:")
        for _, url in owner.mw.pm.profile["ankigptBrowserBookmarks"]
    )
    assert owner.bookmarks() == entries


@pytest.mark.parametrize("already_paused", [False, True])
def test_switching_tabs_preserves_focus_breaks_and_syncs_timer(
    already_paused: bool,
) -> None:
    owner = BrowserTabs.__new__(BrowserTabs)
    owner.mw = MagicMock()
    owner.mw.state = "review"
    owner.mw.findChildren.return_value = []
    owner.tabs = MagicMock()
    owner.disabled_shortcuts = []
    owner.paused_session = None
    session = focus.start(5, 10)
    try:
        if already_paused:
            session.pause()
        owner.tabs.currentIndex.return_value = 1
        owner.tab_changed()
        assert session.paused_at is not None
        owner.mw.reviewer._clear_auto_advance_timers.assert_called_once()
        owner.mw.reviewer.ankigpt._cancel_auto_submit.assert_called_once()
        owner.tabs.currentIndex.return_value = 0
        owner.tab_changed()
        assert (session.paused_at is not None) == already_paused
        assert owner.mw.reviewer.ankigpt._sync_focus_bar.call_count == 2
    finally:
        focus.stop()


def test_builtins_restore_old_profiles_without_duplicates() -> None:
    owner = BrowserTabs.__new__(BrowserTabs)
    owner.mw = MagicMock()
    owner.mw.pm.profile = {
        "ankigptStudyBookmarkAdded": True,
        "ankigptBrowserBookmarks": [
            ["Old myNoise", "https://mynoise.net"],
            ["My site", "https://example.org/"],
        ],
    }
    owner.tabs = MagicMock()
    owner.tabs.count.return_value = 1
    entries = owner.bookmarks()
    assert entries == builtin_bookmarks() + [["My site", "https://example.org/"]]
    owner.save_bookmarks(entries)
    assert owner.mw.pm.profile["ankigptBrowserBookmarks"] == [
        ["My site", "https://example.org/"]
    ]


@pytest.mark.parametrize("title,url", builtin_bookmarks())
def test_builtins_cannot_be_deleted(title: str, url: str) -> None:
    tab = MagicMock()
    tab.bookmarks.currentData.return_value = url
    tab.bookmarks.currentText.return_value = title
    with patch.object(browser, "askUser") as confirm:
        WebsiteTab.remove_bookmark(tab)
    confirm.assert_not_called()
    tab.owner.save_bookmarks.assert_not_called()
    WebsiteTab.update_bookmark_actions(tab)
    tab.remove_bookmark_button.setEnabled.assert_called_with(False)


@pytest.mark.parametrize("confirmed", [False, True])
def test_user_bookmark_deletion_requires_confirmation(confirmed: bool) -> None:
    tab = MagicMock()
    tab.bookmarks.currentData.return_value = "https://example.org/"
    tab.bookmarks.currentText.return_value = "My site"
    tab.owner.bookmarks.return_value = builtin_bookmarks() + [
        ["My site", "https://example.org/"]
    ]
    WebsiteTab.update_bookmark_actions(tab)
    tab.remove_bookmark_button.setEnabled.assert_called_with(True)
    with patch.object(browser, "askUser", return_value=confirmed) as confirm:
        WebsiteTab.remove_bookmark(tab)
    assert confirm.call_args.kwargs["defaultno"] is True
    assert "My site" in confirm.call_args.args[0]
    if confirmed:
        tab.owner.save_bookmarks.assert_called_once_with(builtin_bookmarks())
    else:
        tab.owner.save_bookmarks.assert_not_called()


@pytest.mark.parametrize("requested", ["", "https://mynoise.net/"])
def test_first_browser_open_defaults_to_guide_and_preserves_explicit_urls(
    requested: str,
) -> None:
    mw = MagicMock()
    with (
        patch.object(browser, "_browser", None),
        patch.object(browser, "BrowserTabs") as tabs,
    ):
        browser.show_browser(mw, requested)
        tabs.return_value.new_tab.assert_called_once_with(
            requested or guide_url().toString()
        )
        browser.show_browser(mw)
        assert tabs.return_value.new_tab.call_args.args == ("",)


@pytest.mark.parametrize("user_initiated", [False, True])
@pytest.mark.parametrize("background", [False, True])
def test_popup_requests_require_user_action(
    user_initiated: bool, background: bool
) -> None:
    from aqt.qt import QUrl, QWebEngineNewWindowRequest

    view = MagicMock()
    request = MagicMock()
    request.isUserInitiated.return_value = user_initiated
    request.requestedUrl.return_value = QUrl("https://example.org/")
    request.destination.return_value = (
        QWebEngineNewWindowRequest.DestinationType.InNewBackgroundTab
        if background
        else QWebEngineNewWindowRequest.DestinationType.InNewTab
    )
    WebsiteView.open_requested_window(view, request)
    if user_initiated:
        view.owner.new_tab.assert_called_once_with(background=background)
        request.openIn.assert_called_once_with(
            view.owner.new_tab.return_value.view.page()
        )
    else:
        view.owner.new_tab.assert_not_called()
        request.openIn.assert_not_called()


@pytest.mark.parametrize(
    "url", ["javascript:alert(1)", "file:///C:/private.txt", "data:text/html,test"]
)
def test_popup_user_action_does_not_bypass_url_restrictions(url: str) -> None:
    from aqt.qt import QUrl

    view = MagicMock()
    request = MagicMock()
    request.isUserInitiated.return_value = True
    request.requestedUrl.return_value = QUrl(url)
    WebsiteView.open_requested_window(view, request)
    view.owner.new_tab.assert_not_called()
    request.openIn.assert_not_called()


@pytest.mark.parametrize(
    "url,first_party,main_frame,allowed,blocked",
    [
        (
            "https://pagead2.googlesyndication.com/ad.js",
            "https://example.org",
            False,
            [],
            True,
        ),
        ("https://doubleclick.net/ad", "https://example.org", False, [], True),
        ("https://notdoubleclick.net/ad", "https://example.org", False, [], False),
        (
            "https://doubleclick.net.example.org/ad",
            "https://example.org",
            False,
            [],
            False,
        ),
        (
            "https://example.org/doubleclick.net/ad",
            "https://example.org",
            False,
            [],
            False,
        ),
        ("https://doubleclick.net/ad", "https://example.org", True, [], False),
        (
            "https://doubleclick.net/ad",
            "https://example.org",
            False,
            ["example.org"],
            False,
        ),
        (
            "https://doubleclick.net/ad",
            "https://other.org",
            False,
            ["example.org"],
            True,
        ),
        ("https://cdn.example.org/audio.mp3", "https://example.org", False, [], False),
    ],
)
def test_ad_requests(url, first_party, main_frame, allowed, blocked) -> None:
    from aqt.ankigpt.adfilter import AdFilter
    from aqt.qt import QUrl, QWebEngineUrlRequestInfo

    interceptor = MagicMock()
    interceptor.allowed = frozenset(allowed)
    request = MagicMock()
    request.requestUrl.return_value = QUrl(url)
    request.firstPartyUrl.return_value = QUrl(first_party)
    request.resourceType.return_value = (
        QWebEngineUrlRequestInfo.ResourceType.ResourceTypeMainFrame
        if main_frame
        else QWebEngineUrlRequestInfo.ResourceType.ResourceTypeScript
    )
    AdFilter.interceptRequest(interceptor, request)
    if blocked:
        request.block.assert_called_once_with(True)
    else:
        request.block.assert_not_called()


def test_ad_exception_saved_to_profile() -> None:
    owner = BrowserTabs.__new__(BrowserTabs)
    owner.mw = MagicMock()
    owner.mw.pm.profile = {}
    owner.tabs = MagicMock()
    owner.tabs.count.return_value = 1
    owner.ad_filter = MagicMock()
    owner.ad_filter.allowed = frozenset({"example.org"})
    owner.set_allow_ads("example.org", True)
    owner.ad_filter.allow_site.assert_called_once_with("example.org", True)
    assert owner.mw.pm.profile["ankigptBrowserAllowAds"] == ["example.org"]
