# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""AnkiGPT-owned startup and profile-selection interface."""

from __future__ import annotations

from types import SimpleNamespace

from aqt.qt import *


def build_profile_window(window: QMainWindow) -> SimpleNamespace:
    window.setWindowTitle("Welcome to AnkiGPT")
    window.resize(940, 610)
    window.setMinimumSize(720, 500)

    central = QWidget()
    central.setObjectName("profileCanvas")
    root = QHBoxLayout(central)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)

    brand = QFrame()
    brand.setObjectName("profileBrand")
    brand_layout = QVBoxLayout(brand)
    brand_layout.setContentsMargins(48, 52, 48, 46)
    mark = QLabel("A")
    mark.setObjectName("profileMark")
    mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
    mark.setFixedSize(52, 52)
    title = QLabel("AnkiGPT")
    title.setObjectName("profileBrandTitle")
    strapline = QLabel("Your materials.\nReal understanding.")
    strapline.setObjectName("profileStrapline")
    strapline.setWordWrap(True)
    description = QLabel(
        "A focused learning environment powered by adaptive scheduling and modern AI."
    )
    description.setObjectName("profileDescription")
    description.setWordWrap(True)
    brand_layout.addWidget(mark, 0, Qt.AlignmentFlag.AlignLeft)
    brand_layout.addSpacing(22)
    brand_layout.addWidget(title)
    brand_layout.addWidget(strapline)
    brand_layout.addSpacing(16)
    brand_layout.addWidget(description)
    brand_layout.addStretch()
    brand_layout.addWidget(QLabel("Built on Anki's proven learning engine."))
    root.addWidget(brand, 5)

    panel = QFrame()
    panel.setObjectName("profilePanel")
    panel_layout = QVBoxLayout(panel)
    panel_layout.setContentsMargins(52, 54, 52, 40)
    eyebrow = QLabel("WELCOME BACK")
    eyebrow.setObjectName("profileEyebrow")
    heading = QLabel("Choose your learning space")
    heading.setObjectName("profileHeading")
    subheading = QLabel("Select a profile to continue where you left off.")
    subheading.setObjectName("profileSubheading")
    panel_layout.addWidget(eyebrow)
    panel_layout.addWidget(heading)
    panel_layout.addWidget(subheading)
    panel_layout.addSpacing(20)

    profiles = QListWidget()
    profiles.setObjectName("profileList")
    profiles.setAlternatingRowColors(False)
    panel_layout.addWidget(profiles, 1)

    login = QPushButton("Continue")
    login.setObjectName("profilePrimary")
    login.setDefault(True)
    panel_layout.addWidget(login)

    manage = QHBoxLayout()
    add = QPushButton("New Profile")
    rename = QPushButton("Rename")
    delete_button = QPushButton("Delete")
    manage.addWidget(add)
    manage.addWidget(rename)
    manage.addWidget(delete_button)
    panel_layout.addLayout(manage)

    utility = QHBoxLayout()
    open_backup = QPushButton("Restore Backup")
    downgrade = QPushButton("Downgrade and Quit")
    downgrade.setVisible(False)
    quit_button = QPushButton("Quit")
    utility.addWidget(open_backup)
    utility.addStretch()
    utility.addWidget(downgrade)
    utility.addWidget(quit_button)
    panel_layout.addLayout(utility)
    root.addWidget(panel, 6)

    statusbar = QStatusBar(window)
    statusbar.setVisible(False)
    window.setStatusBar(statusbar)
    window.setCentralWidget(central)
    window.setStyleSheet(_STYLE)
    return SimpleNamespace(
        login=login,
        profiles=profiles,
        openBackup=open_backup,
        quit=quit_button,
        add=add,
        rename=rename,
        delete_2=delete_button,
        downgrade_button=downgrade,
        statusbar=statusbar,
    )


def prompt_profile_name(parent: QWidget, title: str, default: str = "") -> str | None:
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setObjectName("ankigptProfileDialog")
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(26, 24, 26, 22)
    heading = QLabel(title)
    heading.setObjectName("profileDialogTitle")
    hint = QLabel("Profiles keep separate courses, progress, and synchronization.")
    hint.setObjectName("profileDialogHint")
    hint.setWordWrap(True)
    field = QLineEdit(default)
    field.setPlaceholderText("Profile name")
    field.selectAll()
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
    )
    qconnect(buttons.accepted, dialog.accept)
    qconnect(buttons.rejected, dialog.reject)
    layout.addWidget(heading)
    layout.addWidget(hint)
    layout.addSpacing(8)
    layout.addWidget(field)
    layout.addSpacing(8)
    layout.addWidget(buttons)
    dialog.setMinimumWidth(430)
    dialog.setStyleSheet(_DIALOG_STYLE)
    return field.text().strip() if dialog.exec() else None


def confirm_profile_delete(parent: QWidget, name: str) -> bool:
    return confirm_action(
        parent,
        "Delete profile",
        f"Delete “{name}”?",
        "This removes the profile's cards, learning history, and local media. "
        "This action cannot be undone.",
        "Delete Profile",
        danger=True,
    )


def confirm_action(
    parent: QWidget,
    title: str,
    heading_text: str,
    message: str,
    accept_text: str,
    *,
    danger: bool = False,
) -> bool:
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setObjectName("ankigptProfileDialog")
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(26, 24, 26, 22)
    heading = QLabel(heading_text)
    heading.setObjectName("profileDialogTitle")
    warning = QLabel(message)
    warning.setObjectName("profileDialogHint")
    warning.setWordWrap(True)
    buttons = QDialogButtonBox()
    cancel = buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
    remove = buttons.addButton(accept_text, QDialogButtonBox.ButtonRole.AcceptRole)
    remove.setObjectName("profileDanger" if danger else "profilePrimary")
    qconnect(cancel.clicked, dialog.reject)
    qconnect(remove.clicked, dialog.accept)
    layout.addWidget(heading)
    layout.addWidget(warning)
    layout.addSpacing(10)
    layout.addWidget(buttons)
    dialog.setMinimumWidth(450)
    dialog.setStyleSheet(_DIALOG_STYLE)
    return bool(dialog.exec())


def show_profile_message(parent: QWidget, title: str, message: str) -> None:
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setObjectName("ankigptProfileDialog")
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(26, 24, 26, 22)
    heading = QLabel(title)
    heading.setObjectName("profileDialogTitle")
    body = QLabel(message)
    body.setObjectName("profileDialogHint")
    body.setWordWrap(True)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
    qconnect(buttons.accepted, dialog.accept)
    layout.addWidget(heading)
    layout.addWidget(body)
    layout.addWidget(buttons)
    dialog.setMinimumWidth(430)
    dialog.setStyleSheet(_DIALOG_STYLE)
    dialog.exec()


_STYLE = """
QWidget#profileCanvas { background:#ffffff; }
QFrame#profileBrand { background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #10265f,stop:1 #276ce2); color:white; }
QLabel#profileMark { color:#245fce; background:white; border-radius:14px; font-size:27px; font-weight:800; }
QLabel#profileBrandTitle { color:white; font-size:29px; font-weight:800; }
QLabel#profileStrapline { color:white; font-size:25px; font-weight:650; }
QLabel#profileDescription { color:#dce8ff; font-size:14px; }
QFrame#profilePanel { background:#f8faff; }
QLabel#profileEyebrow { color:#3157d5; font-size:11px; font-weight:800; }
QLabel#profileHeading { color:#10204d; font-size:24px; font-weight:750; }
QLabel#profileSubheading { color:#68758b; font-size:13px; }
QListWidget#profileList { background:white; border:1px solid #dce3ed; border-radius:11px; padding:7px; outline:0; font-size:14px; }
QListWidget#profileList::item { min-height:42px; padding:4px 10px; border-radius:7px; }
QListWidget#profileList::item:selected { color:#174bb5; background:#e8efff; }
QPushButton { min-height:31px; padding:4px 13px; border:1px solid #d0d8e5; border-radius:7px; background:white; color:#34435f; }
QPushButton:hover { background:#f0f4fa; }
QPushButton#profilePrimary { min-height:38px; color:white; background:#2367e8; border-color:#2367e8; font-size:14px; font-weight:700; }
QPushButton#profilePrimary:hover { background:#1955c6; }
"""

_DIALOG_STYLE = """
QDialog#ankigptProfileDialog { background:#f8faff; }
QLabel#profileDialogTitle { color:#10204d; font-size:21px; font-weight:750; }
QLabel#profileDialogHint { color:#68758b; font-size:13px; }
QLineEdit { min-height:34px; padding:3px 10px; background:white; border:1px solid #cfd8e6; border-radius:7px; font-size:14px; }
QPushButton { min-height:30px; padding:3px 13px; border:1px solid #d0d8e5; border-radius:7px; background:white; }
QPushButton#profileDanger { color:white; background:#c83e4d; border-color:#c83e4d; font-weight:700; }
"""
