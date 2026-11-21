"""Money and discount math. Money is always integer minor units (kopecks)."""

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal


def to_minor(amount: Decimal | int | float) -> int:
    """Convert a currency amount (e.g. 17899 or 17899.5 UAH) to integer minor units."""
    value = Decimal(str(amount)) * 100
    return int(value.to_integral_value(rounding=ROUND_HALF_UP))


def percent_off(price_minor: int, reference_minor: int, *, rounding: str = ROUND_DOWN) -> int:
    """Discount of `price` relative to `reference` in whole percent.

    The rounding follows the shop's own badges. The Answear platform truncates: 329 vs 639 is
    48.5% and is shown as "-48%" (all 16,972 badged PRM items, 2026-11-21). Footshop rounds:
    9,900 vs 10,999 is 9.99% and is shown as "-10%" (`ROUND_HALF_UP`). Returns 0 when there is
    no discount or the reference is not positive.
    """
    if reference_minor <= 0 or price_minor >= reference_minor:
        return 0
    ratio = Decimal(reference_minor - price_minor) * 100 / Decimal(reference_minor)
    return int(ratio.to_integral_value(rounding=rounding))
