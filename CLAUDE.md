# saleVault

Personal, local-only tool: scrapes the sale sections of fashion shops (PRM.com, then Answear.ua) and shows items sorted by discount, biggest first, with filters, price history and favorites. Single user, not hosted, runs in WSL2 (Ubuntu) on Windows 11.

## Where things are

- `docs/` is local-only and gitignored. It holds the plan, specs, ADRs and research for the developer and Claude. Never commit it and never link to it from tracked files.
  - `docs/plan.md`: roadmap and the current phase. Tick checkboxes when finishing tasks.
  - `docs/specs/`: product, architecture, scraper, data-model, api, ui. They are the source of truth for behavior.
  - `docs/adr/`: decisions. Add a new ADR for any significant change of approach; don't rewrite accepted ones.
  - `docs/research/`: findings about site APIs, plus real response samples.
- `backend/`: Python package `salevault` (scraper, db, api, cli).
- `frontend/`: Vite + React SPA.
- `data/`: runtime data (DB, browser profile, logs, raw dumps). Gitignored.

## Stack

- Backend: Python 3.15 via uv, Playwright (async), Pydantic v2, SQLAlchemy 2 + Alembic, SQLite (WAL), FastAPI, Typer + Rich, tenacity. Quality: ruff, mypy --strict, pytest (+ httpx2 for the test client).
- Frontend: Vite 8, React 19 with React Compiler, TypeScript 7 (strict), pnpm 12, Tailwind v4, shadcn/ui (Radix base, Nova preset), TanStack Query + Router (file-based routes), openapi-fetch, Recharts, Biome, Vitest.
- Task runner: `just` (see `justfile`).

## Commands

- `just setup`: install everything (uv sync, Playwright Chromium, pnpm install)
- `just dev`: backend on :8000 (reload) + Vite on :5173 (proxies `/api`)
- `just start`: build the UI, then a single process on :8000 serves UI + API
- `just check`: lint + type check + tests (`just lint`, `just test`); run before every commit
- `just scrape prm [args]`: scrape a site into the DB; `--resume` continues an interrupted run, `--dry-run` only prints a summary, `--max-pages 1` for a quick smoke run, `--jsonl path` exports items
- `just runs [--site prm]`: recent runs with status and catalog changes
- `just db-upgrade`: apply migrations (scrapes do it automatically)
- `just fmt`, `just build`, `just gen-api`
- New migration: `cd backend && uv run alembic revision --autogenerate -m "..."`, then review the file in `src/salevault/db/migrations/versions/`
- Live tests (hit the real site, open a browser window): `cd backend && uv run pytest -m live`

## Gotchas

- TypeScript 7's npm package has no classic JS compiler API, so `openapi-typescript` is not a project dependency: `just gen-api` runs it through `pnpm dlx` with pinned `typescript@5.9`. Keep it that way until openapi-typescript supports TS 7.
- `src/routeTree.gen.ts` and `src/api/schema.d.ts` are generated but committed (needed by `tsc` on a fresh clone) and excluded from Biome. Never edit them by hand.
- pnpm 12 asks for approval of agent "skills" shipped by `@tanstack/react-router` and `@tanstack/router-plugin`. They are deliberately left unapproved; don't approve them without asking the user.
- shadcn's `cn` helper comes from the `cn` package (shadcn-ui/cn) via `@/lib/utils`. The shadcn CLI sometimes silently skips a component (it did for `sheet`); then write it from `pnpm dlx shadcn@latest view <name>`. Generated `src/components/ui/**` is not linted by Biome.
- Catalog state lives in the URL (`frontend/src/lib/search.ts`); add new filters there, in `validateCatalogSearch`, and in the API query model together.
- Filter EXISTS subqueries must use `aliased(...)` tables: facet queries join `product_sizes` / `product_categories` themselves and auto-correlation would break them.
- PRM does not serve Playwright's headless shell (HTTP 403 at warm-up), so its site config runs a headed Chromium window through WSLg.
- Performance (see `backend/scripts/bench_api.py`, `make_synthetic_db.py`): every sort and cheap facet has an index led by `is_active`; product pages use a deferred join (page of ids first, then full rows); `upgrade()` and finished runs run `ANALYZE` (without statistics for new indexes SQLite picks 20x slower plans). Keep these when touching queries, and re-run the bench on a 200k synthetic DB.
- Facets are cached in-process, keyed by DB URL + query + data version (last finished run, favorites, my sizes). Anything else that changes facet results must be added to `data_version`.
- Categories: the shop's tree (`categoryTree`, root request only) is the source of truth; item `categories` lists are several glued paths, sometimes without a root (ADR-0005). Products are linked to ancestors too.
- API gender values are words (`men`, `women`, `home`, `kids`); shop codes (`M`, `D`, `H`) stay inside the adapter.
- UI-triggered runs are separate processes (`api/launcher.py`): `python -m salevault scrape <site> --trigger ui`, logs in `data/logs/`.
- SQLAlchemy 2.1: never pass a `Result` to `dict()` (it has `.keys()`, so dict treats it as a mapping); use a comprehension. `Result.tuples()` is deprecated.
- The DB lives in `data/salevault.db` (SQLite, WAL). The engine disables pysqlite's implicit transactions and emits `BEGIN` itself (`db/engine.py`); keep it that way.
- Test fixtures must be anonymized: build them with `backend/scripts/make_fixture.py` from `data/raw/...` archives, never copy raw shop responses into the repo.

## Conventions

- **Language:** everything in the repository is in English: code, comments, docs, commit messages, UI text. Product data stays in Ukrainian, as the site provides it.
- **Markdown style:** plain ASCII only. No emojis, no special symbols (arrows, check marks, typographic quotes, ellipsis characters, currency signs), no em or en dashes. Use `-`, `->`, `>=`, `...` instead.
- **Commits:** a single line in Conventional Commits format, `type(scope): summary`, lowercase and imperative, e.g. `feat(scraper): add price segmentation`. Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `build`, `perf`. No body, no trailers.
- Before committing a phase, `just lint && just test` must pass.
- If a new tool needs sudo, ask the user to install it instead of working around it.

## Engineering rules

- **Scraping etiquette (hard rule):** call the site's own JSON API at the polite default rate from the site config, through a stock Playwright Chromium or, as an optional transport planned for phase 5, `curl_cffi` with its Chrome profile. On repeated 403/429, stop the run and report. Respect robots.txt. Off-limits: stealth plugins, CAPTCHA solving, proxy rotation.
- Money is stored as integer minor units (`*_minor`); the API returns whole UAH.
- Site-specific logic lives only in adapters (`scraper/sites/`). The core, DB, API and UI stay site-agnostic.
- Validate external data with Pydantic. On a schema mismatch, fail loudly and save the raw response.
- Tests never hit the network, except the ones marked `live` (run manually: `pytest -m live`).
