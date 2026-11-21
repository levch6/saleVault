# Adding a shop

A shop is supported through an adapter in `backend/src/salevault/scraper/sites/`. Nothing else in the project knows about shops: the database, API and UI work with any adapter.

## Before you start

Only add a shop when all of this holds:

- The sale catalog is public: no login, no account, no personal data.
- The shop's `robots.txt` does not disallow the pages and API paths the adapter uses.
- The shop's terms of use do not forbid this kind of personal use.
- The data comes from the same catalog API or pages the shop's own site uses, at the default polite pace.

If the shop answers with repeated 403 or 429 responses, it does not want automated access: stop there.

## A shop on the Answear platform

PRM and Answear.ua run on the same platform, so they share `AnswearPlatformAdapter` and differ only in configuration. Another shop on this platform is a new `AnswearPlatformConfig` in `scraper/sites/registry.py`:

| Field | Meaning |
|---|---|
| `code` | short id used in the CLI, API and database, e.g. `prm` |
| `display_name` | name shown in the UI |
| `origin`, `base_path` | site origin and the path prefix of the catalog and API, e.g. `https://prm.com` and `/ua` |
| `warmup_path` | page opened first, like a visitor would (usually the sale page) |
| `locale`, `currency`, `api_version` | values the site's frontend sends with API requests |
| `concurrency` | parallel workers; keep 1 unless the catalog is very large |
| `headless` | `False` when the shop does not serve Playwright's headless mode |
| `transport` | `auto`, `browser` or `http` (see [collecting data](scraping.md#transports)) |
| `sort` | sort used for paging inside a segment; `""` (popularity) gives the most stable pages |
| `sex_genders` | maps the shop's `sex` facet codes to the app's genders |
| `in_stock_values` | availability values that count as in stock |

Add the config to `SITES`, then:

1. Run `just scrape <code> --dry-run --max-pages 1` and check the summary.
2. Archive a few raw responses (`--save-raw`, the default) and build anonymized fixtures with `backend/scripts/make_fixture.py`.
3. Add adapter tests for anything shop-specific, and a live test in `backend/tests/live/` if the shop needs one.
4. Run a full scrape and check the coverage (99% or more).

## A shop on another platform

Write a new adapter that implements the `SiteAdapter` protocol from `scraper/base.py`:

| Member | Purpose |
|---|---|
| `code`, `page_size`, `max_pages` | identity, items per page, deepest page one query can reach |
| `warm_up()` | open the starting page through the transport |
| `fetch_page(segment, page)` | fetch one page of a segment and return a `PageResult` (count, normalized `ProductRecord`s, facets, the raw text and, on the root request, the category tree) |
| `root_segments(root)` | split the catalog into first-level segments (by gender) from the root page's facets |
| `gender_of(segment)` | the app gender a segment stands for |

The adapter talks to the shop only through a `Transport` (`open`, `post_json`), so it works with both the HTTP client and the browser and can be tested with a fake transport. Validate every response with Pydantic models, raise `BlockedError` on 403 or 429 and `ContractError` when the response does not match, and let the runner handle pacing, retries and segmentation. Then extend `create_adapter` in the registry to pick the new adapter.
