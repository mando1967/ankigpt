# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Minimal OpenAI-compatible chat client with JSON-schema structured output.

Deliberately built on `requests` (already an aqt dependency) rather than the
openai SDK, so any OpenAI-compatible endpoint works by changing the base URL.
Nothing in this module may touch Qt or the collection: it is called from
background threads.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any

import requests

from aqt.ankigpt import prompts

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-5.6-luna"
DEFAULT_TIMEOUT_SECS = 60
FAKE_ENV_VAR = "ANKIGPT_FAKE_LLM"


class LLMError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class LLMConfig:
    api_key: str
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout_secs: int = DEFAULT_TIMEOUT_SECS

    @property
    def configured(self) -> bool:
        return bool(self.api_key.strip())


class LLMClient:
    """Calls {base_url}/chat/completions and returns the parsed JSON object."""

    max_attempts = 3
    retry_statuses = (408, 409, 425, 429, 500, 502, 503, 504)

    def __init__(self, config: LLMConfig):
        self.config = config
        self._session = requests.Session()

    @property
    def model(self) -> str:
        return self.config.model

    def complete_json(
        self,
        system: str,
        user: str,
        schema_name: str,
        json_schema: dict[str, Any],
    ) -> dict[str, Any]:
        if not self.config.configured:
            raise LLMError("no API key configured")
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        body = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "schema": json_schema,
                    "strict": True,
                },
            },
        }
        headers = {
            "Authorization": f"Bearer {self.config.api_key.strip()}",
            "Content-Type": "application/json",
        }
        last_error: LLMError | None = None
        for attempt in range(self.max_attempts):
            if attempt:
                time.sleep(2**attempt - 1)
            try:
                resp = self._session.post(
                    url, json=body, headers=headers, timeout=self.config.timeout_secs
                )
            except requests.RequestException as exc:
                last_error = LLMError(f"network error: {exc}")
                continue
            if resp.status_code in self.retry_statuses:
                last_error = LLMError(
                    f"server returned {resp.status_code}: {_error_text(resp)}",
                    resp.status_code,
                )
                continue
            if resp.status_code >= 400:
                raise LLMError(
                    f"request failed ({resp.status_code}): {_error_text(resp)}",
                    resp.status_code,
                )
            return _parse_completion(resp)
        assert last_error is not None
        raise last_error


def _error_text(resp: requests.Response) -> str:
    try:
        data = resp.json()
        err = data.get("error", data)
        if isinstance(err, dict):
            return str(err.get("message", err))
        return str(err)
    except ValueError:
        return resp.text[:300]


def _parse_completion(resp: requests.Response) -> dict[str, Any]:
    try:
        data = resp.json()
    except ValueError as exc:
        raise LLMError(f"invalid JSON from server: {exc}") from exc
    try:
        choice = data["choices"][0]
        message = choice["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"unexpected response shape: {str(data)[:300]}") from exc
    if message.get("refusal"):
        raise LLMError(f"model refused: {message['refusal']}")
    if choice.get("finish_reason") == "length":
        raise LLMError("response was cut off (token limit)")
    content = message.get("content")
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content)
    if not content:
        raise LLMError("empty response from model")
    try:
        parsed = json.loads(content)
    except ValueError as exc:
        raise LLMError(f"model returned invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise LLMError("model returned a non-object JSON value")
    return parsed


class FakeLLMClient:
    """Deterministic stand-in used when ANKIGPT_FAKE_LLM=1 or in tests.

    It derives its output from the prompt text so that dialogs and the review
    loop can be exercised end-to-end with no network access.
    """

    model = "fake"
    config = LLMConfig(api_key="fake")

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def complete_json(
        self,
        system: str,
        user: str,
        schema_name: str,
        json_schema: dict[str, Any],
    ) -> dict[str, Any]:
        self.calls.append((schema_name, system, user))
        if schema_name == "extract_concepts":
            return self._extract(user)
        if schema_name == "merge_concepts":
            return self._merge(user)
        if schema_name == "generate_question":
            return self._question(user)
        if schema_name == "grade_answer":
            return self._grade(user)
        raise LLMError(f"fake client: unknown schema {schema_name}")

    @staticmethod
    def _want(user: str, default: int) -> int:
        m = prompts.WANT_RE.search(user)
        return int(m.group(1)) if m else default

    def _extract(self, user: str) -> dict[str, Any]:
        want = self._want(user, 5)
        text = user.split(prompts.CHUNK_MARKER, 1)[-1]
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        concepts = []
        for para in paragraphs:
            words = para.split()
            if len(words) < 4:
                continue
            title = " ".join(words[:5]).strip(" .:#-")
            concepts.append(
                {
                    "title": title,
                    "summary": para[:300],
                    "key_points": [" ".join(words[:8]), " ".join(words[-8:])],
                    "source_excerpt": para[:200],
                }
            )
            if len(concepts) >= want:
                break
        return {"concepts": concepts}

    def _merge(self, user: str) -> dict[str, Any]:
        target = self._want(user, 10)
        payload = user.split(prompts.CANDIDATES_MARKER, 1)[-1].strip()
        try:
            candidates = json.loads(payload)
        except ValueError:
            candidates = []
        seen: set[str] = set()
        merged = []
        for c in candidates:
            key = c.get("title", "").strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(
                {
                    "title": c.get("title", ""),
                    "summary": c.get("summary", ""),
                    "key_points": c.get("key_points", []),
                    "sources": c.get("sources", [])[:3],
                }
            )
            if len(merged) >= target:
                break
        return {"concepts": merged}

    def _question(self, user: str) -> dict[str, Any]:
        title = _after(user, "CONCEPT TITLE:")
        mode = _after(user, "QUESTION FORMAT:")
        level = _after(user, "LEARNER MASTERY:")
        recent = user.split(prompts.RECENT_MARKER, 1)[-1]
        n = sum(1 for line in recent.splitlines() if line.startswith("- "))
        question = f"[fake #{n + 1}, {level}] Explain the concept: {title}"
        out: dict[str, Any] = {
            "question": question,
            "model_answer": f"A model answer about {title}.",
            "key_points": [f"Core idea of {title}", "A supporting detail"],
            "options": [],
            "correct_index": -1,
            "explanation": "",
        }
        if mode == "mcq":
            out["question"] = (
                f"[fake #{n + 1}, {level}] Which statement about {title} is correct?"
            )
            out["options"] = [
                f"The correct statement about {title}",
                "A plausible but wrong statement",
                "Another distractor",
                "A third distractor",
            ]
            out["correct_index"] = 0
            out["explanation"] = (
                "Option 1 restates the concept; the others contradict it."
            )
        return out

    def _grade(self, user: str) -> dict[str, Any]:
        answer = user.rsplit('"""', 2)[-2] if user.count('"""') >= 2 else ""
        if not answer.strip():
            return {
                "score": 0,
                "ease": 1,
                "feedback": "No answer.",
                "missed_points": [],
            }
        if "wrong" in answer.lower():
            return {
                "score": 20,
                "ease": 1,
                "feedback": "That contradicts the material.",
                "missed_points": ["Core idea"],
            }
        return {
            "score": 80,
            "ease": 3,
            "feedback": "Good: you covered the core idea.",
            "missed_points": ["A supporting detail"],
        }


def _after(text: str, marker: str) -> str:
    for line in text.splitlines():
        if line.startswith(marker):
            return line[len(marker) :].strip()
    return ""


def fake_mode_enabled() -> bool:
    return os.environ.get(FAKE_ENV_VAR) == "1"


def make_client(config: LLMConfig) -> LLMClient | FakeLLMClient:
    if fake_mode_enabled():
        return FakeLLMClient()
    return LLMClient(config)
