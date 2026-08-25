# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from __future__ import annotations

import html
import os
import tempfile
from collections.abc import Callable, Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import anki.collection  # noqa: F401  (must precede anki.cards)
import anki.lang
from anki import scheduler_pb2
from anki.cards import Card
from anki.collection import Collection
from aqt.ankigpt.concepts import create_concept_notes, deck_id_for_name
from aqt.ankigpt.prompts import ConceptCandidate
from aqt.ankigpt.review import ConceptReviewController
from aqt.ankigpt.settings import DeckSettings, save_deck_settings
from aqt.ankigpt.store import Store
from aqt.utils import tr


class SyncRunner:
    """Collects async work so tests decide when results 'arrive'."""

    def __init__(self) -> None:
        self.pending: list[tuple[Callable[[], Any], Callable, Callable]] = []

    def __call__(
        self, op: Callable[[], Any], success: Callable, failure: Callable
    ) -> None:
        self.pending.append((op, success, failure))

    def flush(self) -> None:
        while self.pending:
            op, success, failure = self.pending.pop(0)
            try:
                result = op()
            except Exception as exc:
                failure(exc)
            else:
                success(result)


class Harness:
    def __init__(self, col: Collection, store: Store, mode: str = "self"):
        self.col = col
        self.store = store
        self.deck_id = deck_id_for_name(col, "Concepts")
        create_concept_notes(
            col,
            self.deck_id,
            [
                ConceptCandidate(
                    "Opportunity cost", "Next best alternative.", ["k1"], ["s"]
                ),
                ConceptCandidate(
                    "Elasticity",
                    "Responsiveness of quantity demanded to a price change.",
                    [
                        "ratio of percentage changes",
                        "elastic when above 1",
                        "total revenue",
                    ],
                    [],
                ),
            ],
        )
        save_deck_settings(col, self.deck_id, DeckSettings(mode=mode))
        col.decks.select(self.deck_id)
        self.cards = [
            col.get_card(cid) for cid in col.find_cards("deck:Concepts", order=True)
        ]
        self.reviewer = MagicMock()
        mw = self.reviewer.mw
        mw.col = col
        mw.state = "review"
        mw.pm.profile = {"ankigptApiKey": "test-key"}
        mw.pm.get_answer_key.return_value = None
        self.reviewer.state = None
        self.reviewer.typedAnswer = None
        self.runner = SyncRunner()
        self.controller = ConceptReviewController(
            self.reviewer, store_provider=lambda: store, run_async=self.runner
        )

    def show(
        self, card: Card, state: scheduler_pb2.SchedulingState | None = None
    ) -> None:
        self.reviewer.card = card
        if state is None:
            state = scheduler_pb2.SchedulingState()
            state.normal.new.position = 1
        self.reviewer._v3.states.current = state


@pytest.fixture
def harness() -> Iterator[Callable[..., Harness]]:
    if anki.lang.current_i18n is None:
        anki.lang.set_lang("en_US")
    created: list[Harness] = []
    with (
        tempfile.TemporaryDirectory() as d,
        patch.dict(os.environ, {"ANKIGPT_FAKE_LLM": "1"}),
        patch("aqt.ankigpt.review.theme_manager") as theme,
    ):
        theme.body_classes_for_card_ord.return_value = "card"
        col = Collection(os.path.join(d, "test.anki2"))
        store = Store(os.path.join(d, "ankigpt.sqlite"))

        def make(mode: str = "self") -> Harness:
            h = Harness(col, store, mode)
            created.append(h)
            return h

        try:
            yield make
        finally:
            for h in created:
                h.controller.unregister_hooks()
            store.close()
            col.close()


def test_non_concept_card_is_ignored(harness: Callable[..., Harness]) -> None:
    h = harness()
    basic = h.col.models.by_name("Basic")
    assert basic is not None
    note = h.col.new_note(basic)
    note["Front"] = "x"
    h.col.add_note(note, h.deck_id)
    h.show(note.cards()[0])
    assert h.controller.intercept_question() is False
    assert h.controller.intercept_answer() is False
    assert h.controller.suggested_ease() is None
    assert not h.runner.pending


def test_missing_api_key_fails_to_overview(harness: Callable[..., Harness]) -> None:
    h = harness()
    h.reviewer.mw.pm.profile = {}
    with patch.dict(os.environ, {"ANKIGPT_FAKE_LLM": "0", "OPENAI_API_KEY": ""}):
        h.show(h.cards[0])
        assert h.controller.intercept_question() is True
    assert h.reviewer.state == "transition"
    h.reviewer.mw.progress.single_shot.assert_called_once()
    assert not h.runner.pending


def test_generation_flow_and_reapply(harness: Callable[..., Harness]) -> None:
    h = harness()
    card = h.cards[0]
    h.show(card)
    assert h.controller.intercept_question() is True
    assert h.reviewer.state == "transition"
    h.reviewer._clear_auto_advance_timers.assert_called_once()
    h.reviewer.web.eval.assert_called()  # placeholder shown
    assert len(h.runner.pending) == 1
    # a redraw while generating keeps waiting
    assert h.controller.intercept_question() is True
    assert len(h.runner.pending) == 1

    h.runner.flush()
    h.reviewer._showQuestion.assert_called_once()
    assert card.note()["Title"] in card.question()
    assert "[fake #1, new]" in card.question()
    assert h.store.history_count(card.nid) == 1

    # second pass: reviewer proceeds
    assert h.controller.intercept_question() is False
    # card.load() drops the render output; intercept restores it
    card.load()
    assert "[fake" not in card.question()
    assert h.controller.intercept_question() is False
    assert "[fake #1, new]" in card.question()
    assert h.controller.intercept_answer() is False  # self-grade mode
    assert h.controller.suggested_ease() is None
    answer = card.answer()
    assert "Model answer" in answer
    # the answer side names the concept and shows the notes it came from
    title = card.note()["Title"]
    assert f"Concept: {title}" in answer.replace("\u2068", "").replace("\u2069", "")
    assert "ankigpt-source" in answer and "From your notes" in answer
    assert card.note()["Summary"] in answer
    # ... but the question side does not give the concept title away
    assert "From your notes" not in card.question()


def test_recent_questions_feed_the_prompt(harness: Callable[..., Harness]) -> None:
    h = harness()
    card = h.cards[0]
    h.show(card)
    h.controller.intercept_question()
    h.runner.flush()
    h.controller._on_answer_card(h.reviewer, card, 3)
    assert h.controller._current is None
    row = h.store.db.execute(
        "SELECT final_ease FROM question_history WHERE card_id = ?", (card.id,)
    ).fetchone()
    assert row == (3,)

    h.show(card)
    h.controller.intercept_question()
    h.runner.flush()
    assert "[fake #2" in card.question()


def test_stale_result_is_cached_not_shown(harness: Callable[..., Harness]) -> None:
    h = harness()
    first, second = h.cards
    h.show(first)
    h.controller.intercept_question()
    # user moved to another card before generation finished
    h.show(second)
    h.controller.intercept_question()
    h.runner.flush()
    assert h.reviewer._showQuestion.call_count == 1  # only for `second`
    assert "[fake" in second.question()
    assert h.store.get_cached(first.id, first.note().mod) is not None

    # returning to `first` is now a cache hit: no async work
    h.show(first)
    assert h.controller.intercept_question() is False
    assert not h.runner.pending
    assert "[fake" in first.question()
    assert h.store.get_cached(first.id, first.note().mod) is None


def test_generation_failure_leaves_review(harness: Callable[..., Harness]) -> None:
    h = harness()
    card = h.cards[0]
    h.show(card)
    h.controller.intercept_question()
    op, _success, failure = h.runner.pending.pop()
    failure(RuntimeError("boom"))
    assert h.controller._current is None
    h.reviewer.mw.progress.single_shot.assert_called_once()


def test_typed_mode_grading(harness: Callable[..., Harness]) -> None:
    h = harness("typed")
    card = h.cards[0]
    h.show(card)
    h.controller.intercept_question()
    h.runner.flush()
    assert 'id="typeans"' in card.question()

    h.reviewer.typedAnswer = "the next best alternative"
    assert h.controller.intercept_answer() is True
    assert h.controller.intercept_answer() is True  # re-entrant while grading
    assert len(h.runner.pending) == 1
    h.runner.flush()
    h.reviewer._showAnswer.assert_called_once()
    assert h.controller.intercept_answer() is False
    assert h.controller.suggested_ease() == 3
    answer = card.answer()
    assert html.escape(tr.ankigpt_score(score=80)) in answer
    assert "the next best alternative" in answer
    labels = h.controller._on_init_buttons(
        ((1, "Again"), (2, "Hard"), (3, "Good"), (4, "Easy")), h.reviewer, card
    )
    assert labels[2][1].startswith("<b>") and labels[1][1] == "Hard"

    h.controller._on_answer_card(h.reviewer, card, 4)
    row = h.store.db.execute(
        "SELECT user_answer, score, suggested_ease, final_ease FROM question_history "
        "WHERE card_id = ?",
        (card.id,),
    ).fetchone()
    assert row == ("the next best alternative", 80, 3, 4)


def test_typed_mode_empty_answer(harness: Callable[..., Harness]) -> None:
    h = harness("typed")
    card = h.cards[0]
    h.show(card)
    h.controller.intercept_question()
    h.runner.flush()
    h.reviewer.typedAnswer = "   "
    assert h.controller.intercept_answer() is False
    assert not h.runner.pending
    assert h.controller.suggested_ease() == 1


def test_mcq_mode(harness: Callable[..., Harness]) -> None:
    h = harness("mcq")
    card = h.cards[0]
    h.show(card)
    h.controller.intercept_question()
    h.runner.flush()
    assert "ankigpt:choose:3" in card.question()

    # clicks from JS arrive via the webview hook, before the reviewer's own handler
    h.reviewer.state = "question"
    handled = h.controller._on_js_message((False, None), "ankigpt:choose:1", h.reviewer)
    assert handled == (True, None)
    h.reviewer._showAnswer.assert_called_once()
    assert h.controller.intercept_answer() is False
    assert h.controller.suggested_ease() == 1  # wrong option
    assert "ankigpt-option-wrong" in card.answer()
    assert "Incorrect" in card.answer()
    # a second click is ignored
    h.controller._on_js_message((False, None), "ankigpt:choose:0", h.reviewer)
    assert h.reviewer._showAnswer.call_count == 1
    # unrelated messages pass through untouched
    assert h.controller._on_js_message((False, 1), "ease3", h.reviewer) == (False, 1)


def test_mcq_digit_shortcut_and_correct_answer(harness: Callable[..., Harness]) -> None:
    h = harness("mcq")
    card = h.cards[0]
    h.show(card)
    h.controller.intercept_question()
    h.runner.flush()
    shortcuts: list[tuple[str, Callable]] = []
    h.controller._on_state_shortcuts("review", shortcuts)
    assert [k for k, _ in shortcuts] == ["1", "2", "3", "4"]
    h.reviewer.state = "question"
    shortcuts[0][1]()  # choose option 1 (correct in the fake)
    h.reviewer._showAnswer.assert_called_once()
    assert h.controller.intercept_answer() is False
    assert h.controller.suggested_ease() == 3
    assert "Correct" in card.answer()
    # in answer state digits rate the card as usual
    h.reviewer.state = "answer"
    shortcuts[3][1]()
    h.reviewer._answerCard.assert_called_once_with(4)


def test_auto_submit_timer(harness: Callable[..., Harness]) -> None:
    h = harness("typed")
    save_deck_settings(
        h.col,
        h.deck_id,
        DeckSettings(mode="typed", auto_submit=True, auto_submit_delay_ms=500),
    )
    card = h.cards[0]
    h.show(card)
    h.controller.intercept_question()
    h.runner.flush()
    h.reviewer.typedAnswer = "answer"
    h.controller.intercept_answer()
    h.runner.flush()
    h.controller._on_show_answer(card)
    h.reviewer.mw.progress.timer.assert_called_once()
    args, kwargs = h.reviewer.mw.progress.timer.call_args
    assert args[0] == 500
    h.reviewer.state = "answer"
    args[1]()  # fire
    h.reviewer._answerCard.assert_called_once_with(3)


def test_prefetch_populates_cache(harness: Callable[..., Harness]) -> None:
    h = harness()
    first, second = h.cards
    h.show(first)
    h.controller.intercept_question()
    h.runner.flush()
    h.controller._on_show_question(first)
    # queue holds both new cards; the other one gets prefetched
    assert len(h.runner.pending) == 1
    h.runner.flush()
    assert h.store.get_cached(second.id, second.note().mod) is not None
    h.controller._on_show_question(first)
    assert not h.runner.pending  # already cached


def test_stored_documents_feed_passages_and_lookup(
    harness: Callable[..., Harness],
) -> None:
    from aqt.ankigpt import extract
    from aqt.ankigpt.retrieve import StoredSection

    h = harness("typed")
    sample = os.path.join(
        os.path.dirname(__file__), "..", "..", "docs", "ankigpt", "sample-course.md"
    )
    with open(sample, encoding="utf-8") as f:
        text = extract._normalize(f.read())
    sections = [
        StoredSection(s.index, s.title, s.start, s.end)
        for s in extract.split_sections(text, min_chars=300)
    ]
    h.store.add_document(int(h.deck_id), "sample-course.md", sample, text, sections)

    # a well-known concept: retrieval + one lookup call before generation
    card = next(c for c in h.cards if c.note()["Title"] == "Elasticity")
    state = scheduler_pb2.SchedulingState()
    state.normal.review.memory_state.stability = 20  # -> "solid"
    h.show(card, state)
    h.controller.intercept_question()
    h.runner.flush()
    q = card.question()
    assert "[fake" in q
    cur = h.controller._current
    assert cur is not None and cur.passages
    assert any("Elasticity" in p.section for p in cur.passages)
    # the fake lookup adds candidate [1] on top of the lexical passages
    assert len(cur.passages) >= 2
    assert cur.question.source_refs == [1]

    h.reviewer.typedAnswer = "responsiveness of quantity to price"
    h.controller.intercept_answer()
    h.runner.flush()
    answer = card.answer()
    assert "ankigpt-passage" in answer and "Open in source" in answer
    assert "ankigpt:source:" in answer
    assert "&#9733;" in answer  # the starred passage the model relied on

    # clicking the link routes through the webview hook to the source viewer
    with patch("aqt.ankigpt.sources.show_sources") as show:
        first = cur.passages[0]
        handled = h.controller._on_js_message(
            (False, None),
            f"ankigpt:source:{first.doc_id}:{first.start}:{first.end}",
            h.reviewer,
        )
        assert handled == (True, None)
        show.assert_called_once()
        args = show.call_args[0]
        assert args[2] == first.doc_id
        assert (first.start, first.end) in args[3]

    # a new concept gets passages but no lookup call (mastery too low)
    other = next(c for c in h.cards if c.note()["Title"] != "Elasticity")
    h.controller._on_answer_card(h.reviewer, card, 3)
    h.show(other)
    h.controller.intercept_question()
    h.runner.flush()
    cur2 = h.controller._current
    assert cur2 is not None and cur2.card_id == other.id
    assert cur2.passages
