# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""AnkiGPT settings: profile-level LLM config, per-deck review settings, and
the widgets that edit them."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

from anki.collection import Collection
from anki.decks import DeckId
from aqt.ankigpt.credentials import (
    CredentialStorageError,
    migrate_plaintext_api_key,
    read_api_key,
    save_api_key,
)
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
_KEY_PROVIDER = "ankigptProvider"


def llm_config(pm: ProfileManager) -> LLMConfig:
    prof = pm.profile or {}
    legacy_key = str(prof.get(_KEY_API_KEY) or "").strip()
    try:
        api_key = read_api_key(pm)
    except CredentialStorageError:
        api_key = ""
    api_key = api_key or legacy_key or os.environ.get("OPENAI_API_KEY", "")
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
    save_api_key(pm, config.api_key)
    pm.profile.pop(_KEY_API_KEY, None)
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
    migrate_profile_credential(pm)
    tab = _third_party_tab(dialog)
    if tab is None:
        return
    from aqt.ankigpt.ai_setup import AISetupWidget

    group = QGroupBox(tr.ankigpt_preferences_group())
    group_layout = QVBoxLayout(group)
    group_layout.addWidget(AISetupWidget(dialog))

    layout = tab.layout()
    assert layout is not None
    # insert above the trailing spacer
    index = max(layout.count() - 1, 0)
    layout.insertWidget(index, group)  # type: ignore[attr-defined]


def provider_id(pm: ProfileManager) -> str:
    from aqt.ankigpt.providers import PROVIDER_OPENAI

    return str((pm.profile or {}).get(_KEY_PROVIDER) or PROVIDER_OPENAI)


def set_provider_id(pm: ProfileManager, value: str) -> None:
    assert pm.profile is not None
    pm.profile[_KEY_PROVIDER] = value


def migrate_profile_credential(pm: ProfileManager) -> str | None:
    """Migrate legacy plaintext storage; return a safe error for the UI."""
    try:
        migrate_plaintext_api_key(pm, _KEY_API_KEY)
        return None
    except CredentialStorageError as exc:
        return str(exc)


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
MODE_TRUE_FALSE = "true_false"
MODE_FILL_BLANK = "fill_blank"
MODE_MIX = "mix"
STUDY_MODES = (MODE_TYPED, MODE_MCQ, MODE_TRUE_FALSE, MODE_FILL_BLANK)
DECK_MODES = (MODE_SELF, *STUDY_MODES, MODE_MIX)


def mode_label(mode: str) -> str:
    return {
        MODE_SELF: tr.ankigpt_mode_self(),
        MODE_TYPED: tr.ankigpt_mode_typed(),
        MODE_MCQ: tr.ankigpt_mode_mcq(),
        MODE_TRUE_FALSE: tr.ankigpt_mode_true_false(),
        MODE_FILL_BLANK: tr.ankigpt_mode_fill_blank(),
        MODE_MIX: tr.ankigpt_mode_mix(),
    }[mode]


@dataclass
class DeckSettings:
    mode: str = MODE_SELF
    modes: list[str] = field(default_factory=list)
    auto_submit: bool = False
    auto_submit_delay_ms: int = 2500
    context: str = ""
    deep_lookup: bool = True

    @staticmethod
    def from_dict(d: dict[str, Any]) -> DeckSettings:
        mode = d.get("mode", MODE_SELF)
        if mode not in DECK_MODES:
            mode = MODE_SELF
        stored_modes = d.get("modes", [])
        if not isinstance(stored_modes, list):
            stored_modes = []
        return DeckSettings(
            mode=mode,
            modes=[m for m in stored_modes if m in STUDY_MODES],
            auto_submit=bool(d.get("auto_submit", False)),
            auto_submit_delay_ms=int(d.get("auto_submit_delay_ms", 2500)),
            context=str(d.get("context", "")),
            deep_lookup=bool(d.get("deep_lookup", True)),
        )

    def enabled_modes(self) -> list[str]:
        if self.modes:
            return list(self.modes)
        if self.mode == MODE_MIX:
            return list(STUDY_MODES)
        if self.mode == MODE_SELF:
            return list(STUDY_MODES)
        return [self.mode] if self.mode in STUDY_MODES else [MODE_TYPED]


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
        mode_box = QWidget()
        mode_layout = QVBoxLayout(mode_box)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        enabled = set(self.settings.enabled_modes())
        self.mode_checks: dict[str, QCheckBox] = {}
        for mode in STUDY_MODES:
            check = QCheckBox(mode_label(mode))
            check.setChecked(mode in enabled)
            self.mode_checks[mode] = check
            mode_layout.addWidget(check)
        form.addRow(tr.ankigpt_study_modes(), mode_box)

        self.auto_submit = QCheckBox(tr.ankigpt_auto_submit())
        self.auto_submit.setChecked(self.settings.auto_submit)
        form.addRow(self.auto_submit)

        self.delay = QDoubleSpinBox()
        self.delay.setRange(0.5, 30.0)
        self.delay.setSingleStep(0.5)
        self.delay.setValue(self.settings.auto_submit_delay_ms / 1000)
        form.addRow(tr.ankigpt_auto_submit_delay(), self.delay)

        self.deep_lookup = QCheckBox(tr.ankigpt_deep_lookup())
        self.deep_lookup.setChecked(self.settings.deep_lookup)
        self.deep_lookup.setToolTip(tr.ankigpt_deep_lookup_tooltip())
        form.addRow(self.deep_lookup)

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
        self.setMinimumWidth(600)
        restoreGeom(self, "ankigptDeckSettings")

    def accept(self) -> None:
        modes = [mode for mode, check in self.mode_checks.items() if check.isChecked()]
        if not modes:
            from aqt.utils import showWarning

            showWarning(tr.ankigpt_choose_study_mode(), self)
            return
        self.settings = DeckSettings(
            mode=modes[0],
            modes=modes,
            auto_submit=self.auto_submit.isChecked(),
            auto_submit_delay_ms=int(self.delay.value() * 1000),
            context=self.context.toPlainText().strip(),
            deep_lookup=self.deep_lookup.isChecked(),
        )
        save_deck_settings(self.mw.col, self.deck_id, self.settings)
        # questions prefetched under the old mode must not be reused
        try:
            from aqt.ankigpt import get_store

            get_store().drop_all_cached()
        except Exception:
            pass
        saveGeom(self, "ankigptDeckSettings")
        super().accept()

    def reject(self) -> None:
        saveGeom(self, "ankigptDeckSettings")
        super().reject()
