# Kraken 2.0 kick-off demo

A local web page that shows Kraken 2.0 at work: a live diagram of each run (the AI lights
up only when it is called), a table filled from an Excel file, an enriched Excel export,
and a second page that replays a real self-repair.

Private project. Not part of Retrievr and never published with it.

## Run it

Use the Python environment where Retrievr is installed (on the work PC, the Kraken 2.0
environment). No other dependency: the server, the page and the Excel reader/writer use
the standard library only.

```
python demo.py                # opens Edge in app mode on http://127.0.0.1:8765
python demo.py --no-browser   # server only
```

Settings are in `demo.toml` (copy `demo.example.toml`). Press F11 in Edge for full screen.

## Using it

- Drop the parameters file on the table (Excel or CSV). Columns: name, url, access
  (private/public), years, documents (the request in plain words), force learning
  (yes/no), and optionally site id (the Retrievr site key, a slug of the name otherwise).
  `examples/kickoff_parameters.xlsx` is the kick-off file.
- **Run all**, or **Run** / **Re-learn** on a row. Re-learn makes the AI learn the site
  again from scratch (real AI calls, never the response cache).
- **Export enriched Excel** downloads the file with the result columns and a summary sheet.
- **Live / Recorded run**: every live run is recorded in `films/`. In "Recorded run" mode,
  Run plays the last recording of the row: no network, no AI, speed adjustable. This is
  the fallback if the network or a site fails during the demo.

Presenter keys: Space pause, + and − speed, F live/recorded, 1 and 2 pages, ? help,
Enter on page 2 starts the change.

## Page 2

`films/stories.json` holds real repairs recorded from Retrievr's mutation tests (a site's
saved pages, broken the way sites change, repaired by Retrievr with the AI answers of the
test cache). Rebuild it from a Retrievr checkout:

```
uv run --project <Retrievr> python tools/record_stories.py <Retrievr>
```

The "new site" tile uses the most recent recorded learning (Crédit Agricole first).

## Private portals

The demo never signs in. A private row runs through an adapter given by the host
application (`adapter = "module:factory"` in `demo.toml`, shape in `adapter_example.py`):
it opens the vault once at start (hidden prompt), signs in when the row runs and hands
Retrievr a `HostSession`. It can also give the transport to the company AI endpoint.

## Costs shown

Every AI cost on screen is computed from the real token counts with the fixed prices of
`demo.toml` (`[cost]`), so the figures are the same on every machine.

## Layout

```
demo.py              entry point
kdemo/server.py      HTTP server, JSON API, Server-Sent Events, job runner
kdemo/driver.py      one Retrievr run per row, turned into diagram steps
kdemo/observe.py     transports and log tap that watch a run from outside
kdemo/films.py       recording and playback of runs
kdemo/sheet.py       parameters file and enriched export
kdemo/xlsx.py        minimal .xlsx reader/writer (standard library)
static/              the page (no build step, no CDN)
tools/               example file, recipe install, page-2 recording
```
