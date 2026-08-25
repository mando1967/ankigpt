# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from anki import scheduler_pb2
from aqt.ankigpt import prompts
from aqt.ankigpt.llm import FakeLLMClient
from aqt.ankigpt.prompts import (
    GradeRequest,
    MasteryInfo,
    PromptError,
    QuestionRequest,
    mastery_from_state,
    parse_grade,
    parse_question,
)

State = scheduler_pb2.SchedulingState


def fake_card(reps: int = 0, lapses: int = 0, ivl: int = 0) -> MagicMock:
    card = MagicMock()
    card.reps = reps
    card.lapses = lapses
    card.ivl = ivl
    return card


def review_state(
    stability: float | None, lapses: int = 0, difficulty: float = 5.0, days: int = 0
) -> State:
    state = State()
    state.normal.review.scheduled_days = days
    state.normal.review.lapses = lapses
    if stability is not None:
        state.normal.review.memory_state.stability = stability
        state.normal.review.memory_state.difficulty = difficulty
    return state


def test_mastery_new_and_learning() -> None:
    state = State()
    state.normal.new.position = 1
    assert mastery_from_state(state, fake_card()).level == "new"
    state = State()
    state.normal.learning.remaining_steps = 2
    assert mastery_from_state(state, fake_card(reps=1)).level == "learning"


def test_mastery_review_thresholds() -> None:
    assert mastery_from_state(review_state(3), fake_card(reps=2)).level == "developing"
    assert mastery_from_state(review_state(15), fake_card(reps=5)).level == "solid"
    assert mastery_from_state(review_state(60), fake_card(reps=8)).level == "mastered"
    assert mastery_from_state(review_state(365), fake_card(reps=12)).level == "expert"


def test_mastery_demoted_by_lapses_and_difficulty() -> None:
    info = mastery_from_state(review_state(60, lapses=3), fake_card(reps=8))
    assert info.level == "solid"
    info = mastery_from_state(review_state(365, difficulty=9.5), fake_card(reps=8))
    assert info.level == "mastered"
    # never demoted below developing
    info = mastery_from_state(review_state(3, lapses=5), fake_card(reps=8))
    assert info.level == "developing"


def test_mastery_without_fsrs_uses_scheduled_days() -> None:
    info = mastery_from_state(review_state(None, days=45), fake_card(reps=3))
    assert info.level == "mastered"
    assert info.stability_days is None


def test_mastery_relearning_and_filtered() -> None:
    state = State()
    state.normal.relearning.review.lapses = 1
    state.normal.relearning.review.memory_state.stability = 20
    assert mastery_from_state(state, fake_card(reps=4)).level == "relearning"

    state = State()
    state.filtered.rescheduling.original_state.review.memory_state.stability = 50
    assert mastery_from_state(state, fake_card(reps=4)).level == "mastered"

    state = State()
    state.filtered.preview.scheduled_secs = 60
    assert mastery_from_state(state, fake_card(reps=4, ivl=10)).level == "solid"
    assert mastery_from_state(None, fake_card()).level == "new"


def sample_request(mode: prompts.Mode = "self") -> QuestionRequest:
    return QuestionRequest(
        title="Opportunity cost",
        summary="The value of the next best alternative forgone.",
        key_points=["Applies to every choice", "Not only monetary"],
        sources=["Opportunity cost is what you give up..."],
        context="Intro micro",
        mastery=MasteryInfo("solid", stability_days=12),
        mode=mode,
        recent_questions=["Define opportunity cost."],
    )


def test_question_prompt_contains_material_and_recent() -> None:
    system, user = prompts.build_question_prompt(sample_request("mcq"))
    assert "Opportunity cost" in user
    assert "Define opportunity cost." in user
    assert "solid" in user
    assert "exactly 4 answer choices" in user
    assert "ONE question" in system


def test_parse_question_validates_mcq() -> None:
    good = {
        "question": "Which is right?",
        "model_answer": "A",
        "key_points": ["k"],
        "options": ["a", "b", "c", "d"],
        "correct_index": 2,
        "explanation": "because",
    }
    q = parse_question(good, "mcq")
    assert q.correct_index == 2 and len(q.options) == 4
    with pytest.raises(PromptError):
        parse_question({**good, "options": ["a", "b"]}, "mcq")
    with pytest.raises(PromptError):
        parse_question({**good, "correct_index": 7}, "mcq")
    with pytest.raises(PromptError):
        parse_question({**good, "question": " "}, "self")
    # non-mcq modes drop options
    q = parse_question(good, "typed")
    assert q.options == [] and q.correct_index == -1
    # round trip
    assert prompts.GeneratedQuestion.from_json(q.to_json()) == q


def test_parse_grade_clamps_and_derives_ease() -> None:
    g = parse_grade({"score": 140, "ease": 9, "feedback": "x", "missed_points": []})
    assert g.score == 100 and g.ease == 4
    g = parse_grade({"score": 50, "ease": 0, "feedback": "", "missed_points": ["a"]})
    assert g.ease == 2 and g.missed_points == ["a"]


def test_fake_client_end_to_end() -> None:
    client = FakeLLMClient()
    system, user = prompts.build_question_prompt(sample_request("mcq"))
    q = parse_question(
        client.complete_json(
            system, user, "generate_question", prompts.QUESTION_SCHEMA
        ),
        "mcq",
    )
    assert "#2" in q.question  # one recent question -> second question
    assert q.correct_index == 0

    system, user = prompts.build_grade_prompt(
        GradeRequest(
            "t",
            q.question,
            q.model_answer,
            q.key_points,
            "wrong idea",
            MasteryInfo("new"),
        )
    )
    g = parse_grade(
        client.complete_json(system, user, "grade_answer", prompts.GRADE_SCHEMA)
    )
    assert g.ease == 1
