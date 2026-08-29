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
        '<svg><script>alert(1)</script></svg>',
        '<svg><image href="https://example.test/a.png"/></svg>',
        '<svg><rect onclick="alert(1)"/></svg>',
        '<svg><foreignObject><div>unsafe</div></foreignObject></svg>',
    ],
)
def test_svg_sanitizer_rejects_active_or_external_content(svg: str) -> None:
    with pytest.raises(UnsafeVisual):
        sanitize_svg(svg)
