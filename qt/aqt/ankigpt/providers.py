# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Provider metadata for the student-facing AI setup UI."""

from __future__ import annotations

from dataclasses import dataclass

from aqt.ankigpt.llm import DEFAULT_BASE_URL, DEFAULT_MODEL

PROVIDER_OPENAI = "openai"
PROVIDER_COMPATIBLE = "openai-compatible"


@dataclass(frozen=True)
class ProviderDefinition:
    id: str
    name: str
    base_url: str
    model: str
    key_placeholder: str
    help_url: str
    help_steps: tuple[str, ...]


PROVIDERS = (
    ProviderDefinition(
        id=PROVIDER_OPENAI,
        name="OpenAI",
        base_url=DEFAULT_BASE_URL,
        model=DEFAULT_MODEL,
        key_placeholder="sk-...",
        help_url="https://platform.openai.com/api-keys",
        help_steps=(
            "Sign in to the OpenAI Platform (an API account, not just ChatGPT).",
            "Open API keys and create a new secret key.",
            "Copy the complete key now; the provider will not show it again.",
            "Paste it here, choose a model, and select Test Connection.",
            "API billing may need to be enabled separately from a ChatGPT subscription.",
        ),
    ),
    ProviderDefinition(
        id=PROVIDER_COMPATIBLE,
        name="Other / OpenAI-compatible",
        base_url=DEFAULT_BASE_URL,
        model=DEFAULT_MODEL,
        key_placeholder="API key",
        help_url="",
        help_steps=(
            "Create an API key in your provider's developer console.",
            "Copy the complete key and paste it here.",
            "In Advanced, enter the provider's OpenAI-compatible v1 base URL.",
            "Choose a model that supports strict JSON-schema responses.",
            "Select Test Connection before saving.",
        ),
    ),
)


def provider_by_id(provider_id: str) -> ProviderDefinition:
    return next((p for p in PROVIDERS if p.id == provider_id), PROVIDERS[0])
