# ADR-0010: A container image for a one-command start

- **Status:** accepted
- **Date:** 2026-11-21

## Context

A native setup needs uv, Node.js with pnpm, `just`, Playwright's Chromium with its system libraries, and a build of the UI. That is fine for development but a lot for someone who only wants to run the app. A container was not worth it while every scrape needed a visible browser window; since the HTTP client became the default transport (ADR-0002) the browser is only a fallback, and a headed Chromium can run on a virtual display.

## Decision

1. One image, built from the repository root with a multi-stage `Dockerfile`: the UI is built with pnpm on Node, the Python packages are installed with uv (dependencies before the code, cache mounts, bytecode compiled), and the final stage on `python:3.15-slim` holds the virtual environment, the built UI, Chromium with its libraries (`playwright install --with-deps --no-shell chromium`) and Xvfb. `Dockerfile`, `compose.yaml` and `.dockerignore` live at the root, as `docker init` and Compose expect; there is a single image and no helper script, so no `docker/` folder.
2. The browser runs headed on Xvfb (`xvfb-run` wraps the server, so UI-started runs inherit the display), because the shops refuse Playwright's headless mode. It is the same stock Chromium as in a native setup; the scraping rules do not change. `tini` is PID 1 so the browser's processes are reaped.
3. The image runs as an unprivileged user, has a health check on `/api/health` and OCI labels. Base images are pinned by digest, the Dockerfile opts into Docker's build checks with `check=error=true`, and Dependabot updates the base images.
4. `compose.yaml` publishes the port on `127.0.0.1` only (the API has no authentication), keeps the data in a named volume (or `./data` when `SALEVAULT_DATA` points there) and gives Chromium 1 GB of shared memory. The image contains no data; every user collects their own.
5. CI builds the image with the GitHub Actions cache when its inputs change (and monthly), checks the Dockerfile and `compose.yaml`, starts the app and opens `about:blank` in the headed Chromium. Nothing is published and no shop is contacted.

## Alternatives considered

- **Microsoft's Playwright image:** carries all three browsers (about 2 GB) and the distribution's Python instead of 3.15, and is meant for testing.
- **Docker Hardened Images:** free and smaller, but pulling them needs `docker login dhi.io`, which defeats the one-command start.
- **An image without Chromium:** about 700 MB smaller, but a shop that refuses the HTTP client would stop every run in the container. Rejected by the owner for a complete image.
- **`ipc: host`:** what Playwright suggests for Chromium's shared memory; a sized `shm_size` gives the same without sharing the host's IPC namespace.
- **Publishing the image (GHCR):** not needed while `docker compose up --build` builds it in a few minutes; can come later with release tags.

## Consequences

- `git clone` and `docker compose up --build` are enough; the first start builds for several minutes, and the image is about 1.7 GB (Chromium with its fonts and graphics libraries is most of it). Downloaded system packages stay in BuildKit's cache, so rebuilds are quick.
- The native setup (`just setup`) stays the way to develop; the image is for running the app.
- On Windows the repository should be cloned inside WSL: SQLite in WAL mode is unreliable on bind mounts of Windows paths, and the default named volume avoids that entirely.
