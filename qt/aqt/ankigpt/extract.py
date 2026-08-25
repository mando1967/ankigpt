# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Document text extraction and the map/reduce concept extraction pipeline.

Pure Python: runs on a background thread, no Qt or collection access.
"""

from __future__ import annotations

import math
import os
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Protocol

from aqt.ankigpt import prompts
from aqt.ankigpt.prompts import ConceptCandidate

SUPPORTED_EXTENSIONS = (".pdf", ".txt", ".md", ".markdown", ".docx")
CHUNK_CHARS = 12_000
CHUNK_OVERLAP = 500
MERGE_BATCH = 60
DEFAULT_MAX_CHARS_PER_FILE = 150_000  # ~37k tokens, ~13 requests
MAX_PER_CHUNK = 15


class ExtractionError(Exception):
    pass


class Cancelled(Exception):
    pass


class JsonClient(Protocol):
    def complete_json(
        self, system: str, user: str, schema_name: str, json_schema: dict
    ) -> dict: ...


@dataclass
class Document:
    name: str
    text: str
    total_chars: int = 0
    sampled: bool = False
    windows: int = 1
    outline: str = ""

    def __post_init__(self) -> None:
        if not self.total_chars:
            self.total_chars = len(self.text)

    @property
    def coverage(self) -> float:
        return min(1.0, len(self.text) / self.total_chars) if self.total_chars else 1.0


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------


def is_supported(path: str) -> bool:
    return path.lower().endswith(SUPPORTED_EXTENSIONS)


def extract_text(path: str, max_chars: int | None = None) -> Document:
    """Read a document to plain text.

    `max_chars` is a hard cap on how much of the document is sent to the
    LLM (and therefore on how many tokens it can cost). Documents over the
    cap are not cut off at the start: evenly spaced windows spanning the
    whole document are used instead, and a heading outline scanned from the
    full text is attached so the model still sees the overall structure.
    """
    name = os.path.basename(path)
    lower = path.lower()
    if lower.endswith(".pdf"):
        text = _pdf_text(path)
    elif lower.endswith(".docx"):
        text = _docx_text(path)
    elif lower.endswith((".txt", ".md", ".markdown")):
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    else:
        raise ExtractionError(f"unsupported file type: {name}")
    text = _normalize(text)
    total = len(text)
    outline = build_outline(text)
    if max_chars is not None and total > max_chars:
        budget = max(0, max_chars - len(outline))
        segments = sample_evenly(text, budget)
        return Document(
            name=name,
            text=SEGMENT_SEPARATOR.join(segments),
            total_chars=total,
            sampled=True,
            windows=len(segments),
            outline=outline,
        )
    return Document(name=name, text=text, total_chars=total, outline=outline)


SEGMENT_SEPARATOR = "\n\n[...]\n\n"
OUTLINE_MAX_CHARS = 3_000
_HEADING_RE = re.compile(
    r"^(?:#{1,6}\s+\S.*|(?:chapter|part|section|unit|lecture|week|module)\s+[\dIVXivx]+\b.*"
    r"|\d+(?:\.\d+)*\.?\s+[A-Z].*|[A-Z][A-Z0-9 ,:'&-]{3,})$",
    re.IGNORECASE,
)


def _looks_like_heading(line: str) -> bool:
    line = line.strip()
    if not 3 <= len(line) <= 90 or line.endswith((".", ",", ";", ":")):
        return False
    if line.startswith("#"):
        return True
    m = _HEADING_RE.match(line)
    if not m:
        return False
    # all-caps branch must really be mostly letters
    if line.isupper():
        letters = sum(c.isalpha() for c in line)
        return letters >= len(line) * 0.6
    return True


def build_outline(text: str, max_chars: int = OUTLINE_MAX_CHARS) -> str:
    """Cheap, LLM-free table of contents: heading-like lines from the whole
    document with their approximate position, capped at max_chars."""
    if not text:
        return ""
    lines: list[str] = []
    seen: set[str] = set()
    pos = 0
    total = len(text)
    for raw in text.split("\n"):
        line = raw.strip().lstrip("#").strip()
        if _looks_like_heading(raw) and line.lower() not in seen:
            seen.add(line.lower())
            lines.append(f"[{int(100 * pos / total):3d}%] {line}")
        pos += len(raw) + 1
    out = "\n".join(lines)
    if len(out) > max_chars:
        out = out[:max_chars].rsplit("\n", 1)[0]
    return out


def sample_evenly(text: str, budget: int, window: int = CHUNK_CHARS) -> list[str]:
    """Pick evenly spaced windows (on paragraph boundaries) that together
    stay within `budget` characters and span the whole document."""
    if budget <= 0 or not text:
        return []
    if len(text) <= budget:
        return [text]
    # aim for at least four windows so the sample spans the document
    window = max(1000, min(window, budget // 4))
    count = max(1, budget // window)
    window = budget // count
    starts = [
        int(i * (len(text) - window) / max(count - 1, 1)) if count > 1 else 0
        for i in range(count)
    ]
    segments: list[str] = []
    last_end = 0
    for start in starts:
        start = max(start, last_end)
        if start >= len(text):
            break
        # snap forward to a paragraph boundary when one is near
        boundary = text.find("\n\n", start, start + window // 2)
        if boundary != -1 and start != 0:
            start = boundary + 2
        end = min(len(text), start + window)
        if end < len(text):
            cut = text.rfind("\n\n", start + window // 2, end)
            if cut != -1:
                end = cut
        segment = text[start:end].strip()
        if segment:
            segments.append(segment)
        last_end = end
    return segments


def _pdf_text(path: str) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency present in builds
        raise ExtractionError("PDF support requires the pypdf package") from exc
    reader = PdfReader(path)
    pages = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return "\n\n".join(pages)


def _docx_text(path: str) -> str:
    try:
        import docx  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover
        raise ExtractionError("DOCX support requires the python-docx package") from exc
    document = docx.Document(path)
    parts = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text for cell in row.cells))
    return "\n\n".join(parts)


def _normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def chunk_text(
    text: str, chunk_chars: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP
) -> list[str]:
    """Split on paragraph boundaries into chunks of roughly chunk_chars."""
    if not text:
        return []
    if len(text) <= chunk_chars:
        return [text]
    paragraphs = re.split(r"\n\s*\n", text)
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for para in paragraphs:
        # a single paragraph longer than a chunk is split hard
        while len(para) > chunk_chars:
            if current:
                chunks.append("\n\n".join(current))
                current, current_len = [], 0
            chunks.append(para[:chunk_chars])
            para = para[chunk_chars - overlap :]
        if current_len + len(para) + 2 > chunk_chars and current:
            chunks.append("\n\n".join(current))
            # carry over the tail of the previous chunk as overlap
            tail = chunks[-1][-overlap:] if overlap else ""
            current, current_len = ([tail] if tail else []), len(tail)
        current.append(para)
        current_len += len(para) + 2
    if current:
        chunks.append("\n\n".join(current))
    return [c for c in chunks if c.strip()]


def suggest_target_count(total_chars: int) -> int:
    return max(5, min(60, total_chars // 4000))


# ---------------------------------------------------------------------------
# Map / reduce
# ---------------------------------------------------------------------------

ProgressFn = Callable[[str, int, int], None]


def extract_concepts(
    docs: list[Document],
    instructions: str,
    target: int,
    client: JsonClient,
    progress: ProgressFn | None = None,
    should_cancel: Callable[[], bool] | None = None,
    workers: int = 4,
) -> list[ConceptCandidate]:
    def report(stage: str, i: int, n: int) -> None:
        if progress:
            progress(stage, i, n)

    def check_cancel() -> None:
        if should_cancel and should_cancel():
            raise Cancelled()

    chunks: list[tuple[Document, str]] = []
    for doc in docs:
        for chunk in chunk_text(doc.text):
            chunks.append((doc, chunk))
    if not chunks:
        return []
    total_chars = sum(len(c) for _, c in chunks)

    def want_for(chunk: str) -> int:
        share = target * 1.5 * len(chunk) / max(total_chars, 1)
        return max(2, min(MAX_PER_CHUNK, math.ceil(share) + 2))

    def run_chunk(item: tuple[Document, str]) -> list[ConceptCandidate]:
        check_cancel()
        doc, chunk = item
        system, user = prompts.build_extract_prompt(
            chunk,
            instructions,
            want_for(chunk),
            doc.name,
            outline=doc.outline,
            sampled=doc.sampled,
        )
        data = client.complete_json(
            system, user, "extract_concepts", prompts.EXTRACT_SCHEMA
        )
        return prompts.parse_concepts(data)

    candidates: list[ConceptCandidate] = []
    report("extract", 0, len(chunks))
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for i, result in enumerate(pool.map(run_chunk, chunks), start=1):
            candidates.extend(result)
            report("extract", i, len(chunks))
            check_cancel()

    if not candidates:
        return []
    report("merge", 0, 1)
    merged = _reduce(candidates, instructions, target, client, check_cancel)
    report("merge", 1, 1)
    return merged


def _merge_once(
    candidates: list[ConceptCandidate],
    instructions: str,
    target: int,
    client: JsonClient,
) -> list[ConceptCandidate]:
    system, user = prompts.build_merge_prompt(candidates, instructions, target)
    data = client.complete_json(system, user, "merge_concepts", prompts.MERGE_SCHEMA)
    return prompts.parse_concepts(data)


def _reduce(
    candidates: list[ConceptCandidate],
    instructions: str,
    target: int,
    client: JsonClient,
    check_cancel: Callable[[], None],
) -> list[ConceptCandidate]:
    while len(candidates) > MERGE_BATCH:
        batches = [
            candidates[i : i + MERGE_BATCH]
            for i in range(0, len(candidates), MERGE_BATCH)
        ]
        per_batch = max(3, math.ceil(target * 1.3 / len(batches)))
        reduced: list[ConceptCandidate] = []
        for batch in batches:
            check_cancel()
            reduced.extend(_merge_once(batch, instructions, per_batch, client))
        if len(reduced) >= len(candidates):
            # no progress; fall through to a single final merge
            candidates = reduced[:MERGE_BATCH]
            break
        candidates = reduced
    check_cancel()
    return _merge_once(candidates, instructions, target, client)
