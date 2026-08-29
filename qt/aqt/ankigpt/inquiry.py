# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from aqt.ankigpt import prompts
from aqt.ankigpt.llm import connection_error, make_client
from aqt.ankigpt.settings import llm_config
from aqt.operations import QueryOp
from aqt.qt import *
from aqt.utils import showWarning


@dataclass
class InquiryContext:
    mode: str
    title: str
    summary: str
    key_points: list[str]
    course_context: str = ""
    sources: list[str] = field(default_factory=list)


class InquiryDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        pm: object,
        context: InquiryContext,
        apply: Callable[[prompts.InquiryResult], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.pm = pm
        self.context = context
        self.apply_result = apply
        self.result: prompts.InquiryResult | None = None
        self.setWindowTitle("Improve with AI" if context.mode == "edit" else "Ask AI")
        self.resize(680, 560)
        layout = QVBoxLayout(self)
        intro = QLabel(
            f"Ask about <b>{context.title}</b>. Answers are grounded in this concept "
            "and its available course sources."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        presets = QHBoxLayout()
        for label, question in self._presets():
            button = QPushButton(label)
            qconnect(button.clicked, lambda _checked=False, q=question: self.question.setPlainText(q))
            presets.addWidget(button)
        layout.addLayout(presets)
        self.question = QPlainTextEdit()
        self.question.setPlaceholderText("What would you like help understanding or improving?")
        self.question.setMaximumHeight(100)
        layout.addWidget(self.question)
        self.answer = QTextBrowser()
        self.answer.setPlaceholderText("The grounded response will appear here.")
        layout.addWidget(self.answer, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.ask = QPushButton("Ask AI")
        buttons.addButton(self.ask, QDialogButtonBox.ButtonRole.ActionRole)
        self.apply = QPushButton("Apply suggested concept")
        self.apply.setEnabled(False)
        if apply is not None:
            buttons.addButton(self.apply, QDialogButtonBox.ButtonRole.AcceptRole)
        qconnect(self.ask.clicked, self._ask)
        qconnect(self.apply.clicked, self._apply)
        qconnect(buttons.rejected, self.reject)
        layout.addWidget(buttons)

    def _presets(self) -> list[tuple[str, str]]:
        if self.context.mode == "edit":
            return [("Improve clarity", "Rewrite this as a clearer, self-contained concept."), ("Find gaps", "Identify and repair important missing or vague points using only the sources."), ("Simplify", "Make this easier to understand without losing essential meaning.")]
        return [("Explain differently", "Explain this concept in a different way."), ("Give an example", "Give a source-supported example or say if the sources do not contain one."), ("Why it matters", "Why is this concept important and how does it connect to the key points?")]

    def _ask(self) -> None:
        question = self.question.toPlainText().strip()
        if not question:
            return
        config = llm_config(self.pm)  # type: ignore[arg-type]
        if not config.configured:
            showWarning("Configure an AI provider in Settings first.", self)
            return
        self.ask.setEnabled(False)
        self.answer.setPlainText("Thinking…")

        def op(_col: object) -> prompts.InquiryResult:
            system, user = prompts.build_inquiry_prompt(
                mode=self.context.mode, question=question, title=self.context.title,
                summary=self.context.summary, key_points=self.context.key_points,
                context=self.context.course_context, sources=self.context.sources,
            )
            data = make_client(config).complete_json(system, user, "learning_inquiry", prompts.INQUIRY_SCHEMA)
            return prompts.parse_inquiry(data)

        def success(result: prompts.InquiryResult) -> None:
            self.result = result
            refs = f"\n\nSources used: {', '.join(map(str, result.source_refs))}" if result.source_refs else ""
            visual = (
                f"\n\nVisual suggestion ({result.visual_placement} side): "
                f"{result.visual_description}"
                if result.visual_recommended and result.visual_description
                else ""
            )
            self.answer.setPlainText(result.answer + refs + visual)
            self.ask.setEnabled(True)
            self.apply.setEnabled(bool(result.revised_title and result.revised_summary))

        def failure(exc: Exception) -> None:
            error = connection_error(exc, config.api_key)
            self.answer.setPlainText(error.message + (f"\n\n{error.technical_details}" if error.technical_details else ""))
            self.ask.setEnabled(True)

        QueryOp(parent=self, op=op, success=success).failure(failure).without_collection().run_in_background()

    def _apply(self) -> None:
        if self.result is not None and self.apply_result is not None:
            self.apply_result(self.result)
            self.accept()
