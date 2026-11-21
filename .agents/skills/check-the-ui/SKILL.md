---
name: check-the-ui
description: Check saleVault's UI in a real browser safely, on a copy of the user's data and without starting a scrape. Use after UI, CSP or API changes, or when the user asks to look at the app.
---

# Check the UI

The app reads the user's real catalog, and its Refresh menu starts real scrapes. So check it on a copy of the data, on a spare port, and never press Refresh, Resume or Cancel.

## 1. Start the app on a copy

```bash
S=$(mktemp -d)                                   # or the agent's scratch directory
sqlite3 data/salevault.db ".backup $S/salevault.db"
(cd frontend && pnpm build)
(cd backend && SALEVAULT_DATA_DIR=$S uv run salevault serve --port 8001 > $S/server.log 2>&1 &)
until curl -sf -o /dev/null http://127.0.0.1:8001/api/health; do sleep 0.5; done
```

Use `just dev` (port 5173) instead only for changes that need hot reload; it runs on the real data, so do not change anything there.

## 2. Look

With the browser automation you have, open `http://127.0.0.1:8001/`:

- The catalog renders, product images load from the shop's CDN, the Geist font is applied.
- Open an item (drawer, gallery, sizes). A price chart needs at least two price points; to see one, add a row to `price_history` in the copy, never in `data/`.
- Filters, sorting, Favorites and Settings work (writes go to the copy).
- The console has no errors and no Content-Security-Policy violations. A `Failed to load resource` for `/api/health` after you stop the server is expected.
- Check the dark theme by emulating `prefers-color-scheme: dark`.

## 3. Clean up

```bash
fuser -k 8001/tcp        # not `pkill -f`: it matches the shell that runs it
rm -rf "$S" .playwright-mcp
```

Report what was checked, what was not, and anything that looked wrong.
