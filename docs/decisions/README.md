# Architecture decision records

Each record explains one significant decision: the context, what was decided, the alternatives and the consequences. Accepted records are not rewritten; a later change of course gets an "Updates" entry or a new record that supersedes the old one.

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-tech-stack.md) | Python backend, React frontend, SQLite | accepted |
| [0002](0002-fetching-through-the-shop-api.md) | Read the shop's own catalog API, politely, through an HTTP client or a real browser | accepted, amended by 0006 |
| [0003](0003-segmentation-by-gender-and-price.md) | Split big catalogs into segments by gender and price | accepted |
| [0004](0004-price-history-and-staged-runs.md) | Price history as a change log; runs are staged and merged in one transaction | accepted |
| [0005](0005-category-tree-from-the-api.md) | The shop's category tree is the source of truth for categories | accepted, amended by 0009 |
| [0006](0006-reading-catalog-pages.md) | Read catalog pages when robots.txt disallows the API | accepted |
| [0007](0007-reading-modivo.md) | Read Modivo's catalog pages with the one discount filter `robots.txt` allows, and the state they embed as data | accepted |
| [0008](0008-reading-saks85.md) | Read Saks85's catalog pages, later pages through OpenCart's non-SEO URL (`&page=N`), by the owner's decision | accepted |
| [0009](0009-shared-category-tree.md) | One shared category tree for all shops | accepted |
| [0010](0010-container-image.md) | A container image (with a headed Chromium on Xvfb) for a one-command start | accepted |

## Writing a new record

Copy the structure of an existing one: a title `ADR-NNNN: <decision>`, status and date, then Context, Decision, Alternatives considered and Consequences. Number records in order and add them to the table above.
