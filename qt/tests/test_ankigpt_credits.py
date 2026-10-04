# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from unittest.mock import MagicMock, patch

import requests

from aqt.ankigpt.credits import OPENAI_BILLING, fetch_balance
from aqt.ankigpt.llm import LLMConfig


def test_openai_balance_is_not_guessed(monkeypatch):
    monkeypatch.delenv("ANKIGPT_FAKE_LLM", raising=False)
    with patch("aqt.ankigpt.credits.requests.get") as get:
        balance = fetch_balance(LLMConfig("secret"))
    assert balance.text == "AI credits: check billing"
    assert balance.billing_url == OPENAI_BILLING
    get.assert_not_called()


def test_openrouter_balance(monkeypatch):
    monkeypatch.delenv("ANKIGPT_FAKE_LLM", raising=False)
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "data": {"total_credits": 100.5, "total_usage": 25.75}
    }
    with patch("aqt.ankigpt.credits.requests.get") as get:
        get.return_value.__enter__.return_value = response
        balance = fetch_balance(
            LLMConfig("secret", base_url="https://openrouter.ai/api/v1")
        )
    assert balance.text == "AI credits: $74.75"
    assert get.call_args.kwargs["allow_redirects"] is False


def test_failure_does_not_leak_key(monkeypatch):
    monkeypatch.delenv("ANKIGPT_FAKE_LLM", raising=False)
    with patch(
        "aqt.ankigpt.credits.requests.get",
        side_effect=requests.ConnectionError("secret"),
    ):
        result = fetch_balance(
            LLMConfig("secret", base_url="https://openrouter.ai/api/v1")
        )
    assert result.text == "AI credits: unavailable"
    assert "secret" not in result.detail


def test_unknown_host_does_not_receive_key(monkeypatch):
    monkeypatch.delenv("ANKIGPT_FAKE_LLM", raising=False)
    with patch("aqt.ankigpt.credits.requests.get") as get:
        fetch_balance(LLMConfig("secret", base_url="https://openrouter.ai.evil/api/v1"))
    get.assert_not_called()
