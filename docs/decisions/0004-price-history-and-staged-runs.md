# ADR-0004: Price history as a change log; staged runs

- **Status:** accepted
- **Date:** 2026-11-21

## Context

The app shows New and Cheaper badges, a favorites watchlist and price history charts. A run reads about 160,000 items across two shops and can fail midway, especially the long Answear.ua run, while the UI must keep showing consistent data.

## Decision

### Price history as a change log

- `price_history` gets a row only when an item is first seen or one of its prices changes (price, regular price, 30-day lowest price).
- The current state is kept on `products` (price, discount, previous price, run of the last change), so filters and sorts never join the history.
- Presence in the sale is tracked with `products.is_active` and the first and last seen run.

### Staged runs

1. During a run, items go to `run_items` (staging) and fetched pages to `run_pages` (checkpoints).
2. After the last page, one transaction merges the staging into the catalog, writes price history, computes the statistics and clears the staging.
3. Items are deactivated only on a `success` run; partial runs update what they found and remove nothing.
4. `--resume` continues a failed or cancelled run from its checkpoints.

## Alternatives considered

- **A full snapshot per run:** about 160,000 rows per run, almost all duplicates of the previous run.
- **Writing straight into `products` during the run:** the UI would show half-updated data, and a failed run would leave a mess.

## Consequences

- New means first seen in the shop's latest finished run (never on the very first run); Cheaper means the price changed in that run and went down.
- The merge has to be fast: bulk upserts in chunks keep about 200,000 items under a minute with flat memory.

## Updates

- **2026-11-21:** a full run misses about 0.5% of items because the API orders equal items differently between requests. Deactivation therefore has a grace period: an item becomes inactive only after two successful runs in a row without it.
