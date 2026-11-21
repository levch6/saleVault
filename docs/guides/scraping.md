# Collecting data

A scrape (a "run") reads one shop's sale catalog and merges it into the local database. This guide covers starting, watching, cancelling and resuming runs. For what happens inside a run, see [How a scrape works](../concepts/scraping.md).

## Start a run

From the terminal:

```bash
just scrape prm            # one shop
just scrape answear_ua
just scrape footshop_ua
just scrape saks85
just scrape all            # every known shop, one after another
```

From the app: press **Refresh** in the header and pick a shop or **All shops**. The header shows progress (pages, items) for each running shop, and a notification sums up the result when a run ends. The catalog reloads by itself.

Both ways run the same code. A run started from the app is a separate process; its output goes to `data/logs/run-<site>-<time>.log`. **All shops** in the app starts the shops at the same time (when one of them is already running, the others still start), while `just scrape all` runs them one after another. Concurrent runs take turns writing to the database: one waits while the other merges.

Only one run per shop can be active. A run whose process has died, or that has not reported progress for 15 minutes, is marked failed as soon as the app lists runs or a new run of that shop starts.

## Typical durations

| Shop | Sale items | Requests | Time |
|---|---|---|---|
| PRM | about 17,500 | about 260 | 5 to 10 minutes |
| Answear.ua | about 140,000 | about 2,000 | 30 to 40 minutes |
| Footshop | about 15,000 | about 850 | about 12 minutes |
| Saks85 | about 2,900 | about 260 | about 13 minutes |

The pace is set on purpose (about one request per second per worker), so a run cannot be made much faster by better hardware. Footshop needs more requests per item than the others: it is read through its catalog pages, 24 items each, because its `robots.txt` disallows its API ([ADR-0006](../decisions/0006-reading-catalog-pages.md)).

Saks85 has no API either: its catalog pages show 12 items each, so a run is one page view per 12 items ([ADR-0008](../decisions/0008-reading-saks85.md)).

## Read the result

At the end of a run the terminal shows a summary: coverage against the count reported by the shop, request and retry counts, the discount distribution, the deepest discounts, and what changed in the catalog (new items, price drops and increases, items back in the sale, items no longer seen).

Each run ends with one of these statuses:

| Status | Meaning | Effect on the catalog |
|---|---|---|
| `success` | every part of the catalog was fetched (at least 99% of the shop's count overall and 98% per segment) | merged; items missing from two successful runs in a row leave the sale |
| `partial` | some part was short, or a debug limit was used | merged, but nothing is removed |
| `failed` | an error or a block stopped the run | unchanged; the fetched pages are kept for `--resume` |
| `cancelled` | you cancelled it | unchanged; the fetched pages are kept for `--resume` |

`just runs` lists recent runs with their status, duration and catalog changes (`just runs --site prm` for one shop).

## Cancel and resume

- Cancel: Ctrl+C in the terminal, or the cross next to the progress in the app header.
- Resume: `just scrape <shop> --resume`, or **Resume <shop>** in the app's Refresh menu, continues the shop's last failed or cancelled run. It fetches only the pages that are missing and keeps the same run id. While such a run exists, the plain entry for that shop in the menu says "starts over".

Starting a new run (without `--resume`) discards the fetched pages of older unfinished runs of that shop.

## Transports

The scraper talks to a shop through one of two transports. Both follow the same pacing and the same stop-on-block rule.

| Transport | What it is | When it is used |
|---|---|---|
| `http` | a lightweight HTTP client (curl_cffi with its Chrome profile); no window | first, in `auto` mode |
| `browser` | a real Chromium driven by Playwright, calling the API from the shop's page; shown as a window | in `auto` mode, when the shop answers the HTTP client's start page with 403 |

`auto` is the default. Choose one explicitly with `--transport http` or `--transport browser`. The browser runs as a visible window because the shops do not serve Playwright's headless mode; `--headed` and `--headless` override the per-shop setting.

## Quick checks

```bash
just scrape prm --dry-run              # collect and summarize, write nothing
just scrape prm --max-pages 1          # at most one page per segment (status is always partial)
just scrape prm --dry-run --jsonl ../data/exports/prm.jsonl   # also export the items
```

All options are listed in the [command line reference](../reference/cli.md#salevault-scrape).

## Troubleshooting

| Symptom | What to do |
|---|---|
| The run fails with "HTTP 403" or "HTTP 429" | The shop refused the requests twice, with a 60 s pause in between. Respect that: try again much later; the fetched pages are kept, so continue with `--resume`. |
| "A run of ... is already running" | Another run of that shop is active. A dead run is detected automatically (its process is gone, or no progress for 15 minutes). |
| The run was interrupted (Ctrl+C, Cancel, crash, reboot) | `just scrape <shop> --resume` |
| The browser window does not appear | The browser transport needs a display; on Windows 11 this is WSLg. The HTTP transport needs no window. |
| "Contract error", or "N of M items do not match the expected schema" | The shop's API changed. The response that broke the run is kept in `data/raw/<shop>/`; the adapter needs an update. |
| Saving a favorite or sizes fails with "database is busy" | A merge held the database for more than two minutes. Try again in a moment. |
| Coverage below 99% (`partial`) | Usually the catalog changed during the run. Run again; nothing was removed from the catalog. |
