# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""API credential storage backed by the operating system's secure vault."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from aqt.profiles import ProfileManager

SERVICE_NAME = "AnkiGPT"
_SECURE_BACKENDS = (
    "keyring.backends.Windows",
    "keyring.backends.macOS",
    "keyring.backends.SecretService",
    "keyring.backends.kwallet",
)


class CredentialStorageError(RuntimeError):
    pass


class CredentialStore(Protocol):
    def get(self, account: str) -> str: ...

    def set(self, account: str, secret: str) -> None: ...

    def delete(self, account: str) -> None: ...


class KeyringCredentialStore:
    """Use only keyring's OS-backed implementations, never plaintext backends."""

    def _keyring(self):  # type: ignore[no-untyped-def]
        try:
            import keyring
        except ImportError as exc:
            raise CredentialStorageError(
                "secure credential storage is not installed"
            ) from exc
        backend = keyring.get_keyring()
        module = type(backend).__module__
        if not module.startswith(_SECURE_BACKENDS):
            raise CredentialStorageError(
                "no supported operating-system credential vault is available"
            )
        return keyring

    def get(self, account: str) -> str:
        try:
            return self._keyring().get_password(SERVICE_NAME, account) or ""
        except CredentialStorageError:
            raise
        except Exception as exc:
            raise CredentialStorageError(
                "could not read the secure credential"
            ) from exc

    def set(self, account: str, secret: str) -> None:
        try:
            self._keyring().set_password(SERVICE_NAME, account, secret)
        except CredentialStorageError:
            raise
        except Exception as exc:
            raise CredentialStorageError(
                "could not save the secure credential"
            ) from exc

    def delete(self, account: str) -> None:
        try:
            self._keyring().delete_password(SERVICE_NAME, account)
        except CredentialStorageError:
            raise
        except Exception as exc:
            # Deleting a missing entry is harmless; backend failures are not.
            if exc.__class__.__name__ != "PasswordDeleteError":
                raise CredentialStorageError(
                    "could not remove the secure credential"
                ) from exc


def account_for_profile(pm: ProfileManager) -> str:
    """Stable, non-identifying account name for this Anki profile directory."""
    path = os.path.normcase(os.path.abspath(pm.profileFolder(create=False))).encode(
        "utf-8"
    )
    return hashlib.sha256(path).hexdigest()


def read_api_key(
    pm: ProfileManager,
    store_factory: Callable[[], CredentialStore] = KeyringCredentialStore,
) -> str:
    return store_factory().get(account_for_profile(pm))


def save_api_key(
    pm: ProfileManager,
    api_key: str,
    store_factory: Callable[[], CredentialStore] = KeyringCredentialStore,
) -> None:
    account = account_for_profile(pm)
    store = store_factory()
    secret = api_key.strip()
    if secret:
        store.set(account, secret)
    else:
        store.delete(account)


def migrate_plaintext_api_key(
    pm: ProfileManager,
    profile_key: str,
    store_factory: Callable[[], CredentialStore] = KeyringCredentialStore,
) -> bool:
    """Move a legacy profile secret to the vault, deleting it only after success."""
    profile = pm.profile
    if not profile or not (secret := str(profile.get(profile_key) or "").strip()):
        return False
    save_api_key(pm, secret, store_factory)
    profile.pop(profile_key, None)
    pm.save()
    return True
