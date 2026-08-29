# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from aqt.ankigpt.credentials import (
    CredentialStorageError,
    account_for_profile,
    migrate_plaintext_api_key,
    read_api_key,
    save_api_key,
)
from aqt.ankigpt.llm import LLMError, connection_error, redact_secret
from aqt.ankigpt.providers import PROVIDER_OPENAI, provider_by_id


@dataclass
class FakeProfileManager:
    profile: dict = field(default_factory=dict)
    saves: int = 0

    def profileFolder(self, create: bool = True) -> str:
        return "/profiles/Student"

    def save(self) -> None:
        self.saves += 1


class MemoryStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, account: str) -> str:
        return self.values.get(account, "")

    def set(self, account: str, secret: str) -> None:
        self.values[account] = secret

    def delete(self, account: str) -> None:
        self.values.pop(account, None)


def test_secure_store_roundtrip_does_not_write_profile() -> None:
    pm = FakeProfileManager()
    store = MemoryStore()

    def factory() -> MemoryStore:
        return store

    save_api_key(pm, "  sk-test-secret  ", factory)  # type: ignore[arg-type]
    assert read_api_key(pm, factory) == "sk-test-secret"  # type: ignore[arg-type]
    assert pm.profile == {}
    assert len(account_for_profile(pm)) == 64  # type: ignore[arg-type]


def test_plaintext_migration_deletes_only_after_success() -> None:
    pm = FakeProfileManager({"ankigptApiKey": "sk-legacy"})
    store = MemoryStore()
    assert migrate_plaintext_api_key(  # type: ignore[arg-type]
        pm, "ankigptApiKey", lambda: store
    )
    assert "ankigptApiKey" not in pm.profile
    assert read_api_key(pm, lambda: store) == "sk-legacy"  # type: ignore[arg-type]
    assert pm.saves == 1


def test_failed_migration_preserves_plaintext() -> None:
    class BrokenStore(MemoryStore):
        def set(self, account: str, secret: str) -> None:
            raise CredentialStorageError("vault locked")

    pm = FakeProfileManager({"ankigptApiKey": "sk-legacy"})
    with pytest.raises(CredentialStorageError):
        migrate_plaintext_api_key(  # type: ignore[arg-type]
            pm, "ankigptApiKey", BrokenStore
        )
    assert pm.profile["ankigptApiKey"] == "sk-legacy"
    assert pm.saves == 0


def test_error_translation_redacts_exact_and_key_shaped_secrets() -> None:
    secret = "sk-super-secret-value"
    result = connection_error(
        LLMError(f"request failed for {secret} and key-another-secret", 401), secret
    )
    assert not result.ok
    assert "authenticate" in result.message
    assert secret not in result.technical_details
    assert "key-another-secret" not in result.technical_details
    assert result.technical_details.count("[REDACTED]") == 2
    assert secret not in redact_secret(secret, secret)


def test_provider_lookup_falls_back_safely() -> None:
    assert provider_by_id(PROVIDER_OPENAI).name == "OpenAI"
    assert provider_by_id("unknown").id == PROVIDER_OPENAI
