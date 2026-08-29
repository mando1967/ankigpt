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
        self.setObjectName("ankigptSourceWindow")

        heading = QLabel(tr.ankigpt_sources_title())
        heading.setObjectName("ankigptSourceTitle")
        subtitle = QLabel(tr.ankigpt_source_viewer_subtitle())
        subtitle.setObjectName("ankigptSourceSubtitle")
        subtitle.setWordWrap(True)

        sidebar = QFrame()
        sidebar.setObjectName("ankigptSourceSidebar")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_label = QLabel(tr.ankigpt_source_documents())
        sidebar_label.setObjectName("ankigptSourceSection")
        sidebar_layout.addWidget(sidebar_label)
        self.picker = QComboBox()
        for doc in documents:
            self.picker.addItem(doc.name, doc.id)
        sidebar_layout.addWidget(self.picker)
        self.info = QLabel("")
        self.info.setObjectName("ankigptSourceInfo")
        self.info.setWordWrap(True)
        sidebar_layout.addWidget(self.info)
        self.open_btn = QPushButton(tr.ankigpt_open_original())
        qconnect(self.open_btn.clicked, self.open_original)
        sidebar_layout.addWidget(self.open_btn)
        self.next_btn = QPushButton(tr.ankigpt_next_highlight())
        self.next_btn.setObjectName("ankigptSourcePrimary")
        qconnect(self.next_btn.clicked, self.next_highlight)
        sidebar_layout.addWidget(self.next_btn)
        sidebar_layout.addStretch()

        self.browser = QTextBrowser()
        self.browser.setObjectName("ankigptSourceBrowser")
        self.browser.setOpenExternalLinks(False)

        splitter = QSplitter()
        splitter.addWidget(sidebar)
        splitter.addWidget(self.browser)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([245, 755])

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        qconnect(buttons.rejected, self.reject)

        layout = QVBoxLayout()
        layout.setContentsMargins(24, 20, 24, 18)
        layout.addWidget(heading)
        layout.addWidget(subtitle)
        layout.addSpacing(8)
        layout.addWidget(splitter, 1)
        layout.addWidget(buttons)
        self.setLayout(layout)
        self.resize(1040, 760)
        self.setMinimumSize(720, 520)
        self._apply_style()
        restoreGeom(self, "ankigptSources")

        qconnect(self.picker.currentIndexChanged, self._show_current)
        self._highlight_pos = -1
        if current is not None:
            index = self.picker.findData(current)
            if index >= 0:
                self.picker.setCurrentIndex(index)
        self._show_current()

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QDialog#ankigptSourceWindow { background: #f4f7fb; }
            QLabel#ankigptSourceTitle { color: #10204d; font-size: 24px; font-weight: 700; }
            QLabel#ankigptSourceSubtitle { color: #667085; font-size: 13px; }
            QFrame#ankigptSourceSidebar {
                background: #f8faff; border: 1px solid #dfe6ef;
                border-radius: 11px;
            }
            QLabel#ankigptSourceSection { color: #3157d5; font-size: 11px; font-weight: 700; }
            QLabel#ankigptSourceInfo { color: #667085; padding: 8px 2px; }
            QComboBox {
                min-height: 32px; padding: 4px 8px; background: white;
                border: 1px solid #cfd8e6; border-radius: 7px;
            }
            QTextBrowser#ankigptSourceBrowser {
                padding: 18px; background: white; border: 1px solid #dfe6ef;
                border-radius: 11px; selection-background-color: #ffe28a;
            }
            QPushButton { min-height: 29px; padding: 4px 12px; border-radius: 7px; }
            QPushButton#ankigptSourcePrimary {
                color: white; background: #3157d5; border: 1px solid #3157d5;
                font-weight: 600;
            }
            QSplitter::handle { width: 10px; background: transparent; }
            """
        )

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
