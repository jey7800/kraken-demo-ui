"""The private-portal adapter: how the demo gets a logged-in session from the host app.

The demo never logs in itself. On the work PC, Kraken 2.0 provides an adapter (see
``adapter_example.py``): it opens the vault once at start, signs in to a portal when a
private row runs, and hands Retrievr a ``HostSession``. Configure it in ``demo.toml`` as
``adapter = "module:factory"``; the factory is called once, with no argument.
"""

from __future__ import annotations

import importlib
from typing import Protocol, runtime_checkable

import httpx
from retrievr.fetch import HostSession

from kdemo.sheet import SiteRow


@runtime_checkable
class PortalAdapter(Protocol):
    def open_session(self, row: SiteRow) -> HostSession:
        """Sign in to the portal of ``row`` and return the session (raise with a short,
        secret-free message when it fails)."""
        ...

    def close_session(self, session: HostSession) -> None:
        """Release what ``open_session`` opened (browser, transport)."""
        ...

    def llm_transport(self) -> httpx.BaseTransport | None:
        """A new transport to the AI endpoint for one run of a public site (SecureGPT), or
        None for the endpoint configured in Retrievr's settings. Private rows never use
        the AI."""
        ...

    # Optional: ``retrievr_dirs(row) -> (state_dir, output_dir)`` for a private row, so
    # that it runs on the host's own Retrievr state (where its recipe is installed) and
    # files its downloads where the host's filing step reads them.


class AdapterError(RuntimeError):
    pass


def load_adapter(spec: str) -> PortalAdapter | None:
    """``"package.module:factory"`` -> the adapter it creates; ``""`` -> None."""
    if not spec.strip():
        return None
    module_name, _, attr = spec.partition(":")
    if not attr:
        raise AdapterError(f"adapter {spec!r}: expected 'module:factory'")
    module = importlib.import_module(module_name)
    factory = getattr(module, attr, None)
    if factory is None:
        raise AdapterError(f"adapter {spec!r}: {attr} not found in {module_name}")
    adapter = factory()
    missing = [m for m in ("open_session", "close_session", "llm_transport") if not hasattr(adapter, m)]
    if missing:
        raise AdapterError(f"adapter {spec!r} lacks: {', '.join(missing)}")
    return adapter  # type: ignore[no-any-return]
