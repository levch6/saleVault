"""Known sites."""

from salevault.scraper.base import Transport
from salevault.scraper.sites.answear_platform import AnswearPlatformAdapter, AnswearPlatformConfig

PRM = AnswearPlatformConfig(
    code="prm",
    display_name="PRM",
    origin="https://prm.com",
    base_path="/ua",
    warmup_path="/ua/sale/",
    concurrency=1,
    headless=False,  # headless shell gets HTTP 403 at warm-up (checked 2026-11-21)
)

ANSWEAR_UA = AnswearPlatformConfig(
    code="answear_ua",
    display_name="Answear.ua",
    origin="https://answear.ua",
    base_path="",
    warmup_path="/",
    concurrency=2,
    headless=False,  # same Akamai setup as PRM; verified in phase 5
)

SITES: dict[str, AnswearPlatformConfig] = {PRM.code: PRM, ANSWEAR_UA.code: ANSWEAR_UA}


def get_config(code: str) -> AnswearPlatformConfig:
    try:
        return SITES[code]
    except KeyError:
        known = ", ".join(sorted(SITES))
        raise KeyError(f"Unknown site {code!r}; known sites: {known}") from None


def create_adapter(code: str, transport: Transport) -> AnswearPlatformAdapter:
    return AnswearPlatformAdapter(get_config(code), transport)


THUMB_SIZE = (316, 478)
"""Grid cards: about 40 KB per image."""
FULL_SIZE = (1200, 1800)


def image_urls(code: str, name: str, version: str) -> tuple[str, str] | None:
    """(thumbnail, full size) URLs of a product image, or None for an unknown site."""
    config = SITES.get(code)
    if config is None:
        return None
    return (
        config.image_url(name, version, *THUMB_SIZE),
        config.image_url(name, version, *FULL_SIZE),
    )
