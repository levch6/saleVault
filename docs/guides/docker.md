# Running with Docker

The container image runs the whole app (UI, API and scraper, with a Chromium for shops that do not accept the HTTP client) without installing Python, Node.js, Playwright or `just`. For development, use the native setup in [Getting started](../getting-started.md). Background: [ADR-0010](../decisions/0010-container-image.md).

## Requirements

Docker Engine with the Compose plugin, or Docker Desktop. On Windows use Docker Desktop with the WSL 2 backend and clone the repository inside WSL (for example `~/Projects`), not under `C:\`.

## Start

```bash
git clone https://github.com/levch6/saleVault.git
cd saleVault
docker compose up --build
```

The first build takes several minutes and makes an image of about 1.7 GB; later builds reuse the cached layers. Then open http://localhost:8000. The catalog is empty until the first scrape: press **Refresh** in the header, or run one from the terminal:

```bash
docker compose run --rm app salevault scrape prm
```

Stop with Ctrl+C, or run `docker compose up --build --detach` and later `docker compose down`.

## Where the data lives

The database, backups, logs and the browser profile are in the named volume `salevault-data`. They survive restarts, rebuilds and `docker compose down`; only `docker compose down --volumes` deletes them.

To use the `data/` folder of the repository instead (for example to share it with a native setup), create it first so it belongs to you, then point Compose at it:

```bash
mkdir -p data
SALEVAULT_DATA=./data docker compose up --build
```

The container runs as user id 1000. If your user id is different, pass it along: `UID=$(id -u) GID=$(id -g) SALEVAULT_DATA=./data docker compose up --build`.

## Commands

Every `salevault` command works through Compose; see the [command line reference](../reference/cli.md).

| Task | Command |
|---|---|
| scrape a shop | `docker compose run --rm app salevault scrape answear_ua` |
| list recent runs | `docker compose run --rm app salevault runs` |
| back up the database | `docker compose run --rm app salevault db backup` |
| copy the backups out (while it runs) | `docker compose cp app:/app/data/backups ./backups` |
| update | `git pull`, then `docker compose up --build` |

Migrations run automatically on start, with a backup first.

## How it is put together

- One image from the repository root: the UI is built with pnpm, the Python packages are installed with uv, and the final stage on `python:3.15-slim` adds Chromium, its system libraries and a virtual display (Xvfb). Base images are pinned by digest.
- The browser runs as a normal (headed) window on the virtual display, as in a native setup; the shops refuse Playwright's headless mode. Runs use the HTTP client first anyway ([transports](../concepts/scraping.md#transports)).
- The port is published on `127.0.0.1` only: the API has no authentication and can start scrapes. Keep it that way.
- The app runs as an unprivileged user; `tini` reaps the browser's processes; Chromium gets 1 GB of shared memory (`shm_size`).

## Troubleshooting

| Symptom | Fix |
|---|---|
| `permission denied` on the data folder | the folder belongs to another user: `sudo chown -R $(id -u):$(id -g) data`, or pass `UID`/`GID` as above |
| port 8000 is taken | change the left side of `ports` in `compose.yaml`, for example `127.0.0.1:8080:8000` |
| `database is locked` on Windows | the repository is on a Windows drive; clone it inside WSL |
| the browser crashes | keep `shm_size: 1gb` in `compose.yaml` |
