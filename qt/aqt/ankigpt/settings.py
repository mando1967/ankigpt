# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""AnkiGPT settings: profile-level LLM config, per-deck review settings, and
the widgets that edit them."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from anki.collection import Collection
from anki.decks import DeckId
from aqt.ankigpt.extract import DEFAULT_MAX_CHARS_PER_FILE
from aqt.ankigpt.llm import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT_SECS,
    LLMConfig,
    fake_mode_enabled,
)
from aqt.qt import *
from aqt.utils import disable_help_button, restoreGeom, saveGeom, tr

if TYPE_CHECKING:
    from aqt.main import AnkiQt
    from aqt.preferences import Preferences
    from aqt.profiles import ProfileManager

# ---------------------------------------------------------------------------
# Profile-level LLM configuration (unsynced, per profile)
# ---------------------------------------------------------------------------

_KEY_API_KEY = "ankigptApiKey"
_KEY_BASE_URL = "ankigptBaseUrl"
_KEY_MODEL = "ankigptModel"
_KEY_TIMEOUT = "ankigptTimeoutSecs"
_KEY_MAX_CHARS = "ankigptMaxCharsPerFile"


def llm_config(pm: ProfileManager) -> LLMConfig:
    prof = pm.profile or {}
    api_key = prof.get(_KEY_API_KEY) or os.environ.get("OPENAI_API_KEY", "")
    if fake_mode_enabled():
        api_key = api_key or "fake"
    return LLMConfig(
        api_key=api_key,
        base_url=prof.get(_KEY_BASE_URL) or DEFAULT_BASE_URL,
        model=prof.get(_KEY_MODEL) or DEFAULT_MODEL,
        timeout_secs=int(prof.get(_KEY_TIMEOUT) or DEFAULT_TIMEOUT_SECS),
        max_chars_per_file=int(prof.get(_KEY_MAX_CHARS) or DEFAULT_MAX_CHARS_PER_FILE),
    )


def set_llm_config(pm: ProfileManager, config: LLMConfig) -> None:
    assert pm.profile is not None
    pm.profile[_KEY_API_KEY] = config.api_key
    pm.profile[_KEY_BASE_URL] = config.base_url
    pm.profile[_KEY_MODEL] = config.model
    pm.profile[_KEY_TIMEOUT] = config.timeout_secs
    pm.profile[_KEY_MAX_CHARS] = config.max_chars_per_file


def setup_preferences_tab(dialog: Preferences) -> None:
    """Add the AnkiGPT group box to the 'Third Party Services' preferences tab.

    Widgets write straight through to the profile dict, so the dialog's
    normal accept path (mw.pm.save()) persists them.
    """
    pm = dialog.mw.pm
    tab = _third_party_tab(dialog)
    if tab is None:
        return
    group = QGroupBox(tr.ankigpt_preferences_group())
    form = QFormLayout()
    group.setLayout(form)
    config = llm_config(pm)

    api_key = QLineEdit(pm.profile.get(_KEY_API_KEY, "") if pm.profile else "")
    api_key.setEchoMode(QLineEdit.EchoMode.Password)
    api_key.setPlaceholderText("sk-...")
    qconnect(api_key.textChanged, lambda s: _set_profile(pm, _KEY_API_KEY, s.strip()))
    form.addRow(tr.ankigpt_api_key(), api_key)

    base_url = QLineEdit(config.base_url)
    qconnect(
        base_url.textChanged,
        lambda s: _set_profile(pm, _KEY_BASE_URL, s.strip() or DEFAULT_BASE_URL),
    )
    form.addRow(tr.ankigpt_base_url(), base_url)

    model = QLineEdit(config.model)
    qconnect(
        model.textChanged,
        lambda s: _set_profile(pm, _KEY_MODEL, s.strip() or DEFAULT_MODEL),
    )
    form.addRow(tr.ankigpt_model(), model)

    timeout = QSpinBox()
    timeout.setRange(5, 600)
    timeout.setValue(config.timeout_secs)
    qconnect(timeout.valueChanged, lambda v: _set_profile(pm, _KEY_TIMEOUT, int(v)))
    form.addRow(tr.ankigpt_timeout(), timeout)

    max_chars = QSpinBox()
    max_chars.setRange(10_000, 5_000_000)
    max_chars.setSingleStep(10_000)
    max_chars.setGroupSeparatorShown(True)
    max_chars.setValue(config.max_chars_per_file)
    max_chars.setToolTip(tr.ankigpt_max_chars_tooltip())
    qconnect(max_chars.valueChanged, lambda v: _set_profile(pm, _KEY_MAX_CHARS, int(v)))
    form.addRow(tr.ankigpt_max_chars(), max_chars)

    layout = tab.layout()
    assert layout is not None
    # insert above the trailing spacer
    index = max(layout.count() - 1, 0)
    layout.insertWidget(index, group)  # type: ignore[attr-defined]


def _set_profile(pm: ProfileManager, key: str, value: Any) -> None:
    if pm.profile is not None:
        pm.profile[key] = value


def _third_party_tab(dialog: Preferences) -> QWidget | None:
    tabs: QTabWidget = dialog.form.tabWidget
    wanted = tr.preferences_third_party_services()
    for i in range(tabs.count()):
        if tabs.tabText(i) == wanted:
            return tabs.widget(i)
    return None


# ---------------------------------------------------------------------------
# Per-deck settings (synced, in collection config under one key)
# ---------------------------------------------------------------------------

CONFIG_KEY = "ankigptDecks"

MODE_SELF = "self"
MODE_TYPED = "typed"
MODE_MCQ = "mcq"
MODE_MIX = "mix"
DECK_MODES = (MODE_SELF, MODE_TYPED, MODE_MCQ, MODE_MIX)


def mode_label(mode: str) -> str:
    return {
        MODE_SELF: tr.ankigpt_mode_self(),
        MODE_TYPED: tr.ankigpt_mode_typed(),
        MODE_MCQ: tr.ankigpt_mode_mcq(),
        MODE_MIX: tr.ankigpt_mode_mix(),
    }[mode]


@dataclass
class DeckSettings:
    mode: str = MODE_SELF
    auto_submit: bool = False
    auto_submit_delay_ms: int = 2500
    context: str = ""

    @staticmethod
    def from_dict(d: dict[str, Any]) -> DeckSettings:
        mode = d.get("mode", MODE_SELF)
        if mode not in DECK_MODES:
            mode = MODE_SELF
        return DeckSettings(
            mode=mode,
            auto_submit=bool(d.get("auto_submit", False)),
            auto_submit_delay_ms=int(d.get("auto_submit_delay_ms", 2500)),
            context=str(d.get("context", "")),
        )


def _all_deck_settings(col: Collection) -> dict[str, Any]:
    data = col.get_config(CONFIG_KEY, {})
    return data if isinstance(data, dict) else {}


def has_deck_settings(col: Collection, deck_id: DeckId) -> bool:
    return str(deck_id) in _all_deck_settings(col)


def deck_settings(col: Collection, deck_id: DeckId) -> DeckSettings:
    """Settings for a deck, inheriting from the nearest configured parent."""
    data = _all_deck_settings(col)
    if entry := data.get(str(deck_id)):
        return DeckSettings.from_dict(entry)
    try:
        parents = col.decks.parents(DeckId(deck_id))
    except Exception:
        parents = []
    for parent in reversed(parents):
        if entry := data.get(str(parent["id"])):
            return DeckSettings.from_dict(entry)
    return DeckSettings()


def save_deck_settings(
    col: Collection, deck_id: DeckId, settings: DeckSettings
) -> None:
    data = _all_deck_settings(col)
    data[str(deck_id)] = asdict(settings)
    col.set_config(CONFIG_KEY, data)


class DeckSettingsDialog(QDialog):
    def __init__(self, mw: AnkiQt, deck_id: DeckId, parent: QWidget | None = None):
        super().__init__(parent or mw)
        self.mw = mw
        self.deck_id = deck_id
        deck_name = mw.col.decks.name_if_exists(deck_id) or ""
        self.setWindowTitle(tr.ankigpt_deck_settings_title(deck=deck_name))
        disable_help_button(self)
        self.settings = deck_settings(mw.col, deck_id)

        form = QFormLayout()
        self.mode = QComboBox()
        for mode in DECK_MODES:
            self.mode.addItem(mode_label(mode), mode)
        self.mode.setCurrentIndex(DECK_MODES.index(self.settings.mode))
        form.addRow(tr.ankigpt_grading_mode(), self.mode)

        self.auto_submit = QCheckBox(tr.ankigpt_auto_submit())
        self.auto_submit.setChecked(self.settings.auto_submit)
        form.addRow("", self.auto_submit)

        self.delay = QDoubleSpinBox()
        self.delay.setRange(0.5, 30.0)
        self.delay.setSingleStep(0.5)
        self.delay.setValue(self.settings.auto_submit_delay_ms / 1000)
        form.addRow(tr.ankigpt_auto_submit_delay(), self.delay)

        self.context = QPlainTextEdit(self.settings.context)
        self.context.setPlaceholderText(tr.ankigpt_instructions_placeholder())
        form.addRow(tr.ankigpt_deck_context(), self.context)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        qconnect(buttons.accepted, self.accept)
        qconnect(buttons.rejected, self.reject)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.setLayout(layout)
        self.setMinimumWidth(480)
        restoreGeom(self, "ankigptDeckSettings")

    def accept(self) -> None:
        self.settings = DeckSettings(
            mode=str(self.mode.currentData()),
            auto_submit=self.auto_submit.isChecked(),
            auto_submit_delay_ms=int(self.delay.value() * 1000),
            context=self.context.toPlainText().strip(),
        )
        save_deck_settings(self.mw.col, self.deck_id, self.settings)
        saveGeom(self, "ankigptDeckSettings")
        super().accept()

    def reject(self) -> None:
        saveGeom(self, "ankigptDeckSettings")
        super().reject()
