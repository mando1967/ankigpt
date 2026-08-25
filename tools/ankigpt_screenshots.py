# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Render README screenshots from the real app running offscreen.

Usage (from the repo root, after `just build`):

    OPENAI_API_KEY=... out/pyenv/bin/python tools/ankigpt_screenshots.py \
        docs/ankigpt/screenshots [base-dir]

With ANKIGPT_FAKE_LLM=1 it runs without network (placeholder content) —
useful to check layouts. Screens: deck list, create-deck dialog, extraction
progress, concept preview, a typed question, the graded answer, a multiple
choice question, the deck overview and the concept deck settings.
"""

from __future__ import annotations

import faulthandler
import os
import shutil
import sys
import time
import traceback
from collections.abc import Callable
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
sys.path.extend(["pylib", "qt", "out/pylib", "out/qt"])

import aqt  # noqa: E402
from aqt.profiles import ProfileManager  # noqa: E402
from aqt.qt import QWidget  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/ankigpt/screenshots")
BASE = sys.argv[2] if len(sys.argv) > 2 else "/tmp/ankigpt-screenshots-base"
SAMPLE = Path("docs/ankigpt/sample-course.md").resolve()
DECK = "Intro Microeconomics"
INSTRUCTIONS = (
    "First-year intro microeconomics, weeks 1-3. Focus on the core models and "
    "the intuition behind them, not on the numerical examples."
)
TYPED_ANSWER = (
    "It's the value of the next best alternative you give up when you choose "
    "something - not just money, but time and anything else forgone."
)
WIDTH, HEIGHT = 1100, 720
SHOTS: list[str] = []


def seed_base() -> None:
    shutil.rmtree(BASE, ignore_errors=True)
    os.makedirs(BASE, exist_ok=True)
    pm = ProfileManager(Path(BASE))
    pm.setupMeta()
    pm.setLang("en_US")
    pm.db.close()


def run() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    seed_base()
    # allow running alongside a normal Anki/AnkiGPT instance
    aqt.AnkiApp.KEY = f"ankigpt-screenshots-{os.getpid()}"
    app = aqt._run(["anki", "-b", BASE], exec=False)
    assert app is not None

    def pump(cond: Callable[[], bool], what: str, timeout: float = 180) -> None:
        start = time.time()
        while not cond():
            app.processEvents()
            time.sleep(0.02)
            if time.time() - start > timeout:
                raise TimeoutError(f"timed out waiting for {what}")

    def settle(seconds: float = 1.5) -> None:
        end = time.time() + seconds
        while time.time() < end:
            app.processEvents()
            time.sleep(0.02)

    def shot(widget: QWidget, name: str, wait: float = 1.5) -> None:
        settle(wait)
        path = OUT / f"{name}.png"
        widget.grab().save(str(path))
        SHOTS.append(name)
        print(f"[shot] {path}", flush=True)

    pump(lambda: aqt.mw is not None and aqt.mw.col is not None, "profile load", 60)
    mw = aqt.mw
    assert mw is not None
    mw.resize(WIDTH, HEIGHT)
    col = mw.col

    from aqt.ankigpt import get_store
    from aqt.ankigpt.generate_dialog import CreateConceptDeckDialog
    from aqt.ankigpt.settings import (
        DeckSettings,
        DeckSettingsDialog,
        deck_settings,
        save_deck_settings,
    )

    # ---- 1. create-deck dialog, filled in
    dialog = CreateConceptDeckDialog(mw)
    dialog.resize(760, 620)
    dialog.files.append(str(SAMPLE))
    dialog.file_list.addItem(str(SAMPLE))
    dialog._suggest_target()
    dialog.deck_name.setCurrentText(DECK)
    dialog.instructions.setPlainText(INSTRUCTIONS)
    dialog.target.setValue(12)
    dialog.mode.setCurrentIndex(1)  # typed
    shot(dialog, "02-create-deck")

    # ---- 2. extraction with the progress page, then the preview table
    dialog.on_extract()
    # capture the progress page once a few log lines are in (or immediately
    # if extraction is instantaneous, e.g. with the fake client)
    pump(
        lambda: dialog.stack.currentIndex() != 2
        or dialog.progress_log.blockCount() >= 4,
        "progress page",
        120,
    )
    if dialog.stack.currentIndex() == 2:
        shot(dialog, "03-extracting", 0)
    pump(lambda: dialog.stack.currentIndex() == 1, "extraction to finish", 600)
    dialog.table.resizeRowsToContents()
    shot(dialog, "04-preview")
    dialog.on_create()
    pump(lambda: not dialog.isVisible(), "notes to be created", 60)

    # ---- 3. deck list with the new deck and the AI button
    mw.moveToState("deckBrowser")
    mw.deckBrowser.refresh()
    shot(mw, "01-deck-list")

    # ---- 4. overview of the concept deck (badge + Concept Settings)
    deck_id = col.decks.id_for_name(DECK)
    assert deck_id is not None
    col.decks.select(deck_id)
    mw.moveToState("overview")
    shot(mw, "05-overview")

    # ---- 5. typed-mode question, then graded answer
    save_deck_settings(col, deck_id, DeckSettings(mode="typed", context=INSTRUCTIONS))
    reviewer = mw.reviewer
    mw.moveToState("review")
    pump(lambda: reviewer.state == "question", "first generated question")
    settle(1.0)
    reviewer.web.eval(
        "(function(){var t=document.getElementById('typeans');"
        f"if(t){{t.value={TYPED_ANSWER!r};}}}})();"
    )
    shot(mw, "06-review-typed")
    reviewer.typedAnswer = TYPED_ANSWER
    reviewer._showAnswer()
    pump(lambda: reviewer.state == "answer", "grading")
    settle(1.0)
    reviewer.web.eval("window.scrollTo(0, 0);")
    shot(mw, "07-review-graded", 0.5)

    # ---- 5b. the source viewer, opened from the answer's "Open in source" link
    from aqt.ankigpt.sources import SourceViewerDialog

    cur = reviewer.ankigpt._current
    docs = get_store().documents_for_deck(int(deck_id))
    if cur is not None and cur.passages and docs:
        viewer = SourceViewerDialog(
            mw, docs, cur.passages[0].doc_id, [(p.start, p.end) for p in cur.passages]
        )
        viewer.show()
        shot(viewer, "11-source-viewer", 1.0)
        viewer.close()

    # ---- 6. multiple choice on the next card (fresh generation)
    first_id = reviewer.card.id
    save_deck_settings(col, deck_id, DeckSettings(mode="mcq", context=INSTRUCTIONS))
    store = get_store()
    store.db.execute("DELETE FROM question_cache")
    store.db.commit()
    reviewer._answerCard(3)
    pump(
        lambda: reviewer.state == "question" and reviewer.card.id != first_id,
        "next card",
    )
    settle(1.0)
    shot(mw, "08-review-mcq")

    # ---- 7. deck settings dialog
    mw.moveToState("overview")
    settings_dialog = DeckSettingsDialog(mw, deck_id)
    settings_dialog.show()
    shot(settings_dialog, "09-deck-settings", 0.8)
    settings_dialog.close()
    assert deck_settings(col, deck_id).mode == "mcq"

    # ---- 8. the in-app guide
    from aqt.ankigpt.help import GuideDialog

    guide = GuideDialog(mw)
    guide.show()
    shot(guide, "10-guide", 0.8)
    guide.close()

    mw.unloadProfileAndExit()
    pump(lambda: aqt.mw is None or aqt.mw.col is None, "profile unload", 30)


if __name__ == "__main__":
    faulthandler.dump_traceback_later(
        float(os.environ.get("ANKIGPT_SHOTS_TIMEOUT", "900")), exit=True
    )
    try:
        run()
    except BaseException:
        traceback.print_exc()
        print(f"[shots] FAILED after {len(SHOTS)} screenshots", flush=True)
        os._exit(1)
    print(f"[shots] OK: {len(SHOTS)} screenshots in {OUT}", flush=True)
    os._exit(0)
