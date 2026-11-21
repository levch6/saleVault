# ADR-0001: Tech stack

- **Status:** accepted
- **Date:** 2026-11-21

## Context

saleVault needs a scraper for several shops and a local web UI with fast filtering and sorting by discount. It is used by one person, on demand, on their own machine (WSL2 on Windows 11); nothing is hosted. Development speed and stability matter most.

## Decision

**Backend: Python**

| Area | Choice | Why |
|---|---|---|
| Runtime and packaging | Python 3.15, uv (`pyproject.toml` + `uv.lock`) | fast, reproducible installs |
| Fetching | Playwright for Python, curl_cffi | a real browser and a lightweight HTTP client behind one transport interface (ADR-0002) |
| Validation | Pydantic v2 | strict parsing of shop JSON, so API changes surface immediately with a clear error |
| Database | SQLite (WAL), SQLAlchemy 2, Alembic | zero operations; 10^5 to 10^6 indexed rows answer in milliseconds; migrations for schema changes |
| API | FastAPI + Uvicorn | typed; its OpenAPI schema generates the frontend types |
| CLI | Typer + Rich | commands and progress bars |
| Retries | tenacity | exponential backoff |
| Quality | ruff, mypy --strict, pytest | |

**Frontend: TypeScript**

| Area | Choice | Why |
|---|---|---|
| Build | Vite, React, TypeScript (strict) | no server rendering is needed; a single-page app is simplest |
| UI kit | Tailwind CSS v4, shadcn/ui (Radix) | accessible components, quick to build with |
| Server state | TanStack Query | caching, infinite scroll, invalidation after a run |
| Routing and URL state | TanStack Router | typed search params: every filter lives in the URL |
| API client | openapi-typescript + openapi-fetch | end-to-end types from FastAPI to components |
| Charts | Recharts | price history |
| Quality | Biome, Vitest + Testing Library | one fast tool instead of ESLint + Prettier |

**Tasks:** `just`.

## Alternatives considered

- **Python only (FastAPI + Jinja + HTMX):** one language and one process, but faceted filters, an infinite grid and URL state are much easier in React.
- **TypeScript everywhere:** one language, but validating and normalizing shop data is more convenient with Pydantic.
- **Rust:** the bottleneck is the deliberately slow request pace, not CPU.
- **Docker, PostgreSQL:** overhead without benefit for a local single-user app.
- **Next.js:** server rendering is not needed.

## Consequences

- Two languages and, during development, two processes (`just dev`). In everyday use FastAPI serves the built UI from one process (`just start`).
- After API changes, frontend types are regenerated with `just gen-api`.

## Updates

- **2026-11-21:** TypeScript 7 no longer ships the classic compiler API that `openapi-typescript` uses, so `just gen-api` runs the generator through `pnpm dlx` with a pinned TypeScript 5.9. The app itself type-checks with TypeScript 7.
