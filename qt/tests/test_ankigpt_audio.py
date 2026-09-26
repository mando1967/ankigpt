# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from __future__ import annotations

import struct
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from aqt.ankigpt import audio, focus
from aqt.qt import QApplication


@pytest.mark.parametrize("color", ["white", "pink", "brown"])
def test_noise_is_bounded_pcm_with_soft_boundaries(tmp_path: Path, color: str) -> None:
    path = tmp_path / "noise.wav"
    audio.write_noise(path, color, seconds=1)
    with wave.open(str(path)) as source:
        assert source.getparams()[:3] == (1, 2, 24000)
        data = source.readframes(source.getnframes())
    samples = struct.unpack("<24000h", data)
    assert samples[0] == samples[-1] == 0
    assert 0 < max(abs(sample) for sample in samples) <= 10000


@pytest.mark.parametrize(
    "url",
    [
        "https://mynoise.net/NoiseMachines/rainNoiseGenerator.php?l=123#saved",
        "https://www.mynoise.net/",
    ],
)
def test_accepts_mynoise_saved_links(url: str) -> None:
    assert audio.valid_mynoise_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "file:///C:/private.txt",
        "javascript:alert(1)",
        "https://mynoise.net.example.org/",
        "https://mynoise.net@evil.org/",
        "http://mynoise.net/",
        "https://mynoise.net:123/",
        "https://[",
    ],
)
def test_rejects_non_mynoise_links(url: str) -> None:
    assert not audio.valid_mynoise_url(url)


def test_audio_break_resume_and_stop(monkeypatch, tmp_path: Path) -> None:
    # Exercise the widget with a fake media backend: no hardware or audible output.
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    import PyQt6.QtMultimedia as multimedia

    from aqt.qt import QWidget

    mw = QWidget()
    mw.pm = SimpleNamespace(profile={})
    backend = MagicMock()
    monkeypatch.setattr(multimedia, "QMediaPlayer", MagicMock(return_value=backend))
    monkeypatch.setattr(multimedia, "QAudioOutput", MagicMock())
    dialog = audio.BackgroundAudio(mw)
    try:
        path = tmp_path / "own.wav"
        audio.write_noise(path, "white", seconds=1)
        dialog.settings["file"] = str(path)
        dialog.source.setCurrentIndex(dialog.source.findData("local"))
        backend.reset_mock()
        dialog.play()
        backend.play.assert_called_once()
        assert backend.setSource.call_args.args[0].isLocalFile()
        session = focus.start(5, 0)
        session.pause()
        backend.isPlaying.return_value = True
        dialog.pause_for_break()
        backend.pause.assert_called_once()
        dialog.play()
        assert backend.play.call_count == 1
        session.resume()
        dialog.resume_from_break()
        assert backend.play.call_count == 2
        session.pause()
        dialog.pause_for_break()
        dialog.stop()
        session.resume()
        dialog.resume_from_break()
        assert backend.play.call_count == 2
        dialog.volume.setValue(37)
        assert mw.pm.profile["ankigptBackgroundAudio"]["volume"] == 37
        dialog.settings["file"] = str(tmp_path / "missing.wav")
        dialog.play()
        assert "existing local" in dialog.status.text()
    finally:
        focus.stop()
        dialog.dispose()
        app.processEvents()
