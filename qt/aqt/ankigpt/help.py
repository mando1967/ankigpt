# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Help > AnkiGPT Guide: an in-app overview of what AnkiGPT adds to Anki."""

from __future__ import annotations

from typing import TYPE_CHECKING

from aqt.qt import *
from aqt.utils import disable_help_button, restoreGeom, saveGeom, tr

if TYPE_CHECKING:
    from aqt.main import AnkiQt

GUIDE_HTML = """
<h2>What AnkiGPT adds to Anki</h2>
<p>AnkiGPT is Anki with one change: for <b>concept decks</b>, the unit of study is a
<i>concept</i> rather than a fixed card. Anki's scheduler still decides what is due; when a
concept comes up, an AI model writes a fresh question for it on the spot, adapted to how well
you already know it. Ordinary decks, sync, the browser and statistics work exactly as before.</p>

<h3>1. Set up the AI</h3>
<p><b>Preferences &rsaquo; Third Party Services</b>: enter your API key. The base URL and model
are editable, so any OpenAI-compatible service works. <i>Max characters read per document</i>
is a hard cap on how much of each file is sent to the model when building a deck.</p>

<h3>2. Build a concept deck from your material</h3>
<p>Click <b>AI Concept Deck</b> at the bottom of the deck list (or Tools &rsaquo; AnkiGPT).
Add PDF, DOCX, Markdown or text files, write a line of instructions (course name, what to
focus on), choose how many concepts you want and a grading mode, then <b>Extract Concepts</b>.</p>
<ul>
<li>Small documents are read in full. Large ones are read selectively under the per-file
budget: the model skims the section headings and first lines, plans which sections to read,
extracts, and does one check for skipped sections. The progress page shows what happened.</li>
<li>You get a table of proposed concepts (title, summary, key points). Untick or edit rows,
then <b>Create Notes</b>. Each concept becomes a note of the <i>AnkiGPT Concept</i> type,
which you can edit in the browser like any note.</li>
</ul>

<h3>3. Study</h3>
<p>Concept decks carry an <b>AI</b> badge in the deck list, and their overview shows the
grading mode and a <b>Concept Settings</b> button. Study them like any deck. Each question
shows a header with the mode and your mastery level; after answering you also see the model
answer, key points, and a <i>From your notes</i> section with the concept the question came
from.</p>
<p><b>Sources.</b> The documents you built the deck from are kept (next to your
profile, not in the collection). When a question is generated, the most relevant passages
are retrieved from them and shown after you answer, under <i>From your notes</i>; passages
the model relied on are starred. <b>Open in source</b> opens the document with those
passages highlighted; <b>Open Original File</b> opens the file itself. The deck overview's
<b>Sources</b> button browses the stored documents. For concepts you know well, the model
may first read up to two more sections of your documents (one extra request; switch it off
per deck in Concept Settings).</p>

<p>Grading modes (per deck):</p>
<ul>
<li><b>Self-grade</b>: think, press Show Answer, rate with Again/Hard/Good/Easy as usual.</li>
<li><b>Typed answer</b>: type into the box and press Enter. The AI grades it, explains what was
missing and pre-selects a rating (marked &#9733;). Enter or Space accepts it; 1&ndash;4 override.
<i>Automatically submit</i> in Concept Settings skips the confirmation.</li>
<li><b>Multiple choice</b>: click an option or press 1&ndash;4. Correct &rarr; Good, wrong &rarr;
Again, with the explanation shown.</li>
<li><b>Random mix</b>: one of the above, chosen per question.</li>
</ul>
<p>Questions get harder as a concept's memory strengthens: new concepts get basic recall,
well-known ones get application, transfer and critique questions. Recently asked questions are
remembered so they are not repeated.</p>

<h3>4. Settings and data</h3>
<ul>
<li><b>Concept Settings</b> (deck overview, deck gear menu, or Tools &rsaquo; AnkiGPT): grading
mode, auto-submit, and the context given to the AI for this deck.</li>
<li>Question history and prefetched questions live in <code>ankigpt.sqlite</code> next to your
profile; concept notes sync with the rest of your collection.</li>
<li>If no API key is set or the service fails, studying a concept deck stops with an error
rather than showing a degraded card.</li>
<li>Keyboard: everything Anki already does, plus Enter to submit a typed answer
(Shift+Enter for a new line) and 1&ndash;4 to pick a multiple-choice option.</li>
</ul>
"""


class GuideDialog(QDialog):
    def __init__(self, mw: AnkiQt):
        super().__init__(mw)
        self.setWindowTitle(tr.ankigpt_help_title())
        disable_help_button(self)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml(GUIDE_HTML)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        qconnect(buttons.rejected, self.reject)
        qconnect(buttons.accepted, self.accept)
        layout = QVBoxLayout()
        layout.addWidget(browser)
        layout.addWidget(buttons)
        self.setLayout(layout)
        self.resize(720, 640)
        restoreGeom(self, "ankigptGuide")

    def reject(self) -> None:
        saveGeom(self, "ankigptGuide")
        super().reject()


def show_guide(mw: AnkiQt) -> None:
    GuideDialog(mw).show()
