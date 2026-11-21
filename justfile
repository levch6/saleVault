set shell := ["bash", "-euo", "pipefail", "-c"]

backend := "backend"
frontend := "frontend"
url := "http://localhost:8000"

# Pinned generator toolchain: openapi-typescript needs the classic TS 5 compiler API,
# while the app itself type-checks with TS 7.

openapi_ts := "--package openapi-typescript@7.13.0 --package typescript@5.9.3 openapi-typescript"

# List available recipes
default:
    @just --list --unsorted

# Install all dependencies: Python (uv), Playwright Chromium, Node (pnpm), then the git hooks
setup: && hooks
    cd {{ backend }} && uv sync
    cd {{ backend }} && uv run playwright install chromium
    cd {{ frontend }} && pnpm install
    -just links

# Check that the skill links in .agents/ and .claude/ work (a checkout without symlink support,
# for example on Windows outside WSL, turns them into small text files)
links:
    #!/usr/bin/env bash
    set -euo pipefail
    broken=()
    while IFS= read -r link; do
        [ -d "$link" ] || broken+=("$link")
    done < <(git ls-files -s | awk '$1 == "120000" {print $4}')
    if (( ${#broken[@]} )); then
        echo "These skill links do not work: ${broken[*]}" >&2
        echo "On Windows, work inside WSL, or enable symlinks (Developer Mode, then" >&2
        echo "'git config core.symlinks true') and run 'just relink'. The app works either way." >&2
        exit 1
    fi
    echo "Skill links OK"

# Restore the skill links after enabling symlinks (touches only the link paths)
relink:
    #!/usr/bin/env bash
    set -euo pipefail
    git ls-files -s | awk '$1 == "120000" {print $4}' | while IFS= read -r link; do
        rm -f "$link" && git checkout -- "$link"
    done
    just links

# Install the git hooks and build their tools (prek; gitleaks and actionlint take a minute once)
hooks:
    uv run --project {{ backend }} prek install --prepare-hooks

# Bump the pinned revisions of the remote hooks (commit SHAs, releases older than 7 days)
hooks-update:
    uv run --project {{ backend }} prek update --freeze --cooldown-days 7

# Backend on :8000 with reload + Vite on :5173; Ctrl+C (or a crash of either) stops both
dev:
    #!/usr/bin/env bash
    set -euo pipefail
    trap 'kill $(jobs -p) 2>/dev/null || true' EXIT
    (cd {{ backend }} && uv run salevault serve --reload) &
    (cd {{ frontend }} && ./node_modules/.bin/vite) &
    wait -n

# Build the UI, serve UI + API on :8000 and open it in the browser once it is up
start: build
    #!/usr/bin/env bash
    set -euo pipefail
    (for _ in $(seq 1 120); do
        if curl -sf -o /dev/null {{ url }}/api/health; then just open; exit 0; fi
        sleep 0.5
    done) &
    cd {{ backend }} && exec uv run salevault serve

# Open the app in the default browser (the Windows one under WSL)
open:
    #!/usr/bin/env bash
    if command -v explorer.exe >/dev/null; then explorer.exe "{{ url }}" || true
    elif command -v xdg-open >/dev/null; then xdg-open "{{ url }}"
    else echo "Open {{ url }} in a browser"; fi

# Copy the database to data/backups (keeps the last 5; safe while the app runs)
backup:
    cd {{ backend }} && uv run salevault db backup

# Shrink the database file (runs also compact it when it has grown a lot)
vacuum:
    cd {{ backend }} && uv run salevault db vacuum

# Put a saleVault shortcut with the app icon on the Windows desktop (starts the app in WSL)
shortcut:
    #!/usr/bin/env bash
    set -euo pipefail
    # A .bat cannot carry an icon, so the .bat and the .ico live in %LOCALAPPDATA%\saleVault
    # and the desktop gets a .lnk pointing at them.
    case "$PWD" in
        *[%\"]*) echo "The repository path contains % or a quote, which a .bat file cannot hold: $PWD" >&2; exit 1 ;;
    esac
    local_app=$(cmd.exe /c 'echo %LOCALAPPDATA%' 2>/dev/null | tr -d '\r')
    dir="$(wslpath "$local_app")/saleVault"
    mkdir -p "$dir"
    cp {{ frontend }}/public/favicon.ico "$dir/saleVault.ico"
    printf '@echo off\r\ntitle saleVault\r\nwsl.exe -d %s --cd "%s" -- bash -lc "just start"\r\n' \
        "$WSL_DISTRO_NAME" "$PWD" > "$dir/saleVault.bat"
    SV_DIR="$dir" WSLENV=SV_DIR/p powershell.exe -NoProfile -NonInteractive -Command '
        $lnk = Join-Path ([Environment]::GetFolderPath("Desktop")) "saleVault.lnk";
        $s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk);
        $s.TargetPath = Join-Path $env:SV_DIR "saleVault.bat";
        $s.IconLocation = (Join-Path $env:SV_DIR "saleVault.ico") + ",0";
        $s.WorkingDirectory = $env:SV_DIR;
        $s.Description = "Start saleVault";
        $s.Save();
        "Created " + $lnk + " (close its window to stop the app)"' | tr -d '\r'

# Scrape a site into the local DB, e.g. `just scrape prm`, `just scrape prm --resume`, `--dry-run`
scrape site *args:
    cd {{ backend }} && uv run salevault scrape {{ site }} {{ args }}

# Show recent scrape runs, e.g. `just runs --site prm`
runs *args:
    cd {{ backend }} && uv run salevault runs {{ args }}

# Apply pending DB migrations (scrapes do it automatically)
db-upgrade:
    cd {{ backend }} && uv run salevault db upgrade

# Put every product in the shared category tree again and show the coverage per shop
recategorize:
    cd {{ backend }} && uv run salevault db recategorize

# Build the frontend into frontend/dist
build:
    cd {{ frontend }} && pnpm build

# Lint, format check and type check everything (plus spelling, CI security, ASCII Markdown)
lint:
    cd {{ backend }} && uv run ruff check . && uv run ruff format --check . && uv run mypy
    cd {{ frontend }} && pnpm exec biome check . && pnpm exec tsc -b
    uv run --project {{ backend }} typos
    uv run --project {{ backend }} zizmor --offline --quiet .github
    if git grep -n -P '[^\x00-\x7F]' -- '*.md'; then echo "Markdown must be plain ASCII" >&2; exit 1; fi

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
