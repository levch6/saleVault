# Data model

SQLite in WAL mode with foreign keys on. Timestamps are UTC. Money is stored as **integers in minor units** (`*_minor`, kopecks). The schema is managed by Alembic migrations shipped inside the package (`backend/src/salevault/db/migrations/`); models are in `backend/src/salevault/db/models.py`.

## Relationships

```
sites        1 --- * scrape_runs
sites        1 --- * brands
sites        1 --- * categories        (self-reference via parent_id)
sites        1 --- * products
scrape_runs  1 --- * run_pages         (checkpoints)
scrape_runs  1 --- * run_items         (staging, cleared after the merge)
brands       1 --- * products
products     * --- * categories        (via product_categories)
products     1 --- * product_sizes
products     1 --- * price_history * --- 1 scrape_runs
products     1 --- 0..1 favorites
settings                               (standalone key/value)
```

## Tables

### `sites`

`id`, `code` (unique: `prm`, `answear_ua`), `name`, `origin`, `currency`, `created_at`.

### `scrape_runs`

| Column | Notes |
|---|---|
| `id`, `site_id` | |
| `status` | `running`, `success`, `partial`, `failed`, `cancelled` |
| `trigger` | `cli` or `ui` |
| `pid` | process id, for locking and cancel |
| `started_at`, `updated_at`, `finished_at` | `updated_at` is the heartbeat, bumped on every staged page |
| `expected_total` | item count reported by the shop at the start |
| `pages_total`, `pages_done`, `items_seen` | progress |
| `segments_json` | the segment plan with per-segment counts |
| `category_tree_json` | the shop's category tree fetched by this run |
| `stats_json` | run statistics (see the [API](http-api.md#shops-and-runs)) |
| `error` | short reason shown in the UI |

### `run_pages` (checkpoints)

`run_id`, `segment_key`, `page`, `items_count`, `item_ids_json`, `fetched_at`. Primary key `(run_id, segment_key, page)`. The item ids let a resumed run rebuild per-segment coverage.

### `run_items` (staging)

`run_id`, `external_id`, `gender_mask`, `record_json` (the normalized item). Primary key `(run_id, external_id)`. When an item is seen again in another gender segment, its gender bits are OR-ed in.

### `brands`

`id`, `site_id`, `external_id`, `name`, `slug`. Unique `(site_id, external_id)`.

### `categories`

`id`, `site_id`, `external_id`, `name`, `parent_id` (self-reference, nullable), `depth`. Unique `(site_id, external_id)`. Parents and depth come from the category tree of the run.

### `products`

| Column | Notes |
|---|---|
| `id`, `site_id`, `external_id` | unique `(site_id, external_id)` |
| `url` | absolute link to the item on the shop site |
| `brand_id`, `name`, `subtitle`, `color` | |
| `gender_mask` | men 1, women 2, home 4, kids 8 |
| `image_name`, `image_version`, `gallery_json` | image references; URLs are built by the shop adapter |
| `price_minor`, `price_regular_minor`, `price_min30_minor` | current, regular and 30-day lowest price |
| `discount_pct`, `discount_min30_pct`, `savings_minor` | see [prices and badges](../concepts/prices-and-badges.md) |
| `prev_price_minor`, `last_price_change_run_id` | the price before the last change, and the run of that change |
| `is_active`, `missed_runs` | in the sale; `missed_runs` counts successful runs in a row that did not see the item |
| `available_for_buy` | as reported by the shop |
| `first_seen_at`, `first_seen_run_id`, `last_seen_at`, `last_seen_run_id` | |
| `search_text` | casefolded brand, name, subtitle and color, because SQLite `LIKE` ignores case for ASCII only |

Indexes, all led by `is_active` where a sort or a cheap facet needs them:

- `(is_active, discount_pct, savings_minor)`: the main catalog order.
- `(is_active, discount_min30_pct, discount_pct)`, `(is_active, savings_minor)`, `(is_active, price_minor)`, `(is_active, first_seen_at)`: the other sorts.
- `(is_active, brand_id)`, `(is_active, gender_mask)`: brand and gender facets without table lookups.
- `(site_id, is_active, discount_pct)`, `(brand_id)`, `(first_seen_run_id)`, `(last_price_change_run_id)`.

### `product_categories`

`product_id`, `category_id`; primary key on both, index on `category_id`. A product is linked to every category in its list **and all their ancestors**, so a branch filter is a simple lookup.

### `product_sizes`

`product_id`, `variation_id`, `size_external_id`, `label`, `ean`, `availability`, `in_stock`. Primary key `(product_id, variation_id)`, index `(product_id, in_stock, label)` for the size filter and facet. Rewritten for an item on every run that sees it. `in_stock` is resolved by the adapter, so queries never need shop-specific availability values.

### `price_history`

`id`, `product_id`, `run_id`, `observed_at`, `price_minor`, `price_regular_minor`, `price_min30_minor`, `discount_pct`. Index `(product_id, observed_at)`. A row is written only when an item first appears or one of its three prices changes.

### `favorites`

`product_id` (primary key), `added_at`, `price_at_add_minor`, `note`.

### `settings`

`key`, `value_json`. Used keys: `my_sizes` (for example `["M", "43", "W32"]`).

## Merging a run

One transaction after all pages are fetched:

1. Upsert the category tree, then stream `run_items` in chunks of 2,000 (keyset by `external_id`), upserting each chunk's brands and any categories missing from the tree. Memory stays flat: about 200,000 items merge in about 40 s.
2. Upsert `products`: new items get `first_seen_*` and their first `price_history` row; a changed price sets `prev_price_minor` and `last_price_change_run_id` and adds a `price_history` row; every seen item gets `last_seen_*`, `is_active = 1` and `missed_runs = 0`.
3. Rebuild `product_sizes` and `product_categories` for the seen items.
4. Only on `success`: items of the shop not seen get `missed_runs + 1`, and those reaching 2 become inactive.
5. Write the run statistics and clear `run_items` and `run_pages` of the run.

## Derived values

| Value | Definition |
|---|---|
| Latest run of a shop | its latest run with status `success` or `partial` |
| New | `first_seen_run_id` is the latest run of the shop, and the shop has an earlier finished run |
| Price drop | `last_price_change_run_id` is the latest run of the shop, and `price_minor < prev_price_minor` |
| In stock in my size | a `product_sizes` row with a saved label and `in_stock = 1` |

## Volumes

A two-shop catalog holds about 160,000 products; price history starts at one row per product and grows with price changes (a few million rows a year is fine for SQLite). After compaction the database takes about 240 MB.
