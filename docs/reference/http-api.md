# HTTP API

The API serves the UI; it is also handy for scripts on the same machine. It listens on `127.0.0.1:8000` and has no authentication.

- Base path `/api`, JSON. The OpenAPI schema is at `/api/openapi.json`, interactive docs at `/api/docs`. Frontend types are generated from it (`just gen-api`).
- Operation ids are the Python function names (`list_products`, `get_facets`, ...).
- Prices are **whole hryvnias** (`int`), with the currency given separately. The database keeps kopecks.
- Errors: `{"detail": "...", "code": "..."}`. Codes: `not_found` (404), `forbidden` (403, a write sent from another site), `unknown_site` (422), `resume_needs_one_site` (422), `nothing_to_resume` (409), `run_already_running` (409), `run_not_running` (409), `launch_failed` (500), `database_busy` (503, a merge held the database too long), `internal` (500, see the server log). Validation errors are FastAPI's standard 422.
- Only the host names in `SALEVAULT_ALLOWED_HOSTS` are served (400 otherwise). Ids, prices, pages and list lengths are bounded, so out-of-range values are 422, never a server error.
- Unknown query parameters are rejected (422), so a typo never silently drops a filter.

## Catalog

### `GET /api/products`

| Parameter | Type | Description |
|---|---|---|
| `site` | string[] | shop codes, e.g. `prm`; an unknown code matches nothing |
| `gender` | string[] | `men`, `women`, `home`, `kids` (matches any; unisex items match both men and women) |
| `category` | int[] | category id at any level; an item matches if it is linked to it or to a descendant |
| `brand` | int[] | brand ids |
| `size` | string[] | size labels that must be **in stock** |
| `my_sizes` | bool | only items with one of the saved sizes in stock (ignored while no sizes are saved) |
| `price_min`, `price_max` | int | current price, whole hryvnias, inclusive |
| `discount_min`, `discount_max` | int | percent |
| `q` | string | every whitespace-separated word must occur in brand + name + subtitle + color (case-insensitive, also for Cyrillic) |
| `flags` | string[] | `new`, `price_drop`, `favorite` (all must hold) |
| `include_inactive` | bool | default `false` |
| `sort` | enum | `discount_desc` (default), `discount_min30_desc`, `savings_desc`, `price_asc`, `price_desc`, `newest` |
| `page`, `page_size` | int | `page` from 1; `page_size` 1 to 120, default 60 |

Every sort ends with the product id, so pagination is stable. `discount_desc` breaks ties by bigger savings; `discount_min30_desc` puts items without an honest discount last.

Response `ProductPage`: `{items: ProductCard[], total, page, page_size}`.

`ProductCard` (text fields hold the shop's data; placeholders here):

```json
{
  "id": 123,
  "site": "prm",
  "url": "https://shop.example/p/product-123",
  "brand": {"id": 5, "name": "<brand>"},
  "name": "<product name>",
  "subtitle": "<color, fit and model code>",
  "color": "<color>",
  "image": {"thumb": "https://img.example/316x478/<image>", "full": "https://img.example/1200x1800/<image>"},
  "price": 1200, "price_regular": 3000, "price_min30": 3000, "currency": "UAH",
  "discount_pct": 60, "discount_min30_pct": 60, "savings": 1800,
  "prev_price": null,
  "badges": ["new", "price_drop"],
  "genders": ["women"],
  "sizes": [{"label": "S", "in_stock": true, "is_mine": false}],
  "is_favorite": false,
  "is_active": true,
  "first_seen_at": "2026-11-21T10:15:00Z"
}
```

- `badges`: see [prices and badges](../concepts/prices-and-badges.md#badges); `prev_price` is the price before the last change.
- `sizes`: all sizes in the shop's order, with stock and whether the label is one of the saved sizes.

### `GET /api/facets`

Takes the same filters as `/api/products` (no sort or paging) plus `heavy`. Each facet is counted **without its own filter**, so selecting brand A still lists brands B and C with their counts. `total` applies every filter.

| Parameter | Type | Description |
|---|---|---|
| `heavy` | bool | default `true`. `false` skips the category and size counts (the slow part on a large catalog); they come back as `null` |

```json
{
  "total": 17577,
  "sites": [{"value": "prm", "label": "PRM", "count": 17577}],
  "genders": [{"value": "men", "label": "Men", "count": 10674}, "... women, home, kids (always all four)"],
  "categories": [{"id": 3, "name": "<category>", "parent_id": 2, "depth": 1, "count": 9000}],
  "brands": [{"id": 5, "name": "<brand>", "count": 120}],
  "sizes": [{"label": "M", "count": 6183}],
  "price": {"min": 269, "max": 141899},
  "discount": {"min": 0, "max": 79}
}
```

Order: categories by depth then name; brands and sizes by count, then name or label.

### `GET /api/products/{id}`

`ProductDetail` is `ProductCard` plus:

| Field | Meaning |
|---|---|
| `gallery` | images (thumb + full) |
| `category_paths` | one root-to-leaf path per most specific category (unisex items usually have one path per gender tree) |
| `size_details` | sizes with the shop's `availability` value and their `variation_id` (unique per item; labels may repeat) |
| `price_history` | `[{observed_at, price, price_regular, price_min30, discount_pct}]`, oldest first, one point per change |
| `last_seen_at` | when a run last saw the item |

404 `not_found` for an unknown id.

## Favorites and settings

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/favorites` | newest first: `{product: ProductCard, added_at, price_at_add, price_change, note}`; `price_change` is the current price minus the price when added (negative means cheaper). Inactive items stay listed |
| `PUT` | `/api/favorites/{product_id}` | 204; idempotent; optional body `{"note": "..."}` (at most 500 characters); 404 for an unknown product |
| `DELETE` | `/api/favorites/{product_id}` | 204; idempotent |
| `GET` | `/api/settings` | `{"my_sizes": ["M", "43"]}` |
| `PUT` | `/api/settings` | partial update; `my_sizes` is trimmed and deduplicated, at most 100 labels; unknown fields 422 |

## Shops and runs

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/sites` | every known shop, even before its first run: `{code, name, origin, active_products, last_completed, latest, resumable}`. `resumable` is true when the latest run failed or was cancelled and kept its pages. `last_completed` is the latest `success` or `partial` run (the data on screen), `latest` the latest run of any status |
| `GET` | `/api/runs?site=&limit=20` | runs, newest first; `limit` 1 to 200. Runs whose process has died are marked `failed` before listing (also on `/api/sites` and `/api/runs/{id}`) |
| `GET` | `/api/runs/{id}` | `{id, site, status, trigger, started_at, finished_at, expected_total, pages_total, pages_done, items_seen, stats, error}` |
| `POST` | `/api/runs` | body `{"site": "prm" or "all", "headed": null, "resume": false}`; `resume: true` continues the shop's interrupted run (one shop only; 409 `nothing_to_resume` if there is none); 202 `{"run_ids": [...], "skipped": [...]}` once each scraper process has registered its run. With `all`, shops that cannot start are listed in `skipped` and the others still start; with one shop, 409 `run_already_running` or 500 `launch_failed` with the tail of the process output; 422 `unknown_site` |
| `POST` | `/api/runs/{id}/cancel` | 202 with the run; the scraper gets SIGTERM and ends as `cancelled` (resumable from the CLI); 409 `run_not_running`; 404 |
| `GET` | `/api/health` | `{"status": "ok", "version": "...", "db": "ok"}` |

`stats` of a finished run: `{seen, new, price_drops, price_ups, returned, missing, removed, expected, coverage, requests, retries, invalid_items, duration_s}`.

A run started through the API is a separate process (`python -m salevault scrape <shop> --trigger ui`) with its output in `data/logs/`. The API waits until the process has registered its run (at most 60 s; after that the process is terminated) or reports its output if it exits first. When the process ends, the facet cache is warmed with the new data. Cancel sends SIGTERM only if the stored pid still belongs to the process that registered the run (same start time).
