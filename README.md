# Kraken 2.0 kick-off demo

A local web page that shows Kraken 2.0 at work: a live diagram of each run (the AI lights
up only when it is called), a table filled from an Excel file, an enriched Excel export,
a document library where SecureGPT summarises any filed document and answers questions
about it, and a third page that replays a real self-repair.

Private project. Not part of Retrievr and never published with it.

## Run it

Use the Python environment where Retrievr is installed (on the work PC, the Kraken 2.0
environment). No other dependency except `pypdf` (already installed with Retrievr in the
Kraken 2.0 environment) to read PDFs in the library: the server, the page and the Excel
reader/writer use the standard library only.

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
- **Found** is the number of documents matching the request; **Filed** the number of
  files on disk after the run. With `redownload = true` (default), a live run of a public
  site first deletes the files it filed earlier in the demo's output folder, so they are
  downloaded and shown again every time. Private rows never are.
- **Export enriched Excel** downloads the file with the result columns and a summary sheet.
- **Live / Recorded run**: every live run is recorded in `films/`. In "Recorded run" mode,
  Run plays the last recording of the row: no network, no AI, speed adjustable. This is
  the fallback if the network or a site fails during the demo.

Presenter keys: Space pause, + and − speed, F live/recorded, 1 2 3 pages, ? help,
Enter on page 3 starts the change. In the library: / search, ↑ ↓ previous or next
document, Enter to ask, Esc closes the document.

## Page 2: document library

Every file Kraken filed (the demo's `downloads/`, plus the host's folder for a private row),
by issuer then year, updated live after each run (new files glow). Selecting a document
shows:

- **The SecureGPT summary**: headline, key figures with their change and page, key points,
  three suggested questions. Made once per document (by content) and kept in
  `data/library/summaries/`: instant the next time, with the first reading's cost shown.
- **A chat about that document only** (no retrieval: its text is in the prompt, cut at
  `max_chars`). Answers stream, cite pages as chips that open the PDF at that page, and
  come in the language of the question. Each answer is kept in `data/library/answers/`.
- **Its metadata**: type, period, language, size, pages, source, collection date, recipe,
  fingerprint and how Kraken sorted it.

PDF and Excel (.xlsx) files are read (texts extracted once in a worker process with
`pypdf`, cached in `data/library/text/`); .xlsb and .zip are listed only. Private-portal
documents are listed masked: no AI, no preview.

**Recorded mode** replays kept summaries and answers with no network (an answer is found by
its question, whatever the conversation). If the AI is unreachable in Live mode, a kept
answer to the same question is replayed instead. Prepare the library before a demo:

```
python tools/warm_library.py              # texts and summaries of every document
python tools/warm_library.py --answers    # plus the answers to the suggested questions
```

Settings in `demo.toml`, `[library]`: `model` (default: Retrievr's `model_small`),
`max_chars`, `warm` (extract texts in the background at start), `reasoning_effort` (sent
with chat questions for ~1 s answers; dropped by itself if the endpoint refuses it).

## Page 3

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
kdemo/library.py     document library: index from the manifests, text extraction
kdemo/ai.py          summaries and document chat on the OpenAI-compatible endpoint
static/              the page (no build step, no CDN)
tools/               example file, recipe install, page-3 recording, library warm-up
```
