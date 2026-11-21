# Architecture

saleVault is a single-user application that runs on your own machine. There is no hosting, no account and no background service: you start it, optionally refresh the data, browse, and close it.

## Components

```
 Browser                      saleVault (Python)                            Shops
+-----------+     +----------------------------------------------+
| UI (React)|---->| FastAPI on 127.0.0.1:8000                    |
|           |     |   /api/*      catalog, favorites, settings,  |
|           |     |               runs                            |
|           |     |   /           built UI (frontend/dist)        |
+-----------+     |   POST /api/runs --spawn--+                   |
                  |                           v                   |
 Terminal         |  scraper process (python -m salevault scrape) |---> shop catalog API
 just scrape ---->|      stages pages, merges at the end          |     (HTTP client or
                  |                           |                   |      Chromium)
                  |                           v                   |
                  |                SQLite: data/salevault.db      |
                  +----------------------------------------------+
```

| Component | Location | Responsibility |
|---|---|---|
| Scraper | `backend/src/salevault/scraper/` | transports, shop adapters, segmentation, run lifecycle, terminal reports |
| Storage | `backend/src/salevault/db/` | models, migrations, run repository (locking, staging, resume), finalization, backups |
| Domain | `backend/src/salevault/domain/` | pure functions: discount math, normalized records |
| Catalog | `backend/src/salevault/catalog/` | read side: filters, product pages, facets, detail, favorites, settings, facet cache |
| API | `backend/src/salevault/api/` | FastAPI app, routers, error mapping, the run launcher, serving the built UI |
| CLI | `backend/src/salevault/cli.py` | `scrape`, `runs`, `db`, `serve` |
| UI | `frontend/` | catalog, item drawer, favorites, runs, settings |

## Processes

- **Everyday use** (`just start`): one FastAPI process serves the API and the built UI on `127.0.0.1:8000`.
- **Development** (`just dev`): FastAPI with auto-reload on `:8000` and the Vite dev server on `:5173`, which proxies `/api`.
- **Scrapes** are always separate processes. The terminal starts one directly (`just scrape`); the app starts one through `RunLauncher` (`python -m salevault scrape <shop> --trigger ui`) in its own session. A crash of the scraper or the browser cannot take the web server down, and a run survives a restart of the server.
- **Progress** travels through the database: the scraper updates its row in `scrape_runs`, the UI polls `GET /api/sites` about every 1.5 s while a run is active. There are no queues or workers.
- **Cancel** sends SIGTERM to the scraper process, which drops the request in flight, keeps the fetched pages and records the run as `cancelled`.

## Data flow

1. The scraper plans segments, fetches pages and stages every item in `run_items`, recording each fetched page in `run_pages` (the checkpoints that make `--resume` possible).
2. When all pages are fetched, one transaction merges the staged items into the catalog tables, writes price history and computes the run statistics.
3. The API reads only the catalog tables, so the UI never sees a half-merged run.

Details: [How a scrape works](scraping.md) and the [data model](../reference/data-model.md).

## Technology

| Area | Choice |
|---|---|
| Backend | Python 3.15 (uv), FastAPI, Pydantic v2, SQLAlchemy 2 + Alembic, SQLite (WAL), Typer + Rich, tenacity |
| Fetching | curl_cffi (HTTP transport), Playwright Chromium (browser transport) |
| Frontend | Vite, React 19 with the React Compiler, TypeScript 7, Tailwind CSS v4, shadcn/ui (Radix), TanStack Query and Router, openapi-fetch, Recharts |
| Quality | ruff, mypy --strict, pytest; Biome, tsc, Vitest + Testing Library; typos, zizmor; prek git hooks |
| Tasks | just |

Why these: [ADR-0001](../decisions/0001-tech-stack.md).

## Performance

The catalog stays fast at about 200,000 items (p95 under 200 ms for lists and filters). Measured on a real two-shop catalog of 160,600 items: default list 18 ms, filtered lists 12 to 108 ms, item detail 6 ms, cached facets 6 ms, uncached basic facets 74 ms, uncached category and size counts about 0.9 s.

The design rules behind these numbers, to keep when changing queries:

- Every sort and every cheap facet has an index led by `is_active`.
- Product pages use a deferred join: sort narrow rows to get a page of ids, then load the full rows for those ids only.
- The New and Cheaper filters are resolved to id lists first, so SQLite does not walk the discount index looking for rare matches.
- Facets come in two requests: `heavy=false` returns the cheap ones (shops, genders, brands, price and discount ranges) at list speed, and the full request adds category and size counts. The UI asks for both in parallel.
- Facets are cached in the API process, keyed by database, query and a data version (last finished run, favorites, saved sizes). The cache is warmed at startup and after runs started from the app.
- `ANALYZE` runs after every merged run and after any applied migration.
- SQLite settings: WAL, a 64 MB page cache, 256 MB memory map, temporary storage in memory.
