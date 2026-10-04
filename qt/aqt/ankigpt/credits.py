# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Account balance lookup; never infer prepaid credits from token usage."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import requests

from aqt.ankigpt.llm import LLMConfig, fake_mode_enabled

OPENAI_BILLING = "https://platform.openai.com/settings/organization/billing/overview"
OPENROUTER_BILLING = "https://openrouter.ai/settings/credits"

if TYPE_CHECKING:
    from aqt.main import AnkiQt


@dataclass(frozen=True)
class CreditBalance:
    text: str
    detail: str
    billing_url: str = ""


def fetch_balance(config: LLMConfig) -> CreditBalance:
    if fake_mode_enabled():
        return CreditBalance(
            "AI credits: demo", "Demo mode does not use account credits."
        )
    if not config.configured:
        return CreditBalance(
            "AI credits: not connected", "Connect your AI account in AI Setup."
        )
    url = urlsplit(config.base_url)
    if url.scheme == "https" and url.netloc == "api.openai.com":
        return CreditBalance(
            "AI credits: check billing",
            "OpenAI does not document a prepaid balance endpoint for this API key. "
            "Click to view your remaining credits in OpenAI billing.",
            OPENAI_BILLING,
        )
    if (url.scheme, url.netloc, url.path.rstrip("/")) != (
        "https",
        "openrouter.ai",
        "/api/v1",
    ):
        return CreditBalance(
            "AI credits: unavailable",
            "This provider does not have a supported account balance lookup.",
        )
    try:
        with requests.get(
            "https://openrouter.ai/api/v1/credits",
            headers={"Authorization": f"Bearer {config.api_key.strip()}"},
            timeout=10,
            allow_redirects=False,
        ) as response:
            if response.status_code in (401, 403):
                return CreditBalance(
                    "AI credits: check billing",
                    "OpenRouter account balance lookup requires a management key. "
                    "Click to view your credits in billing.",
                    OPENROUTER_BILLING,
                )
            response.raise_for_status()
            data = response.json()["data"]
            purchased = Decimal(str(data["total_credits"]))
            used = Decimal(str(data["total_usage"]))
            if not purchased.is_finite() or not used.is_finite():
                raise ValueError("Invalid balance")
            remaining = purchased - used
        return CreditBalance(
            f"AI credits: ${remaining:,.2f}",
            "Remaining OpenRouter account credits (USD). Refreshes every minute. "
            "Click to open billing.",
            OPENROUTER_BILLING,
        )
    except (
        requests.RequestException,
        ValueError,
        KeyError,
        TypeError,
        InvalidOperation,
    ):
        return CreditBalance(
            "AI credits: unavailable",
            "Could not refresh your balance. It will retry automatically; click to check billing.",
            OPENROUTER_BILLING,
        )


def install_credit_indicator(mw: AnkiQt) -> None:
    from aqt import gui_hooks
    from aqt.ankigpt.settings import llm_config
    from aqt.operations import QueryOp
    from aqt.qt import QTimer, QToolButton, qconnect
    from aqt.utils import openLink

    button = QToolButton(mw)
    button.setAutoRaise(True)
    button.setText("AI credits: checking…")
    button.setAccessibleName("AI account credits remaining")
    button.setStyleSheet("QToolButton { font-size: 11px; padding: 2px 8px; }")
    bar = mw.statusBar()
    bar.setSizeGripEnabled(False)
    bar.addPermanentWidget(button)
    billing_url = ""
    generation = 0
    pending = False
    active = False
    last_config: LLMConfig | None = None

    def display(balance: CreditBalance) -> None:
        nonlocal billing_url
        billing_url = balance.billing_url
        button.setText(balance.text)
        button.setToolTip(balance.detail)

    def refresh() -> None:
        nonlocal pending, last_config
        if not active or pending:
            return
        config = llm_config(mw.pm)
        if config != last_config:
            display(CreditBalance("AI credits: checking…", "Checking account balance."))
            last_config = config
        request_generation = generation
        pending = True

        def done(balance: CreditBalance) -> None:
            nonlocal pending
            pending = False
            if active and request_generation == generation:
                if config == llm_config(mw.pm):
                    display(balance)
                else:
                    refresh()

        QueryOp(
            parent=mw, op=lambda _col: fetch_balance(config), success=done
        ).without_collection().run_in_background()

    timer = QTimer(button)
    timer.setInterval(60_000)
    qconnect(timer.timeout, refresh)

    def opened() -> None:
        nonlocal active, generation, last_config
        active = True
        generation += 1
        last_config = None
        bar.show()
        button.show()
        timer.start()
        refresh()

    def closed() -> None:
        nonlocal active, generation, last_config
        active = False
        generation += 1
        last_config = None
        timer.stop()
        display(
            CreditBalance(
                "AI credits: not connected", "Open a profile to check credits."
            )
        )
        button.hide()
        bar.hide()

    qconnect(
        button.clicked, lambda: openLink(billing_url) if billing_url else refresh()
    )
    gui_hooks.profile_did_open.append(opened)
    gui_hooks.profile_will_close.append(closed)

    def state_changed(_state: str, _old: str) -> None:
        if active and llm_config(mw.pm) != last_config:
            refresh()

    gui_hooks.state_did_change.append(state_changed)
