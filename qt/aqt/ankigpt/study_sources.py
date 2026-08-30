# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Filesystem discovery for study materials.

Kept independent of Qt so folder/drop behavior can be tested without a GUI.
Locally synchronized cloud folders (including OneDrive) are ordinary folders
at this layer.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass, field

from aqt.ankigpt.extract import is_supported


@dataclass(frozen=True)
class CourseBrief:
    subject: str = ""
    level: str = "Introductory"
    focus: str = ""
    exclusions: str = ""
    question_style: str = "Balanced"
    notes: str = ""

    def instructions(self) -> str:
        """Render explicit constraints shared by extraction and review prompts."""
        lines = [
            f"Course or subject: {self.subject or 'Infer conservatively from the sources'}",
            f"Learner level: {self.level}",
            f"Question style: {self.question_style}",
            f"Priority topics: {self.focus or 'No additional priorities'}",
            f"Exclude or de-emphasize: {self.exclusions or 'Nothing specified'}",
        ]
        if self.notes:
            lines.append(f"Additional guidance: {self.notes}")
        return "\n".join(lines)


@dataclass
class SourceDiscovery:
    files: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


def discover_sources(paths: Iterable[str]) -> SourceDiscovery:
    """Expand files/folders into a stable, deduplicated list of documents."""
    result = SourceDiscovery()
    seen: set[str] = set()

    def add_file(path: str) -> None:
        absolute = os.path.abspath(path)
        key = os.path.normcase(os.path.normpath(absolute))
        if key in seen:
            return
        seen.add(key)
        if is_supported(absolute):
            result.files.append(absolute)
        else:
            result.unsupported.append(absolute)

    for raw_path in paths:
        path = os.path.abspath(os.path.expanduser(raw_path))
        if os.path.isfile(path):
            add_file(path)
        elif os.path.isdir(path):
            for root, dirs, names in os.walk(path, followlinks=False):
                dirs.sort(key=str.casefold)
                for name in sorted(names, key=str.casefold):
                    add_file(os.path.join(root, name))
        else:
            result.missing.append(path)
    return result


def total_size(paths: Iterable[str]) -> int:
    total = 0
    for path in paths:
        try:
            total += os.path.getsize(path)
        except OSError:
            pass
    return total


def document_deck_names(root: str, document_names: Iterable[str]) -> list[str]:
    """Stable, collision-safe child deck names for a group of documents."""
    used: dict[str, int] = {}
    destinations: list[str] = []
    for name in document_names:
        stem = os.path.splitext(os.path.basename(name))[0].strip().replace("::", " - ")
        stem = stem or "Untitled document"
        used[stem] = used.get(stem, 0) + 1
        suffix = f" ({used[stem]})" if used[stem] > 1 else ""
        destinations.append(f"{root}::{stem}{suffix}")
    return destinations
