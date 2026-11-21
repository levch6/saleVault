# ADR-0003: Split big catalogs into segments by gender and price

- **Status:** accepted
- **Date:** 2026-11-21

## Context

The catalog API returns at most 80 items per page and at most 125 pages per query, so one query reaches at most 10,000 items. The PRM sale has about 17,500 items, Answear.ua about 143,000. Items also have no reliable unisex flag: the gender filter returns unisex items under both genders, so the per-gender counts add up to more than the total.

## Decision

Split the catalog recursively until every segment holds at most `SAFE_LIMIT = 9,600` items (96% of the cap, leaving room for changes during the run):

```
queue = [Segment(sex=s) for s in facets.sex]
final = []
while queue:
    seg = queue.pop()
    first = fetch_page(seg, page=1)                    # count + first 80 items
    if first.count <= SAFE_LIMIT:
        final.append((seg, first))                     # page 1 is reused
    else:
        lo, hi = seg.price or facets.price_range       # whole currency units
        mid = (lo + hi) // 2
        queue += [seg.with_price(lo, mid), seg.with_price(mid + 1, hi)]
```

- Price bounds are integers and never overlap: `[lo, mid]` and `[mid + 1, hi]`.
- Inside a segment, pages `1..ceil(count / 80)` are fetched and deduplicated by id.
- Items are tagged with the union of the gender segments they were seen in, so an item seen under men and women is unisex.
- Paging uses the shop's popularity order: the API orders ties differently between requests, and with price order (where ties are everywhere) about 0.6% of items fell between pages; popularity lost about 0.08%.

## Alternatives considered

- **Price only:** fewer requests, but no unisex tagging.
- **By category:** deep, overlapping trees that differ between shops; more fragile.
- **Two sorts (ascending and descending price):** breaks above 20,000 items and on equal prices.
- **Quantile splits** (split at the price of the 9,600th item): fewer requests; kept as a possible optimization.

## Consequences

- Overhead of about one request per split plus unisex duplicates (about 15% more requests on PRM).
- Completeness is checked per segment (98%) and per run (99%); a shortfall makes the run `partial`.
- The algorithm is shop-agnostic and tested against a fake adapter with a synthetic catalog.
