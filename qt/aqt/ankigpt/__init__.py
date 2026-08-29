# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""AnkiGPT: LLM-generated questions over FSRS-scheduled concept notes.

This package is the only place the fork adds code; the rest of Anki is
touched in a handful of one-line hooks. See qt/aqt/ankigpt/review.py for the
reviewer integration and generate_dialog.py for deck creation.
"""

from __future__ import annotations

import html
import json
import os
import re
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote

from anki.collection import SearchNode
from anki.decks import DeckId
from anki.notes import NoteId
from anki.utils import split_fields
from aqt import gui_hooks
from aqt.qt import *
from aqt.utils import tr

if TYPE_CHECKING:
    from aqt.ankigpt.store import Store
    from aqt.main import AnkiQt

STORE_FILENAME = "ankigpt.sqlite"
_store: Store | None = None
_menu: QMenu | None = None
_shell_route = "home"
_shell_notice = ""


def show_shell_route(mw: AnkiQt, route: str) -> None:
    """Open a destination in the unified shell from native shortcuts/actions."""
    global _shell_route
    _shell_route = route
    if mw.state == "deckBrowser":
        mw.deckBrowser.refresh()
    else:
        mw.moveToState("deckBrowser")


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

    global _menu
    menu = _menu = QMenu(tr.ankigpt_menu(), mw)
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
    _install_study_hub(mw)
    _install_shell_chrome(mw)
    _install_deck_badges(mw)
    _install_help(mw)
    gui_hooks.profile_did_open.append(lambda: _refresh_notetype_css(mw))
    gui_hooks.profile_did_open.append(lambda: _migrate_api_credential(mw))
    gui_hooks.profile_will_close.append(_close_store)


def _migrate_api_credential(mw: AnkiQt) -> None:
    from aqt.ankigpt.settings import migrate_profile_credential
    from aqt.utils import tooltip

    if error := migrate_profile_credential(mw.pm):
        tooltip(tr.ankigpt_secure_storage_failed(error=error), parent=mw, period=12000)


_BADGE_RE = re.compile(r"""(onclick="return pycmd\('open:(\d+)'\)">)(.*?)(</a>)""")


def badge_deck_tree(tree: str, concept_decks: set[int], label: str) -> str:
    """Append an AI badge to concept decks in the deck browser's tree HTML."""
    if not concept_decks:
        return tree
    badge = (
        ' <span class="ankigpt-badge" style="font-size:0.7em;font-weight:bold;'
        "color:#fff;background:#4a90d9;border-radius:4px;padding:1px 5px;"
        f'vertical-align:middle;">{html.escape(label)}</span>'
    )

    def repl(m: re.Match[str]) -> str:
        if int(m.group(2)) in concept_decks:
            return f"{m.group(1)}{m.group(3)}{badge}{m.group(4)}"
        return m.group(0)

    return _BADGE_RE.sub(repl, tree)


def _install_deck_badges(mw: AnkiQt) -> None:
    from aqt.ankigpt.concepts import concept_deck_ids
    from aqt.deckbrowser import DeckBrowser, DeckBrowserContent

    def on_render(_browser: DeckBrowser, content: DeckBrowserContent) -> None:
        try:
            ids = concept_deck_ids(mw.col)
        except Exception:
            return
        content.tree = badge_deck_tree(content.tree, ids, tr.ankigpt_deck_badge())

    gui_hooks.deck_browser_will_render_content.append(on_render)


def _install_help(mw: AnkiQt) -> None:
    from aqt.ankigpt.help import show_guide

    action = QAction(tr.ankigpt_menu_help(), mw)
    qconnect(action.triggered, lambda: show_guide(mw))
    mw.form.menuHelp.insertAction(mw.form.actionAbout, action)
    if _menu is not None:
        _menu.addSeparator()
        _menu.addAction(action)


def _refresh_notetype_css(mw: AnkiQt) -> None:
    """Keep the concept notetype's styling current for existing collections."""
    from aqt.ankigpt.concepts import NOTETYPE_NAME, ensure_notetype

    try:
        if mw.col and mw.col.models.by_name(NOTETYPE_NAME):
            ensure_notetype(mw.col)
    except Exception:
        pass


def create_concept_deck(mw: AnkiQt) -> None:
    from aqt.ankigpt.generate_dialog import CreateConceptDeckDialog

    CreateConceptDeckDialog(mw)


def _install_deck_browser_button(mw: AnkiQt) -> None:
    """An 'AI Concept Deck' button next to Create Deck / Import File."""
    from aqt.deckbrowser import DeckBrowser, DeckBrowserBottomBar

    entry = ["", "ankigpt", tr.ankigpt_create_deck_button()]
    if entry not in DeckBrowser.drawLinks:
        DeckBrowser.drawLinks.insert(2, entry)

    def on_js_message(  # noqa: PLR0911 - bridge commands are intentionally explicit
        handled: tuple[bool, Any], message: str, context: Any
    ) -> tuple[bool, Any]:
        if message == "ankigpt" and isinstance(
            context, (DeckBrowser, DeckBrowserBottomBar)
        ):
            create_concept_deck(mw)
            return (True, None)
        if message.startswith("ankigpt:route:") and isinstance(context, DeckBrowser):
            global _shell_route
            route = message.removeprefix("ankigpt:route:")
            if route in {
                "home",
                "concepts",
                "library",
                "add",
                "progress",
                "settings",
                "system",
            } or route.startswith(("concept:", "course:", "note:")):
                _shell_route = route
                context.refresh()
            return (True, None)
        if message.startswith("ankigpt:study:") and isinstance(context, DeckBrowser):
            _start_study_from_shell(mw, context, message)
            return (True, None)
        if message.startswith("ankigpt:course-sources:") and isinstance(
            context, DeckBrowser
        ):
            from aqt.ankigpt.sources import show_sources

            try:
                deck_id = DeckId(int(message.rsplit(":", 1)[1]))
            except ValueError:
                return (True, None)
            show_sources(mw, deck_id)
            return (True, None)
        if message.startswith("ankigpt:delete-course:") and isinstance(
            context, DeckBrowser
        ):
            _delete_course_from_shell(mw, context, message)
            return (True, None)
        if message.startswith("ankigpt:save-concept:") and isinstance(
            context, DeckBrowser
        ):
            _save_concept_from_shell(mw, context, message)
            return (True, None)
        if message.startswith("ankigpt:save-note:") and isinstance(
            context, DeckBrowser
        ):
            _save_note_from_shell(mw, context, message)
            return (True, None)
        if message.startswith("ankigpt:add-card:") and isinstance(context, DeckBrowser):
            _add_card_from_shell(mw, context, message)
            return (True, None)
        if message.startswith("ankigpt:save-settings:") and isinstance(
            context, DeckBrowser
        ):
            _save_settings_from_shell(mw, context, message)
            return (True, None)
        if message == "ankigpt:test-settings" and isinstance(context, DeckBrowser):
            _test_shell_settings(mw, context)
            return (True, None)
        if message.startswith("ankigpt:system:") and isinstance(context, DeckBrowser):
            action = message.removeprefix("ankigpt:system:")
            if action == "sync":
                mw.on_sync_button_clicked()
            elif action == "backup":
                mw.on_create_backup_now()
            elif action == "switch-profile":
                mw.unloadProfileAndShowProfileManager()
            elif action == "check-db":
                mw.onCheckDB()
            elif action == "check-media":
                mw.on_check_media_db()
            elif action == "import":
                mw.onImport()
            elif action == "export":
                mw.onExport()
            return (True, None)
        return handled

    gui_hooks.webview_did_receive_js_message.append(on_js_message)


def _install_study_hub(mw: AnkiQt) -> None:
    from aqt.ankigpt.study_hub import render_study_hub
    from aqt.deckbrowser import DeckBrowser, DeckBrowserContent

    def on_render(browser: DeckBrowser, content: DeckBrowserContent) -> None:
        content.tree = render_study_hub(
            browser._render_data.tree,
            browser._render_data.studied_today,
            _shell_route,
            _concept_records(mw),
            _note_records(mw),
            _shell_settings(mw),
            _shell_notice,
        )
        content.stats = ""

    gui_hooks.deck_browser_will_render_content.append(on_render)


def _start_study_from_shell(mw: AnkiQt, browser: object, message: str) -> None:
    """Select the course and enter the scheduler without showing legacy Overview."""
    from aqt.operations.deck import set_current_deck

    try:
        deck_id = DeckId(int(message.rsplit(":", 1)[1]))
    except ValueError:
        return

    def start(_changes: object) -> None:
        mw.col.startTimebox()
        mw.moveToState("review")

    set_current_deck(parent=mw, deck_id=deck_id).success(start).run_in_background(
        initiator=browser
    )


def _delete_course_from_shell(mw: AnkiQt, browser: object, message: str) -> None:
    """Confirm and remove a course through Anki's undoable deck operation."""
    from aqt.operations.deck import remove_decks
    from aqt.utils import askUser

    try:
        deck_id = DeckId(int(message.rsplit(":", 1)[1]))
    except ValueError:
        return
    deck_name = mw.col.decks.name_if_exists(deck_id)
    if not deck_name:
        return
    if not askUser(
        f'Delete the course “{deck_name}”?\n\n'
        "Its cards and any subdecks will also be removed. You can undo this "
        "immediately from the Edit menu.",
        parent=mw,
        defaultno=True,
    ):
        return

    def done(_changes: object) -> None:
        global _shell_route
        _shell_route = "home"
        browser.refresh()  # type: ignore[attr-defined]

    remove_decks(parent=mw, deck_ids=[deck_id], deck_name=deck_name).success(
        done
    ).run_in_background(initiator=browser)


def _shell_settings(mw: AnkiQt) -> dict[str, Any]:
    from aqt.ankigpt.settings import llm_config, provider_id

    config = llm_config(mw.pm)
    return {
        "provider": provider_id(mw.pm),
        "configured": config.configured,
        "model": config.model,
        "base_url": config.base_url,
        "timeout": config.timeout_secs,
        "max_chars": config.max_chars_per_file,
    }


def _save_settings_from_shell(mw: AnkiQt, browser: object, message: str) -> None:
    from aqt.ankigpt.llm import LLMConfig
    from aqt.ankigpt.settings import (
        llm_config,
        set_llm_config,
        set_provider_id,
    )

    global _shell_notice
    try:
        payload = json.loads(unquote(message.split(":", 2)[2]))
        current = llm_config(mw.pm)
        provider = str(payload["provider"])
        if provider not in {"openai", "openai-compatible"}:
            raise ValueError("unsupported provider")
        config = LLMConfig(
            api_key=str(payload.get("key") or current.api_key).strip(),
            base_url=str(payload["base_url"]).strip(),
            model=str(payload["model"]).strip(),
            timeout_secs=max(5, min(600, int(payload["timeout"]))),
            max_chars_per_file=max(10_000, min(5_000_000, int(payload["max_chars"]))),
        )
        if not config.base_url or not config.model:
            raise ValueError("model and base URL are required")
        set_llm_config(mw.pm, config)
        set_provider_id(mw.pm, provider)
        mw.pm.save()
        _shell_notice = "Settings saved securely."
    except Exception as exc:
        _shell_notice = f"Settings were not saved: {exc}"
    browser.refresh()  # type: ignore[attr-defined]


def _test_shell_settings(mw: AnkiQt, browser: object) -> None:
    from aqt.ankigpt.llm import test_connection
    from aqt.ankigpt.settings import llm_config
    from aqt.operations import QueryOp

    def done(result: object) -> None:
        global _shell_notice
        message = getattr(result, "message", "Connection test finished.")
        details = getattr(result, "technical_details", "")
        _shell_notice = str(message) + (f" ({details})" if details else "")
        browser.refresh()  # type: ignore[attr-defined]

    QueryOp(
        parent=mw,
        op=lambda _col: test_connection(llm_config(mw.pm)),
        success=done,
    ).without_collection().run_in_background()


def _concept_records(mw: AnkiQt) -> list[tuple[int, str, str, list[str]]]:
    from aqt.ankigpt.concepts import (
        NOTETYPE_NAME,
        field_to_lines,
        field_to_text,
    )

    notetype = mw.col.models.by_name(NOTETYPE_NAME)
    if not notetype:
        return []
    rows = mw.col.db.all(
        "select id, flds from notes where mid = ? order by id", notetype["id"]
    )
    records = []
    for note_id, packed_fields in rows:
        fields = split_fields(packed_fields)
        if len(fields) < 3:
            continue
        records.append(
            (
                int(note_id),
                field_to_text(fields[0]),
                field_to_text(fields[1]),
                field_to_lines(fields[2]),
            )
        )
    return records


def _note_records(mw: AnkiQt) -> list[dict[str, Any]]:
    """Return a bounded, newest-first view of notes for the shell library."""
    note_ids = [
        int(row[0])
        for row in mw.col.db.all("select id from notes order by id desc limit 500")
    ]
    records: list[dict[str, Any]] = []
    for note_id in note_ids:
        try:
            note = mw.col.get_note(NoteId(note_id))
            cards = note.cards()
            deck_name = (
                mw.col.decks.name(cards[0].current_deck_id()) if cards else "No course"
            )
            fields = [(name, note[name]) for name in note.keys()]
            preview_source = fields[0][1] if fields else "Untitled note"
            preview = re.sub(r"<[^>]+>", " ", preview_source)
            preview = html.unescape(" ".join(preview.split()))[:140] or "Untitled note"
            records.append(
                {
                    "id": note_id,
                    "deck": deck_name,
                    "notetype": str(note.note_type()["name"]),
                    "preview": preview,
                    "fields": fields,
                }
            )
        except Exception:
            continue
    return records


def _save_note_from_shell(mw: AnkiQt, browser: object, message: str) -> None:
    from anki.collection import Collection
    from aqt.operations import CollectionOp

    try:
        payload = json.loads(unquote(message.split(":", 2)[2]))
        note_id = NoteId(int(payload["nid"]))
        fields = payload["fields"]
        if not isinstance(fields, dict):
            return
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return

    def save(col: Collection):
        note = col.get_note(note_id)
        for name in note.keys():
            if name in fields:
                note[name] = str(fields[name])
        return col.update_note(note)

    def done(_changes: object) -> None:
        global _shell_route
        _shell_route = "library"
        browser.refresh()  # type: ignore[attr-defined]

    CollectionOp(parent=mw, op=save).success(done).run_in_background()


def _add_card_from_shell(mw: AnkiQt, browser: object, message: str) -> None:
    from anki.collection import Collection
    from aqt.operations import CollectionOp

    try:
        payload = json.loads(unquote(message.split(":", 2)[2]))
        deck_id = DeckId(int(payload["deck_id"]))
        front = str(payload["front"]).strip()
        back = str(payload["back"]).strip()
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return
    if not front:
        return

    def add(col: Collection):
        notetype = col.models.by_name("Basic") or col.models.current()
        note = col.new_note(notetype)
        keys = note.keys()
        if not keys:
            raise ValueError("The selected note type has no fields")
        note[keys[0]] = front
        if len(keys) > 1:
            note[keys[1]] = back
        return col.add_note(note, deck_id)

    def done(_changes: object) -> None:
        global _shell_route
        _shell_route = "library"
        browser.refresh()  # type: ignore[attr-defined]

    CollectionOp(parent=mw, op=add).success(done).run_in_background()


def _save_concept_from_shell(mw: AnkiQt, browser: object, message: str) -> None:
    from anki.collection import Collection
    from aqt.ankigpt.concepts import points_to_field
    from aqt.operations import CollectionOp

    try:
        payload = json.loads(unquote(message.split(":", 2)[2]))
        note_id = NoteId(int(payload["nid"]))
        title = str(payload["title"]).strip()
        summary = str(payload["summary"]).strip()
        points = [
            line.strip() for line in str(payload["points"]).splitlines() if line.strip()
        ]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return
    if not title or not summary:
        return

    def save(col: Collection):
        note = col.get_note(note_id)
        note["Title"] = html.escape(title)
        note["Summary"] = html.escape(summary)
        note["KeyPoints"] = points_to_field(points)
        return col.update_note(note)

    def done(_changes: object) -> None:
        global _shell_route
        _shell_route = "concepts"
        browser.refresh()  # type: ignore[attr-defined]

    CollectionOp(parent=mw, op=save).success(done).run_in_background()


def _install_shell_chrome(mw: AnkiQt) -> None:
    """Keep legacy Anki chrome out of the primary AnkiGPT experience."""

    def update(state: str, _old_state: str) -> None:
        if state == "deckBrowser":
            mw.toolbarWeb.hide()
            mw.bottomWeb.hide()
            mw.form.menubar.hide()
        elif state != "deckBrowser":
            mw.toolbarWeb.show()
            mw.bottomWeb.show()
            mw.form.menubar.show()

    def after_render(_browser: object) -> None:
        mw.bottomWeb.hide()

    gui_hooks.state_did_change.append(update)
    gui_hooks.deck_browser_did_render.append(after_render)


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
