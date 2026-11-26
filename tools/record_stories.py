"""Record the page-2 stories from Retrievr's mutation tests: real repairs, replayed offline.

    uv run --project <Retrievr checkout> python tools/record_stories.py <Retrievr checkout>

Each story runs a site's snapshot healthy, then broken by a mutation (the site "changed"),
and lets Retrievr detect and repair it, with the AI answers recorded in Retrievr's test
cache (no network, no cost). What happened is written to films/stories.json.
"""

from __future__ import annotations

import json
import logging
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

STORIES = [
    # (story id, site, mutation name, label for the page)
    ("rebuilt", "societegenerale", "json_list", "The page was rebuilt: the list now loads from a hidden data feed"),
    ("renamed", "creditagricole", "rename_classes", "The page was restyled: its building blocks were renamed"),
]
ISSUERS = {"societegenerale": "Société Générale", "creditagricole": "Crédit Agricole"}


def record(retrievr_repo: Path) -> dict[str, Any]:
    sys.path.insert(0, str(retrievr_repo))
    import httpx
    import respx
    from retrievr import Retrievr
    from retrievr.events import Event
    from retrievr.snapshots import ReplayTransport, load_index
    from tests.mutations.harness import ApiDiscovery, MutatedSite, mutations_for
    from tests.mutations.test_mutations import FIXTURES, RECIPES, SITES, YEARS, _settings

    from kdemo.config import DemoConfig
    from kdemo.driver import CHECKS
    from kdemo.observe import AICall, AICallTap

    prices = DemoConfig.load(ROOT / "demo.toml" if (ROOT / "demo.toml").is_file() else None).prices
    out: dict[str, Any] = {"stories": []}
    for story_id, site, mutation_name, label in STORIES:
        recipe_file = SITES[site]
        from retrievr.recipe import load_recipe

        recipe0 = load_recipe(RECIPES / recipe_file)
        mutation = next(m for m in mutations_for(recipe0) if m.name == mutation_name)
        snapshot = FIXTURES / site
        today = load_index(snapshot).captured_on().date()
        replay = ReplayTransport(snapshot, lenient_bodies=True)
        state = Path(tempfile.mkdtemp(prefix=f"story-{site}-"))
        with respx.mock(assert_all_called=False):
            healthy_r = Retrievr(settings=_settings(state), fetch_transport=replay,
                                 sleep=lambda _s: None, today=today)
            recipe = healthy_r.install(RECIPES / recipe_file, site=site)
            healthy = healthy_r.run(site, years=YEARS, download=False)
            mutated = MutatedSite(replay, recipe, mutation, today)
            events: list[Event] = []
            calls: list[AICall] = []
            pages = {"n": 0}

            class Counting(httpx.BaseTransport):
                def __init__(self, inner: httpx.BaseTransport) -> None:
                    self.inner = inner

                def handle_request(self, request: httpx.Request) -> httpx.Response:
                    if not request.url.path.endswith("/robots.txt"):
                        pages["n"] += 1
                    return self.inner.handle_request(request)

            broken_r = Retrievr(
                settings=_settings(state), fetch_transport=Counting(mutated.transport()),
                discoverer=ApiDiscovery(mutated), on_event=events.append,
                sleep=lambda _s: None, today=today,
            )
            with AICallTap(calls.append):
                outcome = broken_r.run(site, years=YEARS, download=False)
        repair = outcome.repair
        checks = {c.name: c for c in (repair.validation.checks if repair and repair.validation else [])}
        tokens_in = sum(c.input_tokens for c in calls)
        tokens_out = sum(c.output_tokens for c in calls)
        latency = sum(_latency(retrievr_repo, c) for c in calls)
        health = outcome.health
        docs_before = len(healthy.all_documents)
        docs_after = len(outcome.all_documents)
        titles = [d.title or d.link_text or "" for d in healthy.all_documents if (d.title or d.link_text)][:9]
        story = {
            "id": story_id,
            "issuer": ISSUERS[site],
            "label": label,
            "mutation": mutation_name,
            "status": outcome.status,
            "repaired": bool(repair and repair.status == "repaired"),
            "rungs": [{"rung": a.rung, "passed": a.passed} for a in (repair.attempts if repair else [])],
            "documents_before": docs_before,
            "documents_after": docs_after,
            "health": {"verdict": health.verdict if health else None,
                       "missing": len(health.missing) if health else 0,
                       "summary": health.summary() if health else ""},
            "ai_calls": len([c for c in calls if c.step.startswith("repair")]),
            "input_tokens": tokens_in,
            "output_tokens": tokens_out,
            "cost": round(prices.cost(tokens_in, tokens_out), 6),
            "ai_seconds": round(latency, 1),
            "pages": pages["n"],
            "estimated_seconds": round(latency + pages["n"] * 1.0),
            "recipe_before": recipe.key,
            "recipe_after": outcome.recipe,
            "checks": [
                {"name": n, "label": lbl, "passed": checks[n].passed if n in checks else None,
                 "detail": checks[n].detail if n in checks else ""}
                for n, lbl in CHECKS
            ],
            "titles": titles,
            "events": [e.kind for e in events],
        }
        out["stories"].append(story)
        logging.info("%s: %s, %d -> %d documents, %d AI calls", story_id, outcome.status, docs_before, docs_after, story["ai_calls"])
    return out


def _latency(repo: Path, call: Any) -> float:
    """The AI call's real latency when it was recorded (kept in Retrievr's test cache)."""
    for path in (repo / "tests" / "fixtures" / "llm_cache").rglob("*.json"):
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        usage = entry.get("usage", {})
        if (entry.get("step") == call.step and usage.get("input_tokens") == call.input_tokens
                and usage.get("output_tokens") == call.output_tokens):
            return float(entry.get("latency_s", 0.0))
    return 0.0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("retrievr").setLevel(logging.WARNING)
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    data = record(Path(sys.argv[1]).resolve())
    path = ROOT / "films" / "stories.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
