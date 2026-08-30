from __future__ import annotations

import os
from unittest.mock import Mock

import pytest

from aqt.ankigpt import url_source


def test_rejects_non_web_and_private_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(url_source.UrlSourceError, match="HTTP or HTTPS"):
        url_source._validate_public_url("file:///etc/passwd")

    monkeypatch.setattr(
        url_source.socket,
        "getaddrinfo",
        lambda *_args: [(None, None, None, None, ("127.0.0.1", 0))],
    )
    with pytest.raises(url_source.UrlSourceError, match="private network"):
        url_source._validate_public_url("http://localhost/notes")


def test_downloads_html_as_readable_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(url_source, "_validate_public_url", lambda value: value)
    response = Mock()
    response.is_redirect = response.is_permanent_redirect = False
    response.headers = {"content-type": "text/html; charset=utf-8"}
    response.iter_content.return_value = [
        b"<html><head><title>Cell Biology</title><script>bad()</script></head>"
        b"<body><h1>Mitosis</h1><p>Cells divide.</p></body></html>"
    ]
    monkeypatch.setattr(url_source.requests, "get", lambda *_args, **_kwargs: response)

    source = url_source.download_url_source("https://example.com/lesson")
    try:
        assert source.name == "Cell Biology.txt"
        assert source.url == "https://example.com/lesson"
        with open(source.path, encoding="utf-8") as handle:
            text = handle.read()
        assert "Mitosis" in text
        assert "Cells divide." in text
        assert "bad()" not in text
    finally:
        os.unlink(source.path)


def test_rejects_oversized_declared_download(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(url_source, "_validate_public_url", lambda value: value)
    response = Mock()
    response.is_redirect = response.is_permanent_redirect = False
    response.headers = {
        "content-type": "application/pdf",
        "content-length": str(url_source.MAX_DOWNLOAD_BYTES + 1),
    }
    monkeypatch.setattr(url_source.requests, "get", lambda *_args, **_kwargs: response)

    with pytest.raises(url_source.UrlSourceError, match="larger than 25 MB"):
        url_source.download_url_source("https://example.com/book.pdf")


def test_bot_challenge_suggests_printing_to_pdf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(url_source, "_validate_public_url", lambda value: value)
    response = Mock()
    response.is_redirect = response.is_permanent_redirect = False
    response.headers = {"content-type": "text/html"}
    response.iter_content.return_value = [
        b"<html><title>Making sure you're not a bot!</title>"
        b"<body>Please wait while we verify your browser.</body></html>"
    ]
    monkeypatch.setattr(url_source.requests, "get", lambda *_args, **_kwargs: response)

    with pytest.raises(url_source.UrlSourceError, match="print it to a PDF"):
        url_source.download_url_source("https://example.com/protected")
