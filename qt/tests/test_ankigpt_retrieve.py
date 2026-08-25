# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from __future__ import annotations

import os
import sqlite3
import tempfile

import anki.collection  # noqa: F401  (must precede anki.cards)
from anki.cards import CardId
from anki.notes import NoteId
from aqt.ankigpt import extract, retrieve
from aqt.ankigpt.prompts import (
    GeneratedQuestion,
    MasteryInfo,
    QuestionRequest,
    build_lookup_prompt,
    build_question_prompt,
    parse_lookup,
    parse_question,
)
from aqt.ankigpt.retrieve import Passage, StoredDocument, StoredSection
from aqt.ankigpt.store import Store

SAMPLE = os.path.join(
    os.path.dirname(__file__), "..", "..", "docs", "ankigpt", "sample-course.md"
)


def sample_doc(doc_id: int = 1, deck_id: int = 7) -> StoredDocument:
    with open(SAMPLE, encoding="utf-8") as f:
        text = extract._normalize(f.read())
    sections = [
        StoredSection(s.index, s.title, s.start, s.end)
        for s in extract.split_sections(text, min_chars=300)
    ]
    return StoredDocument(doc_id, deck_id, "sample-course.md", SAMPLE, text, sections)


def test_lexical_passages_find_the_right_section() -> None:
    doc = sample_doc()
    passages = retrieve.lexical_passages(
        [doc], "Price elasticity of demand", ["responsiveness", "total revenue"]
    )
    assert passages
    top = passages[0]
    assert "Elasticity" in top.section
    assert "elastic" in top.text.lower()
    assert top.doc_id == 1 and top.doc_name == "sample-course.md"
    assert doc.text[top.start : top.end].strip() == top.text
    assert sum(len(p.text) for p in passages) <= retrieve.MAX_PASSAGE_CHARS_TOTAL

    # a concept from another section ranks that section first
    passages = retrieve.lexical_passages(
        [doc], "Comparative advantage", ["opportunity cost", "trade"]
    )
    assert "Comparative advantage" in passages[0].section
    assert retrieve.lexical_passages([doc], "", []) == []


def test_candidate_sections_and_pages() -> None:
    doc = sample_doc()
    doc.pages = [0, 1500, 3000]
    candidates = retrieve.candidate_sections([doc], "Demand", ["substitution effect"])
    assert candidates and candidates[0].section
    assert candidates[0].page in (1, 2, 3)
    assert doc.page_of(0) == 1 and doc.page_of(1600) == 2 and doc.page_of(9999) == 3
    assert "Demand" in candidates[0].label() and "p. " in candidates[0].label()


def test_render_document_html_marks_highlights_and_sections() -> None:
    doc = sample_doc()
    section = doc.sections[2]
    html_out = retrieve.render_document_html(
        doc, [(section.start + 5, section.start + 40)]
    )
    assert '<mark id="hl0">' in html_out and "</mark>" in html_out
    assert f'<a id="sec{section.index}"></a>' in html_out
    assert "<script" not in html_out
    # escaping
    doc2 = StoredDocument(2, 7, "x", "", "a < b & c", [])
    assert "a &lt; b &amp; c" in retrieve.render_document_html(doc2)


def test_store_documents_cache_passages_and_migration() -> None:
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "s.sqlite")
        # a v1 database created by the previous schema
        db = sqlite3.connect(path)
        db.executescript(
            """
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
            INSERT INTO meta VALUES ('version', '1');
            CREATE TABLE question_history (
                id INTEGER PRIMARY KEY, note_id INTEGER NOT NULL, card_id INTEGER NOT NULL,
                created INTEGER NOT NULL, mode TEXT NOT NULL, mastery TEXT NOT NULL,
                question TEXT NOT NULL, model_answer TEXT, options_json TEXT,
                correct_index INTEGER, user_answer TEXT, score INTEGER,
                suggested_ease INTEGER, final_ease INTEGER, feedback TEXT,
                answered_at INTEGER, model TEXT, raw_json TEXT);
            CREATE TABLE question_cache (
                card_id INTEGER PRIMARY KEY, note_id INTEGER NOT NULL,
                note_mod INTEGER NOT NULL, mastery TEXT NOT NULL, mode TEXT NOT NULL,
                created INTEGER NOT NULL, question_json TEXT NOT NULL);
            INSERT INTO question_history (note_id, card_id, created, mode, mastery, question)
                VALUES (1, 1, 0, 'self', 'new', 'old q');
            """
        )
        db.commit()
        db.close()

        store = Store(path)
        assert store.version == 2
        assert store.recent_questions(NoteId(1)) == ["old q"]

        doc = sample_doc()
        doc_id = store.add_document(
            7, doc.name, doc.path, doc.text, doc.sections, [0, 100]
        )
        again = store.add_document(
            7, doc.name, doc.path, doc.text, doc.sections, [0, 100]
        )
        assert doc_id and again and store.document_count(7) == 1
        loaded = store.documents_for_deck(7)[0]
        assert loaded.text == doc.text and loaded.pages == [0, 100]
        assert [s.title for s in loaded.sections] == [s.title for s in doc.sections]
        assert (
            store.get_document(again) is not None and store.documents_for_deck(8) == []
        )

        passages = retrieve.lexical_passages([loaded], "Elasticity", ["responsiveness"])
        q = GeneratedQuestion("q", "a", ["k"], "self", source_refs=[1])
        store.put_cached(CardId(5), NoteId(2), 10, "solid", q, passages)
        cached = store.get_cached(CardId(5), 10)
        assert cached is not None and cached.passages[0].text == passages[0].text
        assert cached.question.source_refs == [1]
        row_id = store.log_question(
            NoteId(2), CardId(5), "self", "solid", q, "m", passages
        )
        refs = store.db.execute(
            "SELECT refs_json FROM question_history WHERE id = ?", (row_id,)
        ).fetchone()[0]
        assert "Elasticity" in refs
        store.close()


def test_prompts_include_passages_and_lookup() -> None:
    doc = sample_doc()
    passages = retrieve.lexical_passages([doc], "Elasticity", ["responsiveness"])
    candidates = retrieve.candidate_sections([doc], "Elasticity", ["responsiveness"])
    req = QuestionRequest(
        title="Elasticity",
        summary="Responsiveness of quantity to price.",
        key_points=["ratio of percentage changes"],
        sources=[],
        context="",
        mastery=MasteryInfo("solid"),
        mode="typed",
        passages=passages,
        lookup_candidates=candidates,
    )
    _system, user = build_question_prompt(req)
    assert "[1] (sample-course.md" in user and passages[0].text[:40] in user
    _system, lookup = build_lookup_prompt(req)
    assert "CANDIDATE SECTIONS" in lookup and "[1] (sample-course.md" in lookup
    assert parse_lookup({"sections": [2, 2, 9, "x", 1, 3]}, 3) == [2, 1]
    q = parse_question(
        {
            "question": "Q?",
            "model_answer": "A",
            "key_points": [],
            "options": [],
            "correct_index": -1,
            "explanation": "",
            "source_refs": [1, "2", "bad"],
        },
        "typed",
    )
    assert q.source_refs == [1, 2]
    assert GeneratedQuestion.from_json(q.to_json()).source_refs == [1, 2]


def test_pdf_pages_offsets() -> None:
    from pypdf import PdfWriter

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "two.pdf")
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        writer.add_blank_page(width=200, height=200)
        with open(path, "wb") as f:
            writer.write(f)
        doc = extract.extract_text(path)
        assert doc.pages == [0, 2]
        assert doc.path == os.path.abspath(path)
        stored = StoredDocument(1, 1, doc.name, doc.path, doc.text, [], doc.pages)
        assert stored.page_of(0) == 1 and stored.page_of(3) == 2


def test_passage_roundtrip() -> None:
    p = Passage(3, "d.pdf", "Sec", 10, 20, "text", page=4)
    assert Passage.from_dict(p.to_dict()) == Passage(
        3, "d.pdf", "Sec", 10, 20, "text", 4
    )
    assert p.label() == 'd.pdf · "Sec" · p. 4'
