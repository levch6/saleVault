set shell := ["bash", "-euo", "pipefail", "-c"]

backend := "backend"
frontend := "frontend"

# Pinned generator toolchain: openapi-typescript needs the classic TS 5 compiler API,
# while the app itself type-checks with TS 7.

openapi_ts := "--package openapi-typescript@7.13.0 --package typescript@5.9.3 openapi-typescript"

# List available recipes
default:
    @just --list --unsorted

# Install all dependencies: Python (uv), Playwright Chromium, Node (pnpm)
setup:
    cd {{ backend }} && uv sync
    cd {{ backend }} && uv run playwright install chromium
    cd {{ frontend }} && pnpm install

# Backend on :8000 with reload + Vite on :5173; Ctrl+C (or a crash of either) stops both
dev:
    #!/usr/bin/env bash
    set -euo pipefail
    trap 'kill $(jobs -p) 2>/dev/null || true' EXIT
    (cd {{ backend }} && uv run salevault serve --reload) &
    (cd {{ frontend }} && ./node_modules/.bin/vite) &
    wait -n

# Build the UI and serve UI + API from a single process on :8000
start: build
    cd {{ backend }} && uv run salevault serve

# Scrape a site's sale section (dry run until DB storage lands), e.g. `just scrape prm --top 50`
scrape site *args:
    cd {{ backend }} && uv run salevault scrape {{ site }} --dry-run {{ args }}

# Build the frontend into frontend/dist
build:
    cd {{ frontend }} && pnpm build

# Lint, format check and type check everything
lint:
    cd {{ backend }} && uv run ruff check . && uv run ruff format --check . && uv run mypy
    cd {{ frontend }} && pnpm exec biome check . && pnpm exec tsc -b

# Auto-format and apply safe lint fixes
fmt:
    cd {{ backend }} && uv run ruff check --fix . && uv run ruff format .
    cd {{ frontend }} && pnpm exec biome check --write .

# Run all tests (no network)
test:
    cd {{ backend }} && uv run pytest
    cd {{ frontend }} && pnpm exec vitest run

# Lint + test; run before every commit
check: lint test

# Regenerate frontend API types from the FastAPI OpenAPI schema
gen-api:
    #!/usr/bin/env bash
    set -euo pipefail
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT
    (cd {{ backend }} && uv run salevault openapi --out "$tmp/openapi.json")
    cd {{ frontend }} && pnpm dlx {{ openapi_ts }} "$tmp/openapi.json" -o src/api/schema.d.ts
