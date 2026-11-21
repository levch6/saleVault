class ScrapeError(Exception):
    """Base class for scraping failures."""


class TransientError(ScrapeError):
    """Temporary failure (5xx, timeout, network); the request may be retried."""


class BlockedError(ScrapeError):
    """The site refused us (403/429 or a block page). Never worked around, only waited out once."""


class ContractError(ScrapeError):
    """The response does not match the API contract (e.g. 422, unexpected schema)."""


class BudgetExceededError(ScrapeError):
    """The run hit its request budget; protects against runaway loops."""
