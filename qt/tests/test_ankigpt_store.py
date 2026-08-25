# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from __future__ import annotations

import os
import tempfile

from anki.cards import CardId
from anki.notes import NoteId
from aqt.ankigpt.prompts import GeneratedQuestion
from aqt.ankigpt.store import Store


def question(n: int, mode: str = "self") -> GeneratedQuestion:
    return GeneratedQuestion(
        question=f"q{n}",
        model_answer="a",
        key_points=["k"],
        mode=mode,  # type: ignore[arg-type]
        options=["a", "b", "c", "d"] if mode == "mcq" else [],
        correct_index=1 if mode == "mcq" else -1,
    )


def test_history_and_recent() -> None:
    with tempfile.TemporaryDirectory() as d:
        store = Store(os.path.join(d, "s.sqlite"))
        nid, cid = NoteId(10), CardId(20)
        ids = [
            store.log_question(nid, cid, "self", "new", question(i), "m")
            for i in range(12)
        ]
        assert store.recent_questions(nid, 3) == ["q11", "q10", "q9"]
        assert store.recent_questions(NoteId(99)) == []
        store.finish_question(
            ids[0],
            user_answer="mine",
            score=80,
            suggested_ease=3,
            final_ease=4,
            feedback="fb",
        )
        row = store.db.execute(
            "SELECT user_answer, score, suggested_ease, final_ease, feedback "
            "FROM question_history WHERE id = ?",
            (ids[0],),
        ).fetchone()
        assert row == ("mine", 80, 3, 4, "fb")
        store.prune(nid, keep=5)
        assert store.history_count(nid) == 5
        assert store.recent_questions(nid, 10) == ["q11", "q10", "q9", "q8", "q7"]
        store.close()


def test_cache_roundtrip_and_invalidation() -> None:
    with tempfile.TemporaryDirectory() as d:
        store = Store(os.path.join(d, "s.sqlite"))
        cid, nid = CardId(1), NoteId(2)
        assert store.get_cached(cid, 100) is None
        store.put_cached(cid, nid, 100, "solid", question(1, "mcq"))
        cached = store.get_cached(cid, 100)
        assert cached is not None
        assert cached.question == question(1, "mcq")
        assert cached.mastery == "solid"
        # note modified -> stale
        assert store.get_cached(cid, 101) is None
        assert store.get_cached(cid, 100) is None  # stale entries are dropped
        store.put_cached(cid, nid, 100, "solid", question(2))
        assert store.get_cached(cid, 100, max_age=-1) is None  # expired
        store.close()


def test_reopen_keeps_data() -> None:
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "s.sqlite")
        store = Store(path)
        store.log_question(NoteId(1), CardId(1), "self", "new", question(1), "m")
        store.close()
        store = Store(path)
        assert store.recent_questions(NoteId(1)) == ["q1"]
        store.close()
