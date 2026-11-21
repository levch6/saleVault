# saleVault documentation

saleVault is a personal, local tool: it collects the sale sections of fashion shops into a local database and shows every item sorted by discount, biggest first. These pages explain how to use it, how it works and how to change it.

The documentation follows the [Diataxis](https://diataxis.fr/) split: a tutorial to get started, guides for specific tasks, concepts that explain how things work, and reference pages for exact details.

## Start here

- [Getting started](getting-started.md): install, collect the first data, open the app.

## Guides

- [Collecting data](guides/scraping.md): running, resuming and cancelling scrapes; transports; troubleshooting.
- [Maintenance](guides/maintenance.md): backups, database size, logs and archives, upgrades.
- [Development](guides/development.md): local setup, checks, tests, migrations and the release flow.
- [Adding a shop](guides/adding-a-shop.md): what a shop needs and how an adapter plugs in.

## Concepts

- [Architecture](concepts/architecture.md): components, processes and the performance design.
- [How a scrape works](concepts/scraping.md): segmentation, staging, finalization and the rules the scraper follows.
- [Prices, discounts and badges](concepts/prices-and-badges.md): how discounts, price history and the New and Cheaper badges are computed.

## Reference

- [Command line](reference/cli.md): `just` recipes and the `salevault` CLI.
- [HTTP API](reference/http-api.md): endpoints, parameters and responses.
- [Configuration](reference/configuration.md): environment variables, site settings and the data directory.
- [Data model](reference/data-model.md): tables, indexes and how a run is merged.

## Decisions

- [Architecture decision records](decisions/README.md): why the project works the way it does.

## Conventions for these pages

- English, plain ASCII Markdown (no emoji, typographic quotes or long dashes).
- Behavior described here is the source of truth: change the docs in the same commit as the code.
- Examples use placeholders instead of real shop content.
