# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

import pytest

from aqt.ankigpt.visuals import UnsafeVisual, sanitize_svg


def test_svg_sanitizer_accepts_instructional_shapes() -> None:
    svg = '<svg viewBox="0 0 10 10"><line x1="0" y1="0" x2="10" y2="10" stroke="#000"/><text x="2" y="5">Force</text></svg>'
    clean = sanitize_svg(svg).decode()
    assert "<line" in clean and "Force" in clean
    assert 'viewBox="0 0 960 540"' in clean


@pytest.mark.parametrize(
    "svg",
    [
        "<svg><script>alert(1)</script></svg>",
        '<svg><image href="https://example.test/a.png"/></svg>',
        '<svg><rect onclick="alert(1)"/></svg>',
        "<svg><foreignObject><div>unsafe</div></foreignObject></svg>",
    ],
)
def test_svg_sanitizer_rejects_active_or_external_content(svg: str) -> None:
    with pytest.raises(UnsafeVisual):
        sanitize_svg(svg)


@pytest.mark.parametrize("kind", ["inquiry", "visual"])
def test_ai_dialog_keeps_qt_result_method(kind: str) -> None:
    from aqt.ankigpt.inquiry import InquiryContext, InquiryDialog
    from aqt.ankigpt.visuals import VisualGenerationDialog
    from aqt.qt import QApplication, QDialog, QWidget

    app = QApplication.instance() or QApplication(["dialog-test"])
    parent = QWidget()
    if kind == "inquiry":
        dialog = InquiryDialog(
            parent, object(), InquiryContext("edit", "Title", "Summary", [])
        )
    else:
        dialog = VisualGenerationDialog(
            parent, "Title", "Summary", [], "", lambda *_: None
        )
    assert dialog.generated_result is None
    assert dialog.result() == QDialog.DialogCode.Rejected
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    dialog.deleteLater()
    parent.deleteLater()
    app.processEvents()
