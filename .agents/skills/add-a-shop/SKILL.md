---
name: add-a-shop
description: Add support for a new shop to saleVault, either as a config for a shop on the Answear platform or as a new adapter, with the robots.txt check, anonymized fixtures, tests and docs. Use when the user asks to support, scrape or add a new store.
---

# Add a shop

Every step that sends a request to the shop (robots.txt, a dry run, a live test, a full scrape) needs the user's go-ahead first. Shop-specific code lives only in `backend/src/salevault/scraper/sites/`.

## 1. Check that the shop may be added

Ask the user for the shop and confirm with them, before writing code:

- The sale catalog is public: no login, no account, no personal data.
- `robots.txt` does not disallow the start page, the sale page or the catalog API path for `User-agent: *`. Fetch it once (with the user's OK) through the HTTP transport and record what you checked in `.notes/research/`.
- The user has looked at the shop's terms of use.

If the shop answers with repeated 403 or 429, stop: it does not want automated access.

## 2. Platform

- **Answear platform** (catalog at `<base>/api/products`, `x-tamago-*` headers, 80 items per page, 125 pages): add an `AnswearPlatformConfig` to `scraper/sites/registry.py` and to `SITES`. Fields are described in `docs/guides/adding-a-shop.md`. Start with `concurrency=1`, `headless=False`, `transport="auto"`, `sort=""`, and map the shop's `sex` facet codes in `sex_genders`.
- **Another platform**: write an adapter that implements `SiteAdapter` (`scraper/base.py`), talks only through a `Transport`, validates every response with Pydantic models, raises `BlockedError` on 403/429 and `ContractError` with `raw=` on a mismatch. Extend `create_adapter`. Write an ADR in `docs/decisions/`.

## 3. Smoke run (with the user's OK)

```bash
just scrape <code> --dry-run --max-pages 1
```

Check the summary: segments, coverage of the sampled pages, discounts that match the shop's badges, no invalid items.

## 4. Fixtures and tests

```bash
cd backend
uv run python scripts/make_fixture.py ../data/raw/<code>/<run>/<segment>__p001.json.gz tests/fixtures/<platform>/<name>.json --items 6
```

- Inspect the output before committing: no shop text may remain (`grep -P '[\x{0400}-\x{04FF}]'` must find nothing; promo badges become `Promo`, sizes in the shop's language become `One size`). Never commit raw responses.
- Add adapter tests for anything shop-specific (gender mapping, availability values, prices). Add a live test in `backend/tests/live/` (marker `live`) only if the shop needs one; never run it without the user's OK.

## 5. Docs and checks

- `README.md`: the supported shops line and the disclaimer (shop names).
- `docs/getting-started.md` and `docs/guides/scraping.md`: catalog size and typical duration.
- `just check`, then commit as `feat(scraper): add <shop>`.

## 6. First full run

Only when the user asks. Watch the first refusal: one pause is allowed per run, the second stops it.
