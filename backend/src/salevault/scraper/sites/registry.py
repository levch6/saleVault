"""Known sites. Answear.ua is added in phase 5, after its config is verified."""

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

SITES: dict[str, AnswearPlatformConfig] = {PRM.code: PRM}


def get_config(code: str) -> AnswearPlatformConfig:
    try:
        return SITES[code]
    except KeyError:
        known = ", ".join(sorted(SITES))
        raise KeyError(f"Unknown site {code!r}; known sites: {known}") from None


def create_adapter(code: str, transport: Transport) -> AnswearPlatformAdapter:
    return AnswearPlatformAdapter(get_config(code), transport)
