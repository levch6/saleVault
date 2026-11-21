# ADR-0008: Read Saks85's catalog pages, later pages through OpenCart's non-SEO URL

- **Status:** accepted
- **Date:** 2026-11-21

## Context

Saks85 (saks85.com) is the fourth shop. It runs OpenCart with the ocFilter module. Its sale (`/catalogue/special/rasprodazha/`, about 2,900 items) is rendered on the server, 12 items per page, and has no JSON API and no product data embedded for scripts: an item exists only as a product card in the page's HTML (link, brand, title, regular and current price, sizes with sold-out ones marked, two pictures). The cards carry no product id.

The shop's pagination links use `?page=N` (`/catalogue/special/rasprodazha/?page=2`), and its infinite scroll loads those same links. Its `robots.txt` for every user agent allows `/` but disallows `/*?page=`, along with `?limit=` and `&limit=` (page size), `?sort=` and `&sort=`, `?order=` and `&order=`, `?filter=`, `?search=` and `&search=`, `?url=` and `&url=`, `?pages_count=` and the filter module's AJAX route. Only page 1 of a listing (12 items) can be read under the spelling the shop links to.

OpenCart also serves every listing under its non-SEO URL, `index.php?route=product/category&path=<category>&filter_ocfilter=<selection>`, and the shop's own page-size links use that form (`...&limit=25`). Pagination there is `&page=N`. No rule of the shop's `robots.txt` matches `&page=` (it lists `page=` only after `?`, while it lists `limit`, `sort`, `order`, `search` and `url` in both spellings). The intent of `/*?page=` is evidently to keep crawlers off paged listings; the `&page=` form is the same listing and the same pages.

## Decision

1. The owner decided to read Saks85 with later pages in the `&page=N` form. This is a deliberate choice: the requested URLs match no rule of the shop's `robots.txt`, but they reach the paged listings that the `/*?page=` rule is meant to keep crawlers off.
2. Page 1 of every segment is loaded by the path the shop's menus link to (`/odyag/special/rasprodazha/stat/choloviche/`); pages 2 and later as OpenCart's non-SEO URL of the same listing, `index.php?route=product/category&path=69&filter_ocfilter=10010:4252492525;10024:4252492559&page=N`. The adapter never requests `?page=`, never changes the page size (12) or the sort, and never calls the filter module. A unit test checks every URL the adapter builds against the shop's rules.
3. Segments are every gender (men, women) in every top-level category of the sale (clothing, shoes, accessories, home fragrance), eight in all, as the shop's menus link to them. The four categories hold the whole sale of each gender (their counts add up to the gender's count), and every item gets its top-level category from the segment it was seen in. Unisex items appear under both genders, as with the other shops. There is no price split: there is no depth cap to work around.
4. Cards are read from the page's markup with the standard library's HTML parser; the raw archive keeps only what was read (as JSON), not the page.
5. Same rules as ADR-0002 for everything else: the default pace, one worker, stop on repeated refusals, no proxies, no CAPTCHA solving, no stealth tooling, both transports.

## Alternatives considered

- **Not supporting the shop:** consistent with the letter and intent of `robots.txt`; this was the recommendation before the owner's decision.
- **Product pages from the sitemap** (listed in `robots.txt` and allowed): about 4,400 product pages per run, sale or not, instead of about 260 listing pages, and still HTML parsing.
- **Many narrow filter combinations read on page 1 only** (category by gender by brand and so on, each at most 12 items): allowed paths, but it works around the pagination rule in a less transparent way and needs several times more requests.
- **Disallowed URLs** (`?page=`, a larger `limit`): not used.

## Consequences

- A run is about 260 page views (about 175 unisex items are seen twice), roughly 8 minutes with one worker. Each page is about 0.35 MB of HTML; the archive keeps about 7 KB of JSON per page.
- Product ids are the product's path (percent-decoded, since listings encode `+` as `%2B`); a path longer than the database's 64 characters keeps its first 47 characters and a hash of the whole. The image folder (the shop's product code) is not unique across colors, so it is not used. A product whose path changes is seen as a new item.
- No lowest price of the last 30 days, no color field, no discount badges. All sampled discounts were whole percents (10, 20, 30, 50), so the default truncation gives the same value as any rounding.
- Size labels are shown without their size system (INT, IT, EUR, ...), like the shop's own size filter does.
- Parsing the markup is more fragile than JSON. The card fields are validated with Pydantic models, a page with products but no item count fails the run, and more than 20% malformed cards stop it, with the parsed listing archived.
- If the shop starts matching `&page=` in `robots.txt`, or refuses these requests, the shop is dropped rather than read another way.

## Updates

- **2026-11-21:** the first full run made 260 requests in 13 minutes with one worker (pages take longer to serve than estimated) and found 2,873 of the 2,873 items the shop reported, every segment complete, with no refusals.
