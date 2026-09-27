# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Small, offline ad filter for unprivileged website tabs only."""

import json

from aqt.qt import (
    QUrl,
    QWebEngineProfile,
    QWebEngineScript,
    QWebEngineUrlRequestInfo,
    QWebEngineUrlRequestInterceptor,
)

# Deliberately limited to advertising infrastructure, not shared CDNs or
# analytics hosts. Match DNS boundaries, never substrings in paths or queries.
AD_HOSTS = frozenset(
    {
        "doubleclick.net",
        "googlesyndication.com",
        "googleadservices.com",
        "googletagservices.com",
        "adnxs.com",
        "adsrvr.org",
        "amazon-adsystem.com",
        "criteo.com",
        "criteo.net",
        "pubmatic.com",
        "rubiconproject.com",
        "openx.net",
        "casalemedia.com",
        "taboola.com",
        "outbrain.com",
    }
)

# Explicit ad markers only: do not hide generic dialogs, sticky navigation,
# video players, or elements merely containing the letters "ad".
AD_SELECTORS = """
ins.adsbygoogle, .google-auto-placed, .adsbygoogle,
[id^="google_ads_iframe"], [id^="div-gpt-ad"],
iframe[id^="aswift_"], iframe[id^="ad_iframe"],
.ad-banner, .ad-container, .ad-overlay, .ad-slot,
#ad-banner, #ad-overlay, #ad-container
""".strip()


def site_host(url: QUrl) -> str:
    return url.host().lower().rstrip(".") if url.scheme() in {"http", "https"} else ""


class AdFilter(QWebEngineUrlRequestInterceptor):
    def __init__(self, profile: QWebEngineProfile, saved: object = None) -> None:
        super().__init__(profile)
        self.profile = profile
        self.allowed = frozenset(
            host
            for host in (saved if isinstance(saved, list) else [])
            if isinstance(host, str)
            and host
            and site_host(QUrl("https://" + host)) == host
        )
        self.script: QWebEngineScript | None = None
        profile.setUrlRequestInterceptor(self)
        self.update_script()

    def interceptRequest(self, info: QWebEngineUrlRequestInfo) -> None:
        if (
            info.resourceType()
            == QWebEngineUrlRequestInfo.ResourceType.ResourceTypeMainFrame
            or site_host(info.firstPartyUrl()) in self.allowed
        ):
            return
        host = site_host(info.requestUrl())
        if any(host == domain or host.endswith("." + domain) for domain in AD_HOSTS):
            info.block(True)

    def allow_site(self, host: str, allow: bool) -> None:
        # Replace the immutable snapshot read by the request interceptor.
        self.allowed = self.allowed | {host} if allow else self.allowed - {host}
        self.update_script()

    def update_script(self) -> None:
        if self.script is not None:
            self.profile.scripts().remove(self.script)
        script = QWebEngineScript()
        script.setName("AnkiGPT ad filtering")
        script.setWorldId(QWebEngineScript.ScriptWorldId.ApplicationWorld)
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
        script.setRunsOnSubFrames(False)
        script.setSourceCode(
            "(() => {"
            "if (!['http:', 'https:'].includes(location.protocol)) return;"
            f"const allowed = {json.dumps(sorted(self.allowed))};"
            "if (allowed.includes(location.hostname.toLowerCase().replace(/\\.$/, ''))) return;"
            "const style = document.createElement('style');"
            f"style.textContent = {json.dumps(AD_SELECTORS + ' {display:none!important;}')};"
            "(document.head || document.documentElement).appendChild(style);"
            "})();"
        )
        self.profile.scripts().insert(script)
        self.script = script
