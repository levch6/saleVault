import pytest

from salevault.domain.brands import brand_key


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("Karl Lagerfeld", "karl-lagerfeld"),
        ("KARL LAGERFELD", "karl-lagerfeld"),
        ("HOKA®", "hoka"),
        ("Levi's®", "levi-s"),
        ("Levi's", "levi-s"),
        ("'47 Brand", "47-brand"),
        ("Max&Co.", "max-co"),
        ("Fjällräven", "fjallraven"),
        ("G-STAR", "g-star"),
        ("  ", "unnamed"),
    ],
)
def test_brand_key(name: str, key: str) -> None:
    assert brand_key(name) == key


def test_different_brands_keep_different_keys() -> None:
    assert brand_key("adidas") != brand_key("adidas Originals")
    assert brand_key("Calvin Klein") != brand_key("Calvin Klein Jeans")
