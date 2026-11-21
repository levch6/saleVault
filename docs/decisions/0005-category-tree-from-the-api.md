# ADR-0005: The shop's category tree is the source of truth

- **Status:** accepted
- **Date:** 2026-11-21

## Context

Each product carries a `categories` list. It is not one root-to-leaf path:

- about 30% of items carry two or three paths glued together (unisex items have one path in the men tree and one in the women tree);
- some extra paths come without their root;
- reading the list as one path produced thousands of conflicting parent links and nonsense paths in the item detail.

Splitting the list at root categories removed most conflicts, but root-less paths still got wrong parents. The API can return the real tree: `categoryTreeRequired: true` adds `categoryTree` to the response (about 50 KB; 286 nodes and 3 roots on PRM).

## Decision

1. The adapter asks for the tree on the root request only (no filters, page 1) and flattens it into nodes with id, name, parent and depth.
2. The tree is stored with the run (`scrape_runs.category_tree_json`) like the rest of the staged data.
3. The merge takes parents and depth from the tree. A category missing from it falls back to the item lists split at roots.
4. A product is linked to every listed category and all its ancestors, so filtering on a branch finds items whose list names only a deeper category.
5. The item detail returns one root-to-leaf path per most specific linked category.

## Alternatives considered

- **Split item lists at roots, no tree:** wrong for root-less paths; kept only as the fallback.
- **Majority vote of parents across items:** still a guess, and ties happen.
- **Ask for the tree on every page:** about 50 KB extra per request for nothing.

## Consequences

- One extra field on one request per run.
- Category filters and facets are correct for unisex items and partial lists.
- Shops without such a tree still work through the fallback.

## Updates

- **2026-11-21:** the catalog filter no longer uses the shops' trees but one shared tree ([ADR-0009](0009-shared-category-tree.md)); the shop's tree still decides the shop's own categories, which the item detail shows and the shared tree is derived from. Depths are now recomputed from the parent links after every merge.
