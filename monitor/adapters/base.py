"""Base abstract adapter definition for e-commerce stores."""

from abc import ABC, abstractmethod
from typing import Any, Dict, Tuple
from monitor.models import FetchResult


class SiteAdapter(ABC):
    """Abstract base class that all site scraper adapters must implement.

    Ensures every store returns data in the unified Observation/FetchResult format.
    Adapters must never guess prices: if a price is missing, set price_cents to None, never 0.
    """

    def __init__(self, site_config: Dict[str, Any]) -> None:
        """Initialize adapter with site configuration from sites.yaml.

        Args:
            site_config: Dictionary containing site settings (name, base_url, currency, delay_seconds, etc.).
        """
        self.site_config: Dict[str, Any] = site_config
        self.site_name: str = site_config.get("name", "Unknown Store")
        self.base_url: str = site_config.get("base_url", "").rstrip("/")
        self.currency: str = site_config.get("currency", "USD")

        # Delay range between page requests [min_seconds, max_seconds]
        delays = site_config.get("delay_seconds", [1.0, 2.0])
        if isinstance(delays, list) and len(delays) >= 2:
            self.delay_range: Tuple[float, float] = (float(delays[0]), float(delays[1]))
        else:
            self.delay_range = (1.0, 2.0)

    @abstractmethod
    def fetch(self) -> FetchResult:
        """Fetch all product observations from the store.

        Returns:
            FetchResult: Object containing a list of Observation objects and any error messages.
        """
        raise NotImplementedError("Subclasses must implement fetch()")
