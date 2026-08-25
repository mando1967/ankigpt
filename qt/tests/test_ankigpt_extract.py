# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from __future__ import annotations

import os
import tempfile

import pytest

from aqt.ankigpt import extract
from aqt.ankigpt.extract import Cancelled, Document, chunk_text, extract_concepts
from aqt.ankigpt.llm import FakeLLMClient


def paragraphs(n: int, size: int = 400) -> str:
    return "\n\n".join(
        f"Paragraph {i} about topic {i}. " + ("lorem ipsum " * (size // 12))
        for i in range(n)
    )


def test_chunk_small_text_is_single_chunk() -> None:
    assert chunk_text("hello") == ["hello"]
    assert chunk_text("") == []


def test_chunk_splits_on_paragraphs_with_overlap() -> None:
    text = paragraphs(30, 400)
    chunks = chunk_text(text, chunk_chars=3000, overlap=200)
    assert len(chunks) > 1
    assert all(len(c) <= 3000 + 200 for c in chunks)
    # every paragraph survives somewhere
    for i in range(30):
        assert any(f"Paragraph {i} " in c for c in chunks)
    # overlap: the tail of chunk 0 starts chunk 1
    assert chunks[1].startswith(chunks[0][-200:])


def test_chunk_hard_splits_giant_paragraph() -> None:
    text = "x" * 10_000
    chunks = chunk_text(text, chunk_chars=4000, overlap=100)
    assert len(chunks) == 3
    assert "".join(c[: 4000 - 100] for c in chunks[:-1]) + chunks[-1] == text


def test_extract_text_txt_and_md() -> None:
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "notes.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write("# Title\r\n\r\nBody  \r\n\r\n\r\n\r\nMore")
        doc = extract.extract_text(path)
        assert doc.name == "notes.md"
        assert doc.text == "# Title\n\nBody\n\nMore"
        with pytest.raises(extract.ExtractionError):
            extract.extract_text(os.path.join(d, "x.xyz"))


def test_extract_concepts_map_reduce_with_fake_client() -> None:
    client = FakeLLMClient()
    docs = [
        Document("a.md", paragraphs(40, 500)),
        Document("b.md", paragraphs(10, 500)),
    ]
    progress: list[tuple[str, int, int]] = []
    result = extract_concepts(
        docs, "focus on topics", 8, client, progress=lambda *a: progress.append(a)
    )
    assert len(result) == 8
    assert all(c.title and c.summary for c in result)
    schemas = [c[0] for c in client.calls]
    assert schemas.count("merge_concepts") == 1
    assert schemas.count("extract_concepts") >= 2
    assert progress[0] == ("extract", 0, schemas.count("extract_concepts"))
    assert progress[-1] == ("merge", 1, 1)


def test_extract_concepts_cancel() -> None:
    client = FakeLLMClient()
    docs = [Document("a.md", paragraphs(5))]
    with pytest.raises(Cancelled):
        extract_concepts(docs, "", 5, client, should_cancel=lambda: True)


def test_suggest_target_count() -> None:
    assert extract.suggest_target_count(0) == 5
    assert extract.suggest_target_count(100_000) == 25
    assert extract.suggest_target_count(10_000_000) == 60
