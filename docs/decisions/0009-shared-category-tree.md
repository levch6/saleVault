# ADR-0009: One shared category tree for all shops

- **Status:** accepted
- **Date:** 2026-11-21

## Context

The category filter showed the shops' own categories merged into one tree. With five shops that was a mess: Answear.ua and PRM start their trees with the gender (so "He" and "She" appeared twice), Footshop has 156 flat categories (some untranslated, gendered duplicates such as "T-shirts", "Men's T-shirts" and "Women's T-shirts"), Saks85 has four top-level ones and Modivo none. Gender is a filter of its own anyway, and nobody wants to pick "jackets" five times to see them in every shop.

The shops do give enough evidence to tell what an item is: a category path (often a style such as "Without a zip" under "Sweatshirts"), the product name, which usually starts with the kind of item, and sometimes a subtitle.

## Decision

1. The app has its own category tree (`domain/taxonomy.py`): seven groups (Clothing, Shoes, Bags, Accessories, Home, Lifestyle, Other) with about fifty leaves, English names, stable slugs (`clothing.jackets`) that URLs use. Gender is not part of it.
2. Every product gets one leaf, from rules on normalized text (casefolded, Latin look-alike letters inside Cyrillic words fixed): keyword stems in Ukrainian plus the Czech and English words shops leave untranslated, ordered from specific to general. The evidence is weighed in this order:
   1. a deepest shop category that names a kind decides;
   2. otherwise that category is a style, read together with its parent ("sports" under "trousers" is sweatpants), and the product name (without the brand) may refine the result within the same group of clothing, shoes, bags or accessories;
   3. without any kind in the path, the name and subtitle decide;
   4. then the first general hint gives a group's catch-all leaf ("Other clothing"); a shop that only says "shoes" is taken as sneakers, which held for 94% of such items;
   5. otherwise "Other".
3. The leaf is stored on the product (`products.category_slug`, indexed with `is_active`) and computed by the merge. A change of the tree or the rules bumps `TAXONOMY_VERSION`; the next start categorizes every stored product again from the database (about 8 s for 240,000 items). `salevault db recategorize` does it on demand and prints how well each shop is covered.
4. The catalog filter and the category facet use only the shared tree; a group matches all of its leaves. The shop's own categories stay in the database (ADR-0005) and in the item detail.

## Alternatives considered

- **Group the filter by shop:** keeps every shop's tree but still cannot find jackets across shops.
- **Show categories only for one shop:** hides the problem.
- **A hand-made mapping of every shop category:** about 1,450 categories today and more with every shop; rules generalize, and the coverage report shows what they miss.
- **A third level (for example kinds of jackets):** most shops do not provide it reliably; two levels keep every leaf meaningful across shops.

## Consequences

- Coverage on the real catalog (2026-11-21, share of active items in a specific leaf): PRM 99.3%, Footshop 99.5%, Saks85 98.5%, Modivo 97.3%, Answear.ua 96.9%. The rest is in a group's catch-all (cases, keychains, gift sets) or, for 2.4% of Modivo (baby sets and the like), in Other.
- Rules can misjudge an item whose name or category is unusual. The rules and their tests are the place to fix it, followed by a version bump.
- New shops are categorized without extra work as long as their words are covered; the coverage report after their first run shows what is missing.
- The category facet is now a cheap indexed GROUP BY, so it is part of the light facets.
