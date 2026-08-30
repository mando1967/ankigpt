# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tools > AnkiGPT > Create Concept Deck from Documents..."""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from anki.collection import Collection, OpChanges
from anki.decks import DeckId
from aqt.ankigpt import extract
from aqt.ankigpt.book_structure import (
    BookUnit,
    classify_book_structure,
    deck_root,
    generation_units,
)
from aqt.ankigpt.concepts import create_concept_notes, deck_id_for_name
from aqt.ankigpt.llm import LLMConfig, make_client
from aqt.ankigpt.prompts import ConceptCandidate
from aqt.ankigpt.settings import (
    DECK_MODES,
    DeckSettings,
    deck_settings,
    llm_config,
    mode_label,
    save_deck_settings,
)
from aqt.ankigpt.study_sources import (
    CourseBrief,
    discover_sources,
    document_deck_names,
    total_size,
)
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


@dataclass
class BookDeckResult:
    deck_name: str
    candidates: list[ConceptCandidate]
    document: extract.Document


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
        self._candidate_decks: list[str] = []
        self._book_doc: extract.Document | None = None
        self._book_chapters: list[BookUnit] = []
        self._book_results: list[BookDeckResult] = []
        self._book_structure_ai = False
        self._separate_documents = False
        self._suggested_subcategory = ""
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
        self.stack.addWidget(self._build_structure_page())
        self.stack.addWidget(self._build_preview_page())
        self.stack.addWidget(self._build_progress_page())
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(500)
        qconnect(self._elapsed_timer.timeout, self._tick_elapsed)
        self._started_at = 0.0
        self._active_unit_status = ""
        self._active_unit_current = 0
        self._active_unit_total = 0
        self._overall_progress_value = 0
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
            QTreeWidget {
                background: palette(base); border: 1px solid #dfe3eb;
                border-radius: 10px;
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

        self.book_source = QCheckBox(tr.ankigpt_book_source())
        self.book_source.setToolTip(tr.ankigpt_book_source_tooltip())
        qconnect(self.book_source.toggled, self._on_book_toggled)
        files_layout.addWidget(self.book_source)
        nonbook_row = QHBoxLayout()
        nonbook_row.addWidget(QLabel(tr.ankigpt_nonbook_organization()))
        self.nonbook_organization = QComboBox()
        self.nonbook_organization.addItem(tr.ankigpt_nonbook_combined(), "combined")
        self.nonbook_organization.addItem(
            tr.ankigpt_nonbook_per_document(), "per_document"
        )
        nonbook_row.addWidget(self.nonbook_organization, 1)
        self.nonbook_options = QWidget()
        self.nonbook_options.setLayout(nonbook_row)
        files_layout.addWidget(self.nonbook_options)
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

        self.subcategory = QLineEdit()
        self.subcategory.setPlaceholderText(tr.ankigpt_subcategory_placeholder())
        form.addRow(tr.ankigpt_subcategory(), self.subcategory)

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

        self.book_options = QWidget()
        book_options_layout = QFormLayout(self.book_options)
        book_options_layout.setContentsMargins(0, 0, 0, 0)
        self.book_count_mode = QComboBox()
        self.book_count_mode.addItem(tr.ankigpt_book_count_automatic(), "auto")
        self.book_count_mode.addItem(tr.ankigpt_book_count_fixed(), "fixed")
        qconnect(self.book_count_mode.currentIndexChanged, self._update_target_enabled)
        book_options_layout.addRow(
            tr.ankigpt_book_concept_count(), self.book_count_mode
        )
        self.book_options.setVisible(False)
        form.addRow(self.book_options)

        self.mode = QComboBox()
        for mode in DECK_MODES:
            self.mode.addItem(mode_label(mode), mode)
        form.addRow(tr.ankigpt_grading_mode(), self.mode)
        content_layout.addWidget(course_group)
        content_layout.addStretch()
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        buttons = QDialogButtonBox()
        self._pin_button_box(buttons)
        self.extract_btn = QPushButton(tr.ankigpt_extract())
        self.extract_btn.setObjectName("ankigptPrimary")
        self.extract_btn.setDefault(True)
        buttons.addButton(self.extract_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        qconnect(self.extract_btn.clicked, self.on_extract)
        qconnect(buttons.rejected, self.reject)
        outer.addWidget(buttons)
        return page

    def _build_structure_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("ankigptCanvas")
        outer = QVBoxLayout(page)
        self._add_page_heading(
            outer,
            tr.ankigpt_step_book_structure(),
            tr.ankigpt_review_book_structure(),
            tr.ankigpt_review_book_structure_subtitle(),
        )
        granularity_row = QHBoxLayout()
        granularity_row.addWidget(QLabel(tr.ankigpt_book_deck_granularity()))
        self.book_split = QComboBox()
        self.book_split.addItem(tr.ankigpt_book_choose_granularity(), None)
        self.book_split.addItem(tr.ankigpt_book_per_chapter(), False)
        self.book_split.addItem(tr.ankigpt_book_per_section(), True)
        self.book_split.setCurrentIndex(0)
        granularity_row.addWidget(self.book_split, 1)
        outer.addLayout(granularity_row)
        self.structure_tree = QTreeWidget()
        self._make_scroll_area_shrinkable(self.structure_tree)
        self.structure_tree.setColumnCount(4)
        self.structure_tree.setHeaderLabels(
            [
                tr.ankigpt_book_structure_title(),
                tr.ankigpt_book_structure_size(),
                tr.ankigpt_book_structure_concepts(),
                tr.ankigpt_book_structure_confidence(),
            ]
        )
        self.structure_tree.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        outer.addWidget(self.structure_tree, 1)
        tools = QHBoxLayout()
        merge_btn = QPushButton(tr.ankigpt_book_merge())
        split_btn = QPushButton(tr.ankigpt_book_split())
        qconnect(merge_btn.clicked, self._merge_book_units)
        qconnect(split_btn.clicked, self._split_book_unit)
        tools.addWidget(merge_btn)
        tools.addWidget(split_btn)
        tools.addStretch()
        outer.addLayout(tools)
        buttons = QDialogButtonBox()
        self._pin_button_box(buttons)
        back_btn = QPushButton(tr.ankigpt_back())
        continue_btn = QPushButton(tr.ankigpt_continue())
        continue_btn.setObjectName("ankigptPrimary")
        buttons.addButton(back_btn, QDialogButtonBox.ButtonRole.ResetRole)
        buttons.addButton(continue_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        qconnect(back_btn.clicked, lambda: self.stack.setCurrentIndex(0))
        qconnect(continue_btn.clicked, self._extract_book_units)
        qconnect(buttons.rejected, self.reject)
        outer.addWidget(buttons)
        return page

    def _back_from_preview(self) -> None:
        self.stack.setCurrentIndex(1 if self.book_source.isChecked() else 0)

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
        self._make_scroll_area_shrinkable(self.table)
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
        self._pin_button_box(buttons)
        back_btn = QPushButton(tr.ankigpt_back())
        buttons.addButton(back_btn, QDialogButtonBox.ButtonRole.ResetRole)
        self.create_btn = QPushButton(tr.ankigpt_create_notes(count=0))
        self.create_btn.setObjectName("ankigptPrimary")
        self.create_btn.setDefault(True)
        buttons.addButton(self.create_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        qconnect(back_btn.clicked, self._back_from_preview)
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
        self._make_scroll_area_shrinkable(self.progress_log)
        outer.addWidget(self.progress_log, 1)

        buttons = QDialogButtonBox()
        self._pin_button_box(buttons)
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

    @staticmethod
    def _make_scroll_area_shrinkable(widget: QAbstractScrollArea) -> None:
        """Let scrolling content yield space to action buttons in short windows."""
        widget.setMinimumSize(0, 0)
        widget.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)

    @staticmethod
    def _pin_button_box(buttons: QDialogButtonBox) -> None:
        buttons.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

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
        self._active_unit_status = ""
        self._active_unit_current = 0
        self._active_unit_total = 0
        self._overall_progress_value = 0
        self._started_at = time.monotonic()
        self._elapsed_timer.start()
        self.stack.setCurrentIndex(3)

    def _tick_elapsed(self) -> None:
        seconds = int(time.monotonic() - self._started_at)
        self.progress_elapsed.setText(tr.ankigpt_progress_elapsed(seconds=str(seconds)))

    def _log(self, message: str) -> None:
        seconds = time.monotonic() - self._started_at
        self.progress_log.appendPlainText(f"[{seconds:6.1f}s] {message}")

    def _on_progress(self, event: extract.ProgressEvent) -> None:
        if self.stack.currentIndex() != 3:
            return
        stage = self._stage_title(event.stage)
        self.progress_stage.setText(
            f"{stage} — {self._active_unit_status}"
            if self._active_unit_status
            else stage
        )
        if self._active_unit_total:
            self._update_book_progress(event)
        elif event.total > 0:
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

    def _update_book_progress(self, event: extract.ProgressEvent) -> None:
        completed = (
            self._active_unit_current
            if event.stage == "done"
            else self._active_unit_current - 1
        )
        value = max(
            self._overall_progress_value,
            round(completed / self._active_unit_total * 1000),
        )
        self._overall_progress_value = value
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(value)

    def _set_active_book_unit(self, path: list[str], current: int, total: int) -> None:
        self._active_unit_status = tr.ankigpt_book_active_unit(
            name=" › ".join(path), current=current, total=total
        )
        self._active_unit_current = current
        self._active_unit_total = total
        baseline = round((current - 1) / total * 1000)
        self._overall_progress_value = max(self._overall_progress_value, baseline)
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(self._overall_progress_value)
        self.progress_stage.setText(
            f"{self._stage_title('extract')} — {self._active_unit_status}"
        )

    def _begin_book_unit(
        self, path: list[str], deck_name: str, current: int, total: int
    ) -> None:
        self._set_active_book_unit(path, current, total)
        self._log(
            tr.ankigpt_book_extracting_unit(
                name=deck_name, current=current, total=total
            )
        )

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
            self._suggest_book_subcategory()
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
        if self.subcategory.text().strip() == self._suggested_subcategory:
            self.subcategory.clear()
        self._suggested_subcategory = ""
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

    def _on_book_toggled(self, checked: bool) -> None:
        self.book_options.setVisible(checked)
        self.nonbook_options.setVisible(not checked)
        self.subcategory.setPlaceholderText(
            tr.ankigpt_book_title_placeholder()
            if checked
            else tr.ankigpt_subcategory_placeholder()
        )
        if checked:
            self._suggest_book_subcategory()
        self._update_target_enabled()

    def _suggest_book_subcategory(self) -> None:
        if (
            not self.book_source.isChecked()
            or len(self.files) != 1
            or (
                self.subcategory.text().strip()
                and self.subcategory.text().strip() != self._suggested_subcategory
            )
        ):
            return
        path = self.files[0]
        display_name = (
            self._remote_sources[path].name
            if path in self._remote_sources
            else os.path.basename(path)
        )
        title = os.path.splitext(display_name)[0].strip()
        if title:
            self.subcategory.setText(title)
            self._suggested_subcategory = title

    def _destination_root(self) -> str:
        return deck_root(self.deck_name.currentText(), self.subcategory.text())

    def _update_target_enabled(self, *_args: object) -> None:
        automatic = (
            self.book_source.isChecked()
            and str(self.book_count_mode.currentData()) == "auto"
        )
        self.target.setEnabled(not automatic)

    def _fill_structure_tree(self) -> None:
        self.structure_tree.clear()

        def add(unit: BookUnit, parent: QTreeWidgetItem | None = None) -> None:
            location = f"{unit.length:,} chars"
            if self._book_doc and self._book_doc.pages:
                first = sum(offset <= unit.start for offset in self._book_doc.pages)
                last = sum(offset < unit.end for offset in self._book_doc.pages)
                location += f" · pp. {max(1, first)}–{max(first, last)}"
            confidence = f"{int(unit.confidence * 100)}%"
            if unit.confidence < 0.65:
                confidence = "⚠ " + confidence
            item = QTreeWidgetItem(
                [unit.title, location, str(unit.suggested_concepts), confidence]
            )
            if self._book_doc:
                excerpt = self._book_doc.text[unit.start : unit.end]
                beginning = " ".join(excerpt[:240].split())
                ending = " ".join(excerpt[-160:].split())
                item.setToolTip(
                    0,
                    tr.ankigpt_book_structure_preview(
                        beginning=beginning, ending=ending
                    ),
                )
            item.setData(0, Qt.ItemDataRole.UserRole, unit)
            item.setFlags(
                item.flags()
                | Qt.ItemFlag.ItemIsEditable
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            item.setCheckState(
                0,
                Qt.CheckState.Checked if unit.included else Qt.CheckState.Unchecked,
            )
            if parent is None:
                self.structure_tree.addTopLevelItem(item)
            else:
                parent.addChild(item)
            for child in unit.children:
                add(child, item)

        for chapter in self._book_chapters:
            add(chapter)
        self.structure_tree.expandAll()
        for column in range(4):
            self.structure_tree.resizeColumnToContents(column)

    def _sync_structure_tree(self) -> None:
        root = self.structure_tree.invisibleRootItem()

        def sync(item: QTreeWidgetItem) -> None:
            unit = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(unit, BookUnit):
                unit.title = item.text(0).strip() or unit.title
                unit.included = item.checkState(0) == Qt.CheckState.Checked
            for index in range(item.childCount()):
                sync(item.child(index))

        for index in range(root.childCount()):
            sync(root.child(index))

    def _book_siblings(self, item: QTreeWidgetItem) -> list[BookUnit]:
        parent = item.parent()
        if parent is None:
            return self._book_chapters
        unit = parent.data(0, Qt.ItemDataRole.UserRole)
        return unit.children if isinstance(unit, BookUnit) else self._book_chapters

    def _merge_book_units(self) -> None:
        items = self.structure_tree.selectedItems()
        if len(items) < 2 or any(
            item.parent() is not items[0].parent() for item in items
        ):
            showWarning(tr.ankigpt_book_merge_selection(), self)
            return
        self._sync_structure_tree()
        siblings = self._book_siblings(items[0])
        units = [
            unit
            for item in items
            if isinstance((unit := item.data(0, Qt.ItemDataRole.UserRole)), BookUnit)
        ]
        indexes = sorted(siblings.index(unit) for unit in units)
        if indexes != list(range(indexes[0], indexes[-1] + 1)):
            showWarning(tr.ankigpt_book_merge_selection(), self)
            return
        block = siblings[indexes[0] : indexes[-1] + 1]
        merged = BookUnit(
            f"{block[0].title} – {block[-1].title}",
            block[0].start,
            block[-1].end,
            [child for unit in block for child in unit.children],
            any(unit.included for unit in block),
        )
        siblings[indexes[0] : indexes[-1] + 1] = [merged]
        self._fill_structure_tree()

    def _split_book_unit(self) -> None:
        items = self.structure_tree.selectedItems()
        if len(items) != 1:
            showWarning(tr.ankigpt_book_split_selection(), self)
            return
        self._sync_structure_tree()
        item = items[0]
        unit = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(unit, BookUnit) or unit.children or self._book_doc is None:
            showWarning(tr.ankigpt_book_split_selection(), self)
            return
        midpoint = unit.start + unit.length // 2
        text = self._book_doc.text
        boundary = text.find("\n\n", midpoint, min(unit.end, midpoint + 2000))
        if boundary == -1:
            boundary = text.rfind("\n\n", max(unit.start, midpoint - 2000), midpoint)
        if boundary <= unit.start or boundary >= unit.end:
            showWarning(tr.ankigpt_book_split_selection(), self)
            return
        siblings = self._book_siblings(item)
        index = siblings.index(unit)
        siblings[index : index + 1] = [
            BookUnit(
                f"{unit.title} (Part 1)",
                unit.start,
                boundary,
                included=unit.included,
            ),
            BookUnit(
                f"{unit.title} (Part 2)",
                boundary,
                unit.end,
                included=unit.included,
            ),
        ]
        self._fill_structure_tree()

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
        if not self.subcategory.text().strip():
            showWarning(
                tr.ankigpt_no_book_title()
                if self.book_source.isChecked()
                else tr.ankigpt_no_subcategory(),
                self,
            )
            return
        if self.book_source.isChecked() and len(self.files) != 1:
            showWarning(tr.ankigpt_book_one_source(), self)
            return
        config = llm_config(self.mw.pm)
        if not config.configured:
            showWarning(tr.ankigpt_no_api_key(), self)
            return
        client = make_client(config)
        files = list(self.files)
        instructions = self._course_instructions()
        target = self.target.value()
        if self.book_source.isChecked():
            self._prepare_book(files[0])
            return
        self._candidate_decks = []
        self._book_results = []
        self._separate_documents = False
        if str(self.nonbook_organization.currentData()) == "per_document":
            self._extract_documents_separately(
                files, client, config, instructions, target
            )
            return
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

    def _extract_documents_separately(
        self,
        files: list[str],
        client: extract.JsonClient,
        config: LLMConfig,
        instructions: str,
        target: int,
    ) -> None:
        mw = self.mw
        root = self._destination_root()
        self._cancel_requested = False
        self._sampled = []
        self._docs = []
        self._start_progress()
        self._log(tr.ankigpt_reading_files())
        self.extract_btn.setEnabled(False)

        def progress(event: extract.ProgressEvent) -> None:
            mw.taskman.run_on_main(lambda: self._on_progress(event))

        def op(_col: Collection) -> list[BookDeckResult]:
            results: list[BookDeckResult] = []
            docs: list[extract.Document] = []
            for path in files:
                if self._cancel_requested:
                    raise extract.Cancelled()
                doc = extract.extract_text(path)
                if remote := self._remote_sources.get(path):
                    doc.path = remote.url
                    doc.name = remote.name
                docs.append(doc)
            destinations = document_deck_names(root, (doc.name for doc in docs))
            for index, (doc, destination) in enumerate(
                zip(docs, destinations, strict=True), start=1
            ):
                mw.taskman.run_on_main(
                    lambda name=doc.name, i=index: self._log(
                        tr.ankigpt_document_extracting_unit(
                            name=name, current=i, total=len(files)
                        )
                    )
                )
                candidates = extract.extract_concepts(
                    [doc],
                    instructions,
                    target,
                    client,
                    progress=progress,
                    should_cancel=lambda: self._cancel_requested,
                    max_chars_per_file=config.max_chars_per_file,
                )
                results.append(BookDeckResult(destination, candidates, doc))
            return results

        QueryOp(parent=self, op=op, success=self._on_document_decks_extracted).failure(
            self._on_extract_failed
        ).without_collection().run_in_background()

    def _on_document_decks_extracted(self, results: list[BookDeckResult]) -> None:
        self._separate_documents = True
        self._on_grouped_extracted(results)

    def _prepare_book(self, path: str) -> None:
        self._cancel_requested = False
        self._start_progress()
        self._log(tr.ankigpt_reading_files())
        self.extract_btn.setEnabled(False)

        client = make_client(llm_config(self.mw.pm))

        def op(_col: Collection) -> tuple[extract.Document, list[BookUnit], bool]:
            doc = extract.extract_text(path)
            if remote := self._remote_sources.get(path):
                doc.path = remote.url
                doc.name = remote.name
            chapters, used_ai = classify_book_structure(doc.text, client)
            return doc, chapters, used_ai

        QueryOp(parent=self, op=op, success=self._on_book_prepared).failure(
            self._on_extract_failed
        ).without_collection().run_in_background()

    def _on_book_prepared(
        self, result: tuple[extract.Document, list[BookUnit], bool]
    ) -> None:
        doc, chapters, used_ai = result
        self.extract_btn.setEnabled(True)
        self._finish_progress(tr.ankigpt_progress_done())
        self._book_doc = doc
        self._book_chapters = chapters
        self._book_structure_ai = used_ai
        if not self._book_chapters:
            showWarning(tr.ankigpt_book_no_structure(), self)
            self.stack.setCurrentIndex(0)
            return
        self.book_split.setCurrentIndex(0)
        self._fill_structure_tree()
        if not used_ai:
            tooltip(tr.ankigpt_book_structure_fallback(), parent=self)
        self.stack.setCurrentIndex(1)

    def _extract_book_units(self) -> None:
        if self._book_doc is None:
            return
        if self.book_split.currentData() is None:
            showWarning(tr.ankigpt_book_choose_granularity_warning(), self)
            self.book_split.setFocus()
            return
        self._sync_structure_tree()
        per_section = bool(self.book_split.currentData())
        units = generation_units(self._book_chapters, per_section)
        if not units:
            showWarning(tr.ankigpt_book_nothing_selected(), self)
            return
        source = self._book_doc
        base_name = self._destination_root()
        instructions = self._course_instructions()
        fixed_target = self.target.value()
        automatic = str(self.book_count_mode.currentData()) == "auto"
        config = llm_config(self.mw.pm)
        client = make_client(config)
        mw = self.mw
        self._cancel_requested = False
        self._start_progress()

        def progress(event: extract.ProgressEvent) -> None:
            mw.taskman.run_on_main(lambda: self._on_progress(event))

        def op(_col: Collection) -> list[BookDeckResult]:
            results: list[BookDeckResult] = []
            for index, (path, unit) in enumerate(units, start=1):
                if self._cancel_requested:
                    raise extract.Cancelled()
                deck_name = "::".join([base_name, *path])
                target = unit.suggested_concepts if automatic else fixed_target
                unit_doc = extract.Document(
                    name=" — ".join(path),
                    text=source.text[unit.start : unit.end],
                    path=source.path,
                )
                mw.taskman.run_on_main(
                    lambda unit_path=path,
                    name=deck_name,
                    i=index: self._begin_book_unit(unit_path, name, i, len(units))
                )
                candidates = extract.extract_concepts(
                    [unit_doc],
                    instructions,
                    target,
                    client,
                    progress=progress,
                    should_cancel=lambda: self._cancel_requested,
                    max_chars_per_file=config.max_chars_per_file,
                )
                if not candidates:
                    mw.taskman.run_on_main(
                        lambda name=deck_name: self._log(
                            tr.ankigpt_book_retrying_unit(name=name)
                        )
                    )
                    retry_instructions = (
                        instructions
                        + "\nThis is one bounded book unit. Extract concrete, "
                        "teachable concepts from its substantive text; ignore only "
                        "navigation, headers, and front matter."
                    )
                    candidates = extract.extract_concepts(
                        [unit_doc],
                        retry_instructions,
                        target,
                        client,
                        progress=progress,
                        should_cancel=lambda: self._cancel_requested,
                        workers=1,
                        max_chars_per_file=config.max_chars_per_file,
                    )
                results.append(BookDeckResult(deck_name, candidates, unit_doc))
            return results

        QueryOp(parent=self, op=op, success=self._on_book_extracted).failure(
            self._on_extract_failed
        ).without_collection().run_in_background()

    def _on_book_extracted(self, results: list[BookDeckResult]) -> None:
        self._separate_documents = False
        self._on_grouped_extracted(results)

    def _on_grouped_extracted(self, results: list[BookDeckResult]) -> None:
        candidates = [
            candidate for result in results for candidate in result.candidates
        ]
        if not candidates:
            self._on_extracted([])
            return
        empty = [result.deck_name for result in results if not result.candidates]
        if empty:
            tooltip(
                tr.ankigpt_units_without_concepts(
                    count=len(empty), names="\n".join(empty[:8])
                ),
                period=12000,
                parent=self,
            )
        self._book_results = results
        self._candidate_decks = [
            result.deck_name for result in results for _candidate in result.candidates
        ]
        self._docs = [result.document for result in results]
        self._sampled = [doc for doc in self._docs if doc.report and doc.report.partial]
        self._on_extracted(candidates)

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
        self.stack.setCurrentIndex(2)
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
        book_mode = len(self._candidate_decks) == len(candidates)
        self.table.setColumnCount(4 if book_mode else 3)
        self.table.setHorizontalHeaderLabels(
            (
                [
                    tr.ankigpt_column_deck(),
                    tr.ankigpt_column_title(),
                    tr.ankigpt_column_summary(),
                    tr.ankigpt_column_key_points(),
                ]
                if book_mode
                else [
                    tr.ankigpt_column_title(),
                    tr.ankigpt_column_summary(),
                    tr.ankigpt_column_key_points(),
                ]
            )
        )
        self.table.setRowCount(len(candidates))
        for row, c in enumerate(candidates):
            offset = 1 if book_mode else 0
            if book_mode:
                deck_item = QTableWidgetItem(self._candidate_decks[row])
                deck_item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                )
                self.table.setItem(row, 0, deck_item)
            title = QTableWidgetItem(c.title)
            title.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsEditable
            )
            title.setCheckState(Qt.CheckState.Checked)
            self.table.setItem(row, offset, title)
            self.table.setItem(row, offset + 1, QTableWidgetItem(c.summary))
            self.table.setItem(
                row, offset + 2, QTableWidgetItem("\n".join(c.key_points))
            )
        self.table.resizeRowsToContents()
        self.table.blockSignals(False)
        self._update_create_button()

    def _selected_with_decks(self) -> list[tuple[str, ConceptCandidate]]:
        out: list[tuple[str, ConceptCandidate]] = []
        book_mode = len(self._candidate_decks) == len(self.candidates)
        for row, original in enumerate(self.candidates):
            offset = 1 if book_mode else 0
            title_item = self.table.item(row, offset)
            if title_item is None or title_item.checkState() != Qt.CheckState.Checked:
                continue
            summary_item = self.table.item(row, offset + 1)
            points_item = self.table.item(row, offset + 2)
            points = [
                line.strip()
                for line in (points_item.text() if points_item else "").splitlines()
                if line.strip()
            ]
            out.append(
                (
                    self._candidate_decks[row] if book_mode else "",
                    ConceptCandidate(
                        title=title_item.text().strip(),
                        summary=(summary_item.text() if summary_item else "").strip(),
                        key_points=points,
                        sources=list(original.sources),
                    ),
                )
            )
        return out

    def _selected(self) -> list[ConceptCandidate]:
        return [candidate for _deck, candidate in self._selected_with_decks()]

    def _update_create_button(self, *_args: object) -> None:
        self.create_btn.setText(tr.ankigpt_create_notes(count=len(self._selected())))

    def on_create(self) -> None:
        selected_with_decks = self._selected_with_decks()
        if not selected_with_decks:
            showWarning(tr.ankigpt_nothing_selected(), self)
            return
        deck_name = self._destination_root()
        instructions = self._course_instructions()
        mode = str(self.mode.currentData())
        mw = self.mw
        grouped: dict[str, list[ConceptCandidate]] = {}
        for candidate_deck, candidate in selected_with_decks:
            grouped.setdefault(candidate_deck or deck_name, []).append(candidate)

        def op(col: Collection) -> OpChanges:
            changes: OpChanges | None = None
            for destination, candidates in grouped.items():
                deck_id = deck_id_for_name(col, destination)
                changes = create_concept_notes(
                    col, deck_id, candidates, context=instructions
                )
                settings = deck_settings(col, deck_id)
                settings.mode = mode
                if instructions:
                    settings.context = instructions
                save_deck_settings(col, deck_id, settings)
            assert changes is not None
            return changes

        docs = list(self._docs)

        def on_done(_changes: OpChanges) -> None:
            if self._candidate_decks:
                documents = {
                    result.deck_name: result.document for result in self._book_results
                }
                for destination in grouped:
                    if document := documents.get(destination):
                        self._store_documents(destination, [document])
                message = (
                    tr.ankigpt_created_document_decks(
                        count=len(grouped), concepts=len(selected_with_decks)
                    )
                    if self._separate_documents
                    else tr.ankigpt_created_book_decks(
                        count=len(grouped), concepts=len(selected_with_decks)
                    )
                )
                tooltip(message, parent=mw)
            else:
                self._store_documents(deck_name, docs)
                tooltip(
                    tr.ankigpt_created_notes(
                        count=len(selected_with_decks), deck=deck_name
                    ),
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
