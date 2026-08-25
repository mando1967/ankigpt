# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator

import pytest

from anki.collection import Collection, SearchNode
from aqt.ankigpt import concepts
from aqt.ankigpt.concepts import (
    FIELD_KEY_POINTS,
    FIELD_SOURCES,
    FIELD_TITLE,
    NOTETYPE_NAME,
    create_concept_notes,
    deck_id_for_name,
    ensure_notetype,
    field_to_lines,
    is_concept_card,
)
from aqt.ankigpt.prompts import ConceptCandidate
from aqt.ankigpt.settings import (
    CONFIG_KEY,
    DeckSettings,
    deck_settings,
    has_deck_settings,
    save_deck_settings,
)


@pytest.fixture
def col() -> Iterator[Collection]:
    with tempfile.TemporaryDirectory() as d:
        collection = Collection(os.path.join(d, "test.anki2"))
        try:
            yield collection
        finally:
            collection.close()


def test_ensure_notetype_is_idempotent(col: Collection) -> None:
    before = len(col.models.all_names_and_ids())
    nt = ensure_notetype(col)
    assert nt["name"] == NOTETYPE_NAME
    assert [f["name"] for f in nt["flds"]] == list(concepts.FIELDS)
    assert len(nt["tmpls"]) == 1
    again = ensure_notetype(col)
    assert again["id"] == nt["id"]
    assert len(col.models.all_names_and_ids()) == before + 1


def test_create_concept_notes_and_detection(col: Collection) -> None:
    deck_id = deck_id_for_name(col, "Course::Week 1")
    assert deck_id_for_name(col, "Course::Week 1") == deck_id
    candidates = [
        ConceptCandidate(
            "Supply & demand", "Prices <b>move</b>.", ["p1", "p2"], ["src"]
        ),
        ConceptCandidate("Elasticity", "Responsiveness.", [], []),
    ]
    create_concept_notes(col, deck_id, candidates, context="Intro micro")

    nids = col.find_notes(col.build_search_string(SearchNode(note=NOTETYPE_NAME)))
    assert len(nids) == 2
    note = col.get_note(nids[0])
    assert note[FIELD_TITLE] == "Supply &amp; demand"
    assert field_to_lines(note[FIELD_KEY_POINTS]) == ["p1", "p2"]
    assert field_to_lines(note[FIELD_SOURCES]) == ["src"]
    assert concepts.field_to_text(note["Summary"]) == "Prices <b>move</b>."

    cards = note.cards()
    assert len(cards) == 1
    assert cards[0].did == deck_id
    assert is_concept_card(col, cards[0])

    basic = col.models.by_name("Basic")
    assert basic is not None
    other = col.new_note(basic)
    other["Front"] = "x"
    col.add_note(other, deck_id)
    assert not is_concept_card(col, other.cards()[0])


def test_deck_settings_roundtrip_and_inheritance(col: Collection) -> None:
    parent = deck_id_for_name(col, "Course")
    child = deck_id_for_name(col, "Course::Week 1")
    assert deck_settings(col, child) == DeckSettings()
    assert not has_deck_settings(col, child)

    save_deck_settings(col, parent, DeckSettings(mode="mcq", context="ctx"))
    assert deck_settings(col, child).mode == "mcq"
    assert deck_settings(col, child).context == "ctx"
    assert not has_deck_settings(col, child)

    save_deck_settings(col, child, DeckSettings(mode="typed", auto_submit=True))
    assert deck_settings(col, child).mode == "typed"
    assert deck_settings(col, parent).mode == "mcq"
    assert set(col.get_config(CONFIG_KEY).keys()) == {str(parent), str(child)}

    # unknown modes fall back safely
    data = col.get_config(CONFIG_KEY)
    data[str(child)]["mode"] = "bogus"
    col.set_config(CONFIG_KEY, data)
    assert deck_settings(col, child).mode == "self"
