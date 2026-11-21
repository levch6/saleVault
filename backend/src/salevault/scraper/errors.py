class ScrapeError(Exception):
    """Base class for scraping failures. `raw` keeps the response body for the archive."""

    def __init__(self, message: str, *, status: int | None = None, raw: str | None = None):
        super().__init__(message)
        self.status = status
        self.raw = raw


class TransientError(ScrapeError):
    """Temporary failure (5xx, timeout, network); the request may be retried."""


class BlockedError(ScrapeError):
    """The site refused us (403/429 or a block page). One pause per run; the next refusal stops
    the run."""


class ContractError(ScrapeError):
    """The response does not match the API contract (e.g. 422, unexpected schema)."""


class BudgetExceededError(ScrapeError):
    """The run hit its request budget; protects against runaway loops."""
