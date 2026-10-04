# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Portable snapshots of generated study questions. Collection reads stay on UI thread."""

from __future__ import annotations

import html
import os
import re
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, cast

from aqt.ankigpt.prompts import GeneratedQuestion, Mode, QuestionRequest

if TYPE_CHECKING:
    from aqt.main import AnkiQt

FORMATS = {
    "PDF": (".pdf", "Questions and answers in a printable document."),
    "AnkiWeb": (
        ".txt",
        "Import this text file into Anki as Basic notes, then sync to AnkiWeb.",
    ),
    "Quizlet": (
        ".txt",
        "Paste the file into Quizlet's Import screen. Choose Tab between terms and definitions, and New line between cards.",
    ),
    "HTML": (
        ".html",
        "Open in a browser to study offline. Use Show Answer, Previous, and Next.",
    ),
}


def card_text(question: GeneratedQuestion) -> tuple[str, str]:
    front = question.question
    if question.options:
        front += "\n\n" + "\n".join(
            f"{i + 1}. {option}" for i, option in enumerate(question.options)
        )
    answer = question.model_answer
    if 0 <= question.correct_index < len(question.options):
        answer = f"{question.correct_index + 1}. {question.options[question.correct_index]}\n\n{answer}"
    if question.explanation:
        answer += "\n\n" + question.explanation
    if question.key_points:
        answer += "\n\n" + "\n".join(f"• {point}" for point in question.key_points)
    return front, answer.strip()


def _html_text(text: str) -> str:
    return (
        html.escape(text).replace("\t", "    ").replace("\r", "").replace("\n", "<br>")
    )


def import_text(questions: list[GeneratedQuestion], anki: bool) -> str:
    lines = ["#separator:Tab", "#html:true", "#columns:Front\tBack"] if anki else []
    for question in questions:
        fields: tuple[str, ...] = card_text(question)
        if anki:
            # Prefix markup also prevents a leading # from becoming an import comment.
            fields = tuple(f"<div>{_html_text(value)}</div>" for value in fields)
        else:
            fields = tuple(" ".join(value.split()) for value in fields)
        lines.append("\t".join(fields))
    return "\n".join(lines) + "\n"


def study_html(
    title: str, questions: list[GeneratedQuestion], interactive: bool = True
) -> str:
    cards = []
    for index, question in enumerate(questions):
        front, back = card_text(question)
        cards.append(
            f"<article><h2>Card {index + 1} · {html.escape(question.mode)}</h2>"
            f'<div>{_html_text(front)}</div><section class="answer">'
            f"<h3>Answer</h3>{_html_text(back)}</section></article>"
        )
    controls = (
        """
<nav aria-label="Study controls"><button id="previous">Previous</button>
<button id="reveal">Show Answer</button><button id="next">Next</button>
<p id="counter" aria-live="polite"></p></nav>
<script>
const cards = [...document.querySelectorAll('article')];
let current = 0;
const reveal = document.getElementById('reveal');
function show() {
  cards.forEach((card, i) => {
    card.hidden = i !== current;
    card.querySelector('.answer').hidden = true;
  });
  reveal.textContent = 'Show Answer';
  document.getElementById('counter').textContent = `Card ${current + 1} of ${cards.length}`;
}
document.getElementById('previous').onclick = () => { current = (current + cards.length - 1) % cards.length; show(); };
document.getElementById('next').onclick = () => { current = (current + 1) % cards.length; show(); };
reveal.onclick = () => {
  const answer = cards[current].querySelector('.answer');
  answer.hidden = !answer.hidden;
  reveal.textContent = answer.hidden ? 'Show Answer' : 'Hide Answer';
};
if (cards.length) show();
else document.querySelector('nav').hidden = true;
</script>"""
        if interactive
        else ""
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>
body {{font-family:Arial,sans-serif;line-height:1.6;margin:32px auto;padding:0 20px;max-width:800px;color:#18233f;background:#f3f6fb}}
article {{background:white;padding:24px;margin:20px 0;border:1px solid #ccd6e5;border-radius:12px;overflow-wrap:anywhere}}
.answer {{border-top:1px solid #ccd6e5;margin-top:24px;padding-top:12px}}
button {{padding:12px 18px;margin:4px;border:1px solid #3157d5;border-radius:8px;background:white;color:#2347a5;cursor:pointer;font-size:16px}}
[hidden] {{display:none!important}} nav {{text-align:center}}
@media print {{body {{background:white;margin:0}} nav {{display:none}} article {{break-inside:avoid}}}}
</style></head><body><h1>{html.escape(title)}</h1>{"".join(cards)}{controls}</body></html>"""


def write_export(
    path: str, format_name: str, title: str, questions: list[GeneratedQuestion]
) -> None:
    """Replace destination only after successful generation/writing."""
    fd, temporary = tempfile.mkstemp(
        suffix=FORMATS[format_name][0], dir=Path(path).parent
    )
    os.close(fd)
    try:
        if format_name == "PDF":
            from aqt.qt import QPageSize, QPdfWriter, QTextDocument

            writer = QPdfWriter(temporary)
            writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
            writer.setTitle(title)
            document = QTextDocument()
            pages = []
            for index, question in enumerate(questions):
                front, back = card_text(question)
                page_break = ' style="page-break-before:always"' if index else ""
                pages.append(
                    f"<h1{page_break}>{html.escape(title)}</h1>"
                    f"<h2>Card {index + 1} of {len(questions)}</h2>"
                    f"<p>{_html_text(front)}</p><hr><h3>Answer</h3>"
                    f"<p>{_html_text(back)}</p>"
                )
            document.setHtml(
                "<html><head><style>body {font-family:Arial;font-size:12pt;}"
                "</style></head><body>" + "".join(pages) + "</body></html>"
            )
            document.print(writer)
            del writer
        else:
            content = (
                study_html(title, questions)
                if format_name == "HTML"
                else import_text(questions, format_name == "AnkiWeb")
            )
            Path(temporary).write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save_study(mw: AnkiQt, message: str) -> None:
    from anki.decks import DeckId
    from aqt.ankigpt import concepts, get_store, prompts, retrieve
    from aqt.ankigpt.llm import make_client
    from aqt.ankigpt.review import ConceptReviewController
    from aqt.ankigpt.settings import deck_settings, llm_config
    from aqt.operations import QueryOp
    from aqt.qt import QInputDialog
    from aqt.utils import getSaveFile, showInfo, showWarning

    try:
        parts = message.removeprefix("ankigpt:save-study:").split(":")
        if len(parts) not in (2, 4):
            raise ValueError("Invalid save request.")
        raw_id, raw_modes = parts[:2]
        count = None
        if len(parts) == 4:
            if parts[2] != "focus":
                raise ValueError("Invalid focus card count.")
            count = int(parts[3])
            if not 1 <= count <= 100:
                raise ValueError("Invalid focus card count.")
        deck_id = DeckId(int(raw_id))
        modes = list(dict.fromkeys(raw_modes.split(",")))
        if not modes or any(
            mode not in ("typed", "mcq", "true_false", "fill_blank") for mode in modes
        ):
            raise ValueError("Select at least one valid study mode.")
        title = mw.col.decks.name_if_exists(deck_id)
        if not title:
            raise ValueError("The selected deck no longer exists.")
        requests: list[QuestionRequest] = []
        seen: set[int] = set()
        store = get_store()
        deck_ids = [
            deck_id,
            *(child_id for _, child_id in mw.col.decks.children(deck_id)),
        ]
        search = " OR ".join(f"did:{int(did)}" for did in deck_ids)
        for card_id in mw.col.find_cards(search):
            card = mw.col.get_card(card_id)
            note = card.note()
            if note.id in seen or not concepts.is_concept_note(mw.col, note):
                continue
            seen.add(note.id)
            settings = deck_settings(mw.col, card.current_deck_id())
            name = concepts.field_to_text(note[concepts.FIELD_TITLE])
            summary = concepts.field_to_text(note[concepts.FIELD_SUMMARY])
            points = concepts.field_to_lines(note[concepts.FIELD_KEY_POINTS])
            docs = store.documents_for_deck(int(card.current_deck_id()))
            for mode in modes:
                requests.append(
                    QuestionRequest(
                        title=name,
                        summary=summary,
                        key_points=points,
                        sources=concepts.field_to_lines(note[concepts.FIELD_SOURCES]),
                        context=settings.context
                        or concepts.field_to_text(note[concepts.FIELD_CONTEXT]),
                        mastery=prompts.mastery_from_state(None, card),
                        mode=cast(Mode, mode),
                        passages=retrieve.lexical_passages(docs, name, points, summary)
                        if docs
                        else [],
                    )
                )
        if not requests:
            raise ValueError(
                "This deck has no AnkiGPT concepts to export in the selected study modes."
            )
    except Exception as exc:
        showWarning(str(exc), parent=mw)
        return

    if count is None:
        count, accepted = QInputDialog.getInt(
            mw,
            "Save study deck",
            "How many cards would you like to generate?",
            20,
            1,
            10000,
            1,
        )
        if not accepted:
            return

    # Spread small exports across concepts and modes, then revisit concepts in
    # other modes. Larger exports generate new questions on subsequent passes.
    concept_count = len(requests) // len(modes)
    ordered = [
        requests[concept * len(modes) + (concept + turn) % len(modes)]
        for turn in range(len(modes))
        for concept in range(concept_count)
    ]
    selected = [ordered[index % len(ordered)] for index in range(count)]

    format_name, accepted = QInputDialog.getItem(
        mw,
        "Save study deck",
        f"Generate {count} cards using the selected study modes.\nIncludes subdecks; only AnkiGPT concepts are included.\nChoose a format:",
        list(FORMATS),
        0,
        False,
    )
    if not accepted:
        return
    extension, instructions = FORMATS[format_name]
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title).strip(" .") or "Study"
    path = getSaveFile(
        mw,  # type: ignore[arg-type]
        "Save study deck",
        "studyExport",
        format_name,
        extension,
        filename + extension,
    )
    if not path:
        return
    try:
        client = make_client(llm_config(mw.pm))
    except Exception as exc:
        showWarning(f"Could not configure question generation: {exc}", parent=mw)
        return

    def finished(questions: list[GeneratedQuestion]) -> None:
        try:
            write_export(path, format_name, title, questions)
        except Exception as exc:
            showWarning(f"Could not save study deck: {exc}", parent=mw)
            return
        showInfo(f"Saved {len(questions)} cards to {path}\n\n{instructions}", parent=mw)

    def generate() -> list[GeneratedQuestion]:
        questions: list[GeneratedQuestion] = []
        recent: dict[str, list[str]] = {}

        def report(completed: int) -> None:
            mw.taskman.run_on_main(
                lambda: mw.progress.update(
                    label=f"Generating study cards: {completed * 100 // count}% ({completed} of {count})",
                    value=completed,
                    max=count,
                )
            )

        report(0)
        for completed, request in enumerate(selected, start=1):
            history = recent.setdefault(request.title, [])
            question = ConceptReviewController._generate(
                client, replace(request, recent_questions=history[-8:])
            )
            questions.append(question)
            history.append(question.question)
            report(completed)
        return questions

    QueryOp(
        parent=mw,
        op=lambda _col: generate(),
        success=finished,
    ).without_collection().with_progress(
        f"Generating study cards: 0% (0 of {count})"
    ).failure(
        lambda exc: showWarning(f"Could not generate study deck: {exc}", parent=mw)
    ).run_in_background()
