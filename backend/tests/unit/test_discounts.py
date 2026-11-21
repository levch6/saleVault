from decimal import Decimal

import pytest

from salevault.domain.discounts import percent_off, to_minor
from salevault.domain.models import build_search_text


@pytest.mark.parametrize(
    ("amount", "expected"),
    [(17899, 1789900), (Decimal("269.5"), 26950), (0, 0), (Decimal("0.005"), 1)],
)
def test_to_minor(amount: Decimal | int, expected: int) -> None:
    assert to_minor(amount) == expected


@pytest.mark.parametrize(
    ("price", "reference", "expected"),
    [
        (1789900, 2499900, 28),  # 28.4% -> 28, site badge "-28%"
        (32900, 63900, 48),  # 48.5% -> 48: the site truncates, it does not round
        (29900, 63900, 53),  # 53.2%
        (50, 100, 50),
        (125, 1000, 87),  # 87.5% -> 87
        (99, 100, 1),
        (100, 100, 0),
        (120, 100, 0),  # price above reference: no discount
        (100, 0, 0),
    ],
)
def test_percent_off(price: int, reference: int, expected: int) -> None:
    assert percent_off(price, reference) == expected


def test_search_text_is_casefolded_and_skips_empty_parts() -> None:
    text = build_search_text("MM6 Maison Margiela", "Штани  STRAIGHT", None, " ")

    assert text == "mm6 maison margiela штани straight"
