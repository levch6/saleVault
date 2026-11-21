# Development

## Setup

```bash
just setup        # Python deps (uv), Playwright Chromium, Node deps (pnpm), git hooks
just dev          # API on :8000 with auto-reload + Vite on http://localhost:5173 (proxies /api)
```

`just dev` stops both servers on Ctrl+C or when either one crashes. API docs (OpenAPI) are at http://localhost:8000/api/docs.

## Repository layout

```
backend/                  Python package `salevault`
  src/salevault/
    scraper/              transports, site adapters, segmentation, run lifecycle, reports
      sites/              shop adapters and their configs (the only shop-specific code)
    db/                   SQLAlchemy models, Alembic migrations, runs, finalization, maintenance
    domain/               pure functions: discount math, records
    catalog/              read side: filters, list, facets, detail, favorites, settings
    api/                  FastAPI app, routers, run launcher
    cli.py                Typer CLI
  scripts/                fixtures, synthetic data, benchmarks, icons, commit message check
  tests/                  unit/, integration/, live/ (hits real shops, run by hand)
frontend/                 Vite + React SPA
  src/api/                generated API types, client, TanStack Query hooks
  src/routes/             file-based routes (TanStack Router)
  src/components/         ui/ (shadcn/ui) and feature components
  src/lib/                URL search state, formatting, sizes
docs/                     this documentation
justfile                  every project command
```

## Checks

```bash
just check        # everything CI runs: lint, format check, types, spelling, CI security, tests
just lint         # ruff, mypy --strict, Biome, tsc, typos, zizmor, ASCII Markdown
just test         # pytest + Vitest (offline)
just fmt          # auto-format and safe fixes
```

Git hooks (installed by `just setup`, or `just hooks`) run quick checks on the staged files and check the commit message. If a hook rewrites files, stage them and commit again. Do not bypass hooks with `--no-verify`; fix what they report.

CI (`.github/workflows/check.yml`) runs `just check` and the UI build on every push to `main` and on pull requests. It never touches the network beyond installing packages.

`main` is protected by a repository ruleset: it cannot be deleted or force-pushed, history stays linear, and changes from anyone but the maintainer arrive as pull requests that are squash-merged once the `lint, test and build` check passes on an up-to-date branch.

## Tests

| Kind | Where | Notes |
|---|---|---|
| Backend unit | `backend/tests/unit/` | adapters, segmentation, runner, CLI, reports |
| Backend integration | `backend/tests/integration/` | real SQLite in a temp dir: migrations, runs, finalization, API |
| Live | `backend/tests/live/` | `cd backend && uv run pytest -m live`; hits the real shops, run by hand only |
| Frontend | `frontend/src/**/*.test.ts(x)` | Vitest + Testing Library in jsdom |

- Test data must not contain shop content. Build fixtures from archived raw responses with `backend/scripts/make_fixture.py`, which keeps structure, ids and prices and replaces names, brands, categories, URLs, image names and EANs with placeholders.
- Frontend helpers live in `frontend/src/test/utils.tsx`: `renderWithClient`, `mockApi` (stubs `fetch` and records calls) and data builders. Seed the query cache instead of mounting a router.
- CLI tests assert on output with terminal styling removed: Typer forces colors when `GITHUB_ACTIONS` is set.

## API types

The frontend types come from the FastAPI OpenAPI schema:

```bash
just gen-api
```

`openapi-typescript` needs the classic TypeScript compiler API, which TypeScript 7 no longer ships, so the recipe runs it through `pnpm dlx` with a pinned TypeScript 5.9. The generated `frontend/src/api/schema.d.ts` and `frontend/src/routeTree.gen.ts` are committed and never edited by hand.

## Database migrations

```bash
cd backend && uv run alembic revision --autogenerate -m "describe the change"
```

Review the generated file in `src/salevault/db/migrations/versions/`. Migrations ship inside the package and run automatically on start; after any applied migration the database runs `ANALYZE`, because SQLite plans queries badly for indexes without statistics.

## Performance work

```bash
cd backend
uv run python scripts/make_synthetic_db.py <data-dir> [--items 200000]   # synthetic catalog through the real pipeline
uv run python scripts/bench_api.py <data-dir> [--runs 20]                # p50 / p95 per API case
```

`bench_api.py` writes settings (saved sizes), so point it at a synthetic database or a copy of yours, never at `data/` directly. See [architecture](../concepts/architecture.md#performance) for the design rules to keep.

## Conventions

- Everything in the repository is in English. Product data stays as the shops serve it (Ukrainian).
- Markdown is plain ASCII: no emoji, typographic quotes, arrows or long dashes.
- Commits: one line in Conventional Commits form, `type(scope): summary`, lowercase and imperative, at most 100 characters, no body. Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `build`, `perf`. The commit-msg hook enforces it.
- Money is stored as integer minor units (`*_minor`); the API returns whole hryvnias.
- Shop-specific logic lives only in `scraper/sites/`. The core, database, API and UI stay shop-agnostic.
- External data is validated with Pydantic. On a schema mismatch the run fails loudly and the raw response is kept.

## Dependency updates

Dependabot opens grouped pull requests monthly (Python, frontend, GitHub Actions; releases younger than 7 days are skipped). They all touch lock files, so merge them one at a time: ask for `@dependabot rebase` onto the current `main`, wait for a green CI, then squash-merge with a one-line subject.
