# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Student-facing AI configuration embedded in Anki Preferences."""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

from aqt.ankigpt.credentials import CredentialStorageError, save_api_key
from aqt.ankigpt.llm import ConnectionResult, LLMConfig, test_connection
from aqt.ankigpt.providers import PROVIDERS, provider_by_id
from aqt.ankigpt.settings import (
    _KEY_API_KEY,
    _KEY_BASE_URL,
    _KEY_MAX_CHARS,
    _KEY_MODEL,
    _KEY_PROVIDER,
    _KEY_TIMEOUT,
    _set_profile,
    llm_config,
    provider_id,
)
from aqt.operations import QueryOp
from aqt.qt import *
from aqt.utils import tr

if TYPE_CHECKING:
    from aqt.preferences import Preferences


class AISetupWidget(QWidget):
    def __init__(self, dialog: Preferences) -> None:
        super().__init__(dialog)
        self.dialog = dialog
        self.pm = dialog.mw.pm
        self._saved_config = llm_config(self.pm)
        self._loading = True
        self._build()
        self._select_provider(provider_id(self.pm))
        self._loading = False

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.provider = QComboBox()
        for definition in PROVIDERS:
            self.provider.addItem(definition.name, definition.id)
        qconnect(self.provider.currentIndexChanged, self._provider_changed)
        form.addRow(tr.ankigpt_provider(), self.provider)

        key_row = QHBoxLayout()
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText(tr.ankigpt_api_key_saved())
        self.api_key.setClearButtonEnabled(True)
        qconnect(self.api_key.editingFinished, self._save_entered_key)
        key_row.addWidget(self.api_key, 1)
        self.show_key = QToolButton()
        self.show_key.setText(tr.ankigpt_show_key())
        self.show_key.setCheckable(True)
        qconnect(self.show_key.toggled, self._toggle_key)
        key_row.addWidget(self.show_key)
        remove_key = QToolButton()
        remove_key.setText(tr.ankigpt_remove_key())
        qconnect(remove_key.clicked, self._remove_key)
        key_row.addWidget(remove_key)
        form.addRow(tr.ankigpt_api_key(), key_row)

        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.addItems([self._saved_config.model])
        qconnect(self.model.currentTextChanged, self._model_changed)
        form.addRow(tr.ankigpt_model(), self.model)
        layout.addLayout(form)

        actions = QHBoxLayout()
        help_btn = QPushButton(tr.ankigpt_api_key_help())
        qconnect(help_btn.clicked, self._show_help)
        actions.addWidget(help_btn)
        self.test_btn = QPushButton(tr.ankigpt_test_connection())
        qconnect(self.test_btn.clicked, self._test)
        actions.addWidget(self.test_btn)
        actions.addStretch()
        layout.addLayout(actions)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.advanced = QGroupBox(tr.ankigpt_advanced())
        self.advanced.setCheckable(True)
        self.advanced.setChecked(False)
        advanced_form = QFormLayout(self.advanced)
        self.base_url = QLineEdit(self._saved_config.base_url)
        qconnect(self.base_url.textChanged, self._base_url_changed)
        advanced_form.addRow(tr.ankigpt_base_url(), self.base_url)
        self.timeout = QSpinBox()
        self.timeout.setRange(5, 600)
        self.timeout.setValue(self._saved_config.timeout_secs)
        qconnect(self.timeout.valueChanged, self._timeout_changed)
        advanced_form.addRow(tr.ankigpt_timeout(), self.timeout)
        self.max_chars = QSpinBox()
        self.max_chars.setRange(10_000, 5_000_000)
        self.max_chars.setSingleStep(10_000)
        self.max_chars.setGroupSeparatorShown(True)
        self.max_chars.setValue(self._saved_config.max_chars_per_file)
        self.max_chars.setToolTip(tr.ankigpt_max_chars_tooltip())
        qconnect(self.max_chars.valueChanged, self._max_chars_changed)
        advanced_form.addRow(tr.ankigpt_max_chars(), self.max_chars)
        layout.addWidget(self.advanced)

    def _select_provider(self, wanted: str) -> None:
        index = self.provider.findData(wanted)
        self.provider.setCurrentIndex(max(index, 0))

    def _provider_changed(self, _index: int) -> None:
        definition = provider_by_id(str(self.provider.currentData()))
        _set_profile(self.pm, _KEY_PROVIDER, definition.id)
        self.api_key.setPlaceholderText(
            tr.ankigpt_api_key_saved()
            if self._saved_config.configured
            else definition.key_placeholder
        )
        if not self._loading and definition.id == "openai":
            self.base_url.setText(definition.base_url)
        if not self.model.currentText().strip():
            self.model.setCurrentText(definition.model)

    def _toggle_key(self, shown: bool) -> None:
        self.api_key.setEchoMode(
            QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password
        )

    def _model_changed(self, value: str) -> None:
        _set_profile(self.pm, _KEY_MODEL, value.strip())

    def _base_url_changed(self, value: str) -> None:
        _set_profile(self.pm, _KEY_BASE_URL, value.strip())

    def _timeout_changed(self, value: int) -> None:
        _set_profile(self.pm, _KEY_TIMEOUT, int(value))

    def _max_chars_changed(self, value: int) -> None:
        _set_profile(self.pm, _KEY_MAX_CHARS, int(value))

    def _candidate_config(self) -> LLMConfig:
        current = llm_config(self.pm)
        return LLMConfig(
            api_key=self.api_key.text().strip() or current.api_key,
            base_url=self.base_url.text().strip(),
            model=self.model.currentText().strip(),
            timeout_secs=self.timeout.value(),
            max_chars_per_file=self.max_chars.value(),
        )

    def _save_entered_key(self) -> bool:
        secret = self.api_key.text().strip()
        if not secret:
            return True
        try:
            save_api_key(self.pm, secret)
        except CredentialStorageError as exc:
            self.status.setText(tr.ankigpt_secure_storage_failed(error=str(exc)))
            return False
        if self.pm.profile is not None:
            self.pm.profile.pop(_KEY_API_KEY, None)
        self.api_key.clear()
        self._saved_config = self._candidate_config()
        self.status.setText(tr.ankigpt_api_key_stored_securely())
        return True

    def _remove_key(self) -> None:
        try:
            save_api_key(self.pm, "")
        except CredentialStorageError as exc:
            self.status.setText(tr.ankigpt_secure_storage_failed(error=str(exc)))
            return
        if self.pm.profile is not None:
            self.pm.profile.pop(_KEY_API_KEY, None)
        self._saved_config = self._candidate_config()
        self.status.setText(tr.ankigpt_api_key_removed())

    def _test(self) -> None:
        config = self._candidate_config()
        if not config.configured:
            self.status.setText(tr.ankigpt_no_api_key())
            return
        self.setEnabled(False)
        self.status.setText(tr.ankigpt_testing_connection())

        def success(result: ConnectionResult) -> None:
            self.setEnabled(True)
            self.status.setText(result.message)
            if result.ok:
                self._save_entered_key()
            elif result.technical_details:
                box = QMessageBox(self)
                box.setIcon(QMessageBox.Icon.Warning)
                box.setWindowTitle(tr.ankigpt_connection_failed_title())
                box.setText(result.message)
                box.setDetailedText(result.technical_details)
                box.exec()

        QueryOp(
            parent=self,
            op=lambda _col: test_connection(config),
            success=success,
        ).without_collection().run_in_background()

    def _show_help(self) -> None:
        definition = provider_by_id(str(self.provider.currentData()))
        steps = "".join(
            f"<li>{html.escape(step)}</li>" for step in definition.help_steps
        )
        link = (
            f'<p><a href="{html.escape(definition.help_url)}">Open the provider API-key page</a></p>'
            if definition.help_url
            else ""
        )
        box = QMessageBox(self)
        box.setWindowTitle(tr.ankigpt_api_key_help())
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(f"<ol>{steps}</ol>{link}")
        box.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        box.exec()
