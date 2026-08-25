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


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------


def is_supported(path: str) -> bool:
    return path.lower().endswith(SUPPORTED_EXTENSIONS)


def extract_text(path: str) -> Document:
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
    return Document(name=name, text=_normalize(text))


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

    chunks: list[tuple[str, str]] = []
    for doc in docs:
        for chunk in chunk_text(doc.text):
            chunks.append((doc.name, chunk))
    if not chunks:
        return []
    total_chars = sum(len(c) for _, c in chunks)

    def want_for(chunk: str) -> int:
        share = target * 1.5 * len(chunk) / max(total_chars, 1)
        return max(2, min(MAX_PER_CHUNK, math.ceil(share) + 2))

    def run_chunk(item: tuple[str, str]) -> list[ConceptCandidate]:
        check_cancel()
        doc_name, chunk = item
        system, user = prompts.build_extract_prompt(
            chunk, instructions, want_for(chunk), doc_name
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
