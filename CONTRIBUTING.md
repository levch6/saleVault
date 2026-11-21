# Contributing

saleVault is a personal project maintained in spare time. Bug reports, ideas and small pull requests are welcome.

## Issues

- **Bugs:** what you ran, what happened and what you expected. Add the run summary or the log from `data/logs/`, with anything personal removed.
- **Shop owners:** if you represent a supported shop and have concerns, open an issue; it is handled first (see the disclaimer in the [README](README.md#disclaimer)).

## Pull requests

1. Run `just setup` once; it also installs the git hooks. On Windows, work inside WSL: the skill folders for coding agents are symbolic links (see [symbolic links on Windows](docs/guides/development.md#symbolic-links-on-windows)).
2. Keep a pull request focused on one change, and update `docs/` in the same pull request when behavior changes.
3. `just check` must pass (CI runs the same).
4. Commit messages are one line in Conventional Commits form, for example `feat(scraper): add price segmentation`; the commit-msg hook checks it. See [development](docs/guides/development.md#conventions) for the details.

If you work with an AI coding agent, point it at `AGENTS.md`; it holds the same rules in more detail.

## Ground rules

- **Scraping rules are not negotiable.** Pull requests that raise the default request pace, continue after a shop refuses requests, or add proxies, IP rotation, CAPTCHA solving or stealth tooling will be declined. See [the rules the scraper follows](docs/concepts/scraping.md#rules-the-scraper-follows).
- **No shop data in the repository.** Never commit scraped data or raw responses. Build test fixtures with `backend/scripts/make_fixture.py`, which anonymizes them.
- **New shops** follow [adding a shop](docs/guides/adding-a-shop.md): public catalog only, and only when the shop's `robots.txt` allows the paths the adapter uses.
- Everything in the repository is in English; Markdown is plain ASCII.
