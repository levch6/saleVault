# saleVault

[![check](https://github.com/levch6/saleVault/actions/workflows/check.yml/badge.svg)](https://github.com/levch6/saleVault/actions/workflows/check.yml)

A personal, local tool that collects the sale sections of fashion shops and shows every item **sorted by discount, biggest first**, which the shops' own websites do not offer.

Supported shops: **PRM** (prm.com/ua), **Answear.ua**, **Footshop** (footshop.ua), **Saks85** (saks85.com) and **Modivo** (modivo.ua).

- Catalog sorted by discount, or by the "honest" discount (against the lowest price of the last 30 days, where the shop reports it), savings, price or newest
- Filters with live counts: shop, gender, one category tree for all shops (jackets from every shop in one click), brand (one entry across shops), size in stock, price, minimum discount, text search
- **Only my sizes**: save your sizes once and see only items you can actually buy
- **NEW** and **cheaper** badges since the previous run, and a price history chart for every item
- Favorites that show how the price moved since you starred an item
- Data refresh from the app (with progress and cancel) or from the terminal; interrupted runs can be resumed

Everything runs on your own computer. Nothing is hosted, there is no account, and the data stays in a local SQLite database.

## How it treats the shops

saleVault reads only the public sale catalog, through the same JSON API that the shop's website uses or, where the shop's `robots.txt` disallows that API, through its catalog pages, at about one request per second. By default it uses a lightweight HTTP client that presents the network profile of a regular Chrome browser, and a real Chromium window when a shop does not accept that client. It follows `robots.txt`, never logs in or touches account pages, and if a shop refuses requests it pauses once and then stops the run. It uses no proxies, no CAPTCHA solving and no stealth plugins. Details: [How a scrape works](docs/concepts/scraping.md#rules-the-scraper-follows).

## Quick start

Requirements: Linux or WSL2 on Windows 11, [uv](https://docs.astral.sh/uv/), Node.js 26 with [pnpm](https://pnpm.io/) 12, and [just](https://just.systems/).

```bash
git clone https://github.com/levch6/saleVault.git && cd saleVault
just setup            # Python and Node packages, Playwright Chromium, git hooks
just scrape prm       # first data: about 17,500 items, 5 to 10 minutes
just start            # open http://localhost:8000
```

The [getting started](docs/getting-started.md) tutorial walks through it step by step.

## Documentation

- [Getting started](docs/getting-started.md)
- Guides: [collecting data](docs/guides/scraping.md), [maintenance](docs/guides/maintenance.md), [development](docs/guides/development.md), [adding a shop](docs/guides/adding-a-shop.md)
- Concepts: [architecture](docs/concepts/architecture.md), [how a scrape works](docs/concepts/scraping.md), [prices, discounts and badges](docs/concepts/prices-and-badges.md)
- Reference: [command line](docs/reference/cli.md), [HTTP API](docs/reference/http-api.md), [configuration](docs/reference/configuration.md), [data model](docs/reference/data-model.md)
- [Architecture decision records](docs/decisions/README.md)

## Project status

A personal project, maintained in spare time. Issues and small pull requests are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md). Security reports: [SECURITY.md](SECURITY.md).

## Disclaimer

saleVault is an independent, unofficial and non-commercial project. It is not affiliated with, authorized, sponsored or endorsed by PRM, Answear, Footshop, Saks85, Modivo or any of their affiliates. Shop names and trademarks belong to their respective owners and are used here only to identify the websites the tool works with.

- The tool is meant for personal use: browsing public sale catalogs more conveniently on your own computer. It is not intended for commercial use, for bulk collection or for republishing shop data.
- The project does not sell, publish or redistribute any shop data. This repository contains no scraped data; test fixtures are anonymized.
- You are solely responsible for how you use the software, including compliance with each shop's terms of use, its `robots.txt` and the laws that apply to you.
- The software is provided "as is", without warranty of any kind, as stated in the [license](LICENSE). The authors accept no liability for any use of it.

If you represent one of these shops and have concerns about this project, please open an issue. It will be answered promptly, and support for your shop will be removed on request.

## License

[MIT](LICENSE)
