# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from pathlib import Path
from types import SimpleNamespace

import pytest

from aqt.ankigpt.prompts import GeneratedQuestion
from aqt.ankigpt.study_export import (
    card_text,
    import_text,
    save_study,
    study_html,
    write_export,
)


def question() -> GeneratedQuestion:
    return GeneratedQuestion(
        question="Which <tag>?\nChoose\tcarefully.",
        model_answer="Second\nline",
        key_points=["Key point"],
        mode="mcq",
        options=["Wrong", "Right"],
        correct_index=1,
        explanation="Because <script>alert(1)</script>",
    )


def test_import_files_preserve_card_boundaries_and_choices() -> None:
    front, back = card_text(question())
    assert "1. Wrong\n2. Right" in front
    assert back.startswith("2. Right")
    for anki in (False, True):
        text = import_text([question(), question()], anki)
        rows = text.splitlines()[3:] if anki else text.splitlines()
        assert len(rows) == 2
        assert all(len(row.split("\t")) == 2 for row in rows)
    assert "&lt;script&gt;" in import_text([question()], True)


def test_html_escapes_content_and_includes_navigation() -> None:
    page = study_html("<Deck>", [question(), question()])
    assert "<title>&lt;Deck&gt;</title>" in page
    assert "<script>alert" not in page
    assert 'id="previous"' in page and 'id="next"' in page
    assert "card.hidden = i !== current" in page
    assert "card.querySelector('.answer').hidden = true" in page
    assert "Show Answer" in page
    assert "<script>" not in study_html("Deck", [question()], False)


def test_html_navigation_reveals_and_resets_answer() -> None:
    from PyQt6.QtQml import QJSEngine

    from aqt.qt import QApplication

    app = QApplication.instance() or QApplication([])
    engine = QJSEngine()
    engine.evaluate("""
    var items = [0, 1].map(() => ({hidden:false, answer:{hidden:false},
      querySelector() { return this.answer; }}));
    var buttons = {previous:{}, next:{}, reveal:{}, counter:{}};
    var document = {querySelectorAll:() => items, getElementById:id => buttons[id]};
    """)
    script = (
        study_html("Deck", [question(), question()])
        .split("<script>")[1]
        .split("</script>")[0]
    )
    result = engine.evaluate(script)
    assert not result.isError(), result.toString()
    assert engine.evaluate("items[0].answer.hidden && items[1].hidden").toBool()
    engine.evaluate("buttons.reveal.onclick()")
    assert not engine.evaluate("items[0].answer.hidden").toBool()
    engine.evaluate("buttons.next.onclick()")
    assert engine.evaluate("items[0].hidden && items[1].answer.hidden").toBool()
    assert engine.evaluate("buttons.counter.textContent").toString() == "Card 2 of 2"
    engine.evaluate("buttons.next.onclick()")
    assert engine.evaluate("buttons.counter.textContent").toString() == "Card 1 of 2"
    engine.evaluate("buttons.previous.onclick()")
    assert engine.evaluate("buttons.counter.textContent").toString() == "Card 2 of 2"
    assert app is not None


def test_failed_write_preserves_existing_file(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "deck.html"
    target.write_text("Original", encoding="utf-8")
    monkeypatch.setattr("aqt.ankigpt.study_export.study_html", lambda *args: 1 / 0)
    with pytest.raises(ZeroDivisionError):
        write_export(str(target), "HTML", "Deck", [question()])
    assert target.read_text() == "Original"
    assert list(tmp_path.iterdir()) == [target]


def test_pdf_contains_questions_and_answers(tmp_path: Path) -> None:
    from pypdf import PdfReader

    from aqt.qt import QApplication, QFontDatabase

    app = QApplication.instance() or QApplication([])
    # Windows offscreen Qt does not discover system fonts automatically.
    font = Path("C:/Windows/Fonts/arial.ttf")
    if font.exists():
        QFontDatabase.addApplicationFont(str(font))
    target = tmp_path / "study.pdf"
    write_export(str(target), "PDF", "Study deck", [question()] * 12)
    reader = PdfReader(str(target))
    text = " ".join("\n".join(page.extract_text() for page in reader.pages).split())
    assert "Study deck" in text and "Answer" in text
    assert "Right" in text and "Wrong" in text
    assert len(reader.pages) > 1
    assert app is not None


@pytest.mark.parametrize(
    "suffix,count,accepted",
    [
        ("", 1, True),
        ("", 7, True),
        ("", 7, False),
        (":focus:3", 3, True),
        (":focus:5", 5, True),
        (":focus:10", 10, True),
        (":focus:20", 20, True),
        (":focus:7", 7, True),
        (":focus:100", 100, True),
    ],
)
def test_save_generates_requested_count_for_concepts_in_subdecks(
    tmp_path: Path, monkeypatch, suffix: str, count: int, accepted: bool
) -> None:
    from anki.collection import Collection
    from aqt.ankigpt.concepts import create_concept_notes
    from aqt.ankigpt.prompts import ConceptCandidate
    from aqt.ankigpt.store import Store

    col = Collection(str(tmp_path / "collection.anki2"))
    store = Store(str(tmp_path / "store.sqlite"))
    try:
        parent = col.decks.id("Parent")
        child = col.decks.id("Parent::Child")
        create_concept_notes(col, child, [ConceptCandidate("Title", "Summary", [], [])])
        target = tmp_path / "study.html"
        monkeypatch.setenv("ANKIGPT_FAKE_LLM", "1")
        monkeypatch.setattr("aqt.ankigpt.get_store", lambda: store)
        monkeypatch.setattr("aqt.ankigpt.settings.llm_config", lambda pm: None)
        monkeypatch.setattr("aqt.qt.QInputDialog.getItem", lambda *args: ("HTML", True))
        count_prompts = []

        def choose_count(*args):
            count_prompts.append(args)
            return count, accepted

        monkeypatch.setattr("aqt.qt.QInputDialog.getInt", choose_count)
        monkeypatch.setattr("aqt.utils.getSaveFile", lambda *args: str(target))
        notices = []
        monkeypatch.setattr(
            "aqt.utils.showInfo", lambda text, **kwargs: notices.append(text)
        )
        monkeypatch.setattr(
            "aqt.utils.showWarning", lambda text, **kwargs: pytest.fail(text)
        )

        progress_updates = []
        main_callbacks = []

        class ImmediateOp:
            def __init__(self, *, parent, op, success):
                self.op, self.success = op, success

            def without_collection(self):
                return self

            def with_progress(self, *args):
                return self

            def failure(self, *args):
                return self

            def run_in_background(self):
                result = self.op(None)
                # Drain after generation to catch incorrectly captured loop values.
                for callback in main_callbacks:
                    callback()
                self.success(result)

        monkeypatch.setattr("aqt.operations.QueryOp", ImmediateOp)
        save_study(
            SimpleNamespace(
                col=col,
                pm=None,
                taskman=SimpleNamespace(run_on_main=main_callbacks.append),
                progress=SimpleNamespace(
                    update=lambda **kwargs: progress_updates.append(kwargs)
                ),
            ),
            f"ankigpt:save-study:{parent}:typed,mcq,typed{suffix}",
        )
        assert len(count_prompts) == (0 if suffix else 1)
        if not accepted:
            assert not target.exists()
            assert not notices
            return
        page = target.read_text(encoding="utf-8")
        assert page.count("<article>") == count
        assert "· typed" in page
        if count > 1:
            assert "· mcq" in page
        assert f"Saved {count} cards" in notices[0]
        assert [update["value"] for update in progress_updates] == list(
            range(count + 1)
        )
        assert all(update["max"] == count for update in progress_updates)
        assert (
            progress_updates[0]["label"] == f"Generating study cards: 0% (0 of {count})"
        )
        assert (
            progress_updates[-1]["label"]
            == f"Generating study cards: 100% ({count} of {count})"
        )
    finally:
        store.close()
        col.close()
