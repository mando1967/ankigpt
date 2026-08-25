# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Sidecar SQLite database for AnkiGPT, stored next to the profile.

Holds the per-concept question history (so new questions avoid recent ones)
and a small cache of pre-generated questions. Kept out of the collection on
purpose: card.custom_data is capped at 100 bytes and the collection config is
synced on every sync. Single connection, main thread only.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass

from anki.cards import CardId
from anki.notes import NoteId
from aqt.ankigpt.prompts import GeneratedQuestion
from aqt.ankigpt.retrieve import Passage, StoredDocument, StoredSection

SCHEMA_VERSION = 2
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
    raw_json TEXT,
    refs_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_hist_note ON question_history(note_id, created DESC);
CREATE TABLE IF NOT EXISTS question_cache (
    card_id INTEGER PRIMARY KEY,
    note_id INTEGER NOT NULL,
    note_mod INTEGER NOT NULL,
    mastery TEXT NOT NULL,
    mode TEXT NOT NULL,
    created INTEGER NOT NULL,
    question_json TEXT NOT NULL,
    refs_json TEXT
);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    deck_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    added INTEGER NOT NULL,
    total_chars INTEGER NOT NULL,
    text TEXT NOT NULL,
    sections_json TEXT NOT NULL,
    pages_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_docs_deck ON documents(deck_id);
"""

_MIGRATIONS: dict[int, list[str]] = {
    # v1 -> v2: references used by each question; documents table (in _SCHEMA)
    2: [
        "ALTER TABLE question_history ADD COLUMN refs_json TEXT",
        "ALTER TABLE question_cache ADD COLUMN refs_json TEXT",
    ],
}


@dataclass
class CachedQuestion:
    question: GeneratedQuestion
    mastery: str
    created: int
    passages: list[Passage]


class Store:
    def __init__(self, path: str):
        self.path = path
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        fresh = not self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='meta'"
        ).fetchone()
        self.db.executescript(_SCHEMA)
        if fresh:
            self.db.execute(
                "INSERT INTO meta (key, value) VALUES ('version', ?)",
                (str(SCHEMA_VERSION),),
            )
        self._migrate()
        self.db.commit()

    def _migrate(self) -> None:
        row = self.db.execute("SELECT value FROM meta WHERE key='version'").fetchone()
        version = int(row[0]) if row else 1
        while version < SCHEMA_VERSION:
            version += 1
            for statement in _MIGRATIONS.get(version, []):
                try:
                    self.db.execute(statement)
                except sqlite3.OperationalError as exc:
                    if "duplicate column" not in str(exc):
                        raise
            self.db.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('version', ?)",
                (str(version),),
            )

    @property
    def version(self) -> int:
        row = self.db.execute("SELECT value FROM meta WHERE key='version'").fetchone()
        return int(row[0]) if row else 0

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
        passages: list[Passage] | None = None,
    ) -> int:
        cur = self.db.execute(
            """INSERT INTO question_history
               (note_id, card_id, created, mode, mastery, question, model_answer,
                options_json, correct_index, model, raw_json, refs_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                json.dumps([p.to_dict() for p in passages]) if passages else None,
            ),
        )
        self.db.commit()
        assert cur.lastrowid is not None
        return cur.lastrowid

    # ---------------------------------------------------------- documents

    def add_document(
        self,
        deck_id: int,
        name: str,
        path: str,
        text: str,
        sections: list[StoredSection],
        pages: list[int] | None = None,
    ) -> int:
        """Store (or replace, by deck + name) a source document."""
        self.db.execute(
            "DELETE FROM documents WHERE deck_id = ? AND name = ?", (deck_id, name)
        )
        cur = self.db.execute(
            """INSERT INTO documents
               (deck_id, name, path, added, total_chars, text, sections_json, pages_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                deck_id,
                name,
                path,
                int(time.time()),
                len(text),
                text,
                json.dumps(
                    [
                        {
                            "index": s.index,
                            "title": s.title,
                            "start": s.start,
                            "end": s.end,
                        }
                        for s in sections
                    ]
                ),
                json.dumps(list(pages or [])),
            ),
        )
        self.db.commit()
        assert cur.lastrowid is not None
        return cur.lastrowid

    def _row_to_document(self, row: tuple) -> StoredDocument:
        doc_id, deck_id, name, path, text, sections_json, pages_json = row
        sections = [
            StoredSection(
                int(s["index"]), str(s["title"]), int(s["start"]), int(s["end"])
            )
            for s in json.loads(sections_json or "[]")
        ]
        return StoredDocument(
            id=int(doc_id),
            deck_id=int(deck_id),
            name=name,
            path=path,
            text=text,
            sections=sections,
            pages=[int(p) for p in json.loads(pages_json or "[]")],
        )

    def documents_for_deck(self, deck_id: int) -> list[StoredDocument]:
        rows = self.db.execute(
            "SELECT id, deck_id, name, path, text, sections_json, pages_json "
            "FROM documents WHERE deck_id = ? ORDER BY added, id",
            (deck_id,),
        ).fetchall()
        return [self._row_to_document(r) for r in rows]

    def document_count(self, deck_id: int) -> int:
        row = self.db.execute(
            "SELECT count(*) FROM documents WHERE deck_id = ?", (deck_id,)
        ).fetchone()
        return int(row[0])

    def get_document(self, doc_id: int) -> StoredDocument | None:
        row = self.db.execute(
            "SELECT id, deck_id, name, path, text, sections_json, pages_json "
            "FROM documents WHERE id = ?",
            (doc_id,),
        ).fetchone()
        return self._row_to_document(row) if row else None

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
            "SELECT note_mod, mastery, created, question_json, refs_json "
            "FROM question_cache WHERE card_id = ?",
            (card_id,),
        ).fetchone()
        if row is None:
            return None
        stored_mod, mastery, created, question_json, refs_json = row
        if stored_mod != note_mod or time.time() - created > max_age:
            self.drop_cached(card_id)
            return None
        passages = [Passage.from_dict(d) for d in json.loads(refs_json or "[]")]
        return CachedQuestion(
            GeneratedQuestion.from_json(question_json), mastery, created, passages
        )

    def put_cached(
        self,
        card_id: CardId,
        note_id: NoteId,
        note_mod: int,
        mastery: str,
        question: GeneratedQuestion,
        passages: list[Passage] | None = None,
    ) -> None:
        self.db.execute(
            """INSERT OR REPLACE INTO question_cache
               (card_id, note_id, note_mod, mastery, mode, created, question_json, refs_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                card_id,
                note_id,
                note_mod,
                mastery,
                question.mode,
                int(time.time()),
                question.to_json(),
                json.dumps([p.to_dict() for p in passages]) if passages else None,
            ),
        )
        self.db.commit()

    def drop_all_cached(self) -> None:
        """Forget prefetched questions, e.g. after a grading-mode change."""
        self.db.execute("DELETE FROM question_cache")
        self.db.commit()

    def drop_cached(self, card_id: CardId) -> None:
        self.db.execute("DELETE FROM question_cache WHERE card_id = ?", (card_id,))
        self.db.commit()
