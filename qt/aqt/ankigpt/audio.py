# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Profile-local background audio, independent of card webview reloads."""

from __future__ import annotations

import random
import struct
import tempfile
import wave
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from aqt.qt import *
from aqt.utils import openLink

if TYPE_CHECKING:
    from aqt.main import AnkiQt

MYNOISE = [
    ("Rain", "https://mynoise.net/NoiseMachines/rainNoiseGenerator.php"),
    (
        "Ocean · Irish Coast",
        "https://mynoise.net/NoiseMachines/windSeaRainNoiseGenerator.php",
    ),
    ("Café", "https://mynoise.net/NoiseMachines/cafeRestaurantNoiseGenerator.php"),
    ("White Noise & Co", "https://mynoise.net/NoiseMachines/whiteNoiseGenerator.php"),
]


def valid_mynoise_url(value: str) -> bool:
    try:
        url = urlsplit(value)
        return (
            url.scheme == "https"
            and url.hostname in {"mynoise.net", "www.mynoise.net"}
            and url.port in {None, 443}
            and not url.username
            and not url.password
            and not any(char.isspace() for char in value)
        )
    except ValueError:
        return False


def write_noise(path: Path, color: str, seconds: int = 12) -> None:
    """Generate our own bounded mono PCM, with softened loop boundaries."""
    if color not in {"white", "pink", "brown"}:
        raise ValueError("Unknown noise color")
    rate = 24000
    rng = random.Random()
    rows = [0.0] * 12
    brown = 0.0
    samples = bytearray()
    count = rate * seconds
    for i in range(count):
        white = rng.uniform(-1, 1)
        if color == "brown":
            brown = 0.995 * brown + 0.025 * white
            value = brown * 3
        elif color == "pink":
            # Independent random values updated at octave-spaced rates.
            index = min(11, ((i + 1) & -(i + 1)).bit_length() - 1)
            rows[index] = white
            value = (sum(rows) + rng.uniform(-1, 1)) / 5
        else:
            value = white
        ramp = min(1.0, i / 480, (count - 1 - i) / 480)
        samples.extend(struct.pack("<h", int(max(-1, min(1, value)) * 10000 * ramp)))
    with wave.open(str(path), "wb") as output:
        output.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        output.writeframes(samples)


class BackgroundAudio(QDialog):
    def __init__(self, mw: AnkiQt) -> None:
        super().__init__(mw)
        from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer

        self.mw = mw
        self.settings = dict((mw.pm.profile or {}).get("ankigptBackgroundAudio", {}))
        self.cache = tempfile.TemporaryDirectory(prefix="ankigpt-audio-")
        self.player = QMediaPlayer(self)
        self.output = QAudioOutput(self)
        self.player.setAudioOutput(self.output)
        self.player.setLoops(QMediaPlayer.Loops.Infinite)
        self.resume_after_break = False
        self.setWindowTitle("Background sounds")
        self.resize(520, 420)
        layout = QVBoxLayout(self)
        self.source = QComboBox()
        for label, value in [
            ("White noise", "white"),
            ("Pink noise", "pink"),
            ("Brown noise", "brown"),
            ("Local audio file", "local"),
        ]:
            self.source.addItem(label, value)
        self.source.setCurrentIndex(
            max(0, self.source.findData(self.settings.get("source", "pink")))
        )
        layout.addWidget(QLabel("Play in AnkiGPT"))
        layout.addWidget(self.source)
        self.file_label = QLabel(
            Path(self.settings.get("file", "")).name or "No local file selected"
        )
        self.file_label.setWordWrap(True)
        layout.addWidget(self.file_label)
        choose = QPushButton("Choose audio file…")
        qconnect(choose.clicked, self.choose_file)
        layout.addWidget(choose)
        row = QHBoxLayout()
        for label, callback in [("Play", self.play), ("Stop", self.stop)]:
            button = QPushButton(label)
            qconnect(button.clicked, callback)
            row.addWidget(button)
        layout.addLayout(row)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(int(self.settings.get("volume", 20)))
        self.volume.setAccessibleName("Background sound volume")
        layout.addWidget(QLabel("Volume"))
        layout.addWidget(self.volume)
        self.mute = QCheckBox("Mute")
        self.mute.setChecked(bool(self.settings.get("muted", False)))
        layout.addWidget(self.mute)
        self.auto = QCheckBox("Start this sound with focus sessions")
        self.auto.setChecked(bool(self.settings.get("auto", False)))
        layout.addWidget(self.auto)
        self.status = QLabel("Stopped")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        layout.addWidget(QLabel("myNoise · website bookmarks"))
        self.links = QComboBox()
        for label, url in MYNOISE:
            self.links.addItem(label, url)
        for url in self.settings.get("favorites", []):
            if isinstance(url, str) and valid_mynoise_url(url):
                self.links.addItem(url, url)
        layout.addWidget(self.links)
        row = QHBoxLayout()
        for label, callback in [
            ("Open in app", self.open_in_app),
            ("Open externally", self.open_mynoise),
            ("Save favorite link…", self.add_favorite),
            ("Remove favorite", self.remove_favorite),
        ]:
            button = QPushButton(label)
            qconnect(button.clicked, callback)
            row.addWidget(button)
        layout.addLayout(row)
        note = QLabel(
            "myNoise playback is controlled on its website. AnkiGPT volume, breaks, and session end affect only audio played here."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        close = QPushButton("Done")
        qconnect(close.clicked, self.hide)
        layout.addWidget(close)
        qconnect(self.source.currentIndexChanged, self.source_changed)
        qconnect(self.volume.valueChanged, self.save)
        qconnect(self.mute.toggled, self.save)
        qconnect(self.auto.toggled, self.save)
        qconnect(self.player.errorOccurred, self.on_error)
        self.save()

    def save(self) -> None:
        self.settings.update(
            source=self.source.currentData(),
            volume=self.volume.value(),
            muted=self.mute.isChecked(),
            auto=self.auto.isChecked(),
        )
        self.output.setVolume(self.volume.value() / 100)
        self.output.setMuted(self.mute.isChecked())
        if self.mw.pm.profile is not None:
            self.mw.pm.profile["ankigptBackgroundAudio"] = self.settings.copy()

    def source_changed(self) -> None:
        self.stop()
        self.player.setSource(QUrl())
        self.save()

    def choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose background audio",
            "",
            "Audio (*.mp3 *.wav *.ogg *.flac *.m4a);;All files (*)",
        )
        if path:
            self.stop()
            self.player.setSource(QUrl())
            self.settings["file"] = path
            self.file_label.setText(Path(path).name)
            self.source.setCurrentIndex(self.source.findData("local"))
            self.save()

    def play(self) -> None:
        from aqt.ankigpt import focus

        if (session := focus.current()) and session.paused_at is not None:
            self.status.setText("Resume your focus session to play audio.")
            return
        try:
            color = self.source.currentData()
            if color == "local":
                path = Path(self.settings.get("file", ""))
                if not path.is_file():
                    self.status.setText("Choose an existing local audio file first.")
                    return
            else:
                path = Path(self.cache.name) / f"{color}.wav"
                if not path.exists():
                    write_noise(path, color)
            url = QUrl.fromLocalFile(str(path.resolve()))
            if self.player.source() != url:
                self.player.setSource(url)
            self.player.play()
            self.status.setText("Playing · " + self.source.currentText())
        except (OSError, ValueError) as error:
            self.on_error(None, str(error))

    def on_error(self, _error: object, message: str) -> None:
        self.stop()
        self.status.setText("Unable to play audio: " + message)

    def stop(self) -> None:
        self.resume_after_break = False
        self.player.stop()
        self.status.setText("Stopped")

    def pause_for_break(self) -> None:
        self.resume_after_break = self.player.isPlaying()
        if self.resume_after_break:
            self.player.pause()
            self.status.setText("Paused for your focus break")

    def resume_from_break(self) -> None:
        if self.resume_after_break:
            self.resume_after_break = False
            self.play()

    def open_mynoise(self) -> None:
        url = self.links.currentData()
        if valid_mynoise_url(url):
            self.stop()
            openLink(url)

    def open_in_app(self) -> None:
        from aqt.ankigpt.browser import show_browser

        url = self.links.currentData()
        if valid_mynoise_url(url):
            self.stop()
            self.hide()
            show_browser(self.mw, url)

    def add_favorite(self) -> None:
        url, ok = QInputDialog.getText(
            self,
            "Save myNoise favorite",
            "Paste a myNoise HTTPS link (including saved sound settings):",
        )
        if not ok:
            return
        url = url.strip()
        if not valid_mynoise_url(url):
            self.status.setText("Enter an HTTPS link on mynoise.net.")
            return
        favorites = list(self.settings.get("favorites", []))
        if url not in favorites:
            favorites.append(url)
            self.links.addItem(url, url)
        self.settings["favorites"] = favorites
        self.links.setCurrentIndex(self.links.findData(url))
        self.save()

    def remove_favorite(self) -> None:
        index = self.links.currentIndex()
        if index >= len(MYNOISE):
            url = self.links.currentData()
            self.links.removeItem(index)
            self.settings["favorites"] = [
                item for item in self.settings.get("favorites", []) if item != url
            ]
            self.save()

    def dispose(self) -> None:
        self.stop()
        self.player.setSource(QUrl())
        self.hide()
        self.cache.cleanup()
        self.deleteLater()


_audio: BackgroundAudio | None = None


def show_audio(mw: AnkiQt) -> None:
    global _audio
    if _audio is None:
        _audio = BackgroundAudio(mw)
    _audio.show()
    _audio.raise_()
    _audio.activateWindow()


def focus_started(mw: AnkiQt) -> None:
    global _audio
    settings = (mw.pm.profile or {}).get("ankigptBackgroundAudio", {})
    if settings.get("auto", False):
        if _audio is None:
            _audio = BackgroundAudio(mw)
        _audio.play()


def focus_paused() -> None:
    if _audio is not None:
        _audio.pause_for_break()


def focus_resumed() -> None:
    if _audio is not None:
        _audio.resume_from_break()


def stop_audio() -> None:
    if _audio is not None:
        _audio.stop()


def close_audio() -> None:
    global _audio
    if _audio is not None:
        _audio.dispose()
        _audio = None
