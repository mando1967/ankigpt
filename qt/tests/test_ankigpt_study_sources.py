# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from __future__ import annotations

from pathlib import Path

from aqt.ankigpt.study_sources import CourseBrief, discover_sources, total_size


def test_course_brief_produces_explicit_prompt_constraints() -> None:
    brief = CourseBrief(
        subject="Statics",
        level="Intermediate",
        focus="moments and equilibrium",
        exclusions="administrative schedules",
        question_style="Applied problems",
        notes="Use SI units",
    )

    instructions = brief.instructions()

    assert "Course or subject: Statics" in instructions
    assert "Priority topics: moments and equilibrium" in instructions
    assert "Exclude or de-emphasize: administrative schedules" in instructions
    assert "Question style: Applied problems" in instructions
    assert "Additional guidance: Use SI units" in instructions


def test_discover_files_and_recursive_folders(tmp_path: Path) -> None:
    notes = tmp_path / "Course"
    nested = notes / "Week 1"
    nested.mkdir(parents=True)
    pdf = notes / "slides.PDF"
    markdown = nested / "notes.md"
    ignored = nested / "recording.mp4"
    pdf.write_bytes(b"pdf")
    markdown.write_text("notes", encoding="utf-8")
    ignored.write_bytes(b"video")

    result = discover_sources([str(notes)])

    assert result.files == [str(pdf.resolve()), str(markdown.resolve())]
    assert result.unsupported == [str(ignored.resolve())]
    assert result.missing == []
    assert total_size(result.files) == 8


def test_discovery_deduplicates_explicit_and_folder_paths(tmp_path: Path) -> None:
    document = tmp_path / "chapter.txt"
    document.write_text("text", encoding="utf-8")

    result = discover_sources([str(document), str(tmp_path), str(document)])

    assert result.files == [str(document.resolve())]


def test_discovery_reports_missing_paths(tmp_path: Path) -> None:
    missing = tmp_path / "missing.docx"

    result = discover_sources([str(missing)])

    assert result.files == []
    assert result.missing == [str(missing.resolve())]
