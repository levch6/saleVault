# saleVault

A local tool that collects the sale sections of fashion shops and shows every item **sorted by discount, biggest first**, something the shops themselves do not offer.

Shops: **PRM.com** (UA) and **Answear.ua**.

- Catalog sorted by discount, or by the "honest" discount (against the lowest price of the last 30 days), savings, price or newest
- Filters with live counts: shop, gender (with unisex), category tree, brand, size in stock, price, minimum discount, text search
- **Only my sizes**: save your sizes once, see only items you can actually buy
- **New** and **cheaper** badges since the previous run; price history chart per item
- Favorites that show how the price moved since you starred an item
- Runs from the UI (with progress and cancel) or the terminal; interrupted runs can be resumed

Personal, local use only. Nothing is hosted; data stays in `data/`.

## Requirements

- Linux or WSL2 (built on Ubuntu under Windows 11; WSLg shows the browser window when a run needs one)
- [uv](https://docs.astral.sh/uv/), Node.js 26 (`.node-version`) with [pnpm](https://pnpm.io/) 12, [just](https://just.systems/)

Python 3.15, the Playwright Chromium build and all packages are installed by `just setup`.

## Quick start

```bash
just setup                # once: Python deps (uv), Playwright Chromium, Node deps (pnpm)
just scrape prm           # first data (~17.5k items, about 8 minutes)
just start                # build the UI, serve it on http://localhost:8000 and open the browser
```

On Windows you can also run `just shortcut` once: it puts a saleVault shortcut with the app icon on the desktop, which starts the app in WSL and opens the browser. Close its window to stop the app.

## Getting data

```bash
just scrape prm           # PRM sale (~17.5k items, about 8 minutes)
just scrape answear_ua    # Answear.ua sale (~143k items, 30-40 minutes)
just scrape all           # every shop
just scrape prm --resume  # continue a run that failed or was cancelled
just runs                 # recent runs: status, duration, new items, price drops, removals
```

Or press **Refresh** in the app header and pick a shop; progress shows in the header, and a toast reports the result.

How it works: the scraper calls each shop's own catalog API at a polite pace (about one request per second per worker). By default (`--transport auto`) it uses a lightweight HTTP client with its built-in Chrome profile (curl_cffi); if a shop does not accept it, it uses a real Chromium driven by Playwright, shown as a window because these shops do not serve headless browsers. If a shop refuses the run, the scraper stops and says so.

Each run is staged page by page and merged into the catalog in one transaction at the end, so an interrupted run never leaves half-updated data. An item is treated as gone from the sale only after two successful runs in a row did not see it.

## Data and maintenance

```
data/
  salevault.db        the catalog (SQLite)
  backups/            just backup (last 5 kept)
  raw/<shop>/         gzipped API responses of the last 2 runs per shop, for debugging
  logs/               output of runs started from the UI (last 20 kept)
  browser/<shop>/     browser profile used when a run falls back to the browser
```

```bash
just backup               # consistent copy of the DB, safe while the app runs
just vacuum               # shrink the DB file (runs also do it when it grows by 100+ MB)
```

Migrations are applied automatically when the app or a scrape starts (`just db-upgrade` does it by hand).

## Troubleshooting

| Symptom | What to do |
|---|---|
| A run stops with "Blocked by site (HTTP 403)" | The shop refused the requests. Wait a while and try again; `--transport browser` forces the real browser. Fetched pages are kept: continue with `--resume` |
| A run was interrupted (Ctrl+C, Cancel, crash) | `just scrape <shop> --resume` continues where it stopped |
| "A run of ... is already running" | Only one run per shop at a time. A dead run is detected automatically (its process is gone, or it has not reported progress for 15 minutes) |
| `just start` fails with "address already in use" | Another instance is running; close it, or run `cd backend && uv run salevault serve --port 8001` |
| The browser window does not appear | WSLg is needed for the browser fallback (Windows 11). The HTTP transport (`--transport http`) needs no window |
| The app shows "API offline" | The server is not running: start it with `just start` |
| The DB file is large | `just vacuum` |

## Development

```bash
just dev        # API on :8000 with auto-reload + Vite on http://localhost:5173
just check      # lint, format check, type check and all tests (offline)
just fmt        # auto-format and apply safe lint fixes
just gen-api    # regenerate frontend API types after changing the API
cd backend && uv run pytest -m live   # tests that hit the real shops (run by hand)
```

API docs (OpenAPI) are served at `/api/docs`. Benchmarks: `backend/scripts/make_synthetic_db.py` builds a 200k-item catalog through the real pipeline, `backend/scripts/bench_api.py` measures the API against it.

## Stack

| Part | Tech |
|---|---|
| Backend | Python 3.15, uv, FastAPI, Pydantic, SQLAlchemy + Alembic, SQLite, Playwright, curl_cffi, Typer, Rich |
| Frontend | Vite, React 19 (with React Compiler), TypeScript 7, Tailwind CSS, shadcn/ui, TanStack Query and Router, Recharts |
| Quality | ruff, mypy (strict), pytest; Biome, tsc, Vitest |

## Disclaimer

A personal project, not affiliated with or endorsed by PRM or Answear. It reads the same public catalog data that the shops' own pages load, slowly, and keeps it only on your machine. Check a shop's terms of use before scraping it, and do not redistribute its data.

## Layout

```
backend/    Python package `salevault`: scraper, storage, catalog queries, HTTP API, CLI
frontend/   single-page app
justfile    all project commands
.github/    CI: lint, type check, tests and UI build on every push
data/       runtime data (database, backups, archives, logs); not tracked
```
