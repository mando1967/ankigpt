# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""End-to-end smoke test for AnkiGPT that boots the real desktop app offscreen.

Usage (from the repo root, after `just build`):

    ANKIGPT_FAKE_LLM=1 QT_QPA_PLATFORM=offscreen \
        out/pyenv/bin/python tools/ankigpt_smoke.py /tmp/ankigpt-smoke-base

It creates a concept deck, reviews it in typed and multiple-choice mode
through the real Reviewer (including the webview bridge), and checks the
sidecar store. Exit code 0 means every step passed.
"""

from __future__ import annotations

import faulthandler
import os
import shutil
import sys
import time
from collections.abc import Callable

os.environ["ANKIGPT_FAKE_LLM"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.extend(["pylib", "qt", "out/pylib", "out/qt"])

import aqt  # noqa: E402
from anki.collection import Collection  # noqa: E402

BASE = sys.argv[1] if len(sys.argv) > 1 else "/tmp/ankigpt-smoke-base"
shutil.rmtree(BASE, ignore_errors=True)
# watchdog: dump all thread stacks and abort if the whole run takes too long
faulthandler.dump_traceback_later(float(os.environ.get("ANKIGPT_SMOKE_TIMEOUT", "120")), exit=True)
print("[smoke] starting app", flush=True)

app = aqt._run(["anki", "-b", BASE], exec=False)
assert app is not None
steps: list[str] = []


def step(name: str) -> None:
    steps.append(name)
    print(f"[smoke] {name}", flush=True)


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
col: Collection = mw.col
step("profile loaded")

from aqt.ankigpt import get_store  # noqa: E402
from aqt.ankigpt.concepts import create_concept_notes, deck_id_for_name  # noqa: E402
from aqt.ankigpt.prompts import ConceptCandidate  # noqa: E402
from aqt.ankigpt.settings import DeckSettings, save_deck_settings  # noqa: E402

deck_id = deck_id_for_name(col, "Smoke")
create_concept_notes(
    col,
    deck_id,
    [
        ConceptCandidate("Opportunity cost", "Next best alternative.", ["k1"], ["s1"]),
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
pump(lambda: reviewer.state == "question" and reviewer.card.id != first_id, "next card")
store = get_store()
row = store.db.execute(
    "SELECT user_answer, suggested_ease, final_ease FROM question_history WHERE card_id = ?",
    (first_id,),
).fetchone()
assert row == ("the value of the next best alternative", 3, 3), row
step("history row recorded")

# switch the deck to multiple choice for the remaining cards
save_deck_settings(col, deck_id, DeckSettings(mode="mcq"))
second_id = reviewer.card.id
reviewer._answerCard(1)  # self-grade path is still fine on the typed card
pump(
    lambda: reviewer.state == "question" and reviewer.card.id not in (first_id, second_id),
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
pump(lambda: mw.state != "review" or reviewer.state == "question", "queue drained or next")
step("review loop continued")

mw.unloadProfileAndExit()
pump(lambda: aqt.mw is None or aqt.mw.col is None, "profile unload", 30)
print(f"[smoke] OK: {len(steps)} steps passed")
os._exit(0)
