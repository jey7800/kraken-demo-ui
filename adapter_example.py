"""Shape of the private-portal adapter (the real one lives in Kraken 2.0).

demo.toml:  adapter = "kraken.demo_adapter:create"

The factory runs once when the demo starts, in its terminal: that is where the vault
password is asked, hidden (getpass), and kept in memory only. It is never a command-line
argument (shell history, process list), never logged, never sent to the page.
"""

from __future__ import annotations

import getpass
import os
from pathlib import Path

import httpx
from retrievr.fetch import HostSession


class ExampleAdapter:
    def __init__(self) -> None:
        self.user = os.environ.get("KRAKEN_DEMO_USER") or input("Portal user: ")
        self._vault_password = getpass.getpass("Vault password (hidden): ")

    def open_session(self, row: object) -> HostSession:
        """Sign in to the portal of ``row`` (its ``id`` and ``name`` say which one) with
        the host's own login code, and return the session it would give Retrievr."""
        raise NotImplementedError("the host application implements the sign-in")

    def close_session(self, session: HostSession) -> None:
        session.transport.close()

    def llm_transport(self) -> httpx.BaseTransport | None:
        """A new transport to the company AI endpoint for one run of a public site, or None."""
        return None

    def retrievr_dirs(self, row: object) -> tuple[Path, Path]:
        """The host's Retrievr state and download folders for a private row."""
        return Path(".retrievr"), Path("downloads")


def create() -> ExampleAdapter:
    return ExampleAdapter()
