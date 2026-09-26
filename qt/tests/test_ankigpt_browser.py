# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from unittest.mock import MagicMock

import pytest

from aqt.ankigpt import focus
from aqt.ankigpt.browser import BrowserTabs, website_url


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
        "data:text/html,test",
        "anki://anything",
        "https://user:pass@example.org",
        "https://",
    ],
)
def test_browser_rejects_non_web_addresses(address: str) -> None:
    assert website_url(address) is None


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
