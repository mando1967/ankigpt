# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from unittest.mock import MagicMock, patch

import pytest
from packaging.version import Version

from anki.collection import GithubRelease
from aqt import update


@pytest.mark.parametrize("tag", ["26.08.3", "v26.08.3", "ankigpt-v26.08.3"])
def test_release_version_formats(tag: str) -> None:
    assert update.ankigpt_release_version(tag) == Version("26.8.3")


@pytest.mark.parametrize(
    "installed,suppressed,manual,prompt",
    [
        ("26.08.2", None, False, True),
        ("26.08.3", None, True, False),
        ("26.08.4", None, True, False),
        ("26.08.2", "ankigpt-v26.08.3", False, False),
        ("26.08.2", "ankigpt-v26.08.3", True, True),
    ],
)
def test_update_comparison(installed, suppressed, manual, prompt) -> None:
    mw = MagicMock()
    mw.pm.meta = {"suppressAnkiGPTUpdate": suppressed}
    release = GithubRelease(tag_name="ankigpt-v26.08.3")
    with (
        patch.object(update, "version_str", installed),
        patch.object(update, "get_latest_release_op") as operation,
        patch.object(update, "prompt_and_install_github_update") as show,
        patch.object(update, "tooltip"),
    ):
        update.check_for_ankigpt_update(mw, manual=manual)
        operation.call_args.kwargs["on_success"](release)
        assert show.called == prompt
