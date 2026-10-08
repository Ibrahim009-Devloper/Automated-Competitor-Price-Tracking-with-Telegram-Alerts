"""Site adapters package with lazy-loading factory.

Adapters are imported on demand when create_adapter() is invoked for a specific site,
ensuring that a missing optional dependency (e.g. Playwright or BeautifulSoup4)
does not crash the entire application during module import time or during --ci-check.
"""

from typing import Any, Dict
from monitor.adapters.base import SiteAdapter


def create_adapter(site_config: Dict[str, Any]) -> SiteAdapter:
    """Factory creating the appropriate SiteAdapter instance lazily.

    Args:
        site_config: Site dictionary from sites.yaml.

    Returns:
        SiteAdapter implementation instance.

    Raises:
        ValueError: If the adapter type is unknown.
        ImportError: If dependencies required for this adapter cannot be loaded.
    """
    adapter_name = site_config.get("adapter", "").strip().lower()
    site_name = site_config.get("name", "Unnamed Site")

    if adapter_name == "shopify":
        try:
            from monitor.adapters.shopify import ShopifyAdapter
            return ShopifyAdapter(site_config)
        except ImportError as err:
            raise ImportError(
                f"Cannot load 'shopify' adapter for site '{site_name}': missing dependency ({err})"
            ) from err

    elif adapter_name == "jsonld":
        try:
            from monitor.adapters.jsonld import JsonLdAdapter
            return JsonLdAdapter(site_config)
        except ImportError as err:
            raise ImportError(
                f"Cannot load 'jsonld' adapter for site '{site_name}': missing dependency ({err})"
            ) from err

    elif adapter_name == "playwright":
        try:
            from monitor.adapters.playwright import PlaywrightAdapter
            return PlaywrightAdapter(site_config)
        except ImportError as err:
            raise ImportError(
                f"Cannot load 'playwright' adapter for site '{site_name}': missing dependency ({err})"
            ) from err

    else:
        raise ValueError(
            f"Unsupported adapter '{adapter_name}' for site '{site_name}'"
        )


def __getattr__(name: str) -> Any:
    """Lazy module-level attribute loader for backwards compatibility."""
    if name == "ShopifyAdapter":
        from monitor.adapters.shopify import ShopifyAdapter
        return ShopifyAdapter
    if name == "JsonLdAdapter":
        from monitor.adapters.jsonld import JsonLdAdapter
        return JsonLdAdapter
    if name == "PlaywrightAdapter":
        from monitor.adapters.playwright import PlaywrightAdapter
        return PlaywrightAdapter
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


__all__ = ["SiteAdapter", "create_adapter", "ShopifyAdapter", "JsonLdAdapter", "PlaywrightAdapter"]
