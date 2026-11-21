# Configuration

saleVault works without any configuration. Defaults live in code; a few paths and the server address can be changed with environment variables.

## Environment variables

Set them in the environment or in a `.env` file at the repository root (not committed).

| Variable | Default | Meaning |
|---|---|---|
| `SALEVAULT_DATA_DIR` | `<repo>/data` | where the database, backups, archives, logs and browser profiles live |
| `SALEVAULT_FRONTEND_DIST` | `<repo>/frontend/dist` | the built UI that `salevault serve` serves |
| `SALEVAULT_HOST` | `127.0.0.1` | address the server binds to |
| `SALEVAULT_PORT` | `8000` | port the server listens on |

The server binds to localhost on purpose: the API has no authentication and is meant for your own browser only.

## User settings

Saved sizes are stored in the database (`settings` table) and edited on the Settings page or through `PUT /api/settings`.

## Shop settings

Each shop has a config in `backend/src/salevault/scraper/sites/registry.py`: origin, paths, locale, number of workers, transport, headless mode and the mapping of the shop's gender codes. See [Adding a shop](../guides/adding-a-shop.md) for every field.

## Run defaults

Fixed in code (`RunOptions` in `scraper/runner.py`):

| Setting | Value |
|---|---|
| Pause after each request, per worker | random 0.8 to 1.6 s |
| Request budget per run | 3,000 |
| Retries for timeouts, network errors and 5xx | 4, backoff 2, 4, 8, 16 s plus jitter |
| On 403 or 429 | one 60 s pause, then the run stops if refused again |
| Segment size limit | 96% of what one query can reach (9,600 items) |
| Completeness for `success` | 98% per segment and 99% overall |

## Data directory

```
data/
  salevault.db        SQLite database (WAL mode, so -wal and -shm files appear next to it)
  backups/            just backup
  raw/<shop>/         raw API responses, last 2 runs
  logs/               logs of runs started from the app, last 20
  browser/<shop>/     browser profile for the browser transport
```
