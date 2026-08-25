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


def test_extract_text_samples_across_whole_file() -> None:
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "big.md")
        parts = []
        for i in range(60):
            parts.append(f"# Section {i}\n\nParagraph {i} " + "word " * 120)
        body = "\n\n".join(parts)
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        full = extract.extract_text(path)
        assert not full.sampled and full.total_chars == len(full.text)
        assert full.outline.splitlines()[0].endswith("Section 0")
        assert "Section 59" in full.outline

        capped = extract.extract_text(path, max_chars=8000)
        assert capped.sampled
        assert len(capped.text) <= 8000
        assert capped.total_chars == len(full.text)
        assert capped.windows >= 3
        # coverage spans the document, not just its head
        assert "Paragraph 0 " in capped.text or "Section 0" in capped.text
        assert any(f"Paragraph {i} " in capped.text for i in range(20, 40))
        assert any(f"Paragraph {i} " in capped.text for i in range(54, 60))
        assert (
            capped.text.count(extract.SEGMENT_SEPARATOR.strip()) == capped.windows - 1
        )
        assert 0 < capped.coverage < 0.3


def test_sample_evenly_and_outline_edge_cases() -> None:
    assert extract.sample_evenly("", 100) == []
    assert extract.sample_evenly("short", 100) == ["short"]
    assert extract.sample_evenly("x" * 100, 0) == []
    text = "\n\n".join(f"para {i} " + "w " * 200 for i in range(100))
    segments = extract.sample_evenly(text, 6000, window=2000)
    assert 2 <= len(segments) <= 4
    assert sum(len(s) for s in segments) <= 6000
    assert segments[0].startswith("para 0")
    assert "para 9" in segments[-1]

    outline = extract.build_outline(
        "Intro line.\n\nCHAPTER 1\n\n## Supply\n\n1.2 Demand curves\n\nplain sentence here.\n"
    )
    lines = [l.split("] ", 1)[1] for l in outline.splitlines()]
    assert lines == ["CHAPTER 1", "Supply", "1.2 Demand curves"]


def test_extract_prompt_includes_outline_and_sampling_note() -> None:
    from aqt.ankigpt import prompts

    _system, user = prompts.build_extract_prompt(
        "chunk", "", 5, "a.pdf", outline="[  0%] Intro", sampled=True
    )
    assert "DOCUMENT OUTLINE" in user and "[  0%] Intro" in user
    assert "evenly spaced excerpts" in user
    _system, user = prompts.build_extract_prompt("chunk", "", 5, "a.pdf")
    assert "OUTLINE" not in user and "excerpts" not in user
