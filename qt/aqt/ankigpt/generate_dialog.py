# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tools > AnkiGPT > Create Concept Deck from Documents..."""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Sequence
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
from aqt.ankigpt.study_sources import CourseBrief, discover_sources, total_size
from aqt.ankigpt.url_source import DownloadedSource, download_url_source
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


class StudySourceList(QListWidget):
    """Document list that accepts files and folders from the desktop."""

    def __init__(self, on_drop: Callable[[list[str]], None]):
        super().__init__()
        self._on_drop = on_drop
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

    def dragEnterEvent(self, event: QDragEnterEvent | None) -> None:
        if event and event.mimeData().hasUrls():
            event.acceptProposedAction()
        elif event:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent | None) -> None:
        if event and event.mimeData().hasUrls():
            event.acceptProposedAction()
        elif event:
            event.ignore()

    def dropEvent(self, event: QDropEvent | None) -> None:
        if not event or not event.mimeData().hasUrls():
            return
        paths = [
            url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()
        ]
        if paths:
            self._on_drop(paths)
            event.acceptProposedAction()


class CreateConceptDeckDialog(QDialog):
    def __init__(self, mw: AnkiQt, parent: QWidget | None = None):
        super().__init__(parent or mw)
        self.mw = mw
        self.files: list[str] = []
        self._remote_sources: dict[str, DownloadedSource] = {}
        self.candidates: list[ConceptCandidate] = []
        self._cancel_requested = False
        self.setWindowTitle(tr.ankigpt_create_deck_title())
        disable_help_button(self)
        self._build_ui()
        self._apply_style()
        restoreGeom(self, "ankigptCreateDeck")
        self.show()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_input_page())
        self.stack.addWidget(self._build_preview_page())
        self.stack.addWidget(self._build_progress_page())
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(500)
        qconnect(self._elapsed_timer.timeout, self._tick_elapsed)
        self._started_at = 0.0
        layout = QVBoxLayout()
        layout.addWidget(self.stack)
        self.setLayout(layout)
        self.resize(940, 760)
        self.setMinimumSize(640, 520)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QDialog { background: #f5f7fb; }
            QWidget#ankigptCanvas { background: #f5f7fb; }
            QLabel#ankigptTitle { font-size: 24px; font-weight: 700; }
            QLabel#ankigptSubtitle { color: #667085; font-size: 13px; }
            QLabel#ankigptStep {
                color: #3157d5; background: #e8edff; border-radius: 9px;
                padding: 4px 9px; font-weight: 700;
            }
            QGroupBox {
                background: palette(base); font-weight: 600;
                border: 1px solid #dfe3eb; border-radius: 12px;
                margin-top: 18px; padding: 20px 12px 12px;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 14px; padding: 1px 6px;
                color: palette(text);
            }
            QListWidget, QLineEdit, QPlainTextEdit, QComboBox, QSpinBox {
                border: 1px solid #cfd5df; border-radius: 7px; padding: 7px;
                background: palette(base);
            }
            QListWidget:focus, QLineEdit:focus, QPlainTextEdit:focus,
            QComboBox:focus, QSpinBox:focus { border: 1px solid #4f6bed; }
            QPushButton {
                min-height: 30px; padding: 3px 14px; border-radius: 7px;
            }
            QPushButton#ankigptPrimary {
                color: white; background: #3157d5; border: 1px solid #3157d5;
                font-weight: 600;
            }
            QPushButton#ankigptPrimary:hover { background: #2448bd; }
            QTableWidget {
                background: palette(base); border: 1px solid #dfe3eb;
                border-radius: 10px; gridline-color: #e8eaf0;
            }
            """
        )

    def _add_page_heading(
        self, layout: QVBoxLayout, step: str, title: str, subtitle: str
    ) -> None:
        step_label = QLabel(step)
        step_label.setObjectName("ankigptStep")
        title_label = QLabel(title)
        title_label.setObjectName("ankigptTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("ankigptSubtitle")
        subtitle_label.setWordWrap(True)
        layout.addWidget(step_label)
        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)

    def _build_input_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("ankigptCanvas")
        outer = QVBoxLayout(page)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("ankigptCanvas")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(10, 8, 10, 12)
        self._add_page_heading(
            content_layout,
            tr.ankigpt_step_materials(),
            tr.ankigpt_create_course(),
            tr.ankigpt_create_course_subtitle(),
        )

        files_group = QGroupBox(tr.ankigpt_study_materials())
        files_layout = QVBoxLayout(files_group)
        intro = QLabel(tr.ankigpt_study_materials_intro())
        intro.setWordWrap(True)
        files_layout.addWidget(intro)
        self.file_list = StudySourceList(self._add_source_paths)
        self.file_list.setToolTip(tr.ankigpt_drop_sources())
        self.file_list.setMinimumHeight(140)
        files_layout.addWidget(self.file_list, 1)
        btns = QHBoxLayout()
        add_btn = QPushButton(tr.ankigpt_add_files())
        qconnect(add_btn.clicked, self.on_add_files)
        folder_btn = QPushButton(tr.ankigpt_add_folder())
        qconnect(folder_btn.clicked, self.on_add_folder)
        url_btn = QPushButton(tr.ankigpt_add_url())
        url_btn.setToolTip(tr.ankigpt_add_url_tooltip())
        qconnect(url_btn.clicked, self.on_add_url)
        remove_btn = QPushButton(tr.ankigpt_remove_file())
        qconnect(remove_btn.clicked, self.on_remove_file)
        clear_btn = QPushButton(tr.ankigpt_clear_files())
        qconnect(clear_btn.clicked, self.on_clear_files)
        btns.addWidget(add_btn)
        btns.addWidget(folder_btn)
        btns.addWidget(url_btn)
        btns.addWidget(remove_btn)
        btns.addWidget(clear_btn)
        source_row = QVBoxLayout()
        source_row.addLayout(btns)
        self.source_summary = QLabel(tr.ankigpt_no_study_materials())
        self.source_summary.setWordWrap(True)
        source_row.addWidget(self.source_summary)
        files_layout.addLayout(source_row)
        content_layout.addWidget(files_group)

        course_group = QGroupBox(tr.ankigpt_course_details())
        form = QFormLayout(course_group)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(10)
        self.deck_name = QComboBox()
        self.deck_name.setEditable(True)
        for deck in self.mw.col.decks.all_names_and_ids(
            skip_empty_default=True, include_filtered=False
        ):
            self.deck_name.addItem(deck.name)
        self.deck_name.setCurrentText("")
        form.addRow(tr.ankigpt_deck_name(), self.deck_name)

        self.subject = QLineEdit()
        self.subject.setPlaceholderText(tr.ankigpt_subject_placeholder())
        form.addRow(tr.ankigpt_subject(), self.subject)

        self.level = QComboBox()
        for label in (
            tr.ankigpt_level_introductory(),
            tr.ankigpt_level_intermediate(),
            tr.ankigpt_level_advanced(),
        ):
            self.level.addItem(label)
        form.addRow(tr.ankigpt_learning_level(), self.level)

        self.focus = QLineEdit()
        self.focus.setPlaceholderText(tr.ankigpt_focus_placeholder())
        form.addRow(tr.ankigpt_focus_topics(), self.focus)

        self.exclusions = QLineEdit()
        self.exclusions.setPlaceholderText(tr.ankigpt_exclusions_placeholder())
        form.addRow(tr.ankigpt_exclusions(), self.exclusions)

        self.question_style = QComboBox()
        for label in (
            tr.ankigpt_style_balanced(),
            tr.ankigpt_style_core_knowledge(),
            tr.ankigpt_style_applied(),
            tr.ankigpt_style_exam(),
        ):
            self.question_style.addItem(label)
        form.addRow(tr.ankigpt_question_style(), self.question_style)

        self.instructions = QPlainTextEdit()
        self.instructions.setPlaceholderText(
            tr.ankigpt_additional_guidance_placeholder()
        )
        self.instructions.setMaximumHeight(70)
        form.addRow(tr.ankigpt_additional_guidance(), self.instructions)

        self.target = QSpinBox()
        self.target.setRange(1, 200)
        self.target.setValue(20)
        form.addRow(tr.ankigpt_target_count(), self.target)

        self.mode = QComboBox()
        for mode in DECK_MODES:
            self.mode.addItem(mode_label(mode), mode)
        form.addRow(tr.ankigpt_grading_mode(), self.mode)
        content_layout.addWidget(course_group)
        content_layout.addStretch()
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        buttons = QDialogButtonBox()
        self.extract_btn = QPushButton(tr.ankigpt_extract())
        self.extract_btn.setObjectName("ankigptPrimary")
        self.extract_btn.setDefault(True)
        buttons.addButton(self.extract_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        qconnect(self.extract_btn.clicked, self.on_extract)
        qconnect(buttons.rejected, self.reject)
        outer.addWidget(buttons)
        return page

    def _build_preview_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("ankigptCanvas")
        outer = QVBoxLayout(page)
        self._add_page_heading(
            outer,
            tr.ankigpt_step_concepts(),
            tr.ankigpt_review_concepts(),
            tr.ankigpt_review_concepts_subtitle(),
        )
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
        self.create_btn.setObjectName("ankigptPrimary")
        self.create_btn.setDefault(True)
        buttons.addButton(self.create_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        qconnect(back_btn.clicked, lambda: self.stack.setCurrentIndex(0))
        qconnect(self.create_btn.clicked, self.on_create)
        qconnect(buttons.rejected, self.reject)
        qconnect(self.table.itemChanged, self._update_create_button)
        outer.addWidget(buttons)
        return page

    def _build_progress_page(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        self.progress_title = QLabel(tr.ankigpt_progress_title())
        font = self.progress_title.font()
        font.setPointSize(font.pointSize() + 3)
        font.setBold(True)
        self.progress_title.setFont(font)
        outer.addWidget(self.progress_title)

        self.progress_stage = QLabel("")
        outer.addWidget(self.progress_stage)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        outer.addWidget(self.progress_bar)

        stats = QHBoxLayout()
        self.progress_candidates = QLabel("")
        self.progress_elapsed = QLabel("")
        stats.addWidget(self.progress_candidates)
        stats.addStretch()
        stats.addWidget(self.progress_elapsed)
        outer.addLayout(stats)

        self.progress_log = QPlainTextEdit()
        self.progress_log.setReadOnly(True)
        self.progress_log.setMaximumBlockCount(500)
        outer.addWidget(self.progress_log, 1)

        buttons = QDialogButtonBox()
        self.progress_back_btn = QPushButton(tr.ankigpt_back())
        buttons.addButton(self.progress_back_btn, QDialogButtonBox.ButtonRole.ResetRole)
        self.progress_cancel_btn = QPushButton(tr.ankigpt_cancel())
        buttons.addButton(
            self.progress_cancel_btn, QDialogButtonBox.ButtonRole.RejectRole
        )
        qconnect(self.progress_back_btn.clicked, lambda: self.stack.setCurrentIndex(0))
        qconnect(self.progress_cancel_btn.clicked, self._cancel_extraction)
        outer.addWidget(buttons)
        return page

    # ---------------------------------------------------------- progress

    _STAGE_ORDER = ("plan", "extract", "gap", "merge", "done")

    def _stage_title(self, stage: str) -> str:
        return {
            "read": tr.ankigpt_progress_reading(),
            "plan": tr.ankigpt_progress_planning(),
            "extract": tr.ankigpt_progress_extracting(),
            "gap": tr.ankigpt_progress_gap(),
            "merge": tr.ankigpt_progress_merging(),
            "done": tr.ankigpt_progress_done(),
        }.get(stage, stage)

    def _start_progress(self) -> None:
        self.progress_log.clear()
        self.progress_bar.setRange(0, 0)
        self.progress_stage.setText(self._stage_title("read"))
        self.progress_candidates.setText("")
        self.progress_elapsed.setText("")
        self.progress_back_btn.setEnabled(False)
        self.progress_cancel_btn.setEnabled(True)
        self._started_at = time.monotonic()
        self._elapsed_timer.start()
        self.stack.setCurrentIndex(2)

    def _tick_elapsed(self) -> None:
        seconds = int(time.monotonic() - self._started_at)
        self.progress_elapsed.setText(tr.ankigpt_progress_elapsed(seconds=str(seconds)))

    def _log(self, message: str) -> None:
        seconds = time.monotonic() - self._started_at
        self.progress_log.appendPlainText(f"[{seconds:6.1f}s] {message}")

    def _on_progress(self, event: extract.ProgressEvent) -> None:
        if self.stack.currentIndex() != 2:
            return
        self.progress_stage.setText(self._stage_title(event.stage))
        if event.total > 0:
            self.progress_bar.setRange(0, event.total)
            self.progress_bar.setValue(event.current)
        else:
            self.progress_bar.setRange(0, 0)
        if event.candidates:
            self.progress_candidates.setText(
                tr.ankigpt_progress_candidates(count=event.candidates)
            )
        if event.message:
            self._log(event.message)

    def _finish_progress(self, status: str) -> None:
        self._elapsed_timer.stop()
        self._tick_elapsed()
        self.progress_stage.setText(status)
        self.progress_cancel_btn.setEnabled(False)
        self.progress_back_btn.setEnabled(True)
        self._log(status)

    def _cancel_extraction(self) -> None:
        self._cancel_requested = True
        self.progress_cancel_btn.setEnabled(False)
        self._log(tr.ankigpt_progress_cancelled())

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
        self._add_source_paths(paths)

    def on_add_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, tr.ankigpt_add_folder(), "", QFileDialog.Option.ShowDirsOnly
        )
        if path:
            self._add_source_paths([path])

    def on_add_url(self) -> None:
        url, accepted = QInputDialog.getText(
            self, tr.ankigpt_add_url(), tr.ankigpt_source_url()
        )
        if not accepted or not url.strip():
            return
        self.setEnabled(False)

        def done(source: DownloadedSource) -> None:
            self.setEnabled(True)
            self._remote_sources[source.path] = source
            self._add_source_paths([source.path])
            item = self.file_list.item(self.file_list.count() - 1)
            if item:
                item.setText(source.name)
                item.setToolTip(source.url)

        def failed(exc: Exception) -> None:
            self.setEnabled(True)
            showWarning(tr.ankigpt_url_failed(error=str(exc)), self)

        QueryOp(
            parent=self,
            op=lambda _col: download_url_source(url),
            success=done,
        ).failure(failed).without_collection().run_in_background()

    def _add_source_paths(self, paths: Sequence[str]) -> None:
        discovered = discover_sources(paths)
        existing = {os.path.normcase(os.path.normpath(path)) for path in self.files}
        added = 0
        for path in discovered.files:
            key = os.path.normcase(os.path.normpath(path))
            if key not in existing:
                existing.add(key)
                self.files.append(path)
                item = QListWidgetItem(os.path.basename(path))
                item.setToolTip(path)
                item.setData(Qt.ItemDataRole.UserRole, path)
                self.file_list.addItem(item)
                added += 1
        skipped = len(discovered.unsupported)
        if skipped or discovered.missing:
            tooltip(
                tr.ankigpt_sources_skipped(
                    unsupported=skipped, missing=len(discovered.missing)
                ),
                parent=self,
            )
        if added:
            self._suggest_target()
        self._update_source_summary()

    def on_remove_file(self) -> None:
        rows = sorted(
            {self.file_list.row(item) for item in self.file_list.selectedItems()},
            reverse=True,
        )
        for row in rows:
            self.file_list.takeItem(row)
            self._remove_remote_file(self.files.pop(row))
        self._suggest_target()
        self._update_source_summary()

    def on_clear_files(self) -> None:
        for path in self.files:
            self._remove_remote_file(path)
        self.files.clear()
        self.file_list.clear()
        self._update_source_summary()

    def _remove_remote_file(self, path: str) -> None:
        if self._remote_sources.pop(path, None):
            try:
                os.unlink(path)
            except OSError:
                pass

    def _update_source_summary(self) -> None:
        if not self.files:
            self.source_summary.setText(tr.ankigpt_no_study_materials())
            return
        size = total_size(self.files)
        self.source_summary.setText(
            tr.ankigpt_study_material_summary(
                count=len(self.files), size=f"{size / (1024 * 1024):.1f} MB"
            )
        )

    def _course_instructions(self) -> str:
        return CourseBrief(
            subject=self.subject.text().strip(),
            level=self.level.currentText(),
            focus=self.focus.text().strip(),
            exclusions=self.exclusions.text().strip(),
            question_style=self.question_style.currentText(),
            notes=self.instructions.toPlainText().strip(),
        ).instructions()

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
        instructions = self._course_instructions()
        target = self.target.value()
        self._cancel_requested = False
        self._sampled: list[extract.Document] = []
        self._docs: list[extract.Document] = []
        mw = self.mw
        self._start_progress()
        self._log(tr.ankigpt_reading_files())

        def progress(event: extract.ProgressEvent) -> None:
            mw.taskman.run_on_main(lambda: self._on_progress(event))

        def log(message: str) -> None:
            mw.taskman.run_on_main(lambda: self._log(message))

        def op(_col: Collection) -> list[ConceptCandidate]:
            docs = []
            for path in files:
                if self._cancel_requested:
                    raise extract.Cancelled()
                doc = extract.extract_text(path)
                if remote := self._remote_sources.get(path):
                    doc.path = remote.url
                    doc.name = remote.name
                docs.append(doc)
                log(f"{doc.name}: {doc.total_chars:,} characters")
            result = extract.extract_concepts(
                docs,
                instructions,
                target,
                client,
                progress=progress,
                should_cancel=lambda: self._cancel_requested,
                max_chars_per_file=config.max_chars_per_file,
            )
            self._sampled = [d for d in docs if d.report and d.report.partial]
            self._docs = docs
            return result

        self.extract_btn.setEnabled(False)
        QueryOp(parent=self, op=op, success=self._on_extracted).failure(
            self._on_extract_failed
        ).without_collection().run_in_background()

    def _on_extract_failed(self, exc: Exception) -> None:
        self.extract_btn.setEnabled(True)
        if isinstance(exc, extract.Cancelled):
            self._finish_progress(tr.ankigpt_progress_cancelled())
            self.stack.setCurrentIndex(0)
            return
        self._finish_progress(f"{tr.ankigpt_progress_failed()}: {exc}")
        showWarning(tr.ankigpt_extraction_failed(error=str(exc)), self)

    def _on_extracted(self, candidates: list[ConceptCandidate]) -> None:
        self.extract_btn.setEnabled(True)
        self._finish_progress(tr.ankigpt_progress_done())
        if not candidates:
            showWarning(tr.ankigpt_no_concepts_found(), self)
            self.stack.setCurrentIndex(0)
            return
        self.candidates = candidates
        self._fill_table(candidates)
        self.stack.setCurrentIndex(1)
        if self._sampled:
            limit = llm_config(self.mw.pm).max_chars_per_file
            lines = "\n".join(
                tr.ankigpt_sampled_file(
                    name=d.name,
                    total=d.total_chars,
                    percent=str(int(100 * d.report.coverage)),
                    read=str(d.report.sections_read),
                    sections=str(d.report.sections_total),
                )
                for d in self._sampled
                if d.report
            )
            tooltip(
                tr.ankigpt_sampled_files(limit=f"{limit:,}", files=lines),
                period=12000,
                parent=self,
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
        instructions = self._course_instructions()
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

        docs = list(self._docs)

        def on_done(_changes: OpChanges) -> None:
            self._store_documents(deck_name, docs)
            tooltip(
                tr.ankigpt_created_notes(count=len(selected), deck=deck_name),
                parent=mw,
            )
            self.close()

        CollectionOp(parent=self, op=op).success(on_done).run_in_background()

    def _store_documents(self, deck_name: str, docs: list[extract.Document]) -> None:
        """Keep the source text so questions can cite and open it later."""
        from aqt.ankigpt import get_store
        from aqt.ankigpt.retrieve import StoredSection

        deck_id = self.mw.col.decks.id_for_name(deck_name)
        if deck_id is None:
            return
        try:
            store = get_store()
            for doc in docs:
                # finer than the reading planner's grouping: citations should
                # name the actual section a passage comes from
                sections = [
                    StoredSection(s.index, s.title, s.start, s.end)
                    for s in extract.split_sections(
                        doc.text, min_chars=300, max_sections=2000
                    )
                ]
                store.add_document(
                    int(deck_id), doc.name, doc.path, doc.text, sections, doc.pages
                )
        except Exception:
            # sources are a convenience; never block deck creation on them
            pass

    def reject(self) -> None:
        for path in list(self._remote_sources):
            self._remove_remote_file(path)
        saveGeom(self, "ankigptCreateDeck")
        super().reject()

    def closeEvent(self, evt: QCloseEvent | None) -> None:
        for path in list(self._remote_sources):
            self._remove_remote_file(path)
        saveGeom(self, "ankigptCreateDeck")
        super().closeEvent(evt)


def open_deck_settings(mw: AnkiQt, deck_id: DeckId | None = None) -> None:
    from aqt.ankigpt.settings import DeckSettingsDialog

    if deck_id is None:
        deck_id = DeckId(mw.col.decks.current()["id"])
    DeckSettingsDialog(mw, deck_id).exec()


__all__ = ["CreateConceptDeckDialog", "open_deck_settings", "DeckSettings"]
