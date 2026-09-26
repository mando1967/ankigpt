# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from unittest.mock import patch

from aqt.ankigpt import focus


def teardown_function(_function: object) -> None:
    focus.stop()


def test_focus_session_tracks_time_and_pauses() -> None:
    session = focus.FocusSession(5, 10, started_at=100)

    assert session.elapsed_seconds(160) == 60
    assert session.remaining_seconds(160) == 540
    session.pause(160)
    assert session.remaining_seconds(220) == 540
    session.resume(220)
    assert session.remaining_seconds(280) == 480


def test_focus_session_clamps_options_and_summarizes() -> None:
    session = focus.start(0, 999)
    assert session.card_goal == 1
    assert session.duration_minutes == 120
    session.answered = 1
    assert session.complete

    summary = focus.finish()

    assert summary is not None
    assert summary["answered"] == 1
    assert summary["goal"] == 1
    assert focus.current() is None


def test_timer_completes_only_after_active_time() -> None:
    session = focus.FocusSession(5, 1, started_at=0)
    session.pause(0)
    with patch.object(focus.time, "monotonic", return_value=120):
        assert not session.complete
        session.resume()
    with patch.object(focus.time, "monotonic", return_value=179):
        assert not session.complete
    with patch.object(focus.time, "monotonic", return_value=180):
        assert session.complete
