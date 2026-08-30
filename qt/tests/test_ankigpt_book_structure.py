# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from aqt.ankigpt.book_structure import (
    classify_book_structure,
    deck_root,
    detect_book_structure,
    generation_units,
)


def test_deck_root_places_subcategory_under_course() -> None:
    assert deck_root(" Engineering ", " Cars ") == "Engineering::Cars"
    assert deck_root("Engineering::", "::Mechanics") == "Engineering::Mechanics"


def test_model_classification_is_validated_against_local_candidates() -> None:
    class Client:
        def complete_json(self, system, user, schema_name, json_schema):
            assert schema_name == "classify_book_structure"
            return {
                "headings": [
                    {
                        "index": 0,
                        "kind": "ignore",
                        "title": "Contents",
                        "confidence": 0.9,
                    },
                    {
                        "index": 1,
                        "kind": "chapter",
                        "title": "Foundations",
                        "confidence": 0.8,
                    },
                    {
                        "index": 2,
                        "kind": "section",
                        "title": "Forces",
                        "confidence": 0.7,
                    },
                    {
                        "index": 999,
                        "kind": "chapter",
                        "title": "Invented",
                        "confidence": 1.0,
                    },
                ]
            }

    text = "# Contents\n\n# Chapter 1\n\n## 1.1 Forces\n\nBody"
    chapters, used_ai = classify_book_structure(text, Client())

    assert used_ai
    assert [chapter.title for chapter in chapters] == ["Foundations"]
    assert [section.title for section in chapters[0].children] == ["Forces"]
    assert chapters[0].confidence == 0.5  # unusually short units are flagged
    assert chapters[0].end == len(text)
    assert chapters[0].children[-1].end == len(text)


def test_numbered_section_runs_are_promoted_to_chapters() -> None:
    class Client:
        def complete_json(self, system, user, schema_name, json_schema):
            return {
                "headings": [
                    {
                        "index": 0,
                        "kind": "chapter",
                        "title": "Book heading",
                        "confidence": 0.99,
                    },
                    {
                        "index": 1,
                        "kind": "section",
                        "title": "1.1 First",
                        "confidence": 0.99,
                    },
                    {
                        "index": 2,
                        "kind": "section",
                        "title": "1.2 Second",
                        "confidence": 0.99,
                    },
                    {
                        "index": 3,
                        "kind": "section",
                        "title": "2.1 Third",
                        "confidence": 0.99,
                    },
                    {
                        "index": 4,
                        "kind": "section",
                        "title": "2.2 Fourth",
                        "confidence": 0.99,
                    },
                ]
            }

    text = "\n\n".join(
        [
            "# Book",
            "## 1.1 First\n" + "a " * 300,
            "## 1.2 Second\n" + "b " * 300,
            "## 2.1 Third\n" + "c " * 300,
            "## 2.2 Fourth\n" + "d " * 300,
        ]
    )
    chapters, used_ai = classify_book_structure(text, Client())

    assert used_ai
    assert [chapter.title for chapter in chapters] == ["Chapter 1", "Chapter 2"]
    assert [len(chapter.children) for chapter in chapters] == [2, 2]
    assert chapters[0].end == chapters[1].start
    assert chapters[1].end == len(text)
    assert [path for path, _unit in generation_units(chapters, False)] == [
        ["Chapter 1"],
        ["Chapter 2"],
    ]


def test_detects_chapters_and_nested_sections() -> None:
    text = """# Chapter 1 Foundations

Intro text.

## 1.1 Forces

Force text.

## 1.2 Moments

Moment text.

# Chapter 2 Motion

Motion text.
"""
    chapters = detect_book_structure(text)

    assert [chapter.title for chapter in chapters] == [
        "Chapter 1 Foundations",
        "Chapter 2 Motion",
    ]
    assert [section.title for section in chapters[0].children] == [
        "1.1 Forces",
        "1.2 Moments",
    ]
    assert text[chapters[0].start : chapters[0].end].startswith("# Chapter 1")
    assert text[chapters[1].start : chapters[1].end].startswith("# Chapter 2")


def test_generation_units_respect_mode_and_exclusions() -> None:
    chapters = detect_book_structure("# Chapter 1\n\n## A\n\none\n\n## B\n\ntwo")
    assert [path for path, _unit in generation_units(chapters, False)] == [
        ["Chapter 1"]
    ]
    chapters[0].children[1].included = False
    assert [path for path, _unit in generation_units(chapters, True)] == [
        ["Chapter 1", "A"]
    ]

    chapter_only = detect_book_structure("# Chapter 1\n\nA chapter without sections.")
    assert [path for path, _unit in generation_units(chapter_only, True)] == [
        ["Chapter 1"]
    ]
