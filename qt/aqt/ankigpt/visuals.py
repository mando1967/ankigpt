# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Callable

from aqt.ankigpt import prompts
from aqt.ankigpt.llm import connection_error, make_client
from aqt.ankigpt.settings import llm_config
from aqt.operations import QueryOp
from aqt.qt import *
from aqt.utils import showWarning

_TAGS = {"svg", "g", "rect", "circle", "ellipse", "line", "polyline", "polygon", "path", "text", "tspan", "marker"}
_ATTRS = {"xmlns", "viewBox", "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry", "width", "height", "d", "points", "fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "opacity", "transform", "text-anchor", "font-size", "font-weight", "font-family", "dominant-baseline", "marker-start", "marker-end", "id", "refX", "refY", "markerWidth", "markerHeight", "orient"}
_SAFE_VALUE = re.compile(r"^[#(),.%+\-\w\s:/]*$")


class UnsafeVisual(ValueError):
    pass


def sanitize_svg(svg: str) -> bytes:
    """Return a small, self-contained SVG or reject unsafe/generated markup."""
    if len(svg) > 200_000 or "<!DOCTYPE" in svg.upper():
        raise UnsafeVisual("visual is too large or contains a document type")
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as exc:
        raise UnsafeVisual("visual is not valid SVG") from exc
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag not in _TAGS:
            raise UnsafeVisual(f"unsupported SVG element: {tag}")
        for raw_name, value in element.attrib.items():
            name = raw_name.rsplit("}", 1)[-1]
            if name not in _ATTRS or name.lower().startswith("on"):
                raise UnsafeVisual(f"unsupported SVG attribute: {name}")
            if "url(" in value.lower() and not value.lower().startswith("url(#"):
                raise UnsafeVisual("external SVG resource")
            if not _SAFE_VALUE.fullmatch(value):
                raise UnsafeVisual(f"unsafe SVG attribute value: {name}")
    if root.tag.rsplit("}", 1)[-1] != "svg":
        raise UnsafeVisual("root element must be svg")
    if "}" in root.tag:
        ET.register_namespace("", root.tag.split("}", 1)[0][1:])
    else:
        root.set("xmlns", "http://www.w3.org/2000/svg")
    root.set("viewBox", "0 0 960 540")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


class VisualGenerationDialog(QDialog):
    def __init__(
        self,
        mw: QWidget,
        title: str,
        summary: str,
        key_points: list[str],
        context: str,
        accepted: Callable[[str, str, str], None],
    ) -> None:
        super().__init__(mw)
        self.mw = mw
        self.concept_title = title
        self.summary = summary
        self.key_points = key_points
        self.context = context
        self.on_accepted = accepted
        self.svg: bytes | None = None
        self.result: prompts.GeneratedVisual | None = None
        self.setWindowTitle("Generate instructional visual")
        self.resize(760, 700)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "AI will design a focused instructional diagram using only this concept. "
            "Review it before adding it to the concept."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.request = QPlainTextEdit()
        self.request.setPlaceholderText(
            "Optional direction, e.g. show the forces and perpendicular distance"
        )
        self.request.setMaximumHeight(75)
        layout.addWidget(self.request)
        self.preview = QLabel("Select Generate visual to create a preview.")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(400)
        self.preview.setWordWrap(True)
        layout.addWidget(self.preview, 1)
        self.details = QLabel("")
        self.details.setWordWrap(True)
        layout.addWidget(self.details)
        buttons = QDialogButtonBox()
        self.generate = QPushButton("Generate visual")
        self.accept_visual = QPushButton("Accept and attach")
        self.accept_visual.setEnabled(False)
        decline = QPushButton("Decline")
        buttons.addButton(self.generate, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(self.accept_visual, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(decline, QDialogButtonBox.ButtonRole.RejectRole)
        qconnect(self.generate.clicked, self._generate)
        qconnect(self.accept_visual.clicked, self._accept)
        qconnect(decline.clicked, self.reject)
        layout.addWidget(buttons)

    def _generate(self) -> None:
        config = llm_config(self.mw.pm)  # type: ignore[attr-defined]
        if not config.configured:
            showWarning("Configure an AI provider in Settings first.", self)
            return
        self.generate.setEnabled(False)
        self.accept_visual.setEnabled(False)
        self.preview.setText("Designing visual…")

        def op(_col: object) -> tuple[prompts.GeneratedVisual, bytes]:
            system, user = prompts.build_visual_prompt(
                title=self.concept_title,
                summary=self.summary,
                key_points=self.key_points,
                context=self.context,
                request=self.request.toPlainText().strip(),
            )
            data = make_client(config).complete_json(
                system, user, "generate_visual", prompts.VISUAL_SCHEMA
            )
            result = prompts.parse_visual(data)
            return result, sanitize_svg(result.svg)

        def success(output: tuple[prompts.GeneratedVisual, bytes]) -> None:
            self.result, self.svg = output
            pixmap = QPixmap()
            if not pixmap.loadFromData(self.svg, "SVG"):
                raise UnsafeVisual("Qt could not render the generated SVG")
            self.preview.setPixmap(
                pixmap.scaled(
                    720,
                    405,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            self.details.setText(
                f"<b>Why this visual:</b> {self.result.rationale}<br>"
                f"<b>Image description:</b> {self.result.alt_text}<br>"
                f"<b>Placement:</b> {self.result.placement} side"
            )
            self.generate.setText("Regenerate")
            self.generate.setEnabled(True)
            self.accept_visual.setEnabled(True)

        def failure(exc: Exception) -> None:
            error = connection_error(exc, config.api_key)
            self.preview.setText(error.message)
            self.details.setText(error.technical_details)
            self.generate.setEnabled(True)

        QueryOp(parent=self, op=op, success=success).failure(failure).without_collection().run_in_background()

    def _accept(self) -> None:
        if self.svg is None or self.result is None:
            return
        filename = self.mw.col.media.write_data(  # type: ignore[attr-defined]
            "ankigpt-visual.svg", self.svg
        )
        self.on_accepted(filename, self.result.alt_text, self.result.placement)
        self.accept()
