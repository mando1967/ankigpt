# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

import pytest

from aqt.ankigpt.book_selection import page_units, parse_ranges, select_chapters
from aqt.ankigpt.book_structure import (
    classify_book_structure,
    detect_book_structure,
    generation_units,
)
from aqt.ankigpt.extract import Document


def test_intact_excerpt_headings():
    text = "  Chapter 10 Motion\nbody\nChapter 11\nForces\nbody"
    chapters = detect_book_structure(text)
    assert [c.title for c in chapters] == ["Chapter 10 Motion", "Chapter 11"]
    assert text[chapters[1].start :].lstrip().startswith("Chapter 11")


def test_chapter_selection_excludes_book_start_before_budget():
    text = (
        "Chapter 1 Intro\n"
        + "excluded " * 20000
        + "\nChapter 10 Motion\nselected ten\nChapter 11 Forces\nselected eleven"
    )
    chapters = detect_book_structure(text)
    select_chapters(chapters, "10-11")
    docs = [
        Document(name=unit.title, text=text[unit.start : unit.end])
        for _, unit in generation_units(chapters, False)
    ]
    assert len(docs) == 2
    assert all(
        "excluded" not in doc.text and "excluded" not in doc.outline for doc in docs
    )
    assert [doc.total_chars for doc in docs] == [len(doc.text) for doc in docs]


def test_missing_chapter_fails_without_mutation():
    chapters = detect_book_structure("Chapter 10 Motion\nbody\nChapter 12 Forces\nbody")
    with pytest.raises(ValueError, match="not detected"):
        select_chapters(chapters, "10-12")
    assert all(c.included for c in chapters)


def test_page_range_excludes_earlier_pages():
    doc = Document(name="book", text="excluded\nselected\nlast", pages=[0, 9, 18])
    units = page_units(doc, "2-3")
    selected = Document(
        name=units[0].title, text=doc.text[units[0].start : units[0].end]
    )
    assert selected.text == "selected\nlast"
    assert selected.total_chars == 13
    with pytest.raises(ValueError, match="3 pages"):
        page_units(doc, "2-4")


@pytest.mark.parametrize("value", ["0", "3-1", "foo", "1,", "-2"])
def test_invalid_ranges(value):
    with pytest.raises(ValueError):
        parse_ranges(value)


def test_overlapping_ranges_merge():
    assert parse_ranges("10–12, 11-14, 17") == [(10, 14), (17, 17)]


def test_ai_cleaned_title_retains_chapter_number():
    class Client:
        def complete_json(self, *args):
            return {
                "headings": [
                    {"index": 0, "kind": "chapter", "title": "Motion", "confidence": 1}
                ]
            }

    chapters, used_ai = classify_book_structure("Chapter 10 Motion\nbody", Client())
    assert used_ai
    select_chapters(chapters, "10")
    assert chapters[0].included
