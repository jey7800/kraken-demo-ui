"""Watching a Retrievr run from outside: transports that report requests, and a log tap
for the AI calls. Nothing here changes what Retrievr does."""

from __future__ import annotations

import logging
import ssl
import threading
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

import httpx
import truststore


class ObservingTransport(httpx.BaseTransport):
    """Calls ``before`` with each request, then sends it through ``inner``."""

    def __init__(
        self,
        inner: httpx.BaseTransport,
        before: Callable[[httpx.Request], None],
        *,
        owns_inner: bool = True,
    ) -> None:
        self._inner = inner
        self._before = before
        self._owns = owns_inner

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        try:
            self._before(request)
        except Exception:  # an observer must never break the run
            logging.getLogger(__name__).exception("observer failed")
        return self._inner.handle_request(request)

    def close(self) -> None:
        if self._owns:
            self._inner.close()


class NetworkTransport(httpx.BaseTransport):
    """The real network, as Retrievr's own client would reach it: the OS trust store and
    the proxy from the environment (HTTP(S)_PROXY, NO_PROXY). Needed because a custom
    transport makes httpx ignore environment proxies."""

    def __init__(self) -> None:
        self._ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self._proxies = urllib.request.getproxies_environment()
        self._by_proxy: dict[str | None, httpx.HTTPTransport] = {}
        self._lock = threading.Lock()

    def _for(self, url: httpx.URL) -> httpx.HTTPTransport:
        proxy = self._proxies.get(url.scheme) or self._proxies.get("all")
        if proxy and urllib.request.proxy_bypass_environment(url.host, self._proxies):
            proxy = None
        with self._lock:
            if proxy not in self._by_proxy:
                self._by_proxy[proxy] = httpx.HTTPTransport(verify=self._ctx, proxy=proxy)
            return self._by_proxy[proxy]

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return self._for(request.url).handle_request(request)

    def close(self) -> None:
        for t in self._by_proxy.values():
            t.close()


@dataclass(frozen=True)
class AICall:
    step: str
    """Retrievr's step name: structure, rules, label, filter, repair:..."""
    model: str
    cached: bool
    input_tokens: int
    output_tokens: int


class AICallTap(logging.Handler):
    """Reads the one log line Retrievr writes per AI call (step, model, cached, tokens)."""

    LOGGER = "retrievr.llm"

    def __init__(self, on_call: Callable[[AICall], None]) -> None:
        super().__init__(level=logging.INFO)
        self._on_call = on_call
        self._logger = logging.getLogger(self.LOGGER)
        self._old_level = self._logger.level

    def __enter__(self) -> AICallTap:
        self._logger.addHandler(self)
        if self._logger.getEffectiveLevel() > logging.INFO:
            self._logger.setLevel(logging.INFO)
        return self

    def __exit__(self, *_exc: object) -> None:
        self._logger.removeHandler(self)
        self._logger.setLevel(self._old_level)

    def emit(self, record: logging.LogRecord) -> None:
        if not str(record.msg).startswith("llm %s model=%s cached=%s tokens"):
            return
        try:
            step, model, cached, tin, tout, _cost = record.args  # type: ignore[misc]
            self._on_call(AICall(str(step), str(model), bool(cached), int(tin), int(tout)))
        except Exception:
            logging.getLogger(__name__).exception("cannot read AI call record")
