"""Demo settings (``demo.toml``), with paths relative to that file."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Prices:
    """Fixed, realistic token prices used for every cost shown (EUR per million tokens)."""

    input_per_million: float = 0.10
    output_per_million: float = 0.40

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self.input_per_million + output_tokens * self.output_per_million) / 1e6


@dataclass
class DemoConfig:
    root: Path
    """Folder of demo.toml: relative paths start here."""
    retrievr_config: Path | None = None
    """Retrievr's own TOML (state dir, output dir, LLM endpoint). None: Retrievr defaults."""
    state_dir: Path | None = None
    output_dir: Path | None = None
    """Override Retrievr's state and output folders (keeps the demo apart from other runs)."""
    env_file: Path | None = None
    """KEY=VALUE lines loaded into the environment at start (the LLM key); never shown."""
    data_dir: Path = Path("data")
    films_dir: Path = Path("films")
    host: str = "127.0.0.1"
    port: int = 8765
    open_browser: bool = True
    fresh_ai_on_learn: bool = True
    """Learning calls the AI for real instead of reusing cached answers."""
    redownload: bool = True
    """Before a live run of a public site, delete the files it filed earlier in the demo's
    output folder, so every run downloads (and shows) them again. Never for private rows."""
    adapter: str = ""
    """``module:factory`` creating the private-portal adapter (Kraken 2.0). Empty: none."""
    ai_name: str = "SecureGPT"
    prices: Prices = field(default_factory=Prices)
    film_max_gap_s: float = 1.5
    """Longest pause kept between two events when a recorded run is played."""

    @classmethod
    def load(cls, path: Path | None) -> DemoConfig:
        if path is None:
            return cls(root=Path.cwd()).resolved()
        with path.open("rb") as fh:
            raw: dict[str, Any] = tomllib.load(fh)
        cfg = cls(root=path.resolve().parent)
        for key in ("retrievr_config", "state_dir", "output_dir", "env_file", "data_dir", "films_dir"):
            if raw.get(key):
                setattr(cfg, key, Path(raw[key]))
        for key in ("host", "adapter", "ai_name"):
            if key in raw:
                setattr(cfg, key, str(raw[key]))
        for key in ("port",):
            if key in raw:
                setattr(cfg, key, int(raw[key]))
        for key in ("open_browser", "fresh_ai_on_learn", "redownload"):
            if key in raw:
                setattr(cfg, key, bool(raw[key]))
        if "film_max_gap_s" in raw:
            cfg.film_max_gap_s = float(raw["film_max_gap_s"])
        cost = raw.get("cost", {})
        cfg.prices = Prices(
            float(cost.get("input_per_million", Prices.input_per_million)),
            float(cost.get("output_per_million", Prices.output_per_million)),
        )
        return cfg.resolved()

    def resolved(self) -> DemoConfig:
        def fix(p: Path | None) -> Path | None:
            return None if p is None else (p if p.is_absolute() else self.root / p)

        self.retrievr_config = fix(self.retrievr_config)
        self.state_dir = fix(self.state_dir)
        self.output_dir = fix(self.output_dir)
        self.env_file = fix(self.env_file)
        self.data_dir = fix(self.data_dir) or self.root / "data"
        self.films_dir = fix(self.films_dir) or self.root / "films"
        return self


def load_env_file(path: Path | None) -> list[str]:
    """Load ``KEY=VALUE`` lines into the environment (existing values win). Returns the
    names loaded, never the values."""
    if path is None or not path.is_file():
        return []
    names = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value
            names.append(key)
    return names
