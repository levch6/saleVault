# How a scrape works

A run reads every item of one shop's sale section and merges it into the catalog. This page explains how it does that and the rules it follows. To run scrapes, see [Collecting data](../guides/scraping.md).

## Rules the scraper follows

saleVault is a personal, non-commercial tool. It is built to read a shop the way one person browsing the sale would, only more patiently.

- **Public data only.** It reads the public sale catalog: no login, no account, no checkout, no personal data.
- **The shop's own data, the shop's own way.** It uses the same JSON catalog API that the shop's website calls in your browser. When a shop's `robots.txt` disallows that API (Footshop), it reads the catalog pages instead, the same pages a visitor loads, and takes the product list from the data embedded in them.
- **Polite pace.** Each worker waits a random 0.8 to 1.6 s after every request. PRM and Footshop use one worker, Answear.ua two. A run may make at most 25% more requests than the pages it planned (and never more than 10,000).
- **robots.txt.** The paths it uses (the start page, the sale page, the catalog API or the catalog pages) are not disallowed by the shops' `robots.txt`. It never touches disallowed paths such as the cart, checkout, account pages or, for Footshop, its API.
- **Stops when refused.** The first HTTP 403 or 429 of a run pauses every worker for 60 s; any further refusal in the same run stops it and reports it.
- **No evasion tooling.** No proxies or IP rotation, no CAPTCHA solving, no stealth browser plugins.
- **Nothing is redistributed.** Data stays in a local database on your machine. The repository contains no scraped data.

## Transports

A transport is how requests reach the shop. Both apply the rules above in the same way.

- **HTTP** (`http`): curl_cffi, a lightweight HTTP client that uses its built-in Chrome profile, so the shop sees a client with the network fingerprint of a regular Chrome browser. No browser window.
- **Browser** (`browser`): a real Chromium started by Playwright. It opens the shop's start page like a visitor, then calls the catalog API with `fetch` from that page, exactly as the shop's own frontend does, or, for a shop read through its catalog pages, navigates from page to page. PRM and Answear.ua do not serve Playwright's headless mode, so the browser runs as a normal visible window (through WSLg on Windows).
- **Auto** (`auto`, the default): try the HTTP client; if the shop answers its start page with 403, before any catalog request, use the browser. That is the only case that switches clients: a 429 asks for less traffic and stops the run, and so does a network error.

Background: [ADR-0002](../decisions/0002-fetching-through-the-shop-api.md) and, for catalog pages, [ADR-0006](../decisions/0006-reading-catalog-pages.md).

## Segmentation

The Answear platform's catalog API returns 80 items per page and at most 125 pages for one query, so one query can reach at most 10,000 items. Bigger catalogs are split into segments that each fit:

1. A first request without filters returns the total count, the gender facet and the price range.
2. The catalog is split by gender. Any segment above 9,600 items (96% of the cap, leaving room for changes during the run) is split in two by price, `[low, mid]` and `[mid + 1, high]`, until it fits.
3. The first page of every segment is fetched while planning and reused.
4. Inside a segment, pages are fetched in the shop's popularity order, which keeps pages the most stable.

Splitting by gender first also tags items: an item seen in both the men and women segments is unisex. Details and alternatives: [ADR-0003](../decisions/0003-segmentation-by-gender-and-price.md).

Footshop's catalog pages hold 24 items each and have no depth limit. Its segments are the sale sections that the shop's own men's, women's and kids' menus link to; there is no price split. The first request is the sale page itself, which gives the total count.

## Run lifecycle

```
running --+-- every segment complete ---------> merge ---------------------> success
          |
          +-- a segment short, or debug limit --> merge (remove nothing) ---> partial
          |
          +-- error or refused by the shop -----> keep staged pages --------> failed
          |
          +-- Ctrl+C or Cancel -----------------> keep staged pages --------> cancelled
```

1. **Start.** The run takes a per-shop lock (at most one active run per shop, enforced by a unique index). A run whose process is gone, or that has not reported progress for 15 minutes, is marked failed first; the app also marks such runs whenever it lists them. The process is identified by its pid and start time, so a reused pid never counts as the scraper. The browser opens only after the lock is taken.
2. **Plan.** The segment plan is stored with the run, so a resumed run continues the same plan.
3. **Fetch.** Every page is staged in the database and recorded as a checkpoint; progress (and, while planning, a heartbeat) is updated as it goes. Each response is validated: a malformed page fails the run with a contract error and the response is archived. A single malformed item is skipped and counted, but more than 20% of a page means the shop changed its schema, and the run fails instead of fetching the rest for nothing.
4. **Check.** A run is complete when every segment reached 98% of its count and the whole run 99% of the shop's total.
5. **Merge.** One transaction merges the staged items into the catalog, writes price history, computes the statistics and records the run's status, so the catalog never shows a merged run that is still `running`. Items not seen are only counted against them on a `success` run, and leave the sale after two successful runs in a row without them; a single miss changes nothing.
6. **Clean up.** Staging is cleared, statistics are refreshed (`ANALYZE`), and the database is compacted if a lot of space is free.

Transient problems (timeouts, network errors, 5xx) are retried up to 4 times with backoff of 2, 4, 8 and 16 s. `--resume` continues a failed or cancelled run from its checkpoints. If the merge itself fails, it is rolled back and the staged pages stay, so a resume simply merges again. Background: [ADR-0004](../decisions/0004-price-history-and-staged-runs.md).

## Categories

The Answear platform's API can return the shop's full category tree on the first request; the run stores it and the merge takes parents and depth from it. Each item is linked to its categories and all their ancestors, so filtering on a branch finds everything below it. Background: [ADR-0005](../decisions/0005-category-tree-from-the-api.md).

Footshop's listing names only an item's main category (for example men's shoes or wallets), so its categories form a flat list.

## Memory

A run keeps only light summaries in memory: item ids with their gender bits, per-segment ids, a discount histogram and the top 50 items. Full records stay in the database staging table; only `--dry-run` and `--jsonl` keep them in memory. A 140,000-item run peaks at about 0.5 GB.
