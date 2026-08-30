# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Book chapter/section detection independent of the reading planner."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

from aqt.ankigpt.extract import split_sections, suggest_target_count

_HEADING = re.compile(
    r"(?m)^(?P<marks>#{1,6})\s+(?P<markdown>\S.*)$|"
    r"^(?P<plain>(?:(?:chapter|part|section|unit)\s+[\dIVXivx]+\b|"
    r"\d+(?:\.\d+)*\.?\s+)[A-Z][^\n]{2,89}|[A-Z][A-Z0-9 ,:'&-]{3,89})$"
)
_CHAPTER = re.compile(r"^(?:chapter|part|unit)\s+[\dIVXivx]+\b", re.IGNORECASE)

STRUCTURE_SCHEMA = {
    "type": "object",
    "properties": {
        "headings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "kind": {
                        "type": "string",
                        "enum": ["chapter", "section", "ignore"],
                    },
                    "title": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["index", "kind", "title", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["headings"],
    "additionalProperties": False,
}


class StructureClient(Protocol):
    def complete_json(
        self, system: str, user: str, schema_name: str, json_schema: dict
    ) -> dict: ...


@dataclass
class BookUnit:
    title: str
    start: int
    end: int
    children: list[BookUnit] = field(default_factory=list)
    included: bool = True
    confidence: float = 1.0

    @property
    def length(self) -> int:
        return max(0, self.end - self.start)

    @property
    def suggested_concepts(self) -> int:
        return suggest_target_count(self.length)


def deck_root(course: str, subcategory: str) -> str:
    """The common parent for ordinary decks and generated book decks."""
    return f"{course.strip().strip(':')}::{subcategory.strip().strip(':')}"


def detect_book_structure(text: str) -> list[BookUnit]:
    """Return chapters with section children while preserving text offsets."""
    headings: list[tuple[int, str, int]] = []
    for match in _HEADING.finditer(text):
        title = (match.group("markdown") or match.group("plain") or "").strip()
        level = len(match.group("marks") or "")
        if not level:
            level = 1 if _CHAPTER.match(title) else 2
        headings.append((match.start(), title, level))

    chapter_positions = [
        i
        for i, (_, title, level) in enumerate(headings)
        if level == 1 or _CHAPTER.match(title)
    ]
    if not chapter_positions:
        return [
            BookUnit(section.title, section.start, section.end)
            for section in split_sections(text, min_chars=1, max_sections=500)
        ]

    chapters: list[BookUnit] = []
    for position, heading_index in enumerate(chapter_positions):
        start, title, chapter_level = headings[heading_index]
        end = (
            headings[chapter_positions[position + 1]][0]
            if position + 1 < len(chapter_positions)
            else len(text)
        )
        chapter = BookUnit(title, start, end)
        candidates = headings[heading_index + 1 :]
        section_heads = [
            item for item in candidates if item[0] < end and item[2] > chapter_level
        ]
        for section_index, (section_start, section_title, _level) in enumerate(
            section_heads
        ):
            section_end = (
                section_heads[section_index + 1][0]
                if section_index + 1 < len(section_heads)
                else end
            )
            chapter.children.append(BookUnit(section_title, section_start, section_end))
        if not chapter.children:
            chapter.children.append(BookUnit(title, start, end))
        chapters.append(chapter)
    return chapters


def classify_book_structure(
    text: str, client: StructureClient
) -> tuple[list[BookUnit], bool]:
    """Classify local candidates with the model, validating all offsets locally."""
    matches = list(_HEADING.finditer(text))
    if len(matches) < 2:
        return detect_book_structure(text), False
    lines: list[str] = []
    candidates: list[tuple[int, str, int]] = []
    for index, match in enumerate(matches[:500]):
        title = (match.group("markdown") or match.group("plain") or "").strip()
        level = len(match.group("marks") or "")
        suggested = (
            "chapter"
            if level == 1 or _CHAPTER.match(title) or re.match(r"^\d+\.?\s+", title)
            else "section"
        )
        candidates.append((match.start(), title, level))
        lines.append(
            f"[{index}] offset={match.start()} suggested={suggested} title={title}"
        )
    system = """Classify candidate book headings. Keep real chapter and section boundaries; ignore table-of-contents entries, repeated headers/footers, and decorative lines. Never invent indices. Chapters contain following sections until the next chapter. Return concise cleaned titles and confidence from 0 to 1."""
    user = "DOCUMENT HEADING CANDIDATES:\n" + "\n".join(lines)
    try:
        data = client.complete_json(
            system, user, "classify_book_structure", STRUCTURE_SCHEMA
        )
        units = _validated_classification(text, candidates, data)
    except Exception:
        units = []
    return (units, True) if units else (detect_book_structure(text), False)


def _validated_classification(
    text: str, candidates: list[tuple[int, str, int]], data: dict
) -> list[BookUnit]:
    selected: list[tuple[int, str, str, float]] = []
    seen: set[int] = set()
    for raw in data.get("headings", []):
        try:
            index = int(raw["index"])
            kind = str(raw["kind"])
            confidence = max(0.0, min(1.0, float(raw["confidence"])))
        except (KeyError, TypeError, ValueError):
            continue
        if index in seen or not 0 <= index < len(candidates) or kind == "ignore":
            continue
        seen.add(index)
        title = str(raw.get("title", "")).strip() or candidates[index][1]
        selected.append((index, kind, title[:120], confidence))
    selected.sort()
    # Exact repeats commonly come from a table of contents followed by the real
    # heading. Keep the later boundary, which is normally the body occurrence.
    last_for_title: dict[tuple[str, str], int] = {}
    for position, (_index, kind, title, _confidence) in enumerate(selected):
        last_for_title[(kind, title.casefold())] = position
    selected = [
        item
        for position, item in enumerate(selected)
        if last_for_title[(item[1], item[2].casefold())] == position
    ]
    if not any(kind == "chapter" for _index, kind, _title, _confidence in selected):
        return []
    chapters: list[BookUnit] = []
    current: BookUnit | None = None
    for position, (index, kind, title, confidence) in enumerate(selected):
        start = candidates[index][0]
        end = (
            candidates[selected[position + 1][0]][0]
            if position + 1 < len(selected)
            else len(text)
        )
        if kind == "chapter":
            if current is not None:
                current.end = start
            current = BookUnit(title, start, end, confidence=confidence)
            chapters.append(current)
        elif kind == "section" and current is not None:
            current.children.append(BookUnit(title, start, end, confidence=confidence))
    if current is not None:
        current.end = len(text)
    for chapter in chapters:
        if not chapter.children:
            chapter.children.append(
                BookUnit(
                    chapter.title,
                    chapter.start,
                    chapter.end,
                    confidence=chapter.confidence,
                )
            )
        else:
            chapter.children[-1].end = chapter.end
    chapters = _promote_numbered_chapter_groups(chapters)
    for chapter in chapters:
        if chapter.length < 500:
            chapter.confidence = min(chapter.confidence, 0.5)
        for section in chapter.children:
            if section.length < 200:
                section.confidence = min(section.confidence, 0.5)
    return [chapter for chapter in chapters if chapter.end > chapter.start]


def _promote_numbered_chapter_groups(chapters: list[BookUnit]) -> list[BookUnit]:
    """Turn 1.1/1.2, 2.1/2.2 section runs into Chapter 1, Chapter 2, etc."""
    promoted: list[BookUnit] = []
    for parent in chapters:
        numbered: list[tuple[str, BookUnit]] = []
        for child in parent.children:
            match = re.match(r"^\s*(\d+)\.\d+(?:\.\d+)*\b", child.title)
            if not match:
                numbered = []
                break
            numbered.append((match.group(1), child))
        majors = [major for major, _child in numbered]
        distinct = list(dict.fromkeys(majors))
        if len(distinct) < 2:
            promoted.append(parent)
            continue
        # A major number must occur in one contiguous run.
        runs = [majors[0]] if majors else []
        for major in majors[1:]:
            if major != runs[-1]:
                runs.append(major)
        if len(runs) != len(set(runs)) or [int(major) for major in runs] != sorted(
            int(major) for major in runs
        ):
            promoted.append(parent)
            continue
        for run_index, major in enumerate(runs):
            children = [
                child for child_major, child in numbered if child_major == major
            ]
            end = (
                next(
                    child.start
                    for child_major, child in numbered
                    if child_major == runs[run_index + 1]
                )
                if run_index + 1 < len(runs)
                else parent.end
            )
            children[-1].end = end
            promoted.append(
                BookUnit(
                    f"Chapter {major}",
                    children[0].start,
                    end,
                    children=children,
                    included=parent.included,
                    confidence=min(
                        parent.confidence, *(child.confidence for child in children)
                    ),
                )
            )
    return promoted


def generation_units(
    chapters: list[BookUnit], per_section: bool
) -> list[tuple[list[str], BookUnit]]:
    units: list[tuple[list[str], BookUnit]] = []
    for chapter in chapters:
        if not chapter.included:
            continue
        if per_section:
            for section in chapter.children:
                if not section.included:
                    continue
                path = (
                    [chapter.title]
                    if section.start == chapter.start
                    and section.end == chapter.end
                    and section.title == chapter.title
                    else [chapter.title, section.title]
                )
                units.append((path, section))
        else:
            units.append(([chapter.title], chapter))
    return units
