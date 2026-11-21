# saleVault

A local tool that collects sale items from fashion shops and shows them **sorted by discount, biggest first**. Filters: brand, gender, category, size, price and minimum discount. Also price history, New and Price drop badges, and favorites.

Supported shops: PRM.com (UA), with Answear.ua planned.

> **Status:** early development.

## Quick start

To be added once the project skeleton is in place.

```bash
just setup        # install dependencies (Python via uv, Node via pnpm, Playwright Chromium)
just scrape prm   # collect the current PRM sale (about 5 min)
just start        # then open http://localhost:8000
```
