# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from __future__ import annotations

from typing import Callable

from packaging.version import Version

import aqt
from anki.buildinfo import buildhash
from anki.buildinfo import version as version_str
from anki.collection import CheckForUpdateResponse, Collection, GithubRelease
from anki.utils import dev_mode, int_time, int_version, plat_desc
from aqt.operations import QueryOp
from aqt.package import (
    download_github_update_and_install as _download_github_update_and_install,
)
from aqt.qt import *
from aqt.utils import openLink, show_warning, showText, tooltip, tr


def check_for_update() -> None:
    from aqt import mw

    def do_check(_col: Collection) -> CheckForUpdateResponse:
        return mw.backend.check_for_update(
            version=int_version(),
            buildhash=buildhash,
            os=plat_desc(),
            install_id=mw.pm.meta["id"],
            last_message_id=max(0, mw.pm.meta["lastMsg"]),
        )

    def on_done(resp: CheckForUpdateResponse) -> None:
        # is clock off?
        if not dev_mode:
            diff = abs(resp.current_time - int_time())
            if diff > 300:
                diff_text = tr.qt_misc_second(count=diff)
                warn = (
                    tr.qt_misc_in_order_to_ensure_your_collection(val="%s") % diff_text
                )
                show_warning(
                    warn,
                    parent=mw,
                    textFormat=Qt.TextFormat.RichText,
                    callback=mw.app.closeAllWindows,
                )
                return
        # should we show a message?
        if msg := resp.message:
            showText(msg, parent=mw, type="html")
            mw.pm.meta["lastMsg"] = resp.last_message_id
        # has Anki been updated?
        if ver := resp.new_version:
            if mw.pm.meta.get("suppressUpdate", None) != ver:
                prompt_to_update(mw, ver)

    def on_fail(exc: Exception) -> None:
        print(f"update check failed: {exc}")

    QueryOp(parent=mw, op=do_check, success=on_done).failure(
        on_fail
    ).without_collection().run_in_background()


def prompt_to_update(mw: aqt.AnkiQt, ver: str) -> None:
    msg = (
        tr.qt_misc_anki_updatedanki_has_been_released(val=ver)
        + tr.qt_misc_would_you_like_to_download_it()
    )

    msgbox = QMessageBox(mw)
    msgbox.setStandardButtons(
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    )
    msgbox.setIcon(QMessageBox.Icon.Information)
    msgbox.setText(msg)

    button = QPushButton(tr.qt_misc_ignore_this_update())
    msgbox.addButton(button, QMessageBox.ButtonRole.RejectRole)
    msgbox.setDefaultButton(QMessageBox.StandardButton.Yes)
    ret = msgbox.exec()

    if msgbox.clickedButton() == button:
        # ignore this update
        mw.pm.meta["suppressUpdate"] = ver
    elif ret == QMessageBox.StandardButton.Yes:
        openLink(aqt.appWebsiteDownloadSection)


def prompt_and_install_github_update(mw: aqt.AnkiQt, release: GithubRelease) -> None:
    msg = f"AnkiGPT {release.tag_name.removeprefix('v')} has been released.\n\n"
    msg += "Would you like to download and install it now?"

    msgbox = QMessageBox(mw)
    msgbox.setStandardButtons(
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    )
    msgbox.setIcon(QMessageBox.Icon.Information)
    msgbox.setText(msg)
    msgbox.setWindowTitle("AnkiGPT Update")

    ignore_button = QPushButton("Ignore this update")
    msgbox.addButton(ignore_button, QMessageBox.ButtonRole.RejectRole)
    msgbox.setDefaultButton(QMessageBox.StandardButton.Yes)
    ret = msgbox.exec()

    if msgbox.clickedButton() == ignore_button:
        mw.pm.meta["suppressAnkiGPTUpdate"] = release.tag_name
    elif ret == QMessageBox.StandardButton.Yes:
        _download_github_update_and_install(release)


def check_for_ankigpt_update(mw: aqt.AnkiQt, *, manual: bool) -> None:
    """Check AnkiGPT's release feed, never the upstream Anki update service."""
    installed = Version(version_str.removeprefix("v"))

    def on_success(release: GithubRelease) -> None:
        available = Version(release.tag_name.removeprefix("v"))
        suppressed = mw.pm.meta.get("suppressAnkiGPTUpdate")
        if available > installed and (manual or suppressed != release.tag_name):
            prompt_and_install_github_update(mw, release)
        elif manual:
            tooltip("No AnkiGPT updates are available.", parent=mw)

    op = get_latest_release_op(
        parent=mw,
        include_prerelease=installed.is_prerelease,
        on_success=on_success,
    )
    if manual:
        op.with_progress().run_in_background()
    else:
        op.failure(lambda exc: print(f"AnkiGPT update check failed: {exc}"))
        op.run_in_background()


def get_latest_release_op(
    parent: QWidget,
    include_prerelease: bool,
    on_success: Callable[[GithubRelease], None],
) -> QueryOp:
    return QueryOp(
        parent=parent,
        op=lambda col: col._backend.get_latest_release(
            include_prerelease=include_prerelease
        ),
        success=on_success,
    )
