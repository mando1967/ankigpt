# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The "AnkiGPT Concept" notetype and note creation.

The notetype is created at runtime from Python (not as a Rust stock notetype)
so the fork does not have to touch proto enums or exhaustive Rust matches.
Its template is a plain Title -> Summary flashcard; the reviewer replaces the
rendered content with generated questions for cards of this notetype.
"""

from __future__ import annotations

import html
import re
from collections.abc import Sequence

from anki.cards import Card
from anki.collection import AddNoteRequest, Collection, OpChanges
from anki.decks import DeckId
from anki.models import NotetypeDict, NotetypeId
from anki.notes import Note
from aqt.ankigpt.prompts import ConceptCandidate

NOTETYPE_NAME = "AnkiGPT Concept"
FIELD_TITLE = "Title"
FIELD_SUMMARY = "Summary"
FIELD_KEY_POINTS = "KeyPoints"
FIELD_SOURCES = "Sources"
FIELD_CONTEXT = "Context"
FIELDS = (FIELD_TITLE, FIELD_SUMMARY, FIELD_KEY_POINTS, FIELD_SOURCES, FIELD_CONTEXT)

_QFMT = '<div class="ankigpt-title">{{Title}}</div>'
_AFMT = (
    "{{FrontSide}}\n<hr id=answer>\n"
    '<div class="ankigpt-summary">{{Summary}}</div>\n'
    '<div class="ankigpt-keypoints">{{KeyPoints}}</div>'
)
CSS_VERSION = 3
_CSS = f"""/* ankigpt-css-v{CSS_VERSION} */
.card {{
  font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-size: 18px;
  text-align: left;
  color: #18233f;
  background: #eef3f9;
  max-width: none;
  margin: 0;
  padding: 28px;
}}
.ankigpt-study-card {{ box-sizing: border-box; max-width: 920px; min-height: calc(100vh - 56px); margin: 0 auto; padding: 34px 42px; background: #fff; border: 1px solid #dfe6ef; border-radius: 16px; box-shadow: 0 14px 38px rgba(31,54,92,.12); }}
.ankigpt-study-top {{ display: flex; align-items: center; justify-content: space-between; gap: 18px; margin: -8px 0 30px; padding-bottom: 16px; border-bottom: 1px solid #e8ecf2; }}
.ankigpt-study-top button {{ padding: 8px 12px; color: #3157d5; background: #edf2ff; border: 0; border-radius: 8px; font-weight: 650; cursor: pointer; }}
.ankigpt-title {{ font-size: 1.3em; font-weight: bold; text-align: center; }}
.ankigpt-keypoints {{ margin-top: 0.8em; }}
.ankigpt-keypoints li {{ margin-bottom: 0.3em; }}
.ankigpt-question {{ margin: 0 auto 1.4em; max-width: 760px; font-size: 1.38em; line-height: 1.5; font-weight: 620; color: #12204a; }}
.ankigpt-banner {{ font-size: 0.8em; color: #888; margin-bottom: 0.6em; }}
.ankigpt-source {{ margin-top: 1.2em; font-size: 0.9em; }}
.ankigpt-source summary {{ cursor: pointer; color: #4a90d9; }}
.ankigpt-source-body {{ margin-top: 0.5em; }}
.ankigpt-passages-title {{ font-weight: bold; margin-top: 0.8em; }}
.ankigpt-passage {{ margin: 0.5em 0; }}
.ankigpt-passage-label {{ font-size: 0.85em; color: #888; }}
.ankigpt-passage-used .ankigpt-passage-label {{ color: #4a90d9; }}
.ankigpt-open-source {{ color: #4a90d9; text-decoration: none; }}
.ankigpt-source blockquote {{ border-left: 3px solid #bbb; margin: 0.5em 0; padding-left: 0.6em; color: #777; }}
.ankigpt-header {{ font-size: 0.72em; letter-spacing: 0.06em; text-transform: uppercase; color: #60708b; text-align: right; }}
.ankigpt-feedback {{ border: 1px solid #bde4cb; border-radius: 10px; background: #effaf3; padding: 16px; margin: 1em 0; }}
.ankigpt-score {{ font-weight: bold; }}
.ankigpt-options {{ list-style: none; padding: 0; max-width: 760px; margin: 0 auto; }}
.ankigpt-options li {{ margin: 0.65em 0; }}
.ankigpt-options button {{
  width: 100%; text-align: left; padding: 0.8em 1em; font-size: 1em;
  color: #263653; border: 1px solid #d5dce7; border-radius: 9px; background: #f8faff; cursor: pointer;
}}
.ankigpt-options button:hover {{ border-color: #7095e8; background: #edf3ff; }}
.ankigpt-option-correct {{ border-color: #3a3 !important; background: #e6f5e6 !important; }}
.ankigpt-option-wrong {{ border-color: #c33 !important; background: #f9e6e6 !important; }}
#typeans {{ display: block; width: min(760px, 100%); box-sizing: border-box; margin: 0 auto; font-size: 1em; font-family: inherit; padding: 14px; border: 1px solid #cfd8e6; border-radius: 9px; resize: vertical; }}
.ankigpt-model-answer,.ankigpt-user-answer,.ankigpt-keypoints {{ padding: 15px 17px; margin: 12px 0; background: #f7f9fc; border-radius: 9px; line-height: 1.5; }}
.ankigpt-source {{ padding: 15px 17px; border: 1px solid #e1e7ef; border-radius: 9px; }}
.ankigpt-study-actions {{ display:flex; justify-content:center; margin:20px 0 6px; }}
.ankigpt-study-actions button {{ min-width:180px; padding:12px 18px; color:#fff; background:#2367e8; border:0; border-radius:8px; font-size:.95em; font-weight:700; cursor:pointer; }}
.ankigpt-rating {{ display:grid; grid-template-columns:1fr repeat(4,auto); align-items:center; gap:9px; margin-top:22px; padding-top:18px; border-top:1px solid #e4e9f0; color:#667085; font-size:.83em; }}
.ankigpt-rating button {{ padding:9px 13px; color:#34435f; background:#f7f9fc; border:1px solid #d8dfe9; border-radius:7px; cursor:pointer; }}
.ankigpt-rating .ease-1:hover {{ border-color:#d55757; }} .ankigpt-rating .ease-2:hover {{ border-color:#d99a32; }} .ankigpt-rating .ease-3:hover,.ankigpt-rating .ease-4:hover {{ border-color:#3fa36c; }}
@media(max-width:700px) {{ .card {{ padding: 10px; }} .ankigpt-study-card {{ min-height: calc(100vh - 20px); padding: 22px 18px; border-radius: 11px; }} .ankigpt-study-top {{ align-items: flex-start; }} }}
.night_mode .card {{ color: #d7d7d7; background-color: #2f2f31; }}
.night_mode .ankigpt-options button {{ background: #3a3a3c; color: #ddd; border-color: #555; }}
.night_mode .ankigpt-option-correct {{ background: #24422a !important; }}
.night_mode .ankigpt-option-wrong {{ background: #4a2626 !important; }}
"""


def concept_notetype_id(col: Collection) -> NotetypeId | None:
    return col.models.id_for_name(NOTETYPE_NAME)


def concept_deck_ids(col: Collection) -> set[int]:
    """Ids of decks that hold at least one concept card."""
    ntid = concept_notetype_id(col)
    if ntid is None:
        return set()
    rows = col.db.list(
        "select distinct did from cards where nid in (select id from notes where mid = ?)",
        ntid,
    )
    return {int(r) for r in rows}


def ensure_notetype(col: Collection) -> NotetypeDict:
    """Return the concept notetype, creating it if this collection lacks it."""
    if existing := col.models.by_name(NOTETYPE_NAME):
        if existing.get("css") != _CSS:
            existing["css"] = _CSS
            col.models.update_dict(existing)
            existing = col.models.by_name(NOTETYPE_NAME) or existing
        return existing
    mm = col.models
    nt = mm.new(NOTETYPE_NAME)
    for name in FIELDS:
        mm.add_field(nt, mm.new_field(name))
    tmpl = mm.new_template("Concept")
    tmpl["qfmt"] = _QFMT
    tmpl["afmt"] = _AFMT
    mm.add_template(nt, tmpl)
    nt["css"] = _CSS
    mm.add(nt)
    created = mm.by_name(NOTETYPE_NAME)
    assert created is not None
    return created


def is_concept_note(col: Collection, note: Note) -> bool:
    ntid = concept_notetype_id(col)
    return ntid is not None and note.mid == ntid


def is_concept_card(col: Collection, card: Card) -> bool:
    ntid = concept_notetype_id(col)
    if ntid is None:
        return False
    return card.note_type()["id"] == ntid


# ---------------------------------------------------------------------------
# Field encoding: fields are HTML in Anki; we keep them readable in the editor
# and convert back to plain text for prompts.
# ---------------------------------------------------------------------------


def points_to_field(points: Sequence[str]) -> str:
    if not points:
        return ""
    items = "".join(f"<li>{html.escape(p)}</li>" for p in points)
    return f"<ul>{items}</ul>"


def sources_to_field(sources: Sequence[str]) -> str:
    return "".join(
        f"<blockquote>{html.escape(s).replace(chr(10), '<br>')}</blockquote>"
        for s in sources
    )


_ITEM_BREAK = re.compile(r"</(?:li|blockquote|p|div)>|<br\s*/?>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")


def field_to_lines(field: str) -> list[str]:
    """Split an HTML field back into plain-text lines (list items, quotes)."""
    parts = _ITEM_BREAK.split(field)
    lines = []
    for part in parts:
        text = html.unescape(_TAG.sub("", part)).strip()
        if text:
            lines.append(text)
    return lines


def field_to_text(field: str) -> str:
    return "\n".join(field_to_lines(field))


def deck_id_for_name(col: Collection, name: str) -> DeckId:
    return DeckId(col.decks.add_normal_deck_with_name(name).id)


def create_concept_notes(
    col: Collection,
    deck_id: DeckId,
    concepts: Sequence[ConceptCandidate],
    context: str = "",
) -> OpChanges:
    nt = ensure_notetype(col)
    requests: list[AddNoteRequest] = []
    for c in concepts:
        note = col.new_note(nt)
        note[FIELD_TITLE] = html.escape(c.title)
        note[FIELD_SUMMARY] = html.escape(c.summary)
        note[FIELD_KEY_POINTS] = points_to_field(c.key_points)
        note[FIELD_SOURCES] = sources_to_field(c.sources)
        note[FIELD_CONTEXT] = html.escape(context)
        requests.append(AddNoteRequest(note=note, deck_id=deck_id))
    return col.add_notes(requests)
