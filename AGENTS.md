# saleVault: instructions for coding agents

Personal, local-only, non-commercial tool: scrapes the sale sections of fashion shops (PRM, Answear.ua, Footshop, Saks85 and Modivo) and shows items sorted by discount, biggest first, with filters, price history and favorites. Single user, not hosted, runs in WSL2 (Ubuntu) on Windows 11. The repository is public: everything tracked must be fit for publication (no shop data, neutral wording, nothing personal).

This file is the shared brief for every coding agent. Tool-specific additions live next to the tool's config (`CLAUDE.md` for Claude Code imports this file). Reusable procedures are skills in `.agents/skills/`.

## Where things are

- `docs/`: public documentation (Diataxis: `getting-started.md`, `guides/`, `concepts/`, `reference/`, `decisions/`). It is the source of truth for behavior: update it in the same commit as the code. Add a new ADR in `docs/decisions/` for any significant change of approach; don't rewrite accepted ones.
- `.notes/`: local-only working notes, gitignored. Never commit it and never link to it from tracked files.
  - `.notes/plan.md`: roadmap, phase checklists, decision log and backlog. Tick checkboxes when finishing tasks.
  - `.notes/research/`: findings about site APIs, plus real response samples (shop content: never copy into the repo).
  - `.notes/archive/`: the original internal specs and ADRs (superseded by `docs/`).
- `backend/`: Python package `salevault` (scraper, db, api, cli).
- `frontend/`: Vite + React SPA.
- `data/`: runtime data (DB, browser profile, logs, raw dumps, backups). Gitignored.
- `.agents/skills/`: project skills (Agent Skills format, one folder with a `SKILL.md` each): `add-a-shop`, `check-the-ui`, `merge-dependabot-prs`; plus `react-router`, `router-plugin` and `router-query`, the skills TanStack ships in its npm packages (links into `frontend/.claude/skills/`, which pnpm maintains).
- `.claude/`: Claude Code config (permissions, a guard hook, `skills/` symlinked to `.agents/skills/`).

## Stack

- Backend: Python 3.15 via uv, Playwright (async), curl_cffi, Pydantic v2, SQLAlchemy 2 + Alembic, SQLite (WAL), FastAPI, Typer + Rich, tenacity. Quality: ruff (with security rules), mypy --strict, pytest.
- Frontend: Vite 8, React 19 with React Compiler, TypeScript 7 (strict), pnpm 12, Tailwind v4, shadcn/ui (Radix base, Nova preset), TanStack Query + Router (file-based routes), openapi-fetch, Recharts, Biome, Vitest + Testing Library.
- Task runner: `just` (see `justfile`). Git hooks: prek (`.pre-commit-config.yaml`).

## Commands

- `just setup`: install everything (uv sync, Playwright Chromium, pnpm install, git hooks)
- `just dev`: backend on :8000 (reload) + Vite on :5173 (proxies `/api`)
- `just start`: build the UI, then a single process on :8000 serves UI + API and the browser opens once it is healthy
- `just check`: lint + type check + tests (`just lint`, `just test`); run before every commit. `just lint` also runs typos, zizmor (CI security) and a plain-ASCII check of tracked Markdown
- `just hooks` (also part of `just setup`): quick checks of the staged files (ruff, mypy, biome, tsc, typos, zizmor, actionlint, gitleaks on the staged changes, ASCII Markdown, nothing from `.notes/` or `data/`, no `.jsonl`/`.db`/`.sqlite`/`.gz` files anywhere) and the commit message format (`backend/scripts/check_commit_msg.py`). gitleaks and actionlint come from their official hook repositories pinned to commit SHAs; prek builds them once (it installs Go itself). Dependabot bumps those pins monthly; `just hooks-update` does it by hand. If a hook rewrites files, stage them and commit again; never bypass hooks with `--no-verify`. prek runs on staged files only after `.pre-commit-config.yaml` itself is staged
- `just scrape prm [args]`: scrape a site into the DB (sends requests to the shop: only when the user asks); `--resume` continues an interrupted run, `--dry-run` only prints a summary, `--max-pages 1` for a quick smoke run, `--jsonl path` exports items
- `just runs [--site prm]`: recent runs with status and catalog changes
- `just db-upgrade`: apply migrations (scrapes and the app do it automatically, with a backup first)
- `just backup` / `just vacuum`: DB copy into `data/backups` (last 5) / compaction (also automatic after a run once free pages exceed 100 MB)
- `just shortcut`: a `saleVault.lnk` with the app icon on the Windows desktop, pointing at a `.bat` and `.ico` in `%LOCALAPPDATA%\saleVault` (only run it when the user asks)
- `just fmt`, `just build`, `just gen-api`
- Logo: `frontend/public/favicon.svg` is the only source (black and white, inverted for dark browser themes); after changing it, `cd backend && uv run python scripts/make_icons.py` renders `favicon.ico`
- New migration: `cd backend && uv run alembic revision --autogenerate -m "..."`, then review the file in `src/salevault/db/migrations/versions/`
- Live tests (hit the real shops; only when the user asks): `cd backend && uv run pytest -m live`

## Repository and CI

- CI (`.github/workflows/check.yml`): `just check` + `just build` on push to main and on PRs. Actions are pinned to commit SHAs with a `# vX.Y.Z` comment (zizmor requires it; Dependabot bumps both); checkout keeps `persist-credentials: false`. Keep it offline (no live tests, no Playwright browsers). Node and pnpm versions come from `.node-version` and `packageManager` in `frontend/package.json`.
- Container (`Dockerfile`, `compose.yaml`, `.dockerignore` at the root; ADR-0010, `docs/guides/docker.md`): one image with the built UI, the venv (uv) and a headed Chromium on Xvfb (`tini` -> `xvfb-run` -> `salevault serve`), running as uid 1000 with `SALEVAULT_DATA_DIR=/app/data`; compose publishes on `127.0.0.1` only and keeps data in the `salevault-data` volume (`SALEVAULT_DATA=./data` to bind the folder). Base images are pinned by digest (Dependabot `docker`). `.github/workflows/docker.yml` builds it with the GHA cache when its inputs change (and monthly), runs `docker buildx build --check`, starts it and opens `about:blank` in the headed Chromium; it never publishes and never contacts a shop. Playwright's bundled Node driver needs `libatomic1`, which slim images lack. Apt downloads use BuildKit cache mounts (`docker-clean` removed). `SALEVAULT_CONTAINER=1` switches the serve warning and the "no runs yet" hint. Locally the Docker socket needs the `docker` group in the session (a new login after joining the group).
- GitHub settings: CodeQL default setup; Actions limited to GitHub-owned actions plus `astral-sh/setup-uv`, `pnpm/action-setup`, `extractions/setup-just`, `extractions/setup-crate` (called by setup-just), `docker/setup-buildx-action` and `docker/build-push-action`, all SHA-pinned (a new third-party action needs an allowlist entry in the repository settings first); wiki and projects off; issue forms in `.github/ISSUE_TEMPLATE/` (shop requests are handled first).
- Branch protection: ruleset "protect main" (no deletion, no force push, linear history, changes through a PR merged by squash with the `lint, test and build` check green on an up-to-date branch). The repository admin role bypasses it, so direct pushes made with the owner's credentials work and print a "bypassed rule" notice; that is expected.
- Dependabot (`.github/dependabot.yml`): monthly, minor and patch grouped per ecosystem (uv, npm, actions, pre-commit hooks, Docker base images), 7-day cooldown. Merge its PRs with the `merge-dependabot-prs` skill.
- Commits use the owner's GitHub noreply address (repository-local `user.email`); keep it that way.

## Gotchas

### Backend

- The DB lives in `data/salevault.db` (SQLite, WAL). The engine disables pysqlite's implicit transactions and emits `BEGIN` itself (`db/engine.py`); keep it that way.
- Writers use `make_session_factory(engine, write=True)` (`BEGIN IMMEDIATE`): a deferred transaction that reads and then writes fails at once, ignoring `busy_timeout` (120 s), when another process wrote in between. The scraper CLI uses a write factory; the API has `SessionDep` (reads) and `WriteSessionDep`, and `RunRepository(write_factory, reader=read_factory)`. Never put the merge, ANALYZE or VACUUM behind a read session.
- Runs store `pid` and `pid_start` (process start time): never signal a pid without `same_process()`. Dead runs are reaped on reads (`RunRepository.reap_dead`), and a unique index allows one running run per site.
- Scraper rules in code: refusals are counted per run (`ScrapeRunner._refused`, shared pause), `auto` falls back to the browser only on a 403 at warm-up, `ScrapeError.raw` carries the body to the archive, more than 20% invalid items per page is a `ContractError`, and the request budget is derived from the plan.
- Transports (`scraper/transports.py`): `auto` (default) = curl_cffi `HttpSession` first, the real browser only if the start page answers 403; `--transport browser|http` to force. PRM and Answear.ua refuse Playwright's headless shell, so the browser path runs a headed window (WSLg).
- Two platforms behind one registry (`scraper/sites/registry.py`, configs implement `SiteConfig`): the Answear platform (PRM, Answear.ua: `POST <base>/api/products`) and Footshop (`footshop.py`). Footshop's robots.txt disallows its API (`*/api/*`, `?ajax=`) and query pagination (`?p=`), so the adapter reads the catalog pages (`/uk/872-znizhki/page-N`, 24 items) and parses the listing JSON embedded in them (Hypernova: `&` and `>` escaped inside an HTML comment); never call those endpoints (ADR-0006). Its segments are the men's, women's and kids' sale sections, no price split; a page number past the end returns the last page, which the adapter treats as empty. Shared adapter helpers live in `scraper/sites/common.py`.
- Saks85 (`saks85.py`, OpenCart with ocFilter) has no API and no embedded product data: the adapter reads the product cards (12 per page) from the markup with `html.parser` and archives the parsed JSON. Its robots.txt disallows `/*?page=` (and `limit`, `sort`, `order`, `filter`, `search` in their spellings); by the owner's decision page 1 is the menu path and later pages are `index.php?route=product/category&path=<id>&filter_ocfilter=<selection>&page=N` (ADR-0008). Never request `?page=`, change the page size or sort, or call the ocFilter route; `test_saks85_adapter.py` checks every URL against those rules. Segments are gender x top-level category (8). Cards have no id: the id is the product path (decoded, hashed past 64 characters).
- Modivo (`modivo.py`, Nuxt 2): robots.txt disallows its APIs (`/m-api/`, `/t-api/`, `/n-api/`) and most catalog filters, and allows exactly `discount:~r-5-99` (the longer Allow wins over `Disallow: /c/*:*-*-*`; `~r-10-99` from the menus is disallowed). The adapter reads `/c/<section>/discount:~r-5-99?p=N` (72 items) and the page's `window.__NUXT__` state, which is devalue's JavaScript, not JSON: `scraper/sites/nuxt_state.py` reads that subset as data and rejects anything else. Never execute the page's script or add a JS engine (an owner decision), never call the APIs, add filters, sort or change the page size; `test_modivo_adapter.py` checks every URL with longest-match precedence (ADR-0007). Segments are men, women, kids, no price split; a page past the end is a 404, which the adapter treats as empty after page 1. Cards and details (prices, sizes) are joined by sku; the archive keeps the listing pruned to `_LISTING_SHAPE`.
- Discount rounding is per shop: `ProductRecord.create(percent_rounding=...)`, truncation for the Answear platform and Modivo, half up for Footshop (its badges show 9.99% as -10%).
- The API trusts only `SALEVAULT_ALLOWED_HOSTS` (tests add `testserver` in `backend/tests/conftest.py`), refuses non-GET requests from other origins and serves the UI with a strict CSP; unexpected errors are JSON (`internal`), a locked database is 503 (`database_busy`).
- Filter EXISTS subqueries must use `aliased(...)` tables: facet queries join `product_sizes` / `product_categories` themselves and auto-correlation would break them.
- Facets: `heavy=false` skips the size counts (the slow part at 240k items); the UI asks for both variants in parallel. They are cached in-process, keyed by DB URL + query + data version (count and last finish time of finished runs, favorites, my sizes); anything else that changes facet results must be added to `data_version`.
- Performance (see `backend/scripts/bench_api.py`, `make_synthetic_db.py`): every sort and cheap facet has an index led by `is_active`; product pages use a deferred join (page of ids first, then full rows); New / Price drop flags are resolved to ids bound as one JSON value (`json_each`, SQLite allows only 32,766 variables); `upgrade()` and finished runs run `ANALYZE`. Keep these when touching queries, and re-run the bench on a 200k synthetic DB.
- `backend/scripts/bench_api.py` writes settings (my sizes): run it only on a copy of the DB (`sqlite3 data/salevault.db ".backup <copy>"`).
- Categories: the shop's tree (`categoryTree`, root request only) is the source of truth for the shop's own categories; item `categories` lists are several glued paths, sometimes without a root (ADR-0005). Products are linked to ancestors too; depths are recomputed from parent links after every merge.
- The catalog filter uses the shared category tree (`domain/taxonomy.py`, ADR-0009), stored per product in `products.category_slug` by the merge. Rules are ordered stems (Ukrainian, plus Czech and English shop words); evidence order: deepest shop category, then a style with its parent plus the brand-less name within one group, then the name, then group hints. After changing the tree or rules, bump `TAXONOMY_VERSION` (the next start recategorizes everything), add cases to `tests/unit/test_taxonomy.py` and check `just recategorize` on a copy of the DB (coverage per shop). Slugs are in URLs: never reuse a removed one. Cyrillic look-alike letters in rule files need `# ruff: noqa: RUF001`.
- API gender values are words (`men`, `women`, `home`, `kids`); shop codes (`M`, `D`, `H`) stay inside the adapter.
- Brands are stored per shop but filtered and counted by `brands.name_key` (`domain/brands.py`), so a brand sold by several shops is one entry; the API `brand` param takes keys. Changing `brand_key` needs a migration that recomputes the stored keys.
- UI-triggered runs are separate processes (`api/launcher.py`): `python -m salevault scrape <site> --trigger ui [--resume]`, logs in `data/logs/`.
- SQLAlchemy 2.1: never pass a `Result` to `dict()` (it has `.keys()`, so dict treats it as a mapping); use a comprehension. `Result.tuples()` is deprecated.
- CLI tests: Typer forces ANSI styling when `GITHUB_ACTIONS` is set, so assert on `plain(result)` (`tests/unit/test_cli.py`), never on raw `result.output`.
- Test fixtures must be anonymized: build them with `backend/scripts/make_fixture.py` from `data/raw/...` archives (it handles the Answear API format, Footshop listings, Saks85 cards and Modivo listings), never copy raw shop responses into the repo.

### Frontend

- TypeScript 7's npm package has no classic JS compiler API, so `openapi-typescript` is not a project dependency: `just gen-api` runs it through `pnpm dlx` with pinned `typescript@5.9`. Keep it that way until openapi-typescript supports TS 7.
- `src/routeTree.gen.ts` and `src/api/schema.d.ts` are generated but committed (needed by `tsc` on a fresh clone) and excluded from Biome. Never edit them by hand.
- Package skills: the owner approved the agent skills of `@tanstack/react-router` and `@tanstack/router-plugin` (`permissions` in `frontend/pnpm-workspace.yaml`). `pnpm install` links them into `frontend/.claude/skills/` (gitignored there) at the installed version; `.agents/skills/` and `.claude/skills/` link to those folders, so the links resolve after `just setup`. Approve skills of any other package only when the user asks.
- `frontend/pnpm-workspace.yaml` overrides `minimatch` to `^11.0.1` (security advisory; shadcn 4.23 -> ts-morph 26 pins 10.x). Remove it once shadcn depends on ts-morph >= 28.
- shadcn's `cn` helper comes from the `cn` package (shadcn-ui/cn) via `@/lib/utils`. The shadcn CLI sometimes silently skips a component (it did for `sheet`); then write it from `pnpm dlx shadcn@latest view <name>`. Generated `src/components/ui/**` is not linted by Biome.
- Catalog state lives in the URL (`frontend/src/lib/search.ts`); add new filters there, in `validateCatalogSearch`, and in the API query model together.
- Frontend tests: `src/test/utils.tsx` has `renderWithClient`, `mockApi` (stubs fetch and records calls) and data builders. Seed the QueryClient cache instead of mounting a router; prices contain non-breaking spaces, so normalize the expected text. Radix menus and checkboxes work in jsdom without polyfills.
- React keys must be stable ids (Biome forbids array indexes): sizes use `variation_id`, images their URL after de-duplication.

### Local environment

- Stopping dev servers: `pkill -f 'salevault serve'` also matches the shell that runs it and kills that very command (exit 144). Use `fuser -k 8000/tcp 5173/tcp`.
- Checking the UI in a browser: follow the `check-the-ui` skill (it runs on a copy of the data and never starts a scrape).
- The nine skill links in `.agents/skills/` and `.claude/skills/` are symlinks (Claude Code reads only `.claude/skills/`; other agents read `.agents/skills/`). A checkout without symlink support (Windows outside WSL) turns them into text files: `just links` checks them (`just setup` warns), `just relink` restores them after `git config core.symlinks true`. Add a new link with `ln -s`, never as a copy.

## Conventions

- **Language:** everything in the repository is in English: code, comments, docs, commit messages, UI text. Product data stays in Ukrainian, as the site provides it. Chat with the user in the language they use.
- **Tone for public files:** neutral and factual about the shops; no vendor names of their protection, no wording that suggests evasion. The disclaimer lives in `README.md`.
- **Markdown style:** plain ASCII only. No emojis, no special symbols (arrows, check marks, typographic quotes, ellipsis characters, currency signs), no em or en dashes. Use `-`, `->`, `>=`, `...` instead.
- **Commits:** a single line in Conventional Commits format, `type(scope): summary`, lowercase and imperative, at most 100 characters, e.g. `feat(scraper): add price segmentation`. Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `build`, `perf`. No body, no trailers.
- `just check` must pass before every commit; commit and push only when the user asks.
- If a new tool needs sudo, ask the user to install it instead of working around it.

## Engineering rules

- **Scraping rules (hard rule, see `docs/concepts/scraping.md`):** read only the public catalog, through the shop's own JSON API or, when robots.txt disallows the API, through its catalog pages (ADR-0006); keep the default pace (random 0.8-1.6 s per worker); respect robots.txt; on repeated 403/429 stop the run and report, never continue another way. Transports: the HTTP client (curl_cffi with its Chrome profile, the owner's choice) and a stock Playwright Chromium. Off-limits: proxies or IP rotation, CAPTCHA solving, stealth plugins, raising the pace, touching login or account pages. Anything that sends requests to a shop (scrapes, live tests, robots.txt checks) needs the user's go-ahead.
- Money is stored as integer minor units (`*_minor`); the API returns whole UAH.
- Site-specific logic lives only in adapters (`scraper/sites/`). The core, DB, API and UI stay site-agnostic.
- Validate external data with Pydantic. On a schema mismatch, fail loudly and save the raw response.
- Tests never hit the network, except the ones marked `live` (run manually: `pytest -m live`).
