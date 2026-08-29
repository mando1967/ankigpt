# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""End-to-end smoke test for AnkiGPT that boots the real desktop app offscreen.

Usage (from the repo root, after `just build`):

    out/pyenv/bin/python tools/ankigpt_smoke.py /tmp/ankigpt-smoke-base

It creates a concept deck, reviews it in typed and multiple-choice mode
through the real Reviewer (including the webview bridge), and checks the
sidecar store. Uses the fake LLM, so no network is needed. Exit code 0 means
every step passed.
"""

from __future__ import annotations

import faulthandler
import json
import os
import shutil
import sys
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote

os.environ["ANKIGPT_FAKE_LLM"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
sys.path.extend(["pylib", "qt", "out/pylib", "out/qt"])

import aqt  # noqa: E402
from aqt.profiles import ProfileManager  # noqa: E402

BASE = sys.argv[1] if len(sys.argv) > 1 else "/tmp/ankigpt-smoke-base"
STEPS: list[str] = []


def step(name: str) -> None:
    STEPS.append(name)
    print(f"[smoke] {name}", flush=True)


def seed_base() -> None:
    """A brand-new base dir triggers a modal language dialog in aqt._run."""
    shutil.rmtree(BASE, ignore_errors=True)
    os.makedirs(BASE, exist_ok=True)
    pm = ProfileManager(Path(BASE))
    pm.setupMeta()
    pm.setLang("en_US")
    pm.db.close()


def run() -> None:
    seed_base()
    print("[smoke] starting app", flush=True)
    app = aqt._run(["anki", "-b", BASE], exec=False)
    assert app is not None

    def pump(cond: Callable[[], bool], what: str, timeout: float = 30) -> None:
        start = time.time()
        while not cond():
            app.processEvents()
            time.sleep(0.02)
            if time.time() - start > timeout:
                raise TimeoutError(f"timed out waiting for {what}")

    pump(lambda: aqt.mw is not None and aqt.mw.col is not None, "profile load", 60)
    mw = aqt.mw
    assert mw is not None
    col = mw.col
    step("profile loaded")

    import aqt.ankigpt as ankigpt_shell
    from aqt.ankigpt import get_store
    from aqt.ankigpt.concepts import create_concept_notes, deck_id_for_name
    from aqt.ankigpt.prompts import ConceptCandidate
    from aqt.ankigpt.settings import DeckSettings, save_deck_settings

    library_deck_id = col.decks.id("Library Smoke")
    add_payload = quote(
        json.dumps(
            {
                "deck_id": int(library_deck_id),
                "front": "Modern shell front",
                "back": "Modern shell back",
            }
        )
    )
    mw.web._onBridgeCmd(f"ankigpt:add-card:{add_payload}")
    pump(
        lambda: bool(col.find_notes('"Modern shell front"')),
        "shell card creation",
    )
    normal_note_id = col.find_notes('"Modern shell front"')[0]
    assert ankigpt_shell._shell_route == "library"
    step("standard card created in shell")

    save_payload = quote(
        json.dumps(
            {
                "nid": int(normal_note_id),
                "fields": {
                    "Front": "Modern shell front edited",
                    "Back": "Modern shell back edited",
                },
            }
        )
    )
    mw.web._onBridgeCmd(f"ankigpt:save-note:{save_payload}")
    pump(
        lambda: "edited" in col.get_note(normal_note_id)["Front"],
        "shell note save",
    )
    step("standard card edited in shell")

    mw.onBrowse()
    assert mw.state == "deckBrowser" and ankigpt_shell._shell_route == "library"
    mw.onStats()
    assert ankigpt_shell._shell_route == "progress"
    mw.onPrefs()
    assert ankigpt_shell._shell_route == "settings"
    mw.onAddCard()
    assert ankigpt_shell._shell_route == "add"
    step("global actions stay inside unified shell")

    empty_deck_id = col.decks.id("Empty Smoke")
    mw.web._onBridgeCmd(f"ankigpt:study:{int(empty_deck_id)}")
    pump(lambda: mw.state == "deckBrowser", "empty course return to shell")
    assert mw.state != "overview"
    step("empty study session returned to shell without Overview")

    deck_id = deck_id_for_name(col, "Smoke")
    create_concept_notes(
        col,
        deck_id,
        [
            ConceptCandidate(
                "Opportunity cost", "Next best alternative.", ["k1"], ["s1"]
            ),
            ConceptCandidate("Elasticity", "Responsiveness of quantity.", ["k2"], []),
            ConceptCandidate("Marginal utility", "Extra satisfaction.", ["k3"], []),
        ],
        context="Intro micro",
    )
    save_deck_settings(col, deck_id, DeckSettings(mode="typed"))
    col.decks.select(deck_id)
    step("concept deck created")

    reviewer = mw.reviewer
    mw.moveToState("review")
    pump(lambda: reviewer.state == "question", "first generated question")
    card = reviewer.card
    assert card is not None
    q = card.question()
    assert "[fake #1" in q and 'id="typeans"' in q, q
    step("typed question shown")

    reviewer.typedAnswer = "the value of the next best alternative"
    reviewer._showAnswer()
    pump(lambda: reviewer.state == "answer", "grading")
    a = card.answer()
    assert "Suggested grade" in a and "next best alternative" in a, a
    assert reviewer._defaultEase() == 3
    step("typed answer graded, suggested ease = Good")

    first_id = card.id
    reviewer._answerCard(3)
    pump(
        lambda: reviewer.state == "question" and reviewer.card.id != first_id,
        "second card",
    )
    store = get_store()
    row = store.db.execute(
        "SELECT user_answer, suggested_ease, final_ease FROM question_history "
        "WHERE card_id = ?",
        (first_id,),
    ).fetchone()
    assert row == ("the value of the next best alternative", 3, 3), row
    step("history row recorded")

    # switch the deck to multiple choice for the remaining cards; drop any
    # question that was prefetched in typed mode
    save_deck_settings(col, deck_id, DeckSettings(mode="mcq"))
    store.db.execute("DELETE FROM question_cache")
    store.db.commit()
    second_id = reviewer.card.id
    reviewer.typedAnswer = None
    reviewer._showAnswer()  # nothing typed: graded locally as Again, no LLM call
    pump(lambda: reviewer.state == "answer", "second answer")
    assert reviewer._defaultEase() == 1
    step("empty typed answer graded Again without LLM")

    reviewer._answerCard(1)
    pump(
        lambda: reviewer.state == "question"
        and reviewer.card.id not in (first_id, second_id),
        "third card",
    )
    q = reviewer.card.question()
    assert "ankigpt:choose:" in q, q
    step("mcq question shown")

    # a click arriving from JS goes through the webview bridge
    reviewer.web._onBridgeCmd("ankigpt:choose:1")
    pump(lambda: reviewer.state == "answer", "mcq answer")
    a = reviewer.card.answer()
    assert "ankigpt-option-wrong" in a and reviewer._defaultEase() == 1, a
    step("mcq wrong choice graded Again")

    reviewer._answerCard(1)
    pump(
        lambda: mw.state != "review" or reviewer.state == "question",
        "queue drained or next card",
    )
    step("review loop continued")

    mw.unloadProfileAndExit()
    pump(lambda: aqt.mw is None or aqt.mw.col is None, "profile unload", 30)


if __name__ == "__main__":
    # watchdog: dump all thread stacks and abort if the run wedges
    faulthandler.dump_traceback_later(
        float(os.environ.get("ANKIGPT_SMOKE_TIMEOUT", "120")), exit=True
    )
    try:
        run()
    except BaseException:
        traceback.print_exc()
        print(f"[smoke] FAILED after {len(STEPS)} steps", flush=True)
        os._exit(1)
    print(f"[smoke] OK: {len(STEPS)} steps passed", flush=True)
    # skip Qt/WebEngine teardown, which can crash on exit in offscreen mode
    os._exit(0)
