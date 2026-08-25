# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""AnkiGPT: LLM-generated questions over FSRS-scheduled concept notes.

This package is the only place the fork adds code; the rest of Anki is
touched in a handful of one-line hooks. See qt/aqt/ankigpt/review.py for the
reviewer integration and generate_dialog.py for deck creation.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

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
    gui_hooks.profile_will_close.append(_close_store)


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
