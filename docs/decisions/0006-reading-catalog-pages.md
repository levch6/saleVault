# ADR-0006: Read catalog pages when robots.txt disallows the API

- **Status:** accepted
- **Date:** 2026-11-21

## Context

Footshop (footshop.ua) is the third shop. Its website loads more products and applies filters through JSON endpoints (`?ajax=true` and paths under `/api/`), but its `robots.txt` disallows `*/api/*`, `*/graphql/*` and `*?ajax=` for every user agent, as well as query pagination (`?p=`) and page size changes (`/perpage-`). ADR-0002 reads every shop through its own catalog API, which here would mean using paths the shop asked automated clients not to use.

`robots.txt` does allow the catalog pages themselves, including path pagination (`/uk/872-znizhki/page-2`). Each catalog page is rendered on the server and carries its product listing as JSON for the page's own scripts: 24 complete items per page with prices, sizes and images, plus the total count and the number of pages. The last page of the whole sale (page 634 of 634) is served, so there is no depth cap; a page number past the end returns the last page again.

The shop has no gender path filter exposed in its pages (applying its gender filter goes through the disallowed endpoint), but its men's, women's and kids' menus each link to a sale category of their own. Their counts match the shop's gender facet, and unisex items appear in both the men's and women's sale.

## Decision

1. When a shop's `robots.txt` disallows its catalog API, read the **catalog pages** that a visitor or a search engine loads, and take the listing from the JSON embedded in them. Never call the disallowed endpoints.
2. Same rules as ADR-0002 for everything else: the default pace, one worker, stop on repeated refusals, no proxies, no CAPTCHA solving, no stealth tooling, both transports (`get` loads a page like a visitor; the browser navigates to it).
3. Segments are the shop's own gender sections of the sale (men, women, kids). There is no price split: no price filter is exposed in page paths, and none is needed without a depth cap.
4. The start page is the sale page itself, and it doubles as the first page of the root request, so no page is loaded twice.
5. The raw archive keeps only the listing JSON of a page, not the whole HTML.

## Alternatives considered

- **The shop's JSON endpoints:** disallowed by `robots.txt`.
- **Product pages or sitemaps:** one request per item, about 15,000 per run instead of about 850.
- **Parsing the visible HTML markup:** fragile and with less data than the embedded JSON, which is the data the page itself renders from.
- **Not supporting the shop:** possible, but reading allowed pages at the polite pace is within the project's rules.

## Consequences

- A page is about 0.5 to 0.7 MB of HTML before compression for 24 items, and a full run is about 850 page views (the men's and women's sections overlap by the unisex items). The first full run made 853 requests in 24 minutes with one worker and found 15,189 of the 15,190 items the shop reported; paging in the shop's popularity order stayed stable over that time.
- No lowest price of the last 30 days, so no honest discount for this shop. Categories are the item's main category only; there is no category tree (ADR-0005 does not apply).
- The listing shows only the sizes that can be bought now, so every listed size counts as in stock.
- The shop rounds its discount badges (9.99% is shown as "-10 %"), while the Answear platform truncates; the adapter computes the discount the way the shop does.
- The embedded JSON belongs to the shop's frontend and can change with any release. The Pydantic models fail loudly and the listing of the failing page is archived, as with the API shops.

## Updates

- **2026-11-21:** after the first full run (one worker, no refusals) the shop uses two workers, like Answear.ua; a run takes about 12 minutes.
- **2026-11-21:** Saks85 embeds no listing JSON in its pages, so its product cards are read from the markup, and only what was read is archived: [ADR-0008](0008-reading-saks85.md).
