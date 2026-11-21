"""Known sites."""

from salevault.domain.models import Gender
from salevault.scraper.base import SiteAdapter, SiteConfig, Transport
from salevault.scraper.sites.answear_platform import AnswearPlatformAdapter, AnswearPlatformConfig
from salevault.scraper.sites.footshop import FootshopAdapter, FootshopConfig, FootshopSection
from salevault.scraper.sites.modivo import ModivoAdapter, ModivoConfig, ModivoSection
from salevault.scraper.sites.saks85 import (
    Saks85Adapter,
    Saks85Category,
    Saks85Config,
    Saks85Gender,
)

PRM = AnswearPlatformConfig(
    code="prm",
    display_name="PRM",
    origin="https://prm.com",
    base_path="/ua",
    warmup_path="/ua/sale/",
    concurrency=1,
    headless=False,  # the site does not serve Playwright's headless shell (HTTP 403)
)

ANSWEAR_UA = AnswearPlatformConfig(
    code="answear_ua",
    display_name="Answear.ua",
    origin="https://answear.ua",
    base_path="",
    warmup_path="/",
    concurrency=2,
    headless=False,  # same as PRM
)

FOOTSHOP_UA = FootshopConfig(
    code="footshop_ua",
    display_name="Footshop",
    origin="https://www.footshop.ua",
    language="uk",
    sale_path="/uk/872-znizhki",
    # The "Sale" links of the men's, women's and kids' menus. Unisex items are in both of the
    # first two (like the shop's own gender filter); kids' items are in one of them as well.
    sections={
        "men": FootshopSection("/uk/2536-colovica-moda-znizki", Gender.MEN),
        "women": FootshopSection("/uk/2581-zinoca-moda-znizki", Gender.WOMEN),
        "kids": FootshopSection("/uk/2986-ditaca-moda-znizki", Gender.KIDS),
    },
    concurrency=2,  # about 850 pages per run; the first run with one worker had no refusals
)

SAKS85 = Saks85Config(
    code="saks85",
    display_name="Saks85",
    origin="https://saks85.com",
    sale_path="special/rasprodazha",
    sale_selection="10010:4252492525",
    catalog=Saks85Category("catalogue", "0"),
    # The sale's top-level categories (clothing, shoes, accessories, home fragrance) and the
    # gender filter, as linked from the shop's menus. Unisex items are in both genders.
    categories={
        "clothing": Saks85Category("odyag", "69"),
        "shoes": Saks85Category("vzuttya", "20"),
        "accessories": Saks85Category("aksesuary", "84"),
        "home": Saks85Category("aromaty-dlya-domu-ta-avto", "254"),
    },
    genders={
        "men": Saks85Gender("stat/choloviche", "10024:4252492559", Gender.MEN),
        "women": Saks85Gender("stat/zhinoche", "10024:4252492560", Gender.WOMEN),
    },
)

MODIVO_UA = ModivoConfig(
    code="modivo_ua",
    display_name="Modivo",
    origin="https://modivo.ua",
    root_path="/c/modivo",
    # robots.txt allows exactly this discount filter (5 to 99%), the one the sale page uses.
    sale_filter="discount:~r-5-99",
    # The gender sections of the catalog's menu. Unisex items are in both of the first two.
    sections={
        "men": ModivoSection("/c/choloviky", Gender.MEN),
        "women": ModivoSection("/c/zhinky", Gender.WOMEN),
        "kids": ModivoSection("/c/dity", Gender.KIDS),
    },
    concurrency=2,  # about 900 heavy pages per run (2 to 3 MB each); owner's call
)

SITES: dict[str, SiteConfig] = {
    config.code: config for config in (PRM, ANSWEAR_UA, FOOTSHOP_UA, SAKS85, MODIVO_UA)
}


def get_config(code: str) -> SiteConfig:
    try:
        return SITES[code]
    except KeyError:
        known = ", ".join(sorted(SITES))
        raise KeyError(f"Unknown site {code!r}; known sites: {known}") from None


def create_adapter(code: str, transport: Transport) -> SiteAdapter:
    config = get_config(code)
    if isinstance(config, AnswearPlatformConfig):
        return AnswearPlatformAdapter(config, transport)
    if isinstance(config, FootshopConfig):
        return FootshopAdapter(config, transport)
    if isinstance(config, Saks85Config):
        return Saks85Adapter(config, transport)
    if isinstance(config, ModivoConfig):
        return ModivoAdapter(config, transport)
    raise TypeError(f"No adapter for {type(config).__name__}")


def image_urls(code: str, name: str, version: str) -> tuple[str, str] | None:
    """(thumbnail, full size) URLs of a product image, or None for an unknown site."""
    config = SITES.get(code)
    return config.image_urls(name, version) if config is not None else None
