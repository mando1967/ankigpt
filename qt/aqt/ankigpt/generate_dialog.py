# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tools > AnkiGPT > Create Concept Deck from Documents..."""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import TYPE_CHECKING

from anki.collection import Collection, OpChanges
from anki.decks import DeckId
from aqt.ankigpt import extract
from aqt.ankigpt.concepts import create_concept_notes, deck_id_for_name
from aqt.ankigpt.llm import make_client
from aqt.ankigpt.prompts import ConceptCandidate
from aqt.ankigpt.settings import (
    DECK_MODES,
    DeckSettings,
    deck_settings,
    llm_config,
    mode_label,
    save_deck_settings,
)
from aqt.operations import CollectionOp, QueryOp
from aqt.qt import *
from aqt.utils import (
    disable_help_button,
    getFile,
    restoreGeom,
    saveGeom,
    showWarning,
    tooltip,
    tr,
)

if TYPE_CHECKING:
    from aqt.main import AnkiQt


class CreateConceptDeckDialog(QDialog):
    def __init__(self, mw: AnkiQt, parent: QWidget | None = None):
        super().__init__(parent or mw)
        self.mw = mw
        self.files: list[str] = []
        self.candidates: list[ConceptCandidate] = []
        self._cancel_requested = False
        self.setWindowTitle(tr.ankigpt_create_deck_title())
        disable_help_button(self)
        self._build_ui()
        restoreGeom(self, "ankigptCreateDeck")
        self.show()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_input_page())
        self.stack.addWidget(self._build_preview_page())
        layout = QVBoxLayout()
        layout.addWidget(self.stack)
        self.setLayout(layout)
        self.setMinimumSize(640, 520)

    def _build_input_page(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)

        files_group = QGroupBox(tr.ankigpt_documents())
        files_layout = QHBoxLayout(files_group)
        self.file_list = QListWidget()
        files_layout.addWidget(self.file_list, 1)
        btns = QVBoxLayout()
        add_btn = QPushButton(tr.ankigpt_add_files())
        qconnect(add_btn.clicked, self.on_add_files)
        remove_btn = QPushButton(tr.ankigpt_remove_file())
        qconnect(remove_btn.clicked, self.on_remove_file)
        btns.addWidget(add_btn)
        btns.addWidget(remove_btn)
        btns.addStretch()
        files_layout.addLayout(btns)
        outer.addWidget(files_group, 1)

        form = QFormLayout()
        self.deck_name = QComboBox()
        self.deck_name.setEditable(True)
        for deck in self.mw.col.decks.all_names_and_ids(
            skip_empty_default=True, include_filtered=False
        ):
            self.deck_name.addItem(deck.name)
        self.deck_name.setCurrentText("")
        form.addRow(tr.ankigpt_deck_name(), self.deck_name)

        self.instructions = QPlainTextEdit()
        self.instructions.setPlaceholderText(tr.ankigpt_instructions_placeholder())
        self.instructions.setMaximumHeight(90)
        form.addRow(tr.ankigpt_instructions(), self.instructions)

        self.target = QSpinBox()
        self.target.setRange(1, 200)
        self.target.setValue(20)
        form.addRow(tr.ankigpt_target_count(), self.target)

        self.mode = QComboBox()
        for mode in DECK_MODES:
            self.mode.addItem(mode_label(mode), mode)
        form.addRow(tr.ankigpt_grading_mode(), self.mode)
        outer.addLayout(form)

        buttons = QDialogButtonBox()
        self.extract_btn = QPushButton(tr.ankigpt_extract())
        self.extract_btn.setDefault(True)
        buttons.addButton(self.extract_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        qconnect(self.extract_btn.clicked, self.on_extract)
        qconnect(buttons.rejected, self.reject)
        outer.addWidget(buttons)
        return page

    def _build_preview_page(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            [
                tr.ankigpt_column_title(),
                tr.ankigpt_column_summary(),
                tr.ankigpt_column_key_points(),
            ]
        )
        header = self.table.horizontalHeader()
        assert header is not None
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setWordWrap(True)
        outer.addWidget(self.table, 1)

        buttons = QDialogButtonBox()
        back_btn = QPushButton(tr.ankigpt_back())
        buttons.addButton(back_btn, QDialogButtonBox.ButtonRole.ResetRole)
        self.create_btn = QPushButton(tr.ankigpt_create_notes(count=0))
        self.create_btn.setDefault(True)
        buttons.addButton(self.create_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        qconnect(back_btn.clicked, lambda: self.stack.setCurrentIndex(0))
        qconnect(self.create_btn.clicked, self.on_create)
        qconnect(buttons.rejected, self.reject)
        qconnect(self.table.itemChanged, self._update_create_button)
        outer.addWidget(buttons)
        return page

    # ------------------------------------------------------------ actions

    def on_add_files(self) -> None:
        paths = getFile(
            self,
            tr.ankigpt_add_files(),
            None,
            filter=tr.ankigpt_file_filter(),
            key="ankigpt",
            multi=True,
        )
        if not paths:
            return
        assert not isinstance(paths, str)
        for path in paths:
            if not extract.is_supported(path):
                showWarning(
                    tr.ankigpt_unsupported_file(name=os.path.basename(path)), self
                )
                continue
            if path not in self.files:
                self.files.append(path)
                self.file_list.addItem(path)
        self._suggest_target()

    def on_remove_file(self) -> None:
        row = self.file_list.currentRow()
        if row < 0:
            return
        self.file_list.takeItem(row)
        del self.files[row]
        self._suggest_target()

    def _suggest_target(self) -> None:
        total = 0.0
        limit = llm_config(self.mw.pm).max_chars_per_file
        for path in self.files:
            try:
                if path.lower().endswith(".pdf"):
                    # rough estimate without parsing: ~2.5k chars per 4KB
                    total += min(os.path.getsize(path) * 0.6, limit)
                else:
                    total += min(os.path.getsize(path), limit)
            except OSError:
                pass
        if total:
            self.target.setValue(extract.suggest_target_count(int(total)))

    def on_extract(self) -> None:
        if not self.files:
            showWarning(tr.ankigpt_no_files(), self)
            return
        if not self.deck_name.currentText().strip():
            showWarning(tr.ankigpt_no_deck_name(), self)
            return
        config = llm_config(self.mw.pm)
        if not config.configured:
            showWarning(tr.ankigpt_no_api_key(), self)
            return
        client = make_client(config)
        files = list(self.files)
        instructions = self.instructions.toPlainText().strip()
        target = self.target.value()
        self._cancel_requested = False
        self._truncated: list[tuple[str, int]] = []
        mw = self.mw

        def progress(stage: str, i: int, n: int) -> None:
            def update() -> None:
                if mw.progress.want_cancel():
                    self._cancel_requested = True
                if stage == "extract":
                    label = tr.ankigpt_extracting_chunk(current=str(i), total=n)
                else:
                    label = tr.ankigpt_merging()
                mw.progress.update(label=label, value=i, max=n)

            mw.taskman.run_on_main(update)

        def op(_col: Collection) -> list[ConceptCandidate]:
            mw.taskman.run_on_main(
                lambda: mw.progress.update(label=tr.ankigpt_reading_files())
            )
            docs = [
                extract.extract_text(path, max_chars=config.max_chars_per_file)
                for path in files
            ]
            self._truncated = [(d.name, d.total_chars) for d in docs if d.truncated]
            return extract.extract_concepts(
                docs,
                instructions,
                target,
                client,
                progress=progress,
                should_cancel=lambda: self._cancel_requested,
            )

        self.extract_btn.setEnabled(False)
        QueryOp(parent=self, op=op, success=self._on_extracted).failure(
            self._on_extract_failed
        ).with_progress(
            tr.ankigpt_extracting()
        ).without_collection().run_in_background()

    def _on_extract_failed(self, exc: Exception) -> None:
        self.extract_btn.setEnabled(True)
        if isinstance(exc, extract.Cancelled):
            return
        showWarning(tr.ankigpt_extraction_failed(error=str(exc)), self)

    def _on_extracted(self, candidates: list[ConceptCandidate]) -> None:
        self.extract_btn.setEnabled(True)
        if not candidates:
            showWarning(tr.ankigpt_no_concepts_found(), self)
            return
        self.candidates = candidates
        self._fill_table(candidates)
        self.stack.setCurrentIndex(1)
        if self._truncated:
            limit = llm_config(self.mw.pm).max_chars_per_file
            names = "\n".join(
                f"{name} ({total:,} chars)" for name, total in self._truncated
            )
            showWarning(
                tr.ankigpt_truncated_files(limit=f"{limit:,}", files=names), self
            )

    def _fill_table(self, candidates: Sequence[ConceptCandidate]) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(len(candidates))
        for row, c in enumerate(candidates):
            title = QTableWidgetItem(c.title)
            title.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsEditable
            )
            title.setCheckState(Qt.CheckState.Checked)
            self.table.setItem(row, 0, title)
            self.table.setItem(row, 1, QTableWidgetItem(c.summary))
            self.table.setItem(row, 2, QTableWidgetItem("\n".join(c.key_points)))
        self.table.resizeRowsToContents()
        self.table.blockSignals(False)
        self._update_create_button()

    def _selected(self) -> list[ConceptCandidate]:
        out = []
        for row, original in enumerate(self.candidates):
            title_item = self.table.item(row, 0)
            if title_item is None or title_item.checkState() != Qt.CheckState.Checked:
                continue
            summary_item = self.table.item(row, 1)
            points_item = self.table.item(row, 2)
            points = [
                line.strip()
                for line in (points_item.text() if points_item else "").splitlines()
                if line.strip()
            ]
            out.append(
                ConceptCandidate(
                    title=title_item.text().strip(),
                    summary=(summary_item.text() if summary_item else "").strip(),
                    key_points=points,
                    sources=list(original.sources),
                )
            )
        return out

    def _update_create_button(self, *_args: object) -> None:
        self.create_btn.setText(tr.ankigpt_create_notes(count=len(self._selected())))

    def on_create(self) -> None:
        selected = self._selected()
        if not selected:
            showWarning(tr.ankigpt_nothing_selected(), self)
            return
        deck_name = self.deck_name.currentText().strip()
        instructions = self.instructions.toPlainText().strip()
        mode = str(self.mode.currentData())
        mw = self.mw

        def op(col: Collection) -> OpChanges:
            deck_id = deck_id_for_name(col, deck_name)
            changes = create_concept_notes(col, deck_id, selected, context=instructions)
            settings = deck_settings(col, deck_id)
            settings.mode = mode
            if instructions:
                settings.context = instructions
            save_deck_settings(col, deck_id, settings)
            return changes

        def on_done(_changes: OpChanges) -> None:
            tooltip(
                tr.ankigpt_created_notes(count=len(selected), deck=deck_name),
                parent=mw,
            )
            self.close()

        CollectionOp(parent=self, op=op).success(on_done).run_in_background()

    def reject(self) -> None:
        saveGeom(self, "ankigptCreateDeck")
        super().reject()

    def closeEvent(self, evt: QCloseEvent | None) -> None:
        saveGeom(self, "ankigptCreateDeck")
        super().closeEvent(evt)


def open_deck_settings(mw: AnkiQt, deck_id: DeckId | None = None) -> None:
    from aqt.ankigpt.settings import DeckSettingsDialog

    if deck_id is None:
        deck_id = DeckId(mw.col.decks.current()["id"])
    DeckSettingsDialog(mw, deck_id).exec()


__all__ = ["CreateConceptDeckDialog", "open_deck_settings", "DeckSettings"]
