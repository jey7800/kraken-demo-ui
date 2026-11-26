"""Install a hand-written recipe into the demo's state under a site id.

    python tools/install_recipe.py <recipe.yaml> <site-id> [--config demo.toml]

The site id is the one the parameters file gives the row (a slug of its name, e.g.
"societe-generale", unless the file has a "site id" column).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from retrievr import Retrievr  # noqa: E402

from kdemo.config import DemoConfig  # noqa: E402
from kdemo.driver import SiteRunner  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("recipe", type=Path)
    parser.add_argument("site")
    parser.add_argument("--config", type=Path, default=ROOT / "demo.toml")
    args = parser.parse_args()
    cfg = DemoConfig.load(args.config if args.config.is_file() else None)
    settings = SiteRunner(cfg, lambda _e: None).settings(fresh_ai=False)
    recipe = Retrievr(settings=settings).install(args.recipe, site=args.site)
    print(f"installed {recipe.key} as {args.site} in {settings.state.state_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
