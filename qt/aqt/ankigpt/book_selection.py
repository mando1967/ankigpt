# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Explicit source selection before any AI reading budget is applied."""

from __future__ import annotations

import re

from aqt.ankigpt.book_structure import BookUnit
from aqt.ankigpt.extract import Document


def parse_ranges(value: str) -> list[tuple[int, int]]:
    ranges = []
    for part in value.replace("–", "-").replace("—", "-").split(","):
        match = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+)\s*)?", part)
        if not match:
            raise ValueError("Enter numbers or ranges, for example 10-18 or 3, 7-9.")
        first = int(match[1])
        last = int(match[2] or match[1])
        if first < 1 or last < first:
            raise ValueError("Ranges must start at 1 or later and run forwards.")
        ranges.append((first, last))
    merged: list[tuple[int, int]] = []
    for first, last in sorted(ranges):
        if merged and first <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(last, merged[-1][1]))
        else:
            merged.append((first, last))
    return merged


def select_chapters(chapters: list[BookUnit], value: str) -> None:
    ranges = parse_ranges(value)
    selected = []
    detected: set[int] = set()
    for chapter in chapters:
        match = re.match(r"^(?:chapter\s+)?(\d+)\b", chapter.title, re.IGNORECASE)
        number = (
            chapter.number
            if chapter.number is not None
            else int(match[1])
            if match
            else None
        )
        if number is not None:
            detected.add(number)
        selected.append(number is not None and any(a <= number <= b for a, b in ranges))
    # Fail closed: never silently process only part of the requested range.
    if any(sum(a <= n <= b for n in detected) != b - a + 1 for a, b in ranges):
        raise ValueError(
            "Some requested chapter numbers were not detected. "
            f"Detected chapter numbers: {', '.join(str(n) for n in sorted(detected)) or 'none'}. "
            "Use PDF page positions if the book's headings cannot be read."
        )
    for chapter, included in zip(chapters, selected):
        chapter.included = included
        for child in chapter.children:
            child.included = included


def page_units(doc: Document, value: str) -> list[BookUnit]:
    if not doc.pages:
        raise ValueError("Page selection is available for PDFs only.")
    ranges = parse_ranges(value)
    if ranges[-1][1] > len(doc.pages):
        raise ValueError(
            f"This PDF has {len(doc.pages)} pages. Use PDF page positions, not printed page numbers."
        )
    units = []
    for first, last in ranges:
        start = doc.pages[first - 1]
        end = doc.pages[last] if last < len(doc.pages) else len(doc.text)
        title = f"PDF pages {first}-{last}"
        unit = BookUnit(title, start, end)
        unit.children = [BookUnit(title, start, end)]
        units.append(unit)
    return units
