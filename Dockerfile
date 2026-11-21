# syntax=docker/dockerfile:1
# check=error=true

# saleVault in one image: the built UI, the API and the scraper, with a Chromium for shops that
# do not accept the HTTP client. Quick start: `docker compose up --build`, then
# http://localhost:8000. See docs/guides/docker.md and docs/decisions/0010-container-image.md.
#
# Base images are pinned by digest; Dependabot proposes updates.

FROM ghcr.io/astral-sh/uv:0.13.9@sha256:d3b601f0c7b118bc1753febf7c41cc80981df678445e0254284eecf84db79a7d AS uv


# --- The UI --------------------------------------------------------------------------------------
FROM node:26-trixie-slim@sha256:e6bedef217677b276c591795e169840edd9096dbf13f29df8ef8d1856b8820bc AS frontend

ENV CI=true
WORKDIR /src/frontend
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
# pnpm at the version `packageManager` names (Node no longer ships Corepack).
RUN npm install --global --no-fund --no-audit "$(node -p 'require("./package.json").packageManager')"
RUN --mount=type=cache,id=pnpm-store,target=/pnpm/store \
    pnpm fetch --frozen-lockfile --store-dir /pnpm/store
COPY frontend/ ./
RUN --mount=type=cache,id=pnpm-store,target=/pnpm/store \
    pnpm install --offline --frozen-lockfile --store-dir /pnpm/store \
    && pnpm build


# --- Python packages ---------------------------------------------------------------------------
FROM python:3.15-slim-trixie@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928 AS backend

COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src/backend
# Dependencies first, so code changes do not reinstall them.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=backend/uv.lock,target=uv.lock \
    --mount=type=bind,source=backend/pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project
COPY backend/pyproject.toml backend/uv.lock ./
COPY backend/src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable


# --- The app ---------------------------------------------------------------------------------
FROM python:3.15-slim-trixie@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928 AS app

LABEL org.opencontainers.image.title="saleVault" \
      org.opencontainers.image.description="Personal price tracker for fashion sales, sorted by discount" \
      org.opencontainers.image.source="https://github.com/levch6/saleVault" \
      org.opencontainers.image.licenses="MIT"

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    SALEVAULT_DATA_DIR=/app/data \
    SALEVAULT_FRONTEND_DIST=/app/frontend/dist \
    SALEVAULT_HOST=0.0.0.0 \
    SALEVAULT_CONTAINER=1

COPY --from=backend /app/.venv /app/.venv
# Keep downloaded packages in BuildKit's cache instead of the image, so rebuilds do not fetch
# them again.
RUN rm -f /etc/apt/apt.conf.d/docker-clean \
    && echo 'Binary::apt::APT::Keep-Downloaded-Packages "true";' > /etc/apt/apt.conf.d/keep-cache
# Chromium with the libraries it needs, and a virtual display: the shops refuse Playwright's
# headless mode, so the browser runs headed on Xvfb. tini reaps the browser's child processes;
# Playwright's own Node driver needs libatomic.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    apt-get update \
    && apt-get install --yes --no-install-recommends libatomic1 tini xvfb xauth \
    && playwright install --with-deps --no-shell chromium
RUN useradd --uid 1000 --shell /usr/sbin/nologin app \
    && mkdir -p /app/data \
    && chown app:app /app/data
COPY --from=frontend /src/frontend/dist /app/frontend/dist

USER app
WORKDIR /app
VOLUME ["/app/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"]
ENTRYPOINT ["tini", "--", "xvfb-run", "--auto-servernum", "--server-args=-screen 0 1440x900x24"]
CMD ["salevault", "serve"]
