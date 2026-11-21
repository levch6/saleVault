# saleVault

A local tool that collects sale items from fashion shops and shows them **sorted by discount, biggest first**. Filters: brand, gender, category, size, price and minimum discount. Also price history, New and Price drop badges, and favorites.

Supported shops: PRM.com (UA), with Answear.ua planned.

> **Status:** usable. Shops: PRM.com (UA) and Answear.ua. Scraper, local catalog with price history, API and UI (catalog sorted by discount, filters, my sizes, item drawer with price chart, favorites, runs).

## Requirements

- Linux or WSL2 (developed on Ubuntu under Windows 11)
- [uv](https://docs.astral.sh/uv/), Node.js with [pnpm](https://pnpm.io/), [just](https://just.systems/)

Python 3.15, the Playwright Chromium build and all packages are installed by `just setup`.

## Quick start

```bash
just setup    # Python deps (uv), Playwright Chromium, Node deps (pnpm)
just start    # build the UI and serve it together with the API on http://localhost:8000
```

On WSL2 the app opens in a regular Windows browser at `localhost`.

## Scraping

```bash
just scrape prm                 # full PRM sale (~17.5k items, ~8 min) into data/salevault.db
just scrape answear_ua          # Answear.ua (~143k items, about 30-40 min)
just scrape all                 # every shop
just scrape prm --resume        # continue a run that failed or was cancelled
just runs                       # recent runs: status, duration, new items, price drops, removals
just scrape prm --dry-run       # collect and print a summary without touching the DB
```

Each run is staged page by page and merged into the catalog in one transaction at the end, so an interrupted run never leaves half-updated data. Price changes are kept as a history. An item is treated as gone from the sale only after two successful runs in a row did not see it.

The scraper calls the shop's own catalog API at a polite rate (about one request per second per worker). By default (`--transport auto`) it uses a lightweight HTTP client with its built-in Chrome profile (curl_cffi); if a shop does not accept it, it uses a real Chromium driven by Playwright (a window is shown, since these shops do not serve headless browsers). If a shop refuses the run, the scraper stops and reports it.

## Development

```bash
just dev      # API on :8000 with auto-reload + Vite on http://localhost:5173
just check    # lint, format check, type check and all tests
just fmt      # auto-format and apply safe lint fixes
just gen-api  # regenerate frontend API types after changing the API
```

API docs (OpenAPI) are served at `/api/docs`.

## Stack

| Part | Tech |
|---|---|
| Backend | Python 3.15, uv, FastAPI, Pydantic, SQLAlchemy + Alembic, SQLite, Playwright, Typer |
| Frontend | Vite, React (with React Compiler), TypeScript, Tailwind CSS, shadcn/ui, TanStack Query and Router |
| Quality | ruff, mypy (strict), pytest; Biome, tsc, Vitest |

## Layout

```
backend/    Python package `salevault`: scraper, storage, HTTP API, CLI
frontend/   single-page app
justfile    all project commands
data/       runtime data (database, browser profile, logs); not tracked
```
