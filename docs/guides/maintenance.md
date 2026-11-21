# Maintenance

Everything saleVault stores lives in the `data/` directory of the project (configurable, see [configuration](../reference/configuration.md)). Nothing leaves your machine.

## What is in `data/`

```
data/
  salevault.db        the catalog, price history, favorites and settings (SQLite)
  backups/            copies made by `just backup` (the last 5 are kept)
  raw/<shop>/         gzipped API responses of the last 2 runs per shop, for debugging
  logs/               output of runs started from the app (the last 20 are kept)
  browser/<shop>/     the browser profile used by the browser transport
```

## Back up

```bash
just backup
```

Writes a consistent copy of the database to `data/backups/salevault-<UTC time>.db` and keeps the 5 newest. It uses the SQLite backup API, so it is safe while the app or a scrape is running. To restore, stop the app and copy a backup over `data/salevault.db`.

## Keep the database small

Each run stages its pages in the database and deletes them after merging. SQLite keeps the freed space for reuse, so the file can grow after big runs. After every run the scraper checks the free space and compacts the file (`VACUUM`) when more than 100 MB is free. To compact by hand:

```bash
just vacuum
```

A two-shop catalog (about 160,000 items) takes about 240 MB after compaction.

## Logs and archives

- Raw API responses of the last 2 runs of each shop are kept in `data/raw/<shop>/`. Turn this off for a run with `--no-save-raw`.
- Logs of runs started from the app are kept in `data/logs/` (the 20 newest). Runs started from the terminal print to the terminal.

## Upgrade

```bash
git pull
just setup
```

Database migrations run automatically when the app or a scrape starts; `just db-upgrade` applies them by hand. Before migrating an existing database, a backup is written to `data/backups/`.

## Troubleshooting the app

| Symptom | What to do |
|---|---|
| `just start` fails with "address already in use" | Another instance is running: close it, or start on another port with `cd backend && uv run salevault serve --port 8001`. |
| The app shows "API offline" | The server is not running: start it with `just start`. |
| The database file is large | `just vacuum` |

Problems with scrapes are covered in [collecting data](scraping.md#troubleshooting).

## Start over

Stop the app and delete `data/salevault.db` (and `data/raw/` if you like). The next scrape creates a fresh database. Favorites and saved sizes are stored in the database, so back it up first if you want to keep them.
