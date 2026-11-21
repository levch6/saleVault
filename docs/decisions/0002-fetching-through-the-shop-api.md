# ADR-0002: Read the shop's own catalog API, politely

- **Status:** accepted
- **Date:** 2026-11-21

## Context

PRM and Answear.ua run on the same e-commerce platform. Their websites load the catalog from a JSON API (`POST .../api/products`) with filters, sorting and paging. Both shops refuse plain HTTP clients such as curl or httpx with HTTP 403 on every URL, and they also refuse Playwright's headless browser. A regular, visible Chromium window loads the sites normally.

## Decision

1. Read the catalog **through the shop's own JSON API**, never by parsing HTML pages.
2. Two transports implement one interface, so adapters and the runner do not depend on how requests travel:
   - **Browser:** Chromium driven by Playwright with a persistent profile per shop. It opens the shop's start page like a visitor and then calls the API with `fetch` from that page, the same way the shop's frontend does. Because the shops do not serve headless mode, it runs as a visible window.
   - **HTTP:** curl_cffi with its built-in Chrome profile, which the shops accept. No browser window, less memory.
3. `auto` (the default) tries the HTTP transport first and switches to the browser when the shop does not accept it on the start page. `--transport` and the shop config can force either one.

### Rules for every transport

- A random pause of 0.8 to 1.6 s after every request of a worker; one worker by default (two for the large Answear.ua catalog); at most 3,000 requests per run.
- Only public catalog data: no login, no account pages, no personal data.
- Respect `robots.txt`; the paths used (start page, sale page, catalog API) are not disallowed by either shop.
- On 403 or 429: one 60 s pause and a retry. If the shop refuses again, the run stops with a clear message. There is no attempt to continue another way after a refusal.
- No proxies or IP rotation, no CAPTCHA solving, no stealth plugins.
- Personal, non-commercial use; the data is not published.

## Alternatives considered

- **Plain HTTP clients (httpx, curl):** refused with 403.
- **Parsing product HTML:** fragile, slower and less data than the JSON API.
- **Intercepting responses while scrolling the site:** slow, and paging and filters are hard to control.
- **Browser only:** works everywhere but needs a visible window and about 300 MB of memory per run. Kept as the fallback and as an explicit option.
- **HTTP client with a browser profile:** this is client impersonation at the network level. Accepted for a personal, low-volume tool under the same pace and stop-on-refusal rules; the browser remains available for anyone who prefers it.

## Consequences

- Speed is bounded by the deliberate pace, not by hardware: PRM takes 5 to 10 minutes, Answear.ua 30 to 40. Hence checkpoints and `--resume` (ADR-0004).
- When a shop changes its API, the Pydantic models fail loudly and the raw responses of the run are kept for updating the adapter.
- If a shop starts refusing both transports, it is treated as unavailable; the project does not escalate.

## Updates

- **2026-11-21:** confirmed that Playwright's headless shell gets 403 on the start page while a headed window works, so both shop configs run the browser headed. Playwright's `context.request` was not pursued; page-context `fetch` works and is the documented approach.
- **2026-11-21:** the HTTP transport was added and made the default (`auto`) after it read the full PRM catalog (about 17,500 items) with the same pace and rules.
