# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""AnkiGPT: LLM-generated questions over FSRS-scheduled concept notes.

This package is the only place the fork adds code; the rest of Anki is
touched in a handful of one-line hooks. See qt/aqt/ankigpt/review.py for the
reviewer integration and generate_dialog.py for deck creation.
"""

from __future__ import annotations

import html
import os
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from anki.collection import SearchNode
from anki.decks import DeckId
from aqt import gui_hooks
from aqt.qt import *
from aqt.utils import tr

if TYPE_CHECKING:
    from aqt.ankigpt.store import Store
    from aqt.main import AnkiQt

STORE_FILENAME = "ankigpt.sqlite"
_store: Store | None = None


def get_store() -> Store:
    """The sidecar database for the open profile."""
    global _store
    if _store is None:
        from aqt import mw
        from aqt.ankigpt.store import Store

        assert mw is not None and mw.pm.profile is not None
        _store = Store(os.path.join(mw.pm.profileFolder(), STORE_FILENAME))
    return _store


def _close_store() -> None:
    global _store
    if _store is not None:
        _store.close()
        _store = None


def install(mw: AnkiQt) -> None:
    """Add menu entries and hooks. Called once from AnkiQt setup."""
    from aqt.ankigpt.generate_dialog import CreateConceptDeckDialog, open_deck_settings

    menu = QMenu(tr.ankigpt_menu(), mw)
    create_action = QAction(tr.ankigpt_menu_create_deck(), mw)
    qconnect(create_action.triggered, lambda: CreateConceptDeckDialog(mw))
    menu.addAction(create_action)
    settings_action = QAction(tr.ankigpt_menu_deck_settings(), mw)
    qconnect(settings_action.triggered, lambda: open_deck_settings(mw))
    menu.addAction(settings_action)
    mw.form.menuTools.insertMenu(mw.form.actionPreferences, menu)

    def on_deck_options_menu(deck_menu: QMenu, deck_id: int) -> None:
        if not deck_has_concepts(mw, DeckId(deck_id)):
            return
        action = deck_menu.addAction(tr.ankigpt_menu_deck_settings())
        assert action is not None
        qconnect(action.triggered, lambda: open_deck_settings(mw, DeckId(deck_id)))

    gui_hooks.deck_browser_will_show_options_menu.append(on_deck_options_menu)
    _install_deck_browser_button(mw)
    _install_overview(mw)
    gui_hooks.profile_will_close.append(_close_store)


def create_concept_deck(mw: AnkiQt) -> None:
    from aqt.ankigpt.generate_dialog import CreateConceptDeckDialog

    CreateConceptDeckDialog(mw)


def _install_deck_browser_button(mw: AnkiQt) -> None:
    """An 'AI Concept Deck' button next to Create Deck / Import File."""
    from aqt.deckbrowser import DeckBrowser, DeckBrowserBottomBar

    entry = ["", "ankigpt", tr.ankigpt_create_deck_button()]
    if entry not in DeckBrowser.drawLinks:
        DeckBrowser.drawLinks.insert(2, entry)

    def on_js_message(
        handled: tuple[bool, Any], message: str, context: Any
    ) -> tuple[bool, Any]:
        if message == "ankigpt" and isinstance(context, DeckBrowserBottomBar):
            create_concept_deck(mw)
            return (True, None)
        return handled

    gui_hooks.webview_did_receive_js_message.append(on_js_message)


def _install_overview(mw: AnkiQt) -> None:
    """Badge + settings button on the overview of a concept deck."""
    from aqt.ankigpt.settings import deck_settings, mode_label
    from aqt.overview import Overview, OverviewContent

    def on_render_content(overview: Overview, content: OverviewContent) -> None:
        deck_id = DeckId(mw.col.decks.current()["id"])
        if not deck_has_concepts(mw, deck_id):
            return
        settings = deck_settings(mw.col, deck_id)
        badge = (
            '<div class="ankigpt-overview">'
            f"<b>{html.escape(tr.ankigpt_overview_badge())}</b> &middot; "
            f"{html.escape(tr.ankigpt_grading_mode())}: "
            f"{html.escape(mode_label(settings.mode))}"
            "</div>"
        )
        content.desc = badge + content.desc

    def on_render_bottom(
        link_handler: Callable[[str], bool], links: list[list[str]]
    ) -> Callable[[str], bool]:
        deck_id = DeckId(mw.col.decks.current()["id"])
        if not deck_has_concepts(mw, deck_id):
            return link_handler
        links.append(["", "ankigpt_settings", tr.ankigpt_concept_settings_button()])

        def handler(url: str) -> bool:
            if url == "ankigpt_settings":
                from aqt.ankigpt.generate_dialog import open_deck_settings

                open_deck_settings(mw, deck_id)
                mw.overview.refresh()
                return True
            return link_handler(url)

        return handler

    gui_hooks.overview_will_render_content.append(on_render_content)
    gui_hooks.overview_will_render_bottom.append(on_render_bottom)


def deck_has_concepts(mw: AnkiQt, deck_id: DeckId) -> bool:
    from aqt.ankigpt.concepts import NOTETYPE_NAME
    from aqt.ankigpt.settings import has_deck_settings

    if has_deck_settings(mw.col, deck_id):
        return True
    name = mw.col.decks.name_if_exists(deck_id)
    if not name:
        return False
    search = mw.col.build_search_string(
        SearchNode(deck=name), SearchNode(note=NOTETYPE_NAME)
    )
    return bool(mw.col.find_cards(search))
