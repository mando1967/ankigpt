# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Retrieval of source passages for question generation, plus rendering of a
stored document with highlighted passages. Pure Python, no Qt."""

from __future__ import annotations

import bisect
import html
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9'-]+")
_STOPWORDS = frozenset(
    """a an and are as at be by for from has have in is it its of on or that the
    this to was were will with which what when where who why how not but can
    into than then there these those such also each other some more most only
    over under between about their them they you your we our one two""".split()
)
PASSAGE_CHARS = 1_200
MAX_PASSAGES = 3
MAX_CANDIDATES = 8
MAX_PASSAGE_CHARS_TOTAL = 3_500


@dataclass
class StoredSection:
    index: int
    title: str
    start: int
    end: int


@dataclass
class StoredDocument:
    id: int
    deck_id: int
    name: str
    path: str
    text: str
    sections: list[StoredSection]
    pages: list[int] = field(default_factory=list)  # char offset where each page starts

    def page_of(self, offset: int) -> int | None:
        if not self.pages:
            return None
        return bisect.bisect_right(self.pages, offset)

    def section_at(self, offset: int) -> StoredSection | None:
        for s in self.sections:
            if s.start <= offset < s.end:
                return s
        return None


@dataclass
class Passage:
    """A piece of a stored document, with enough metadata to cite and open it."""

    doc_id: int
    doc_name: str
    section: str
    start: int
    end: int
    text: str
    page: int | None = None
    score: float = 0.0

    def label(self) -> str:
        bits = [self.doc_name]
        if self.section:
            bits.append(f'"{self.section}"')
        if self.page is not None:
            bits.append(f"p. {self.page}")
        return " · ".join(bits)

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "doc_name": self.doc_name,
            "section": self.section,
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "page": self.page,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Passage:
        return Passage(
            doc_id=int(d["doc_id"]),
            doc_name=str(d.get("doc_name", "")),
            section=str(d.get("section", "")),
            start=int(d.get("start", 0)),
            end=int(d.get("end", 0)),
            text=str(d.get("text", "")),
            page=d.get("page"),
        )


# ---------------------------------------------------------------------------
# Lexical retrieval
# ---------------------------------------------------------------------------


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS]


def query_terms(
    title: str, key_points: Iterable[str], summary: str = ""
) -> dict[str, float]:
    """Weighted query: title terms count most, key points next, summary least."""
    weights: dict[str, float] = {}
    for term in tokenize(title):
        weights[term] = weights.get(term, 0.0) + 3.0
    for point in key_points:
        for term in tokenize(point):
            weights[term] = weights.get(term, 0.0) + 1.5
    for term in tokenize(summary):
        weights[term] = weights.get(term, 0.0) + 0.5
    return weights


def _section_texts(doc: StoredDocument) -> list[tuple[StoredSection, str]]:
    if doc.sections:
        return [(s, doc.text[s.start : s.end]) for s in doc.sections]
    return [(StoredSection(0, "", 0, len(doc.text)), doc.text)]


def rank_sections(
    docs: list[StoredDocument], terms: dict[str, float]
) -> list[tuple[float, StoredDocument, StoredSection, str]]:
    """BM25-style ranking of every section of every document."""
    entries: list[tuple[StoredDocument, StoredSection, str, dict[str, int]]] = []
    df: dict[str, int] = {}
    total_len = 0
    for doc in docs:
        for section, text in _section_texts(doc):
            counts: dict[str, int] = {}
            for tok in tokenize(text):
                counts[tok] = counts.get(tok, 0) + 1
            for term in counts:
                if term in terms:
                    df[term] = df.get(term, 0) + 1
            entries.append((doc, section, text, counts))
            total_len += sum(counts.values())
    if not entries:
        return []
    avg_len = max(1.0, total_len / len(entries))
    n = len(entries)
    k1, b = 1.2, 0.75
    ranked = []
    for doc, section, text, counts in entries:
        length = max(1, sum(counts.values()))
        score = 0.0
        for term, weight in terms.items():
            tf = counts.get(term, 0)
            if not tf:
                continue
            idf = math.log(1 + (n - df.get(term, 0) + 0.5) / (df.get(term, 0) + 0.5))
            score += (
                weight
                * idf
                * (tf * (k1 + 1))
                / (tf + k1 * (1 - b + b * length / avg_len))
            )
        if score > 0:
            ranked.append((score, doc, section, text))
    ranked.sort(key=lambda r: -r[0])
    return ranked


def _best_window(text: str, terms: dict[str, float], size: int) -> tuple[int, int]:
    """Offsets (within text) of the ~size-char window densest in query terms."""
    if len(text) <= size:
        return 0, len(text)
    positions = [
        (m.start(), terms.get(m.group(0), 0.0))
        for m in _TOKEN_RE.finditer(text.lower())
        if m.group(0) in terms
    ]
    if not positions:
        return 0, size
    best_start, best_score = 0, -1.0
    j = 0
    for i, (pos, _w) in enumerate(positions):
        while positions[j][0] < pos - size:
            j += 1
        score = sum(w for _p, w in positions[j : i + 1])
        if score > best_score:
            best_score, best_start = score, max(0, positions[j][0] - 80)
    start = best_start
    # snap to paragraph boundaries where possible
    prev = text.rfind("\n\n", max(0, start - 300), start)
    if prev != -1:
        start = prev + 2
    end = min(len(text), start + size)
    nxt = text.find("\n\n", end - 200, end + 200)
    if nxt != -1:
        end = nxt
    return start, end


def lexical_passages(
    docs: list[StoredDocument],
    title: str,
    key_points: Iterable[str],
    summary: str = "",
    limit: int = MAX_PASSAGES,
    max_total_chars: int = MAX_PASSAGE_CHARS_TOTAL,
) -> list[Passage]:
    """Top passages for a concept: best section windows across the deck's documents."""
    terms = query_terms(title, key_points, summary)
    if not terms:
        return []
    out: list[Passage] = []
    used = 0
    for score, doc, section, text in rank_sections(docs, terms):
        if len(out) >= limit or used >= max_total_chars:
            break
        rel_start, rel_end = _best_window(text, terms, PASSAGE_CHARS)
        start, end = section.start + rel_start, section.start + rel_end
        passage_text = doc.text[start:end].strip()
        if not passage_text:
            continue
        out.append(
            Passage(
                doc_id=doc.id,
                doc_name=doc.name,
                section=section.title,
                start=start,
                end=end,
                text=passage_text,
                page=doc.page_of(start),
                score=score,
            )
        )
        used += len(passage_text)
    return out


def candidate_sections(
    docs: list[StoredDocument],
    title: str,
    key_points: Iterable[str],
    summary: str = "",
    limit: int = MAX_CANDIDATES,
    max_chars: int = 12_000,
) -> list[Passage]:
    """Whole sections the model may ask for in a lookup step (full text kept
    in memory so no database access is needed off the main thread)."""
    terms = query_terms(title, key_points, summary)
    out: list[Passage] = []
    for score, doc, section, text in rank_sections(docs, terms)[:limit]:
        body = text[:max_chars]
        out.append(
            Passage(
                doc_id=doc.id,
                doc_name=doc.name,
                section=section.title,
                start=section.start,
                end=section.start + len(body),
                text=body.strip(),
                page=doc.page_of(section.start),
                score=score,
            )
        )
    return out


def preview(text: str, max_chars: int = 200) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= max_chars else text[:max_chars].rsplit(" ", 1)[0] + "…"


# ---------------------------------------------------------------------------
# Rendering a document with highlights
# ---------------------------------------------------------------------------


def render_document_html(
    doc: StoredDocument, highlights: list[tuple[int, int]] | None = None
) -> str:
    """Whole document as HTML: section headings become anchors, highlighted
    ranges become <mark> elements with ids hl0, hl1, ... in document order."""
    highlights = sorted(
        (max(0, s), min(len(doc.text), e)) for s, e in (highlights or [])
    )
    marks: list[tuple[int, str]] = []  # (offset, html to insert)
    for i, (s, e) in enumerate(highlights):
        if e > s:
            marks.append((s, f'<mark id="hl{i}">'))
            marks.append((e, "</mark>"))
    for section in doc.sections:
        if section.start > 0 or section.title:
            marks.append(
                (
                    section.start,
                    f'<a id="sec{section.index}"></a>',
                )
            )
    marks.sort(key=lambda m: m[0])
    pieces: list[str] = []
    pos = 0
    for offset, tag in marks:
        pieces.append(_para_html(doc.text[pos:offset]))
        pieces.append(tag)
        pos = offset
    pieces.append(_para_html(doc.text[pos:]))
    body = "".join(pieces)
    return (
        "<html><head><style>"
        "body{font-family:sans-serif;font-size:14px;line-height:1.45;margin:16px;}"
        "mark{background:#ffe680;color:#000;padding:0 2px;}"
        "</style></head><body>"
        f"{body}</body></html>"
    )


def _para_html(text: str) -> str:
    return html.escape(text).replace("\n\n", "<br><br>").replace("\n", "<br>")
