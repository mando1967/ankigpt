# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from __future__ import annotations

import os
import tempfile

import pytest

from aqt.ankigpt import extract, prompts
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
    progress: list[extract.ProgressEvent] = []
    result = extract_concepts(
        docs, "focus on topics", 8, client, progress=progress.append
    )
    assert len(result) == 8
    assert all(c.title and c.summary for c in result)
    schemas = [c[0] for c in client.calls]
    assert schemas.count("merge_concepts") == 1
    assert schemas.count("extract_concepts") >= 2
    assert (progress[0].stage, progress[0].current, progress[0].total) == ("plan", 0, 2)
    extract_events = [e for e in progress if e.stage == "extract"]
    assert extract_events[0].total == schemas.count("extract_concepts")
    assert extract_events[-1].candidates > 0
    assert "candidates" in extract_events[-1].message
    assert progress[-1].stage == "done"
    assert any(e.stage == "merge" and "concepts ready" in e.message for e in progress)


def test_extract_concepts_cancel() -> None:
    client = FakeLLMClient()
    docs = [Document("a.md", paragraphs(5))]
    with pytest.raises(Cancelled):
        extract_concepts(docs, "", 5, client, should_cancel=lambda: True)


def test_suggest_target_count() -> None:
    assert extract.suggest_target_count(0) == 5
    assert extract.suggest_target_count(100_000) == 25
    assert extract.suggest_target_count(10_000_000) == 60


def make_doc(sections: int = 60, words: int = 120) -> str:
    parts = []
    for i in range(sections):
        parts.append(f"# Section {i}\n\nParagraph {i} " + "word " * words)
    return "\n\n".join(parts)


def test_extract_text_reads_whole_file_and_builds_outline() -> None:
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "big.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(make_doc())
        doc = extract.extract_text(path)
        assert doc.total_chars == len(doc.text)
        assert doc.outline.splitlines()[0].endswith("Section 0")
        assert "Section 59" in doc.outline
        assert doc.report is None


def test_split_sections_headings_tiny_merge_and_fallback() -> None:
    sections = extract.split_sections(make_doc(10, 400), min_chars=500)
    assert [s.title for s in sections] == [f"Section {i}" for i in range(10)]
    assert sections[0].start == 0 and sections[-1].end == len(make_doc(10, 400))
    assert all(s.text.startswith("# Section") for s in sections)

    # tiny sections are merged into their predecessor
    text = "# A\n\n" + "a " * 800 + "\n\n# B\n\nshort\n\n# C\n\n" + "c " * 800
    sections = extract.split_sections(text, min_chars=100)
    assert [s.title for s in sections] == ["A", "C"]
    assert "short" in sections[1].text

    # a run of short sections forms bounded groups, not one giant section
    run = "\n\n".join(f"# S{i}\n\n" + "w " * 100 for i in range(40))
    sections = extract.split_sections(run, min_chars=500)
    assert 3 <= len(sections) <= 15
    assert all(500 <= s.length <= 2200 for s in sections[:-1])

    # no headings: fixed-size pseudo sections
    plain = "plain words " * 5000
    sections = extract.split_sections(plain)
    assert len(sections) >= 4
    assert all(s.title.startswith("Part ") for s in sections)

    # too many sections are grouped
    many = "\n\n".join(f"# H{i}\n\n" + "x " * 900 for i in range(400))
    sections = extract.split_sections(many, min_chars=100, max_sections=100)
    assert len(sections) <= 100
    assert sections[-1].end == len(many)


def test_skim_and_allocate_budget() -> None:
    sections = extract.split_sections(make_doc(20, 400), min_chars=100)
    skim = extract.build_skim(sections, len(make_doc(20, 400)))
    lines = skim.splitlines()
    assert len(lines) == 20
    assert lines[3].startswith("[3] (")
    assert "Section 3: Paragraph 3 word" in lines[3]

    budget = sections[0].length * 2 + 100
    plan = extract.allocate_budget(
        sections, [(5, 3), (2, 5), (9, 5), (2, 1), (99, 5)], budget
    )
    # highest priority first (2 and 9), then 5 does not fit
    assert plan.indices() == {2, 9}
    assert plan.chars <= budget
    assert [s.index for s, _ in plan.picks] == [2, 9]  # document order
    # a partial read is sampled within the section
    plan = extract.allocate_budget(sections, [(4, 5)], sections[4].length // 2)
    assert plan.picks and plan.picks[0][1] < sections[4].length
    rendered = extract.render_plan(plan)
    assert 0 < len(rendered) <= sections[4].length // 2 + 50


def test_extract_concepts_plans_reading_under_budget() -> None:
    client = FakeLLMClient()
    text = make_doc(80, 200)  # ~80k chars, well over the budget
    doc = Document("course.md", text)
    budget = 45_000
    result = extract_concepts(
        [doc], "focus on later sections", 6, client, max_chars_per_file=budget
    )
    assert len(result) == 6
    schemas = [c[0] for c in client.calls]
    assert schemas.count("plan_reading") == 1
    assert schemas.count("find_gaps") == 1
    assert schemas.index("plan_reading") < schemas.index("extract_concepts")
    assert doc.report is not None and doc.report.planned and doc.report.partial
    assert doc.report.sections_total >= 10
    assert 0 < doc.report.sections_read < doc.report.sections_total
    # everything sent to the model for this document stays within the budget
    sent = sum(
        len(user.split(prompts.CHUNK_MARKER, 1)[-1])
        for name, _sys, user in client.calls
        if name == "extract_concepts"
    )
    assert sent <= budget
    # the fake planner picks every fourth section, so the read spans the doc
    read_chunks = [
        user for name, _sys, user in client.calls if name == "extract_concepts"
    ]
    assert any("Paragraph 0 " in u for u in read_chunks)
    assert any("Section 3" in u for u in read_chunks)  # outline present


def test_extract_concepts_small_doc_skips_planning() -> None:
    client = FakeLLMClient()
    doc = Document("small.md", make_doc(3, 50))
    extract_concepts([doc], "", 3, client, max_chars_per_file=100_000)
    schemas = [c[0] for c in client.calls]
    assert "plan_reading" not in schemas and "find_gaps" not in schemas
    assert doc.report is not None and not doc.report.partial


def test_extract_concepts_falls_back_to_sampling_when_plan_fails() -> None:
    class BrokenPlanner(FakeLLMClient):
        def complete_json(self, system, user, schema_name, json_schema):  # type: ignore[override]
            if schema_name == "plan_reading":
                raise RuntimeError("planner down")
            return super().complete_json(system, user, schema_name, json_schema)

    client = BrokenPlanner()
    doc = Document("big.md", make_doc(40, 200))
    result = extract_concepts([doc], "", 5, client, max_chars_per_file=12_000)
    assert result
    assert doc.report is not None and doc.report.fallback and doc.report.partial
    assert "find_gaps" not in [c[0] for c in client.calls]


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
    assert "selected sections" in user
    _system, user = prompts.build_extract_prompt("chunk", "", 5, "a.pdf")
    assert "OUTLINE" not in user and "excerpts" not in user
    assert "hard relevance constraints" in _system
    assert "instead of guessing" in _system
