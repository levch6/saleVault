# ADR-0007: Read Modivo's catalog pages and the state they embed

- **Status:** accepted
- **Date:** 2026-11-21

## Context

Modivo (modivo.ua) is the fifth shop. Its website is built with Nuxt 2: catalog pages are rendered on the server, and later the browser loads data through the shop's API paths (`/m-api/`, `/t-api/`, `/n-api/`). Its `robots.txt` disallows those API paths for every user agent, and most filter combinations of the catalog pages as well: the price filter (`/c/*tsina:*`), `/c/*:*-*-*`, `/c/*:*:*:*:*`, `/c/*%26*`, sorting (`/*orderDir`), search (`/s/`) and the account pages. It allows `/*discount:~r-5-99*`, the discount filter (5 to 99%) of the shop's sale page. The sale of a section, `/c/zhinky/discount:~r-5-99`, and its pages, `?p=2`, also match the shorter `Disallow: /c/*:*-*-*`; under the precedence of RFC 9309 (the longest matching rule wins) the `Allow` rule applies. Other spellings of the discount filter, such as `~r-10-99` in many menu links, are disallowed.

A catalog page shows 72 items. Each page embeds its state for the page's scripts as JavaScript, not JSON: `window.__NUXT__=(function(a,b,...){...}(...))`, written by devalue. About 3,000 parameters are bound to literal arguments, the function body fills in objects that refer to each other with assignments, and it returns the state. The listing in it has the item count and the number of pages, the product cards (brand, name, link, pictures) and, per item, the regular, current and lowest 30-day (Omnibus) price, the color and every size with its availability. The page's JSON-LD names only links and names. A page is 2 to 3 MB of HTML. The last page of the whole sale (886 of 886, about 63,700 items) is served; a page number past the end answers 404.

The shop's menus have a men's, a women's and a kids' section. Their sales add up to about 1,350 items more than the whole sale: unisex items are in both the men's and the women's section.

## Decision

1. Read the sale of the catalog pages with the one filter `robots.txt` allows, `discount:~r-5-99`, and the shop's own pagination, `?p=N`. Never call the API paths, add filters, sort or change the page size. A unit test checks every URL the adapter builds against the shop's rules with that precedence.
2. Read the embedded state as data, with a small reader for the subset of JavaScript that devalue writes (`scraper/sites/nuxt_state.py`): literals, object and array literals, parameter names, the constructors devalue uses and assignments to parameters. It never runs the shop's code. Anything outside that subset is a contract error, which fails the run and archives the page.
3. Segments are the men's, women's and kids' sections; kids' items get the kids gender. The start page is the whole sale and gives the total count. There is no price split: there is no depth cap to work around.
4. The raw archive keeps only the listing the adapter read, pruned to the fields it uses, not the page.
5. Same rules as ADR-0002 for everything else: the default pace, two workers (as for Answear.ua and Footshop, given about 900 heavy pages per run), stop on repeated refusals, no proxies, no CAPTCHA solving, no stealth tooling, both transports.

## Alternatives considered

- **The shop's API paths:** disallowed by `robots.txt`.
- **Running the page's script in a JavaScript engine:** it would execute the shop's code and add a dependency, while the state is plain data that a reader of about 400 lines handles.
- **The visible markup of the product cards:** more fragile, and less data than the state the cards are rendered from.
- **JSON-LD:** links and names only, no prices or sizes.
- **Product pages:** one request per item, about 64,000 per run instead of about 900.
- **Segments by gender and top-level category** (to get categories): the shop's top-level categories overlap (its sport category holds clothing and shoes), so it means more segments and items seen twice; not done for now.

## Consequences

- A run is about 900 page views (1 + 532 women + 246 men + 127 kids), roughly 40 to 55 minutes with one worker or about half that with two (the smoke runs took 2.7 to 3.7 s per page, pause included). Reading a page's state takes about 0.25 s; the archive keeps about 250 KB of JSON per page (about 28 KB gzipped).
- No categories: the category the state gives an item is the section the listing was loaded from.
- The shop truncates its discount percent (3,799 of 4,199 is 9.5% and shown as 9%), for every sampled item; that is the default rounding.
- The state has the Omnibus price, but it is empty for every sampled item on this Ukrainian storefront, so there is no honest discount for now. It is stored when present.
- Every size is listed, sold-out ones marked unavailable; few left counts as last items. Size labels are those of the shop's size filter (XS, 38); its product cards show some in another system (34 for a women's XS).
- The card names an item by its kind and color; the rest of its full name (model, color, fit) is only in the pictures' alt text, and becomes the subtitle.
- The state belongs to the shop's frontend and can change with any release. The reader and the Pydantic models fail loudly, and the listing of the failing page is archived.
