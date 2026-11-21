# saleVault

A local tool that collects sale items from fashion shops and shows them **sorted by discount, biggest first**. Filters: brand, gender, category, size, price and minimum discount. Also price history, New and Price drop badges, and favorites.

Supported shops: PRM.com (UA), with Answear.ua planned.

> **Status:** early development. The PRM scraper works in dry-run mode (prints a summary); storage and the catalog UI are next.

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
just scrape prm                 # full PRM sale (~17k items, a few minutes), prints the top discounts
just scrape prm --max-pages 1   # quick smoke run
just scrape prm --jsonl ../data/exports/prm.jsonl   # also export normalized items
```

The scraper drives a real Chromium through Playwright and calls the shop's own catalog API from the page, at a polite rate (about one request per second). PRM rejects headless browsers, so a Chromium window is shown during the run (WSLg on Windows 11). There is no stealth or anti-bot evasion: if the site blocks the run, the scraper stops and reports it.

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
