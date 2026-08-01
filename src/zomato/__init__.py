"""zomato-py: Unofficial Python client for Zomato web API.

Discover restaurants, read reviews, browse collections, and find events
happening near you — all without an API key.
"""

from .client import ZomatoClient, Location, CITY_IDS
from .exceptions import (
    ZomatoError,
    ZomatoAPIError,
    ZomatoAuthError,
    ZomatoNotFoundError,
    DistrictError,
)

__version__ = "0.1.0"
__all__ = [
    "ZomatoClient",
    "Location",
    "CITY_IDS",
    "ZomatoError",
    "ZomatoAPIError",
    "ZomatoAuthError",
    "ZomatoNotFoundError",
    "DistrictError",
]