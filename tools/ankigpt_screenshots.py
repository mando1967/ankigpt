# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Render README screenshots from the real app running offscreen.

Usage (from the repo root, after `just build`):

    OPENAI_API_KEY=... out/pyenv/bin/python tools/ankigpt_screenshots.py \
        docs/ankigpt/screenshots [base-dir]

With ANKIGPT_FAKE_LLM=1 it runs without network (placeholder content) —
useful to check layouts. Screens cover the current Study Hub routes and the
AI-assisted typed-answer reviewer shown in the repository documentation.
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
from aqt.qt import QFont, QFontDatabase, QWidget  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/ankigpt/screenshots")
BASE = sys.argv[2] if len(sys.argv) > 2 else "/tmp/ankigpt-screenshots-base"
SAMPLE = Path("docs/ankigpt/sample-course.md").resolve()
COURSE = "Intro Microeconomics"
SUBCATEGORY = "Core Notes"
DECK = f"{COURSE}::{SUBCATEGORY}"
INSTRUCTIONS = (
    "First-year intro microeconomics, weeks 1-3. Focus on the core models and "
    "the intuition behind them, not on the numerical examples."
)
TYPED_ANSWER = (
    "It's the value of the next best alternative you give up when you choose "
    "something - not just money, but time and anything else forgone."
)
WIDTH, HEIGHT = 1280, 850
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
    for font_path in (
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ):
        if Path(font_path).exists() and QFontDatabase.addApplicationFont(font_path) >= 0:
            app.setFont(QFont("Segoe UI", 10))
            break

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
    mw.show()
    settle()
    col = mw.col

    from aqt.ankigpt.generate_dialog import CreateConceptDeckDialog
    from aqt.ankigpt.settings import (
        DeckSettings,
        save_deck_settings,
    )

    # ---- 1. create-deck dialog, filled in
    dialog = CreateConceptDeckDialog(mw)
    dialog.resize(760, 620)
    dialog._add_source_paths([str(SAMPLE)])
    dialog.deck_name.setCurrentText(COURSE)
    dialog.subcategory.setText(SUBCATEGORY)
    dialog.instructions.setPlainText(INSTRUCTIONS)
    dialog.target.setValue(12)
    dialog.mode.setCurrentIndex(1)  # typed
    shot(dialog, "02-create-deck")

    # ---- 2. representative book structure review
    from aqt.ankigpt import extract
    from aqt.ankigpt.book_structure import detect_book_structure

    book_dialog = CreateConceptDeckDialog(mw)
    book_dialog.resize(900, 650)
    book_dialog.book_source.setChecked(True)
    book_dialog.deck_name.setCurrentText("Physical Geology")
    book_dialog.subcategory.setText("Physical Geology, 2nd Edition")
    book_text = "\n\n".join(
        [
            "# Chapter 1 Foundations",
            "## 1.1 What Is Geology?\n" + "Earth systems and inquiry. " * 180,
            "## 1.2 Why Study Earth?\n" + "Hazards and resources. " * 150,
            "# Chapter 2 Minerals",
            "## 2.1 Elements and Atoms\n" + "Atomic structure and bonding. " * 170,
            "## 2.2 Mineral Properties\n" + "Physical properties. " * 190,
        ]
    )
    book_dialog._book_doc = extract.Document("physical-geology.md", book_text)
    book_dialog._book_chapters = detect_book_structure(book_text)
    book_dialog._fill_structure_tree()
    book_dialog.stack.setCurrentIndex(1)
    shot(book_dialog, "17-book-structure")
    book_dialog.close()

    # ---- 3. extraction with progress, then concept review
    dialog.on_extract()
    # capture the progress page once a few log lines are in (or immediately
    # if extraction is instantaneous, e.g. with the fake client)
    pump(
        lambda: dialog.stack.currentIndex() != 3
        or dialog.progress_log.blockCount() >= 4,
        "progress page",
        120,
    )
    if dialog.stack.currentIndex() == 3:
        shot(dialog, "03-extracting", 0)
    else:
        dialog.stack.setCurrentIndex(3)
        shot(dialog, "03-extracting", 0)
        dialog.stack.setCurrentIndex(2)
    pump(lambda: dialog.stack.currentIndex() == 2, "extraction to finish", 600)
    dialog.table.resizeRowsToContents()
    shot(dialog, "04-preview")
    dialog.on_create()
    pump(lambda: not dialog.isVisible(), "notes to be created", 60)

    # ---- 3. current Study Hub and its primary routes
    mw.moveToState("deckBrowser")
    import aqt.ankigpt as ankigpt_module

    def shell_shot(route: str, name: str) -> None:
        ankigpt_module._shell_route = route
        mw.deckBrowser.refresh()
        settle(3.0)
        mw.deckBrowser.web.eval("window.scrollTo(0, 0);")
        shot(mw.deckBrowser.web, name, 1.0)

    deck_id = col.decks.id_for_name(DECK)
    assert deck_id is not None
    shell_shot("home", "01-deck-list")
    shell_shot("concepts", "14-concepts")
    concepts = ankigpt_module._concept_records(mw)
    if concepts:
        shell_shot(f"concept:{concepts[0][0]}", "12-concept-editor")
    shell_shot(f"course:{int(deck_id)}", "15-course")
    shell_shot("settings", "16-settings")
    shell_shot("about", "13-about")
    ankigpt_module._shell_route = "home"

    # ---- 4. select the generated course before entering the reviewer
    col.decks.select(deck_id)

    # ---- 5. current typed-mode question, then graded answer
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
