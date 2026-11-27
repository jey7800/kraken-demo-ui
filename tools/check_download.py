"""Why does a file download return an HTML page? Fetch one file three ways and show what came back.

    python tools/check_download.py [url ...]

1. as the demo does (environment proxy only, like Retrievr's own client);
2. with the Windows system proxy settings too (what browsers and urllib use);
3. with no proxy at all.

Prints statuses, redirects, content type, the first bytes and, for an HTML page, its title
and a short extract. Never prints proxy credentials, cookies or headers.
"""

from __future__ import annotations

import re
import ssl
import sys
import urllib.request
from html import unescape
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
import truststore  # noqa: E402
from retrievr.config import FetchSettings  # noqa: E402

from kdemo.observe import NetworkTransport  # noqa: E402

DEFAULT_URLS = [
    "https://www.societegenerale.com/sites/default/files/resultats_publication/fr/2024-08/t2-2024-Etats-financiers_FR.pdf",
    "https://investor-relations.db.com/files/documents/quarterly-results/2024/Transcript-Analyst-Call-25-April-2024.pdf",
]
MARKERS = ("zscaler", "netskope", "bluecoat", "symantec", "forcepoint", "mcafee", "websense", "proxy",
           "incapsula", "imperva", "_incapsula_resource", "captcha", "blocked", "access denied",
           "authentication", "sign in", "login", "caution", "warning", "policy", "forbidden")


def show_proxy(label: str, proxies: dict[str, str]) -> None:
    def safe(url: str) -> str:
        parts = urlsplit(url if "://" in url else "http://" + url)
        creds = " (with credentials)" if parts.username else ""
        return f"{parts.scheme}://{parts.hostname}:{parts.port or ''}{creds}"

    shown = {k: safe(v) for k, v in proxies.items() if k in ("http", "https", "all")}
    print(f"  {label}: {shown or 'none'}")


def describe(resp: httpx.Response) -> None:
    for r in [*resp.history, resp]:
        print(f"  HTTP {r.status_code}  {r.url.host}{r.url.path[:70]}")
    ctype = resp.headers.get("content-type", "?")
    head = resp.content[:8]
    print(f"  content-type: {ctype}, {len(resp.content)} bytes, starts with {head!r}")
    if resp.content.startswith(b"%PDF"):
        print("  -> a real PDF")
        return
    text = resp.text
    title = re.search(r"<title[^>]*>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
    print(f"  -> NOT a PDF. Page title: {unescape(title.group(1)).strip()[:120] if title else '(none)'}")
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    body = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", body))).strip()
    print(f"  text: {body[:300]}")
    found = sorted({m for m in MARKERS if m in text.lower()})
    print(f"  words seen: {', '.join(found) or 'none of the usual proxy/firewall words'}")


def fetch(label: str, url: str, transport: httpx.BaseTransport | None, *, trust_env: bool) -> None:
    print(f"\n[{label}]")
    ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    headers = {"User-Agent": FetchSettings().user_agent}
    try:
        with httpx.Client(transport=transport, verify=ctx, trust_env=trust_env, headers=headers,
                          follow_redirects=True, timeout=30) as client:
            describe(client.get(url))
    except httpx.HTTPError as exc:
        print(f"  failed: {type(exc).__name__}: {str(exc)[:200]}")


class SystemProxyTransport(httpx.BaseTransport):
    """Proxy from the Windows settings (registry) as well as the environment."""

    def __init__(self) -> None:
        self._ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self._proxies = urllib.request.getproxies()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        proxy = self._proxies.get(request.url.scheme)
        if proxy and urllib.request.proxy_bypass(request.url.host):
            proxy = None
        with httpx.HTTPTransport(verify=self._ctx, proxy=proxy) as t:
            resp = t.handle_request(request)
            resp.read()
            return resp


def main() -> int:
    urls = sys.argv[1:] or DEFAULT_URLS
    print("Proxy settings seen by Python:")
    show_proxy("environment (HTTP(S)_PROXY)", urllib.request.getproxies_environment())
    show_proxy("environment + Windows settings", urllib.request.getproxies())
    for url in urls:
        print(f"\n=== {urlsplit(url).netloc}{urlsplit(url).path[-60:]}")
        fetch("1. as the demo does", url, NetworkTransport(), trust_env=False)
        fetch("2. with Windows proxy settings", url, SystemProxyTransport(), trust_env=False)
        fetch("3. no proxy", url, httpx.HTTPTransport(verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)),
              trust_env=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
