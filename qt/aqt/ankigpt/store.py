# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Sidecar SQLite database for AnkiGPT, stored next to the profile.

Holds the per-concept question history (so new questions avoid recent ones)
and a small cache of pre-generated questions. Kept out of the collection on
purpose: card.custom_data is capped at 100 bytes and the collection config is
synced on every sync. Single connection, main thread only.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass

from anki.cards import CardId
from anki.notes import NoteId
from aqt.ankigpt.prompts import GeneratedQuestion

SCHEMA_VERSION = 1
CACHE_TTL_SECS = 7 * 24 * 3600

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS question_history (
    id INTEGER PRIMARY KEY,
    note_id INTEGER NOT NULL,
    card_id INTEGER NOT NULL,
    created INTEGER NOT NULL,
    mode TEXT NOT NULL,
    mastery TEXT NOT NULL,
    question TEXT NOT NULL,
    model_answer TEXT,
    options_json TEXT,
    correct_index INTEGER,
    user_answer TEXT,
    score INTEGER,
    suggested_ease INTEGER,
    final_ease INTEGER,
    feedback TEXT,
    answered_at INTEGER,
    model TEXT,
    raw_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_hist_note ON question_history(note_id, created DESC);
CREATE TABLE IF NOT EXISTS question_cache (
    card_id INTEGER PRIMARY KEY,
    note_id INTEGER NOT NULL,
    note_mod INTEGER NOT NULL,
    mastery TEXT NOT NULL,
    mode TEXT NOT NULL,
    created INTEGER NOT NULL,
    question_json TEXT NOT NULL
);
"""


@dataclass
class CachedQuestion:
    question: GeneratedQuestion
    mastery: str
    created: int


class Store:
    def __init__(self, path: str):
        self.path = path
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(_SCHEMA)
        self.db.execute(
            "INSERT OR IGNORE INTO meta (key, value) VALUES ('version', ?)",
            (str(SCHEMA_VERSION),),
        )
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # ------------------------------------------------------------ history

    def log_question(
        self,
        note_id: NoteId,
        card_id: CardId,
        mode: str,
        mastery: str,
        question: GeneratedQuestion,
        model: str,
    ) -> int:
        cur = self.db.execute(
            """INSERT INTO question_history
               (note_id, card_id, created, mode, mastery, question, model_answer,
                options_json, correct_index, model, raw_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                note_id,
                card_id,
                int(time.time()),
                mode,
                mastery,
                question.question,
                question.model_answer,
                question.to_json() if question.options else None,
                question.correct_index if question.options else None,
                model,
                question.to_json(),
            ),
        )
        self.db.commit()
        assert cur.lastrowid is not None
        return cur.lastrowid

    def finish_question(
        self,
        row_id: int,
        *,
        user_answer: str | None,
        score: int | None,
        suggested_ease: int | None,
        final_ease: int,
        feedback: str | None,
    ) -> None:
        self.db.execute(
            """UPDATE question_history
               SET user_answer = ?, score = ?, suggested_ease = ?, final_ease = ?,
                   feedback = ?, answered_at = ?
               WHERE id = ?""",
            (
                user_answer,
                score,
                suggested_ease,
                final_ease,
                feedback,
                int(time.time()),
                row_id,
            ),
        )
        self.db.commit()

    def recent_questions(self, note_id: NoteId, n: int = 8) -> list[str]:
        rows = self.db.execute(
            "SELECT question FROM question_history WHERE note_id = ? "
            "ORDER BY created DESC, id DESC LIMIT ?",
            (note_id, n),
        ).fetchall()
        return [r[0] for r in rows]

    def history_count(self, note_id: NoteId) -> int:
        row = self.db.execute(
            "SELECT count(*) FROM question_history WHERE note_id = ?", (note_id,)
        ).fetchone()
        return int(row[0])

    def prune(self, note_id: NoteId, keep: int = 50) -> None:
        self.db.execute(
            """DELETE FROM question_history WHERE note_id = ? AND id NOT IN (
                 SELECT id FROM question_history WHERE note_id = ?
                 ORDER BY created DESC, id DESC LIMIT ?)""",
            (note_id, note_id, keep),
        )
        self.db.commit()

    # -------------------------------------------------------------- cache

    def get_cached(
        self, card_id: CardId, note_mod: int, max_age: int = CACHE_TTL_SECS
    ) -> CachedQuestion | None:
        row = self.db.execute(
            "SELECT note_mod, mastery, created, question_json FROM question_cache "
            "WHERE card_id = ?",
            (card_id,),
        ).fetchone()
        if row is None:
            return None
        stored_mod, mastery, created, question_json = row
        if stored_mod != note_mod or time.time() - created > max_age:
            self.drop_cached(card_id)
            return None
        return CachedQuestion(
            GeneratedQuestion.from_json(question_json), mastery, created
        )

    def put_cached(
        self,
        card_id: CardId,
        note_id: NoteId,
        note_mod: int,
        mastery: str,
        question: GeneratedQuestion,
    ) -> None:
        self.db.execute(
            """INSERT OR REPLACE INTO question_cache
               (card_id, note_id, note_mod, mastery, mode, created, question_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                card_id,
                note_id,
                note_mod,
                mastery,
                question.mode,
                int(time.time()),
                question.to_json(),
            ),
        )
        self.db.commit()

    def drop_cached(self, card_id: CardId) -> None:
        self.db.execute("DELETE FROM question_cache WHERE card_id = ?", (card_id,))
        self.db.commit()
