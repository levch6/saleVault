"""Helpers shared by the site adapters: status handling, start page, item validation."""

import logging
from collections.abc import Callable, Sequence
from typing import Any

from salevault.domain.models import ProductRecord
from salevault.scraper.base import HttpResponse, Transport
from salevault.scraper.errors import BlockedError, ContractError, ScrapeError, TransientError

log = logging.getLogger(__name__)

MAX_INVALID_SHARE = 0.2
"""A page with more invalid items than this means the item schema changed: stop the run."""


def raise_for_status(response: HttpResponse) -> None:
    status = response.status
    if status == 200:
        return
    if status == 0 or status >= 500:
        raise TransientError(f"HTTP {status}: {short(response.text)}", status=status)
    if status in (403, 429):
        raise BlockedError(f"HTTP {status}", status=status, raw=response.text)
    raise ContractError(f"HTTP {status}: {short(response.text)}", status=status, raw=response.text)


async def open_start_page(transport: Transport, url: str) -> None:
    """Open the shop's start page like a visitor; a refusal here is a `BlockedError`."""
    try:
        status = await transport.open(url)
    except Exception as exc:  # navigation timeouts, DNS, browser errors
        raise ScrapeError(f"Could not open {url}: {exc}") from exc
    check_start_status(status, url)


def check_start_status(status: int, url: str) -> None:
    """A refusal of the start page is a `BlockedError` (`auto` then tries the browser)."""
    if status in (403, 429):
        raise BlockedError(f"Warm-up page {url} returned HTTP {status}", status=status)
    if status >= 400 or status == 0:
        raise ScrapeError(f"Warm-up page {url} returned HTTP {status}", status=status)


class ItemNormalizer:
    """Normalizes the items of one page. Invalid items are skipped (the first one is logged),
    but a page where too many fail stops the run: the shop changed its item format."""

    def __init__(self) -> None:
        self._warned = False

    def __call__(
        self,
        raw_items: Sequence[dict[str, Any]],
        normalize: Callable[[dict[str, Any]], ProductRecord],
        *,
        raw: str,
    ) -> tuple[tuple[ProductRecord, ...], int]:
        """Returns the valid items and the number of invalid ones."""
        items: list[ProductRecord] = []
        invalid = 0
        for raw_item in raw_items:
            try:
                items.append(normalize(raw_item))
            except ValueError as exc:  # pydantic's ValidationError is a ValueError
                invalid += 1
                if not self._warned:
                    self._warned = True
                    log.warning("Skipping invalid item %s: %s", raw_item.get("id"), short(str(exc)))
        if raw_items and invalid > MAX_INVALID_SHARE * len(raw_items):
            # Fail loudly instead of fetching the rest of the shop for nothing, and keep this
            # response for updating the models.
            raise ContractError(
                f"{invalid} of {len(raw_items)} items do not match the expected schema", raw=raw
            )
        return tuple(items), invalid


def clean(text: str | None) -> str | None:
    return text.strip() or None if text is not None else None


def short(text: str, limit: int = 300) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit] + "..."
