# Command line

## `just` recipes

Run from the repository root. `just` without arguments lists them.

| Recipe | What it does |
|---|---|
| `just setup` | install Python deps (uv), Playwright Chromium, Node deps (pnpm), then the git hooks |
| `just start` | build the UI, serve UI + API on http://localhost:8000 and open the browser once it is up |
| `just dev` | API with auto-reload on :8000 + Vite on :5173 |
| `just open` | open the app in the default browser (the Windows one under WSL) |
| `just scrape <shop> [options]` | `salevault scrape`, see below |
| `just runs [options]` | `salevault runs`, see below |
| `just backup` | copy the database to `data/backups/` (keeps 5) |
| `just vacuum` | compact the database file |
| `just db-upgrade` | apply pending migrations (done automatically on start) |
| `just recategorize` | put every product in the shared category tree again and show how well each shop is covered (done automatically on start when the rules changed) |
| `just shortcut` | Windows only: put a saleVault shortcut with the app icon on the desktop |
| `just build` | build the UI into `frontend/dist` |
| `just check` | `just lint` + `just test`; what CI runs |
| `just lint` | ruff, mypy, Biome, tsc, typos, zizmor, ASCII Markdown check |
| `just test` | pytest and Vitest (offline) |
| `just fmt` | auto-format and apply safe fixes |
| `just gen-api` | regenerate the frontend API types from the OpenAPI schema |
| `just hooks` | install the git hooks and build their tools (gitleaks, actionlint) |
| `just hooks-update` | bump the pinned revisions of the remote hooks (releases older than 7 days) |

## `salevault`

The Python CLI. Run it as `cd backend && uv run salevault ...`, or through the `just` recipes.

### `salevault scrape`

```
salevault scrape SITE [OPTIONS]
```

Scrape the sale section of a shop and merge it into the local catalog. `SITE` is a shop code (`prm`, `answear_ua`, `footshop_ua`, `saks85`, `modivo_ua`) or `all`.

| Option | Default | Meaning |
|---|---|---|
| `--dry-run` | off | collect and summarize, write nothing to the database |
| `--resume` | off | continue the shop's last failed or cancelled run |
| `--transport auto\|browser\|http` | per shop (`auto`) | how to reach the shop, see [transports](../concepts/scraping.md#transports) |
| `--headed` / `--headless` | per shop | visible browser window or headless (browser transport only) |
| `--max-pages N` | none | debug: at most N pages per segment; the run is always `partial` |
| `--save-raw` / `--no-save-raw` | save | archive raw API responses in `data/raw/` (last 2 runs) |
| `--jsonl PATH` | none | also write the normalized items to a JSONL file |
| `--top N` | 20 | how many top discounts to print in the summary |
| `-v`, `--verbose` | off | debug logging |

Exit codes: 0 on `success` or `partial`, 1 on failure, 130 after Ctrl+C, 143 after SIGTERM.

### `salevault runs`

```
salevault runs [--site CODE] [--limit N]
```

Recent runs, newest first (default 20), with status, duration, items and catalog changes.

### `salevault db`

| Command | Meaning |
|---|---|
| `db upgrade` | apply pending migrations |
| `db recategorize` | categorize every product again with the current rules and print the share of each shop's active items in a specific category, a group's catch-all and Other |
| `db backup [--keep N]` | consistent copy into `data/backups/`, keeping the newest N (default 5) |
| `db vacuum` | compact the database file |

### `salevault serve`

```
salevault serve [--host HOST] [--port PORT] [--reload]
```

Run the API server; it also serves the built UI when `frontend/dist` exists. Host and port default to the [settings](configuration.md) (`127.0.0.1:8000`).

### Other commands

- `salevault openapi --out PATH`: write the OpenAPI schema (used by `just gen-api`).
- `salevault version`: print the version.
