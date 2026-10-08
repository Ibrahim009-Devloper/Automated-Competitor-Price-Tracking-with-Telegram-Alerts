"""Site adapters package."""

from monitor.adapters.base import SiteAdapter
from monitor.adapters.shopify import ShopifyAdapter
from monitor.adapters.jsonld import JsonLdAdapter
from monitor.adapters.playwright import PlaywrightAdapter

__all__ = ["SiteAdapter", "ShopifyAdapter", "JsonLdAdapter", "PlaywrightAdapter"]

