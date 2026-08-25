# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Source viewer: the stored text of a document with referenced passages
highlighted, and a button to open the original file."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from anki.decks import DeckId
from aqt.ankigpt.retrieve import StoredDocument, render_document_html
from aqt.qt import *
from aqt.utils import disable_help_button, restoreGeom, saveGeom, tooltip, tr

if TYPE_CHECKING:
    from aqt.main import AnkiQt


class SourceViewerDialog(QDialog):
    def __init__(
        self,
        mw: AnkiQt,
        documents: list[StoredDocument],
        current: int | None = None,
        highlights: list[tuple[int, int]] | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent or mw)
        self.mw = mw
        self.documents = documents
        self.highlights = highlights or []
        self.setWindowTitle(tr.ankigpt_sources_title())
        disable_help_button(self)

        top = QHBoxLayout()
        self.picker = QComboBox()
        for doc in documents:
            self.picker.addItem(doc.name, doc.id)
        top.addWidget(QLabel(tr.ankigpt_documents()))
        top.addWidget(self.picker, 1)
        self.open_btn = QPushButton(tr.ankigpt_open_original())
        qconnect(self.open_btn.clicked, self.open_original)
        top.addWidget(self.open_btn)
        self.next_btn = QPushButton(tr.ankigpt_next_highlight())
        qconnect(self.next_btn.clicked, self.next_highlight)
        top.addWidget(self.next_btn)

        self.info = QLabel("")
        self.info.setWordWrap(True)
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(False)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        qconnect(buttons.rejected, self.reject)

        layout = QVBoxLayout()
        layout.addLayout(top)
        layout.addWidget(self.info)
        layout.addWidget(self.browser, 1)
        layout.addWidget(buttons)
        self.setLayout(layout)
        self.resize(820, 700)
        restoreGeom(self, "ankigptSources")

        qconnect(self.picker.currentIndexChanged, self._show_current)
        self._highlight_pos = -1
        if current is not None:
            index = self.picker.findData(current)
            if index >= 0:
                self.picker.setCurrentIndex(index)
        self._show_current()

    def _current_doc(self) -> StoredDocument | None:
        doc_id = self.picker.currentData()
        for doc in self.documents:
            if doc.id == doc_id:
                return doc
        return None

    def _show_current(self) -> None:
        doc = self._current_doc()
        if doc is None:
            self.browser.setHtml("")
            return
        highlights = [(s, e) for s, e in self.highlights if e > s]
        self.browser.setHtml(render_document_html(doc, highlights))
        pages = f", {len(doc.pages)} pages" if doc.pages else ""
        self.info.setText(
            tr.ankigpt_source_info(
                chars=f"{len(doc.text):,}", sections=str(len(doc.sections)), pages=pages
            )
        )
        self.open_btn.setEnabled(bool(doc.path) and os.path.exists(doc.path))
        self.next_btn.setVisible(bool(highlights))
        self._highlight_pos = -1
        if highlights:
            self.next_highlight()

    def next_highlight(self) -> None:
        count = len([h for h in self.highlights if h[1] > h[0]])
        if not count:
            return
        self._highlight_pos = (self._highlight_pos + 1) % count
        self.browser.scrollToAnchor(f"hl{self._highlight_pos}")

    def open_original(self) -> None:
        doc = self._current_doc()
        if doc is None or not doc.path or not os.path.exists(doc.path):
            tooltip(tr.ankigpt_original_missing(), parent=self)
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(doc.path))

    def reject(self) -> None:
        saveGeom(self, "ankigptSources")
        super().reject()


def show_sources(
    mw: AnkiQt,
    deck_id: DeckId,
    doc_id: int | None = None,
    highlights: list[tuple[int, int]] | None = None,
) -> None:
    from aqt.ankigpt import get_store
    from aqt.utils import showInfo

    docs = get_store().documents_for_deck(deck_id)
    if doc_id is not None and all(d.id != doc_id for d in docs):
        if doc := get_store().get_document(doc_id):
            docs.append(doc)
    if not docs:
        showInfo(tr.ankigpt_no_sources(), parent=mw)
        return
    SourceViewerDialog(mw, docs, doc_id, highlights).show()
