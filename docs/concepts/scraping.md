# How a scrape works

A run reads every item of one shop's sale section and merges it into the catalog. This page explains how it does that and the rules it follows. To run scrapes, see [Collecting data](../guides/scraping.md).

## Rules the scraper follows

saleVault is a personal, non-commercial tool. It is built to read a shop the way one person browsing the sale would, only more patiently.

- **Public data only.** It reads the public sale catalog: no login, no account, no checkout, no personal data.
- **The shop's own API.** It uses the same JSON catalog API that the shop's website calls in your browser, instead of parsing pages.
- **Polite pace.** Each worker waits a random 0.8 to 1.6 s after every request. PRM uses one worker, Answear.ua two. A run is also capped at 3,000 requests.
- **robots.txt.** The paths it uses (the start page, the sale page, the catalog API) are not disallowed by the shops' `robots.txt`. It never touches disallowed paths such as cart, checkout or account pages.
- **Stops when refused.** On HTTP 403 or 429 it pauses once for 60 s and retries; if the shop refuses again, the run stops and reports it.
- **No evasion tooling.** No proxies or IP rotation, no CAPTCHA solving, no stealth browser plugins.
- **Nothing is redistributed.** Data stays in a local database on your machine. The repository contains no scraped data.

## Transports

A transport is how requests reach the shop. Both apply the rules above in the same way.

- **HTTP** (`http`): curl_cffi, a lightweight HTTP client that uses its built-in Chrome profile, so the shop sees a client with the network fingerprint of a regular Chrome browser. No browser window.
- **Browser** (`browser`): a real Chromium started by Playwright. It opens the shop's start page like a visitor, then calls the catalog API with `fetch` from that page, exactly as the shop's own frontend does. The shops do not serve Playwright's headless mode, so the browser runs as a normal visible window (through WSLg on Windows).
- **Auto** (`auto`, the default): try the HTTP client; if the shop does not accept it on the start page, use the browser.

Background: [ADR-0002](../decisions/0002-fetching-through-the-shop-api.md).

## Segmentation

The catalog API returns 80 items per page and at most 125 pages for one query, so one query can reach at most 10,000 items. Bigger catalogs are split into segments that each fit:

1. A first request without filters returns the total count, the gender facet and the price range.
2. The catalog is split by gender. Any segment above 9,600 items (96% of the cap, leaving room for changes during the run) is split in two by price, `[low, mid]` and `[mid + 1, high]`, until it fits.
3. The first page of every segment is fetched while planning and reused.
4. Inside a segment, pages are fetched in the shop's popularity order, which keeps pages the most stable.

Splitting by gender first also tags items: an item seen in both the men and women segments is unisex. Details and alternatives: [ADR-0003](../decisions/0003-segmentation-by-gender-and-price.md).

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

1. **Start.** The run takes a per-shop lock (at most one active run per shop). A run whose process is gone, or that has not reported progress for 15 minutes, is marked failed first. The browser opens only after the lock is taken.
2. **Plan.** The segment plan is stored with the run, so a resumed run continues the same plan.
3. **Fetch.** Every page is staged in the database and recorded as a checkpoint; progress is updated as it goes. Each response is validated: a malformed page fails the run with a contract error, while a single malformed item is skipped and counted.
4. **Check.** A run is complete when every segment reached 98% of its count and the whole run 99% of the shop's total.
5. **Merge.** One transaction merges the staged items into the catalog, writes price history and computes the statistics. Items not seen are only counted against them on a `success` run, and leave the sale after two successful runs in a row without them; a single miss changes nothing.
6. **Clean up.** Staging is cleared, statistics are refreshed (`ANALYZE`), and the database is compacted if a lot of space is free.

Transient problems (timeouts, network errors, 5xx) are retried up to 4 times with backoff of 2, 4, 8 and 16 s. `--resume` continues a failed or cancelled run from its checkpoints. If the merge itself fails, it is rolled back and the staged pages stay, so a resume simply merges again. Background: [ADR-0004](../decisions/0004-price-history-and-staged-runs.md).

## Categories

The API can return the shop's full category tree on the first request; the run stores it and the merge takes parents and depth from it. Each item is linked to its categories and all their ancestors, so filtering on a branch finds everything below it. Background: [ADR-0005](../decisions/0005-category-tree-from-the-api.md).

## Memory

A run keeps only light summaries in memory: item ids with their gender bits, per-segment ids, a discount histogram and the top 50 items. Full records stay in the database staging table; only `--dry-run` and `--jsonl` keep them in memory. A 140,000-item run peaks at about 0.5 GB.
