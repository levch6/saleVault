"""One brand across shops: shops spell the same brand differently ("KARL LAGERFELD" and
"Karl Lagerfeld", "HOKA®" and "Hoka", "Fjällräven" and "Fjallraven")."""

import re
import unicodedata

_SYMBOLS = re.compile(r"[®™©]")
_SEPARATORS = re.compile(r"[^\w]+|_+")


def brand_key(name: str) -> str:
    """The brand's key: accents and trademark signs removed, casefolded, words joined with "-"
    ("Levi's®" -> "levi-s", "'47 Brand" -> "47-brand", "Max&Co." -> "max-co")."""
    text = unicodedata.normalize("NFKD", name)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = _SYMBOLS.sub("", text).casefold()
    return "-".join(part for part in _SEPARATORS.split(text) if part) or "unnamed"
