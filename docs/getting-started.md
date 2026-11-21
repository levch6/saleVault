# Getting started

This tutorial takes you from a fresh clone to a catalog of sale items sorted by discount. It takes about 15 minutes, most of it waiting for the first scrape.

## 1. Check the requirements

- Linux, or WSL2 on Windows 11. The browser transport opens a regular Chromium window; on WSL2 it appears through WSLg.
- [uv](https://docs.astral.sh/uv/) (installs Python 3.15 for the project by itself).
- Node.js 26 (see `.node-version`; [fnm](https://github.com/Schniz/fnm) picks it up) with [pnpm](https://pnpm.io/) 12.
- [just](https://just.systems/), the task runner used for every project command.

Nothing needs `sudo`.

## 2. Install

```bash
git clone https://github.com/levch6/saleVault.git
cd saleVault
just setup
```

`just setup` installs the Python packages (uv), the Playwright Chromium build, the frontend packages (pnpm) and the git hooks.

## 3. Collect the first data

```bash
just scrape prm
```

The scraper reads the shop's sale catalog through the shop's own catalog API, about one request per second. You see a progress bar and, at the end, a summary with the deepest discounts. PRM has about 17,500 sale items and takes 5 to 10 minutes. Depending on the transport, a Chromium window may appear during the run; leave it open.

Other shops: `just scrape answear_ua` (about 140,000 items, 30 to 40 minutes) or `just scrape all`.

## 4. Open the app

```bash
just start
```

This builds the UI, starts a single server on http://localhost:8000 and opens it in your browser (the Windows browser when you run under WSL). Stop it with Ctrl+C.

On Windows you can also run `just shortcut` once: it adds a saleVault shortcut with the app icon to the desktop, which starts the app in WSL and opens the browser.

## 5. Look around

- **Catalog:** every active sale item, biggest discount first. The sidebar filters by shop, gender, discount, price, category, brand and size in stock; every filter shows live counts. The search box (press `/`) matches brand, name, subtitle and color. All filters live in the URL, so a view can be bookmarked.
- **Settings:** save your sizes once, then turn on **Only my sizes** above the grid to see only items you can actually buy.
- **Item drawer:** click a picture for the gallery, sizes with availability, the price history chart and a link to the item on the shop site.
- **Favorites:** star items to follow their price; the Favorites page shows how the price moved since you starred them.
- **Refresh:** the button in the header starts a new scrape of one shop or all of them and shows its progress. After the second run of a shop, items get **NEW** and **cheaper** badges.

## Next steps

- [Collecting data](guides/scraping.md): resuming, cancelling, transports and troubleshooting.
- [Maintenance](guides/maintenance.md): backups and keeping the database small.
- [How a scrape works](concepts/scraping.md), including the rules the scraper follows.
