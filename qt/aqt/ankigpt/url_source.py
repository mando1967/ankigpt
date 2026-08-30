# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Download a web page or supported remote document as a local study source."""

from __future__ import annotations

import ipaddress
import os
import socket
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024
_PDF_FALLBACK = (
    "The website appears to be blocking automated access. Open the page in your "
    "browser, print it to a PDF, then add that PDF as study material."
)
_BOT_BLOCK_MARKERS = (
    "verify you are human",
    "checking your browser",
    "access denied",
    "unusual traffic",
    "enable javascript and cookies",
    "cloudflare ray id",
    "complete the captcha",
    "are you a robot",
    "not a bot",
    "making sure you're not",
    "making sure you’re not",
    "automated access",
)
_SUPPORTED_SUFFIXES = {".pdf", ".docx", ".txt", ".md"}
_CONTENT_SUFFIXES = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "text/markdown": ".md",
    "text/plain": ".txt",
}


class UrlSourceError(Exception):
    pass


@dataclass(frozen=True)
class DownloadedSource:
    path: str
    url: str
    name: str


def _validate_public_url(url: str) -> str:
    parsed = urlsplit(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UrlSourceError("Enter a valid HTTP or HTTPS URL.")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, None)}
    except OSError as exc:
        raise UrlSourceError("The website address could not be resolved.") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise UrlSourceError("Local and private network addresses are not allowed.")
    return parsed.geturl()


def _filename(url: str, content_type: str) -> tuple[str, str]:
    raw_name = unquote(Path(urlsplit(url).path).name) or "web-page"
    suffix = Path(raw_name).suffix.lower()
    if suffix not in _SUPPORTED_SUFFIXES:
        suffix = _CONTENT_SUFFIXES.get(content_type, ".txt")
    name = (
        raw_name if Path(raw_name).suffix.lower() == suffix else f"{raw_name}{suffix}"
    )
    return name, suffix


def _looks_like_bot_block(text: str, title: str = "") -> bool:
    combined = f"{title}\n{text}".casefold()
    return len(combined) < 10_000 and any(
        marker in combined for marker in _BOT_BLOCK_MARKERS
    )


def download_url_source(url: str) -> DownloadedSource:
    """Fetch *url*, validating every redirect and limiting response size."""
    current = _validate_public_url(url)
    response: requests.Response | None = None
    for _ in range(6):
        response = requests.get(
            current,
            allow_redirects=False,
            stream=True,
            timeout=(10, 30),
            headers={"User-Agent": "AnkiGPT/1.0 (study document importer)"},
        )
        if response.is_redirect or response.is_permanent_redirect:
            location = response.headers.get("location")
            response.close()
            if not location:
                raise UrlSourceError("The website returned an invalid redirect.")
            current = _validate_public_url(urljoin(current, location))
            continue
        break
    else:
        raise UrlSourceError("The website redirected too many times.")

    assert response is not None
    try:
        response.raise_for_status()
        declared = int(response.headers.get("content-length", "0") or 0)
        if declared > MAX_DOWNLOAD_BYTES:
            raise UrlSourceError("The document is larger than 25 MB.")
        body = bytearray()
        for chunk in response.iter_content(64 * 1024):
            body.extend(chunk)
            if len(body) > MAX_DOWNLOAD_BYTES:
                raise UrlSourceError("The document is larger than 25 MB.")
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
    except requests.HTTPError as exc:
        if response.status_code in {401, 403, 429}:
            raise UrlSourceError(_PDF_FALLBACK) from exc
        raise UrlSourceError(f"The document could not be downloaded: {exc}") from exc
    except requests.RequestException as exc:
        raise UrlSourceError(f"The document could not be downloaded: {exc}") from exc
    finally:
        response.close()

    name, suffix = _filename(current, content_type)
    data = bytes(body)
    if content_type in {"text/html", "application/xhtml+xml"} or (
        suffix == ".txt" and data.lstrip().lower().startswith(b"<!doctype html")
    ):
        soup = BeautifulSoup(data, "html.parser")
        for element in soup(["script", "style", "noscript", "template"]):
            element.decompose()
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        text = soup.get_text("\n", strip=True)
        if not text:
            raise UrlSourceError("No readable text was found on that web page.")
        if _looks_like_bot_block(text, title):
            raise UrlSourceError(_PDF_FALLBACK)
        data = text.encode("utf-8")
        suffix = ".txt"
        name = f"{title or urlsplit(current).hostname or 'web-page'}.txt"

    handle = tempfile.NamedTemporaryFile(
        prefix="ankigpt-url-", suffix=suffix, delete=False
    )
    try:
        handle.write(data)
    finally:
        handle.close()
    return DownloadedSource(os.path.abspath(handle.name), current, name)
